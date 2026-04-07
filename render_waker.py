#!/usr/bin/env python3
"""Render server waker.

Keeps a Render web service warm by periodically pinging one or more endpoints,
defaulting to every 14 minutes (840 seconds), which is below Render's 15-minute
idle sleep window.
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

DEFAULT_INTERVAL_SECONDS = 14 * 60
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 5.0
DEFAULT_FAILURE_RETRY_SECONDS = 60
DEFAULT_MAX_JITTER_SECONDS = 20
DEFAULT_ENDPOINTS = ("/health", "/")
DEFAULT_USER_AGENT = "collageauto-render-waker/1.0"

TARGET_URL_ENV_KEYS = (
    "WAKER_TARGET_URL",
    "TARGET_URL",
    "RENDER_TARGET_URL",
    "RENDER_SERVER_URL",
)


class ConfigError(ValueError):
    """Raised when the waker configuration is invalid."""


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
    expected_status_min: int
    expected_status_max: int
    verify_ssl: bool
    user_agent: str
    once: bool


@dataclass(frozen=True)
class PingResult:
    ok: bool
    url: str
    status: int | None
    latency_ms: int
    detail: str


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Keep a Render web service awake via periodic pings")
    parser.add_argument("--target-url", help="Base URL of the Render web service (e.g. https://my-app.onrender.com)")
    parser.add_argument("--endpoints", help="Comma-separated endpoints or absolute URLs (default: /health,/)")
    parser.add_argument("--interval-seconds", type=int, help="Heartbeat interval (default: 840)")
    parser.add_argument("--timeout-seconds", type=int, help="Per-request timeout (default: 20)")
    parser.add_argument("--retries", type=int, help="Retries after first failure (default: 3)")
    parser.add_argument("--retry-backoff-seconds", type=float, help="Initial retry backoff in seconds (default: 5)")
    parser.add_argument("--failure-retry-seconds", type=int, help="Retry delay after a failed cycle (default: 60)")
    parser.add_argument("--max-jitter-seconds", type=int, help="Max early jitter to fire before interval (default: 20)")
    parser.add_argument("--expected-status-min", type=int, help="Minimum acceptable status code (default: 200)")
    parser.add_argument("--expected-status-max", type=int, help="Maximum acceptable status code (default: 399)")
    parser.add_argument("--verify-ssl", choices=["true", "false"], help="Verify SSL certs (default: true)")
    parser.add_argument("--user-agent", help=f"User-Agent header (default: {DEFAULT_USER_AGENT})")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level (default: INFO)")
    parser.add_argument("--once", action="store_true", help="Run one ping cycle and exit")
    return parser


def _load_config(args: argparse.Namespace) -> tuple[WakerConfig, str]:
    target_url_raw = args.target_url or _first_env_value(TARGET_URL_ENV_KEYS)
    if not target_url_raw:
        env_hint = ", ".join(TARGET_URL_ENV_KEYS)
        raise ConfigError(
            f"Missing target URL. Set --target-url or one of: {env_hint}"
        )

    target_url = _sanitize_target_url(target_url_raw)

    endpoints_raw = args.endpoints if args.endpoints is not None else os.environ.get("WAKER_ENDPOINTS")
    endpoints = _parse_endpoints(endpoints_raw)

    interval_seconds = args.interval_seconds
    if interval_seconds is None:
        interval_seconds = _parse_int(
            "WAKER_INTERVAL_SECONDS", os.environ.get("WAKER_INTERVAL_SECONDS"), DEFAULT_INTERVAL_SECONDS, 30
        )
    if interval_seconds >= 900:
        raise ConfigError(
            "Interval must be below 900 seconds to beat Render's 15-minute idle sleep window"
        )

    timeout_seconds = args.timeout_seconds
    if timeout_seconds is None:
        timeout_seconds = _parse_int(
            "WAKER_TIMEOUT_SECONDS", os.environ.get("WAKER_TIMEOUT_SECONDS"), DEFAULT_TIMEOUT_SECONDS, 1
        )

    retries = args.retries
    if retries is None:
        retries = _parse_int("WAKER_RETRIES", os.environ.get("WAKER_RETRIES"), DEFAULT_RETRIES, 0)

    retry_backoff_seconds = args.retry_backoff_seconds
    if retry_backoff_seconds is None:
        retry_backoff_seconds = _parse_float(
            "WAKER_RETRY_BACKOFF_SECONDS",
            os.environ.get("WAKER_RETRY_BACKOFF_SECONDS"),
            DEFAULT_RETRY_BACKOFF_SECONDS,
            0.0,
        )

    failure_retry_seconds = args.failure_retry_seconds
    if failure_retry_seconds is None:
        failure_retry_seconds = _parse_int(
            "WAKER_FAILURE_RETRY_SECONDS",
            os.environ.get("WAKER_FAILURE_RETRY_SECONDS"),
            DEFAULT_FAILURE_RETRY_SECONDS,
            1,
        )

    max_jitter_seconds = args.max_jitter_seconds
    if max_jitter_seconds is None:
        max_jitter_seconds = _parse_int(
            "WAKER_MAX_JITTER_SECONDS",
            os.environ.get("WAKER_MAX_JITTER_SECONDS"),
            DEFAULT_MAX_JITTER_SECONDS,
            0,
        )
    if max_jitter_seconds >= interval_seconds:
        raise ConfigError("Max jitter must be smaller than interval")

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

    verify_ssl_raw = args.verify_ssl
    if verify_ssl_raw is None:
        verify_ssl = _parse_bool(os.environ.get("WAKER_VERIFY_SSL"), True)
    else:
        verify_ssl = _parse_bool(verify_ssl_raw, True)

    user_agent = (args.user_agent or os.environ.get("WAKER_USER_AGENT") or DEFAULT_USER_AGENT).strip()
    if not user_agent:
        raise ConfigError("User-Agent cannot be blank")

    once = args.once or _parse_bool(os.environ.get("WAKER_ONCE"), False)

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
        expected_status_min=expected_status_min,
        expected_status_max=expected_status_max,
        verify_ssl=verify_ssl,
        user_agent=user_agent,
        once=once,
    )
    return config, log_level


def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _status_ok(config: WakerConfig, status: int | None) -> bool:
    return status is not None and config.expected_status_min <= status <= config.expected_status_max


def _ping_url(config: WakerConfig, url: str) -> PingResult:
    request_headers = {
        "User-Agent": config.user_agent,
        "Cache-Control": "no-cache",
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
            resp.read(1)
        latency_ms = int((time.monotonic() - start) * 1000)
        if _status_ok(config, status):
            return PingResult(True, url, status, latency_ms, "ok")
        return PingResult(
            False,
            url,
            status,
            latency_ms,
            f"status {status} outside accepted range {config.expected_status_min}-{config.expected_status_max}",
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


def _ping_cycle(config: WakerConfig, urls: Sequence[str], stop_event: threading.Event) -> PingResult:
    attempts = config.retries + 1
    last_result: PingResult | None = None

    for attempt in range(1, attempts + 1):
        for url in urls:
            result = _ping_url(config, url)
            if result.ok:
                if attempt > 1:
                    logging.info(
                        "Ping recovered on retry attempt %s: %s status=%s latency=%sms",
                        attempt,
                        result.url,
                        result.status,
                        result.latency_ms,
                    )
                return result
            last_result = result
            logging.warning(
                "Ping failed attempt=%s/%s url=%s status=%s latency=%sms detail=%s",
                attempt,
                attempts,
                result.url,
                result.status,
                result.latency_ms,
                result.detail,
            )

        if attempt < attempts:
            backoff = config.retry_backoff_seconds * (2 ** (attempt - 1))
            jitter = random.uniform(0, min(3, float(config.max_jitter_seconds)))
            delay = backoff + jitter
            logging.info("Waiting %.2fs before retry", delay)
            if stop_event.wait(delay):
                break

    return last_result or PingResult(False, urls[0], None, 0, "No ping attempt executed")


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle(signum: int, _frame: object) -> None:
        signame = signal.Signals(signum).name
        logging.warning("Received %s. Stopping waker...", signame)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle)


def run(config: WakerConfig) -> int:
    urls = _resolve_ping_urls(config.target_url, config.endpoints)
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    logging.info(
        "Starting Render waker target=%s urls=%s interval=%ss timeout=%ss retries=%s",
        config.target_url,
        list(urls),
        config.interval_seconds,
        config.timeout_seconds,
        config.retries,
    )

    cycle = 0
    successes = 0
    failures = 0
    next_run = time.monotonic()  # immediate first ping

    while not stop_event.is_set():
        now = time.monotonic()
        if now < next_run:
            stop_event.wait(next_run - now)
            continue

        cycle += 1
        result = _ping_cycle(config, urls, stop_event)

        if result.ok:
            successes += 1
            logging.info(
                "Ping success cycle=%s url=%s status=%s latency=%sms",
                cycle,
                result.url,
                result.status,
                result.latency_ms,
            )
            if config.once:
                break

            # Fire a little early to stay safely under Render's 15-minute idle limit.
            early_jitter = random.uniform(0, float(config.max_jitter_seconds))
            wait_seconds = max(1.0, float(config.interval_seconds) - early_jitter)
            next_run = time.monotonic() + wait_seconds
            logging.info(
                "Next heartbeat in %.2fs (configured=%ss early_jitter=%.2fs)",
                wait_seconds,
                config.interval_seconds,
                early_jitter,
            )
        else:
            failures += 1
            logging.error(
                "Ping cycle failed cycle=%s url=%s status=%s latency=%sms detail=%s",
                cycle,
                result.url,
                result.status,
                result.latency_ms,
                result.detail,
            )
            if config.once:
                break

            next_run = time.monotonic() + float(config.failure_retry_seconds)
            logging.warning(
                "Failure retry scheduled in %ss to recover quickly",
                config.failure_retry_seconds,
            )

    logging.info(
        "Waker stopped cycles=%s successes=%s failures=%s",
        cycle,
        successes,
        failures,
    )

    if config.once and failures > 0:
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
        config, log_level = _load_config(args)
        _setup_logging(log_level)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
