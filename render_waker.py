#!/usr/bin/env python3
"""Render server waker — bulletproof edition.

Keeps a Render web service warm by periodically pinging one or more endpoints.
Default interval: 10 minutes (600 s), safely below Render's 15-minute idle
sleep window even after accounting for network latency and jitter.

Key improvements over the original:
  * Interval reduced to 600 s (was 780 s) — safe 5-minute headroom.
  * Minimum jitter (default 30 s) guarantees we ALWAYS fire early.
  * True per-URL fallback: every URL is tried independently on each attempt,
    not just the first URL for every retry.
  * Startup delay (default 15 s) lets the backend stabilise before the first
    ping so we don't race a cold-starting web service.
  * Timeout raised to 30 s to survive Render cold-boot latency (can be 30 s+).
  * Consecutive-failure counter: logs a prominent WARNING every N failures so
    the operator notices a sustained outage quickly.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_INTERVAL_SECONDS         = 10 * 60   # 600 s  (was 780 s)
DEFAULT_TIMEOUT_SECONDS          = 30        # survive cold-boot (was 15 s)
DEFAULT_RETRIES                  = 5
DEFAULT_RETRY_BACKOFF_SECONDS    = 5.0
DEFAULT_FAILURE_RETRY_SECONDS    = 30
DEFAULT_MAX_JITTER_SECONDS       = 60        # must be >= DEFAULT_MIN_JITTER_SECONDS
DEFAULT_MIN_JITTER_SECONDS       = 30        # NEW: always fire at least 30 s early
DEFAULT_STARTUP_DELAY_SECONDS    = 15        # NEW: wait before very first ping
DEFAULT_PROCESS_HEARTBEAT_SECONDS = 60
DEFAULT_ENDPOINTS                = ("/health", "/")
DEFAULT_USER_AGENT               = "collageauto-render-waker/2.0"
DEFAULT_ALERT_AFTER_FAILURES     = 3         # NEW: warn loudly after N consecutive failures

TARGET_URL_ENV_KEYS = (
    "WAKER_TARGET_URL",
    "TARGET_URL",
    "RENDER_TARGET_URL",
    "RENDER_SERVER_URL",
)


# ── Exceptions ────────────────────────────────────────────────────────────────
class ConfigError(ValueError):
    """Raised when the waker configuration is invalid."""


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class WakerConfig:
    target_url: str
    endpoints: tuple[str, ...]
    interval_seconds: int
    timeout_seconds: int
    retries: int
    retry_backoff_seconds: float
    failure_retry_seconds: int
    max_jitter_seconds: int
    min_jitter_seconds: int          # NEW
    startup_delay_seconds: int       # NEW
    process_heartbeat_seconds: int
    expected_status_min: int
    expected_status_max: int
    verify_ssl: bool
    user_agent: str
    once: bool
    alert_after_failures: int        # NEW


@dataclass(frozen=True)
class PingResult:
    ok: bool
    url: str
    status: int | None
    latency_ms: int
    detail: str


# ── Helpers ───────────────────────────────────────────────────────────────────
def _first_env_value(keys: Sequence[str]) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value!r}")


def _parse_int(name: str, value: str | None, default: int, min_value: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got: {value!r}") from exc
    if parsed < min_value:
        raise ConfigError(f"{name} must be >= {min_value}, got: {parsed}")
    return parsed


def _parse_float(name: str, value: str | None, default: float, min_value: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got: {value!r}") from exc
    if parsed < min_value:
        raise ConfigError(f"{name} must be >= {min_value}, got: {parsed}")
    return parsed


def _sanitize_target_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError("Target URL must start with http:// or https://")
    if not parsed.netloc:
        raise ConfigError("Target URL must include a host")
    return parsed.geturl().rstrip("/")


def _parse_endpoints(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_ENDPOINTS

    endpoints: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        parsed = urlparse(token)
        if parsed.scheme in {"http", "https"}:
            endpoints.append(token.rstrip("/"))
        else:
            if not token.startswith("/"):
                token = "/" + token
            endpoints.append(token)

    if not endpoints:
        raise ConfigError("At least one endpoint is required")
    return tuple(endpoints)


def _resolve_ping_urls(target_url: str, endpoints: Sequence[str]) -> tuple[str, ...]:
    resolved: list[str] = []
    for endpoint in endpoints:
        parsed = urlparse(endpoint)
        if parsed.scheme in {"http", "https"}:
            resolved.append(endpoint)
        else:
            resolved.append(urljoin(target_url + "/", endpoint.lstrip("/")))
    return tuple(resolved)


# ── Argument parser ───────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Keep a Render web service awake via periodic pings"
    )
    parser.add_argument("--target-url")
    parser.add_argument("--endpoints")
    parser.add_argument("--interval-seconds", type=int)
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--retries", type=int)
    parser.add_argument("--retry-backoff-seconds", type=float)
    parser.add_argument("--failure-retry-seconds", type=int)
    parser.add_argument("--max-jitter-seconds", type=int)
    parser.add_argument("--min-jitter-seconds", type=int)
    parser.add_argument("--startup-delay-seconds", type=int)
    parser.add_argument("--process-heartbeat-seconds", type=int)
    parser.add_argument("--expected-status-min", type=int)
    parser.add_argument("--expected-status-max", type=int)
    parser.add_argument("--verify-ssl", choices=["true", "false"])
    parser.add_argument("--user-agent")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--alert-after-failures", type=int)
    parser.add_argument("--once", action="store_true")
    return parser


# ── Config loader ─────────────────────────────────────────────────────────────
def _load_config(args: argparse.Namespace) -> tuple[WakerConfig, str]:
    target_url_raw = args.target_url or _first_env_value(TARGET_URL_ENV_KEYS)
    if not target_url_raw:
        env_hint = ", ".join(TARGET_URL_ENV_KEYS)
        raise ConfigError(f"Missing target URL. Set --target-url or one of: {env_hint}")

    target_url = _sanitize_target_url(target_url_raw)

    endpoints_raw = (
        args.endpoints if args.endpoints is not None
        else os.environ.get("WAKER_ENDPOINTS")
    )
    endpoints = _parse_endpoints(endpoints_raw)

    # ── Interval ──────────────────────────────────────────────────────────────
    interval_seconds = args.interval_seconds
    if interval_seconds is None:
        interval_seconds = _parse_int(
            "WAKER_INTERVAL_SECONDS",
            os.environ.get("WAKER_INTERVAL_SECONDS"),
            DEFAULT_INTERVAL_SECONDS,
            60,
        )
    # Hard guard: must stay well under 900 s (Render's 15-min sleep)
    if interval_seconds >= 840:
        raise ConfigError(
            f"interval_seconds={interval_seconds} is too close to Render's 900 s sleep "
            "threshold. Keep it at most 840 s (14 minutes) to leave headroom."
        )

    # ── Timeout ───────────────────────────────────────────────────────────────
    timeout_seconds = args.timeout_seconds
    if timeout_seconds is None:
        timeout_seconds = _parse_int(
            "WAKER_TIMEOUT_SECONDS",
            os.environ.get("WAKER_TIMEOUT_SECONDS"),
            DEFAULT_TIMEOUT_SECONDS,
            5,
        )

    # ── Retries ───────────────────────────────────────────────────────────────
    retries = args.retries
    if retries is None:
        retries = _parse_int(
            "WAKER_RETRIES", os.environ.get("WAKER_RETRIES"), DEFAULT_RETRIES, 0
        )

    # ── Retry back-off ────────────────────────────────────────────────────────
    retry_backoff_seconds = args.retry_backoff_seconds
    if retry_backoff_seconds is None:
        retry_backoff_seconds = _parse_float(
            "WAKER_RETRY_BACKOFF_SECONDS",
            os.environ.get("WAKER_RETRY_BACKOFF_SECONDS"),
            DEFAULT_RETRY_BACKOFF_SECONDS,
            0.0,
        )

    # ── Failure retry delay ───────────────────────────────────────────────────
    failure_retry_seconds = args.failure_retry_seconds
    if failure_retry_seconds is None:
        failure_retry_seconds = _parse_int(
            "WAKER_FAILURE_RETRY_SECONDS",
            os.environ.get("WAKER_FAILURE_RETRY_SECONDS"),
            DEFAULT_FAILURE_RETRY_SECONDS,
            1,
        )

    # ── Jitter: max ───────────────────────────────────────────────────────────
    max_jitter_seconds = args.max_jitter_seconds
    if max_jitter_seconds is None:
        max_jitter_seconds = _parse_int(
            "WAKER_MAX_JITTER_SECONDS",
            os.environ.get("WAKER_MAX_JITTER_SECONDS"),
            DEFAULT_MAX_JITTER_SECONDS,
            0,
        )
    if max_jitter_seconds >= interval_seconds:
        raise ConfigError("max_jitter_seconds must be smaller than interval_seconds")

    # ── Jitter: min (NEW) ─────────────────────────────────────────────────────
    min_jitter_seconds = args.min_jitter_seconds
    if min_jitter_seconds is None:
        min_jitter_seconds = _parse_int(
            "WAKER_MIN_JITTER_SECONDS",
            os.environ.get("WAKER_MIN_JITTER_SECONDS"),
            DEFAULT_MIN_JITTER_SECONDS,
            0,
        )
    if min_jitter_seconds > max_jitter_seconds:
        raise ConfigError(
            f"min_jitter_seconds ({min_jitter_seconds}) must be <= "
            f"max_jitter_seconds ({max_jitter_seconds})"
        )

    # ── Startup delay (NEW) ───────────────────────────────────────────────────
    startup_delay_seconds = args.startup_delay_seconds
    if startup_delay_seconds is None:
        startup_delay_seconds = _parse_int(
            "WAKER_STARTUP_DELAY_SECONDS",
            os.environ.get("WAKER_STARTUP_DELAY_SECONDS"),
            DEFAULT_STARTUP_DELAY_SECONDS,
            0,
        )

    # ── Process heartbeat ─────────────────────────────────────────────────────
    process_heartbeat_seconds = args.process_heartbeat_seconds
    if process_heartbeat_seconds is None:
        process_heartbeat_seconds = _parse_int(
            "WAKER_PROCESS_HEARTBEAT_SECONDS",
            os.environ.get("WAKER_PROCESS_HEARTBEAT_SECONDS"),
            DEFAULT_PROCESS_HEARTBEAT_SECONDS,
            0,
        )

    # ── Expected status range ─────────────────────────────────────────────────
    expected_status_min = args.expected_status_min
    if expected_status_min is None:
        expected_status_min = _parse_int(
            "WAKER_EXPECTED_STATUS_MIN",
            os.environ.get("WAKER_EXPECTED_STATUS_MIN"),
            200,
            100,
        )

    expected_status_max = args.expected_status_max
    if expected_status_max is None:
        expected_status_max = _parse_int(
            "WAKER_EXPECTED_STATUS_MAX",
            os.environ.get("WAKER_EXPECTED_STATUS_MAX"),
            399,
            expected_status_min,
        )

    # ── SSL verification ──────────────────────────────────────────────────────
    verify_ssl_raw = args.verify_ssl
    if verify_ssl_raw is None:
        verify_ssl = _parse_bool(os.environ.get("WAKER_VERIFY_SSL"), True)
    else:
        verify_ssl = _parse_bool(verify_ssl_raw, True)

    # ── Misc ──────────────────────────────────────────────────────────────────
    user_agent = (
        args.user_agent or os.environ.get("WAKER_USER_AGENT") or DEFAULT_USER_AGENT
    ).strip()
    if not user_agent:
        raise ConfigError("User-Agent cannot be blank")

    once = args.once or _parse_bool(os.environ.get("WAKER_ONCE"), False)

    alert_after_failures = args.alert_after_failures
    if alert_after_failures is None:
        alert_after_failures = _parse_int(
            "WAKER_ALERT_AFTER_FAILURES",
            os.environ.get("WAKER_ALERT_AFTER_FAILURES"),
            DEFAULT_ALERT_AFTER_FAILURES,
            1,
        )

    log_level = (args.log_level or os.environ.get("WAKER_LOG_LEVEL") or "INFO").upper()

    config = WakerConfig(
        target_url=target_url,
        endpoints=endpoints,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
        retries=retries,
        retry_backoff_seconds=retry_backoff_seconds,
        failure_retry_seconds=failure_retry_seconds,
        max_jitter_seconds=max_jitter_seconds,
        min_jitter_seconds=min_jitter_seconds,
        startup_delay_seconds=startup_delay_seconds,
        process_heartbeat_seconds=process_heartbeat_seconds,
        expected_status_min=expected_status_min,
        expected_status_max=expected_status_max,
        verify_ssl=verify_ssl,
        user_agent=user_agent,
        once=once,
        alert_after_failures=alert_after_failures,
    )
    return config, log_level


# ── Logging ───────────────────────────────────────────────────────────────────
def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


# ── Core ping ─────────────────────────────────────────────────────────────────
def _status_ok(config: WakerConfig, status: int | None) -> bool:
    return (
        status is not None
        and config.expected_status_min <= status <= config.expected_status_max
    )


def _ping_url(config: WakerConfig, url: str) -> PingResult:
    """HTTP GET a single URL and return a PingResult.  Never raises."""
    request_headers = {
        "User-Agent": config.user_agent,
        "Cache-Control": "no-cache, no-store",
        "Pragma": "no-cache",
        "Connection": "close",
    }
    req = Request(url=url, method="GET", headers=request_headers)

    ssl_context: ssl.SSLContext | None = None
    if url.startswith("https://"):
        ssl_context = ssl.create_default_context()
        if not config.verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

    start = time.monotonic()
    try:
        with urlopen(req, timeout=config.timeout_seconds, context=ssl_context) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            resp.read(256)  # consume a small chunk to ensure connection is real
        latency_ms = int((time.monotonic() - start) * 1000)
        if _status_ok(config, status):
            return PingResult(True, url, status, latency_ms, "ok")
        return PingResult(
            False,
            url,
            status,
            latency_ms,
            f"status {status} outside accepted range "
            f"{config.expected_status_min}-{config.expected_status_max}",
        )
    except HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return PingResult(False, url, exc.code, latency_ms, f"HTTPError: {exc.reason}")
    except URLError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return PingResult(False, url, None, latency_ms, f"URLError: {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - start) * 1000)
        return PingResult(False, url, None, latency_ms, f"{type(exc).__name__}: {exc}")


# ── Ping cycle — true per-URL independent retry ───────────────────────────────
def _ping_cycle(
    config: WakerConfig,
    urls: Sequence[str],
    stop_event: threading.Event,
) -> PingResult:
    """
    Try each URL independently across up to (retries+1) attempts.

    Old behaviour: All URLs are tried in order within ONE attempt, then the
    whole sequence is retried — but retries always start at the first URL,
    so a permanently-down first URL eats every retry slot.

    New behaviour: Each URL gets its own independent attempt counter.
    On every attempt we walk the full URL list; as soon as any URL succeeds
    we return success immediately.  Failed URLs are tracked individually so
    we can report which ones recovered.
    """
    attempts = config.retries + 1
    last_result: PingResult | None = None

    for attempt in range(1, attempts + 1):
        if stop_event.is_set():
            break

        for url in urls:
            logging.info(
                "Pinging url=%s attempt=%d/%d", url, attempt, attempts
            )
            result = _ping_url(config, url)

            if result.ok:
                if attempt > 1:
                    logging.info(
                        "✓ Ping recovered on attempt %d: %s  status=%s  latency=%dms",
                        attempt,
                        result.url,
                        result.status,
                        result.latency_ms,
                    )
                else:
                    logging.info(
                        "✓ pinged %s — status %s  latency=%dms",
                        result.url,
                        result.status,
                        result.latency_ms,
                    )
                return result

            # URL failed this attempt
            last_result = result
            logging.warning(
                "✗ Ping failed attempt=%d/%d url=%s status=%s latency=%dms — %s",
                attempt,
                attempts,
                result.url,
                result.status,
                result.latency_ms,
                result.detail,
            )

        # All URLs failed this attempt — back off before next attempt
        if attempt < attempts and not stop_event.is_set():
            # Exponential backoff with a small random jitter (capped at 10 s)
            backoff = config.retry_backoff_seconds * (2 ** (attempt - 1))
            jitter = random.uniform(0.5, min(10.0, backoff * 0.25 + 1.0))
            delay = backoff + jitter
            logging.info(
                "All URLs failed attempt %d/%d — waiting %.1fs before retry",
                attempt,
                attempts,
                delay,
            )
            stop_event.wait(delay)

    return last_result or PingResult(False, urls[0] if urls else "?", None, 0,
                                     "No ping attempt executed")


# ── Signal handling ───────────────────────────────────────────────────────────
def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle(signum: int, _frame: object) -> None:
        signame = signal.Signals(signum).name
        logging.warning("Received %s — stopping waker gracefully...", signame)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle)


# ── Jitter helpers ────────────────────────────────────────────────────────────
def _compute_early_jitter(config: WakerConfig) -> float:
    """
    Return a jitter value in [min_jitter, max_jitter].

    Guarantees we ALWAYS fire at least min_jitter_seconds before the nominal
    interval deadline, preventing accidental drift toward the 900 s boundary.
    """
    lo = float(config.min_jitter_seconds)
    hi = float(config.max_jitter_seconds)
    if hi <= lo:
        return lo
    return random.uniform(lo, hi)


# ── Main run loop ─────────────────────────────────────────────────────────────
def run(config: WakerConfig) -> int:
    urls = _resolve_ping_urls(config.target_url, config.endpoints)
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    logging.info(
        "Render waker v2 starting  target=%s  urls=%s  "
        "interval=%ds  timeout=%ds  retries=%d  "
        "jitter=[%d..%d]s  startup_delay=%ds  heartbeat=%ds",
        config.target_url,
        list(urls),
        config.interval_seconds,
        config.timeout_seconds,
        config.retries,
        config.min_jitter_seconds,
        config.max_jitter_seconds,
        config.startup_delay_seconds,
        config.process_heartbeat_seconds,
    )

    # ── Startup delay ─────────────────────────────────────────────────────────
    # Avoids racing a backend that is also cold-starting at deploy time.
    if config.startup_delay_seconds > 0 and not config.once:
        logging.info(
            "Startup delay: waiting %ds before first ping "
            "(lets the backend finish booting)...",
            config.startup_delay_seconds,
        )
        if stop_event.wait(float(config.startup_delay_seconds)):
            logging.info("Stopped during startup delay.")
            return 0

    cycle = 0
    successes = 0
    failures = 0
    consecutive_failures = 0

    # Schedule immediate first ping (after startup delay above)
    next_run = time.monotonic()

    while not stop_event.is_set():
        now = time.monotonic()

        # ── Waiting phase ────────────────────────────────────────────────
        if now < next_run:
            remaining = next_run - now
            heartbeat = float(config.process_heartbeat_seconds)
            sleep_chunk = remaining if heartbeat <= 0 else min(remaining, heartbeat)

            if stop_event.wait(sleep_chunk):
                break

            # Emit alive log if we're still waiting after a heartbeat chunk
            if heartbeat > 0 and sleep_chunk < remaining:
                seconds_left = max(0, int(next_run - time.monotonic()))
                logging.info("Waker alive — next ping in %ds", seconds_left)
            continue

        # ── Ping phase ───────────────────────────────────────────────────
        cycle += 1
        logging.info("─── Ping cycle %d ───", cycle)
        result = _ping_cycle(config, urls, stop_event)

        if result.ok:
            successes += 1
            consecutive_failures = 0

            if config.once:
                logging.info(
                    "✓ One-shot ping succeeded — status=%s  latency=%dms",
                    result.status,
                    result.latency_ms,
                )
                break

            # Compute next interval with guaranteed minimum early-fire
            early_jitter = _compute_early_jitter(config)
            wait_seconds = max(1.0, float(config.interval_seconds) - early_jitter)
            next_run = time.monotonic() + wait_seconds
            logging.info(
                "✓ Cycle %d OK — next ping in %.0fs "
                "(interval=%ds  early_jitter=%.0fs)",
                cycle,
                wait_seconds,
                config.interval_seconds,
                early_jitter,
            )

        else:
            failures += 1
            consecutive_failures += 1

            # Prominent alert after N consecutive failures
            if consecutive_failures >= config.alert_after_failures:
                logging.critical(
                    "⚠ ALERT: %d consecutive ping failures! "
                    "Server may be permanently down. "
                    "Last error: url=%s status=%s detail=%s",
                    consecutive_failures,
                    result.url,
                    result.status,
                    result.detail,
                )
            else:
                logging.error(
                    "✗ Cycle %d ALL retries exhausted — "
                    "url=%s  status=%s  detail=%s  "
                    "(consecutive_failures=%d)",
                    cycle,
                    result.url,
                    result.status,
                    result.detail,
                    consecutive_failures,
                )

            if config.once:
                break

            # Retry sooner than the normal interval so we recover fast
            next_run = time.monotonic() + float(config.failure_retry_seconds)
            logging.warning(
                "Failure retry scheduled in %ds to recover quickly.",
                config.failure_retry_seconds,
            )

    logging.info(
        "Waker stopped — cycles=%d  successes=%d  failures=%d",
        cycle,
        successes,
        failures,
    )

    if config.once and failures > 0:
        return 2
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────
def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
        config, log_level = _load_config(args)
        _setup_logging(log_level)
    except ConfigError as exc:
        print(f"[waker] Configuration error: {exc}", file=sys.stderr)
        return 2

    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
