import asyncio
import contextlib
import os
import re
import sys
from collections import deque
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, field_validator


# ── Queue state ───────────────────────────────────────────────────────────────
# Initialized inside lifespan() so they are bound to uvicorn's event loop,
# not the import-time loop (which may differ or not exist yet).
_RUN_QUEUE_CONDITION: asyncio.Condition | None = None
_ACTIVE_REQUEST_ID: Optional[str] = None
_WAITING_REQUEST_IDS: deque[str] = deque()


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    """Initialize async primitives bound to uvicorn's event loop."""
    global _RUN_QUEUE_CONDITION
    _RUN_QUEUE_CONDITION = asyncio.Condition()
    yield
    # Cleanup on shutdown (nothing to clean up, but lifespan pattern is correct here)


app = FastAPI(title="LMS Auto-Feedback API", version="1.0.0", lifespan=_lifespan)

# ── CORS ───────────────────────────────────────────────────────────────────────
# Allow all origins so the Netlify-hosted frontend can reach this Render backend.
# Credentials are NOT included (we pass them in the JSON body, not cookies).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Cache-Control"],
)

# Absolute path of the project root (same directory as server.py)
PROJECT_ROOT = Path(__file__).parent.resolve()


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(parsed, minimum)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


MAX_QUEUE_DEPTH = _env_int("RUN_QUEUE_MAX_DEPTH", 5)
QUEUE_HEARTBEAT_SECONDS = _env_int("RUN_QUEUE_HEARTBEAT_SECONDS", 5)
STREAM_HEARTBEAT_SECONDS = _env_int("RUN_STREAM_HEARTBEAT_SECONDS", 15)



# ── Request schema ─────────────────────────────────────────────────────────────
class RunRequest(BaseModel):
    username: str
    password: str

    @field_validator("username", "password", mode="before")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        v = str(v).strip()
        if not v:
            raise ValueError("Field must not be blank")
        return v


# ── ANSI stripper ──────────────────────────────────────────────────────────────
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_TOKEN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|session|authorization|cookie)\s*[:=]\s*([^\s,;]+)"
)


def _sanitize_stream_line(text: str, username: str, password: str) -> str:
    sanitized = _ANSI_RE.sub("", text)
    for secret in (username, password):
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = _TOKEN_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", sanitized)
    return sanitized


async def _queue_enter(request_id: str) -> tuple[bool, int]:
    """Return (accepted, queue_position). Position 0 means run immediately."""
    global _ACTIVE_REQUEST_ID
    assert _RUN_QUEUE_CONDITION is not None, "Queue condition not initialized (lifespan not started)"

    async with _RUN_QUEUE_CONDITION:
        if _ACTIVE_REQUEST_ID is None and not _WAITING_REQUEST_IDS:
            _ACTIVE_REQUEST_ID = request_id
            return True, 0

        if len(_WAITING_REQUEST_IDS) >= MAX_QUEUE_DEPTH:
            return False, -1

        _WAITING_REQUEST_IDS.append(request_id)
        return True, len(_WAITING_REQUEST_IDS)


async def _queue_wait_for_turn(request_id: str):
    assert _RUN_QUEUE_CONDITION is not None, "Queue condition not initialized"
    while True:
        position = 0
        timed_out = False

        async with _RUN_QUEUE_CONDITION:
            if _ACTIVE_REQUEST_ID == request_id:
                return

            try:
                position = _WAITING_REQUEST_IDS.index(request_id) + 1
            except ValueError:
                raise RuntimeError("Request was removed from queue before execution")

            try:
                await asyncio.wait_for(_RUN_QUEUE_CONDITION.wait(), timeout=QUEUE_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                timed_out = True

        if timed_out:
            yield f"data: [QUEUED] position={position}\n\n"
            yield f"data: Waiting in queue (position {position})...\n\n"


async def _queue_exit(request_id: str) -> None:
    global _ACTIVE_REQUEST_ID
    assert _RUN_QUEUE_CONDITION is not None, "Queue condition not initialized"

    async with _RUN_QUEUE_CONDITION:
        if _ACTIVE_REQUEST_ID == request_id:
            if _WAITING_REQUEST_IDS:
                _ACTIVE_REQUEST_ID = _WAITING_REQUEST_IDS.popleft()
            else:
                _ACTIVE_REQUEST_ID = None
            _RUN_QUEUE_CONDITION.notify_all()
            return

        try:
            _WAITING_REQUEST_IDS.remove(request_id)
            _RUN_QUEUE_CONDITION.notify_all()
        except ValueError:
            pass


# ── SSE generator ──────────────────────────────────────────────────────────────
async def _run_bot_generator(username: str, password: str, request_id: str, initial_position: int):
    process: asyncio.subprocess.Process | None = None

    try:
        run_headful = _env_flag("BOT_HEADFUL", False)
        run_dry_run = _env_flag("BOT_DRY_RUN", False)

        if initial_position > 0:
            yield f"data: [QUEUED] position={initial_position}\n\n"
            yield f"data: Request accepted. Queue position: {initial_position}\n\n"

        async for queue_line in _queue_wait_for_turn(request_id):
            yield queue_line

        yield "data: [STARTED]\n\n"
        yield f"data: Execution slot acquired. Starting {'headful' if run_headful else 'headless'} automation...\n\n"

        env = os.environ.copy()
        env["LMS_USERNAME"] = username
        env["LMS_PASSWORD"] = password
        env["PYTHONUNBUFFERED"] = "1"      # no output buffering
        env["NO_COLOR"]         = "1"      # suppress Rich / logging ANSI
        env["FORCE_COLOR"]      = "0"
        env["TERM"]             = "dumb"
        env["BOT_NON_INTERACTIVE"] = "1"
        env["BOT_DISABLE_ERROR_ARTIFACTS"] = "1"
        env["BOT_SERVER_MODE"] = "1"
        env["REQUEST_ID"] = request_id

        cmd = [sys.executable, "main.py"]
        if run_headful:
            cmd.append("--headful")
        if run_dry_run:
            cmd.append("--dry-run")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=str(PROJECT_ROOT),
        )

        assert process.stdout is not None

        while True:
            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=STREAM_HEARTBEAT_SECONDS,
                )
            except asyncio.TimeoutError:
                yield "data: [HEARTBEAT]\n\n"
                yield "data: Automation is still running...\n\n"
                continue

            if not line:
                break
            text = _sanitize_stream_line(
                line.decode("utf-8", errors="replace").strip(),
                username=username,
                password=password,
            )
            if text:
                yield f"data: {text}\n\n"

        await process.wait()

        if process.returncode != 0:
            yield f"data: [ERROR] Process exited with code {process.returncode}\n\n"
            yield "data: [FAILED]\n\n"
        else:
            yield "data: [DONE]\n\n"

    except asyncio.CancelledError:
        if process and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
            except Exception:
                process.kill()
                await process.wait()
        raise
    except Exception as exc:
        yield f"data: [ERROR] Server runtime failure: {exc}\n\n"
        yield "data: [FAILED]\n\n"
    finally:
        if process and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
            except Exception:
                process.kill()
                await process.wait()

        await _queue_exit(request_id)

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/health")
@app.head("/")
@app.head("/health")
def health():
    """Health check — used by Render and uptime monitors."""
    return JSONResponse(
        {
            "status": "ok",
            "service": "lms-auto-feedback",
            "activeRun": _ACTIVE_REQUEST_ID is not None,
            "queuedRuns": len(_WAITING_REQUEST_IDS),
            "maxQueueDepth": MAX_QUEUE_DEPTH,
        }
    )


@app.post("/api/run")
async def run_bot(req: RunRequest):
    """
    Accepts credentials, spawns main.py, and streams its stdout as SSE.
    The frontend reads the stream and renders each line in the live terminal.
    """
    request_id = uuid4().hex[:10]
    accepted, position = await _queue_enter(request_id)
    if not accepted:
        return JSONResponse(
            {
                "error": "Run queue is full. Please retry shortly.",
                "maxQueueDepth": MAX_QUEUE_DEPTH,
            },
            status_code=429,
        )

    headers = {
        "Cache-Control":    "no-cache, no-store, must-revalidate",
        "Pragma":           "no-cache",
        "Expires":          "0",
        "X-Request-Id":     request_id,
        "X-Accel-Buffering": "no",          # stop Nginx from buffering SSE
        "Connection":        "keep-alive",
        "Content-Type":      "text/event-stream",
    }
    return StreamingResponse(
        _run_bot_generator(req.username, req.password, request_id, position),
        media_type="text/event-stream",
        headers=headers,
    )
