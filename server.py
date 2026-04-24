import asyncio
import contextlib
import os
import re
import sys
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, field_validator


# ── LRU Dict for bounded request metadata ──────────────────────────────────────
class LRURequestMetadata:
    """Thread-safe LRU dict that auto-evicts oldest entries when capacity exceeded."""
    def __init__(self, max_size: int = 50):
        self.max_size = max_size
        self._data: OrderedDict = OrderedDict()
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: dict) -> None:
        """Set key-value, evicting oldest if over capacity."""
        async with self._lock:
            if key in self._data:
                del self._data[key]  # Remove to re-add at end
            self._data[key] = value
            # Only attempt eviction if over capacity AND dict is not empty (guards StopIteration)
            if len(self._data) > self.max_size and len(self._data) > 1:
                try:
                    oldest_key = next(iter(self._data))
                    del self._data[oldest_key]
                except (StopIteration, KeyError):
                    pass  # Fallback: data already within limits or key disappeared

    async def get(self, key: str, default=None):
        """Get value by key."""
        async with self._lock:
            return self._data.get(key, default)

    async def pop(self, key: str, default=None):
        """Remove and return value."""
        async with self._lock:
            return self._data.pop(key, default)

    async def items(self):
        """Get items snapshot."""
        async with self._lock:
            return list(self._data.items())

    async def __contains__(self, key: str) -> bool:
        """Check key existence."""
        async with self._lock:
            return key in self._data

    async def __len__(self) -> int:
        """Get size."""
        async with self._lock:
            return len(self._data)


# ── Startup tracking (for cold-start detection) ─────────────────────────────────
_SERVICE_START_TIME: float = time.time()
_LAST_REQUEST_TIME: float = time.time()
_RESTART_REASON: Optional[str] = None
_CRASH_COUNT: int = 0

# ── Queue state ───────────────────────────────────────────────────────────────
# Initialized inside lifespan() so they are bound to uvicorn's event loop,
# not the import-time loop (which may differ or not exist yet).
_RUN_QUEUE_CONDITION: asyncio.Condition | None = None
_ACTIVE_REQUEST_ID: Optional[str] = None
_WAITING_REQUEST_IDS: deque[str] = deque()

# Per-request metadata with automatic LRU eviction (max 50 concurrent requests).
# Stores: username, student_name (from [BOT_META] line), start_time (epoch float).
_REQUEST_META: LRURequestMetadata | None = None

# Live subprocess handles — keyed by request_id so DELETE /api/run/{id} can kill them.
_ACTIVE_PROCESSES: dict[str, asyncio.subprocess.Process] = {}

# Estimated seconds a typical full automation run takes on the free Render tier.
_ETA_PER_RUN_SECONDS: int = int(os.getenv("BOT_ETA_SECONDS", "90"))

# Memory management: max number of concurrent request metadata entries
_REQUEST_META_MAX_SIZE: int = int(os.getenv("REQUEST_META_MAX_SIZE", "50"))

# Maximum allowed runtime for a single bot subprocess (in seconds, default 600 = 10 min)
_BOT_MAX_RUNTIME_SECONDS: int = int(os.getenv("BOT_MAX_RUNTIME", "600"))

# Max age before force-cleanup (seconds) — redundant safety net
_REQUEST_META_MAX_AGE: int = 600  # 10 minutes

async def _memory_cleanup_task():
    """Periodically garbage-collect old request metadata as safety net.
    LRU dict handles primary cleanup; this is redundant safety."""
    while True:
        try:
            await asyncio.sleep(120)  # cleanup every 2 minutes
            if _REQUEST_META is None:
                continue
            now = time.time()
            items = await _REQUEST_META.items()
            expired = [
                rid for rid, meta in items
                if meta.get("start_time") and (now - meta["start_time"]) > _REQUEST_META_MAX_AGE
            ]
            for rid in expired:
                await _REQUEST_META.pop(rid, None)
            if expired:
                print(f"[CLEANUP] Removed {len(expired)} expired request metadata entries (safety cleanup)", file=sys.stderr)
        except Exception:
            pass

@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    """Initialize async primitives bound to uvicorn's event loop."""
    global _RUN_QUEUE_CONDITION, _REQUEST_META
    _RUN_QUEUE_CONDITION = asyncio.Condition()
    _REQUEST_META = LRURequestMetadata(max_size=_REQUEST_META_MAX_SIZE)
    
    # Start background cleanup task
    cleanup_task = asyncio.create_task(_memory_cleanup_task())
    
    yield
    
    # Kill all active processes before shutdown (guaranteed cleanup)
    for request_id, process in list(_ACTIVE_PROCESSES.items()):
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3)
            except Exception:
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    logger.warning(f"Process {request_id} did not respond to SIGKILL during lifespan shutdown")
                except Exception:
                    pass
            finally:
                # Explicitly close pipes to free OS resources (safe even if None)
                try:
                    if process.stdout is not None and hasattr(process.stdout, 'close'):
                        try:
                            process.stdout.close()
                        except Exception:
                            pass
                except Exception:
                    pass
                
                try:
                    if process.stderr is not None and hasattr(process.stderr, 'close'):
                        try:
                            process.stderr.close()
                        except Exception:
                            pass
                except Exception:
                    pass
    
    # Cleanup on shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="LMS Auto-Feedback API", version="1.0.0", lifespan=_lifespan)

# ── CORS ───────────────────────────────────────────────────────────────────────
# Allow all origins so the Netlify-hosted frontend can reach this Render backend.
# Credentials are NOT included (we pass them in the JSON body, not cookies).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Cache-Control"],
    expose_headers=["X-Request-Id"],
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


async def _queue_enter(request_id: str, username: str) -> tuple[bool, int]:
    """Return (accepted, queue_position). Position 0 means run immediately."""
    global _ACTIVE_REQUEST_ID
    assert _RUN_QUEUE_CONDITION is not None, "Queue condition not initialized (lifespan not started)"
    assert _REQUEST_META is not None, "RequestMetadata not initialized"

    async with _RUN_QUEUE_CONDITION:
        meta = {
            "username": username,
            "student_name": "",
            "start_time": None,  # set when run actually begins
        }
        await _REQUEST_META.set(request_id, meta)

        if _ACTIVE_REQUEST_ID is None and not _WAITING_REQUEST_IDS:
            _ACTIVE_REQUEST_ID = request_id
            meta["start_time"] = time.time()
            await _REQUEST_META.set(request_id, meta)
            return True, 0

        if len(_WAITING_REQUEST_IDS) >= MAX_QUEUE_DEPTH:
            await _REQUEST_META.pop(request_id, None)
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
    assert _REQUEST_META is not None, "RequestMetadata not initialized"

    async with _RUN_QUEUE_CONDITION:
        if _ACTIVE_REQUEST_ID == request_id:
            if _WAITING_REQUEST_IDS:
                _ACTIVE_REQUEST_ID = _WAITING_REQUEST_IDS.popleft()
                # Record when this newly-active request actually starts running.
                if _ACTIVE_REQUEST_ID:
                    meta = await _REQUEST_META.get(_ACTIVE_REQUEST_ID)
                    if meta:
                        meta["start_time"] = time.time()
                        await _REQUEST_META.set(_ACTIVE_REQUEST_ID, meta)
            else:
                _ACTIVE_REQUEST_ID = None
            _RUN_QUEUE_CONDITION.notify_all()
            await _REQUEST_META.pop(request_id, None)
            return

        try:
            _WAITING_REQUEST_IDS.remove(request_id)
            _RUN_QUEUE_CONDITION.notify_all()
        except ValueError:
            pass
        await _REQUEST_META.pop(request_id, None)


# ── SSE generator with buffering for backpressure ────────────────────────────
class SSEBuffer:
    """Buffers SSE lines to reduce yielding overhead and provide backpressure."""
    def __init__(self, chunk_size_bytes: int = 512):
        self.chunk_size = max(64, chunk_size_bytes)  # Min chunk size to prevent pathological behavior
        self.buffer = []
        self.buffer_size = 0
    
    def add(self, line: str) -> list[str]:
        """Add line to buffer; return list of chunks to yield when buffer is full."""
        try:
            # Safely handle encoding edge cases (bytes, non-string, etc)
            if isinstance(line, bytes):
                line = line.decode('utf-8', errors='replace')
            elif not isinstance(line, str):
                line = str(line)
            
            sse_line = f"data: {line}\n\n"
            self.buffer.append(sse_line)
            # Track actual byte size for accurate chunking
            self.buffer_size += len(sse_line.encode('utf-8', errors='replace'))
            
            if self.buffer_size >= self.chunk_size:
                return self.flush()
            return []
        except Exception as e:
            # Fallback: flush on encoding error to prevent buffer corruption
            print(f"[SSEBuffer] Error encoding line: {e}", file=sys.stderr)
            return self.flush()
    
    def flush(self) -> list[str]:
        """Flush all buffered lines."""
        result = self.buffer
        self.buffer = []
        self.buffer_size = 0
        return result
    
    def has_pending(self) -> bool:
        """Check if buffer has pending data."""
        return len(self.buffer) > 0


async def _run_bot_generator(username: str, password: str, request_id: str, initial_position: int):
    process: asyncio.subprocess.Process | None = None
    sse_buffer = SSEBuffer(chunk_size_bytes=512)

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
        _ACTIVE_PROCESSES[request_id] = process

        assert process.stdout is not None

        # Track bot runtime to enforce global timeout
        run_start_time = time.time()

        while True:
            # Check if subprocess has exceeded max runtime
            elapsed_seconds = time.time() - run_start_time
            if elapsed_seconds > _BOT_MAX_RUNTIME_SECONDS:
                logger.warning(f"Bot subprocess {request_id} exceeded max runtime ({_BOT_MAX_RUNTIME_SECONDS}s), terminating")
                yield f"data: [ERROR] Automation exceeded maximum runtime ({_BOT_MAX_RUNTIME_SECONDS}s)\n\n"
                yield "data: [FAILED]\n\n"
                if process.returncode is None:
                    process.terminate()
                break

            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=STREAM_HEARTBEAT_SECONDS,
                )
            except asyncio.TimeoutError:
                # Flush any pending buffered logs before heartbeat
                for buffered_line in sse_buffer.flush():
                    yield buffered_line
                yield "data: [HEARTBEAT]\n\n"
                yield "data: Automation is still running...\n\n"
                continue

            if not line:
                break
            raw_text = line.decode("utf-8", errors="replace").strip()

            # Intercept [BOT_META] lines to populate queue metadata (not sent to client).
            if "[BOT_META]" in raw_text:
                meta_match = re.search(r"student_name=(.+)$", raw_text)
                if meta_match and _REQUEST_META:
                    meta = await _REQUEST_META.get(request_id)
                    if meta:
                        meta["student_name"] = meta_match.group(1).strip()
                        await _REQUEST_META.set(request_id, meta)
                continue  # do not forward meta lines to the SSE stream

            text = _sanitize_stream_line(raw_text, username=username, password=password)
            if text:
                # Buffer logs instead of yielding immediately for efficiency
                chunks_to_yield = sse_buffer.add(text)
                for chunk in chunks_to_yield:
                    yield chunk

        # Flush any remaining buffered logs at end of stream
        for buffered_line in sse_buffer.flush():
            yield buffered_line

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
            except asyncio.TimeoutError:
                logger.warning(f"Process {request_id} did not respond to terminate on cancel, forcing kill")
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    logger.error(f"Process {request_id} did not respond to SIGKILL on cancel")
                except Exception:
                    pass
            except Exception:
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    logger.error(f"Process {request_id} did not respond to SIGKILL on cancel")
                except Exception:
                    pass
        raise
    except Exception as exc:
        yield f"data: [ERROR] Server runtime failure: {exc}\n\n"
        yield "data: [FAILED]\n\n"
    finally:
        # Guaranteed process cleanup with resource deallocation
        _ACTIVE_PROCESSES.pop(request_id, None)
        if process and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(f"Process {request_id} did not respond to terminate in finally, forcing kill")
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    logger.error(f"Process {request_id} did not respond to SIGKILL in finally block")
                except Exception:
                    pass
            except Exception:
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    logger.error(f"Process {request_id} did not respond to SIGKILL in finally block")
                except Exception:
                    pass
        
        # Explicitly close pipes to free OS resources (safe even if None)
        if process:
            try:
                if process.stdout is not None and hasattr(process.stdout, 'close'):
                    try:
                        process.stdout.close()
                    except Exception:
                        pass
            except Exception:
                pass
            
            try:
                if process.stderr is not None and hasattr(process.stderr, 'close'):
                    try:
                        process.stderr.close()
                    except Exception:
                        pass
            except Exception:
                pass

        await _queue_exit(request_id)

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/health")
@app.head("/")
@app.head("/health")
def health():
    """Enhanced health check with startup diagnostics for cold-start detection."""
    global _LAST_REQUEST_TIME
    
    now = time.time()
    uptime_seconds = now - _SERVICE_START_TIME
    seconds_since_last_request = now - _LAST_REQUEST_TIME
    
    # Update last request time AFTER computing elapsed (fixes diagnostic reporting)
    _LAST_REQUEST_TIME = time.time()
    
    # Determine if service is cold-starting (booted <30 seconds ago)
    is_cold_start = uptime_seconds < 30
    
    return JSONResponse(
        {
            "status": "ok",
            "service": "lms-auto-feedback",
            "activeRun": _ACTIVE_REQUEST_ID is not None,
            "queuedRuns": len(_WAITING_REQUEST_IDS),
            "maxQueueDepth": MAX_QUEUE_DEPTH,
            # ── Diagnostics for cold-start detection ────────────────────────────
            "uptime_seconds": int(uptime_seconds),
            "is_cold_start": is_cold_start,
            "seconds_since_last_request": int(seconds_since_last_request),
            "crash_count": _CRASH_COUNT,
            "restart_reason": _RESTART_REASON,
        }
    )


@app.get("/api/queue")
async def get_queue():
    """Return live queue state for the frontend queue panel."""
    now = time.time()

    async def _format_entry(request_id: str, position: int) -> dict:
        meta = await _REQUEST_META.get(request_id, {}) if _REQUEST_META else {}
        start = meta.get("start_time") if meta else None
        if position == 0 and start is not None:
            # Active run: ETA = estimated_total - elapsed (floor at 0)
            elapsed = now - start
            eta_secs = max(0, int(_ETA_PER_RUN_SECONDS - elapsed))
        else:
            # Queued: active run remaining + (position * full ETA)
            active_meta = await _REQUEST_META.get(_ACTIVE_REQUEST_ID or "", {}) if _REQUEST_META and _ACTIVE_REQUEST_ID else {}
            active_start = active_meta.get("start_time") if active_meta else None
            active_remaining = max(0, _ETA_PER_RUN_SECONDS - (now - active_start)) if active_start else _ETA_PER_RUN_SECONDS
            eta_secs = int(active_remaining + position * _ETA_PER_RUN_SECONDS)

        return {
            "requestId": request_id,
            "username": meta.get("username", "") if meta else "",
            "studentName": meta.get("student_name", "") if meta else "",
            "position": position,
            "etaSeconds": eta_secs,
        }

    active: dict | None = None
    if _ACTIVE_REQUEST_ID:
        active = await _format_entry(_ACTIVE_REQUEST_ID, 0)

    waiting = [
        await _format_entry(rid, idx + 1)
        for idx, rid in enumerate(_WAITING_REQUEST_IDS)
    ]

    return JSONResponse({
        "active": active,
        "waiting": waiting,
        "etaPerRunSeconds": _ETA_PER_RUN_SECONDS,
    })


@app.delete("/api/run/{request_id}")
async def cancel_run(request_id: str):
    """
    Immediately kill a running/queued bot process and remove it from the queue.
    Called by the frontend Stop button so the server-side run is truly terminated.
    """
    process = _ACTIVE_PROCESSES.get(request_id)
    if process and process.returncode is None:
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        _ACTIVE_PROCESSES.pop(request_id, None)

    await _queue_exit(request_id)
    return JSONResponse({"cancelled": True, "requestId": request_id})


@app.post("/api/run")
async def run_bot(req: RunRequest):
    """
    Accepts credentials, spawns main.py, and streams its stdout as SSE.
    The frontend reads the stream and renders each line in the live terminal.
    """
    request_id = uuid4().hex[:10]
    accepted, position = await _queue_enter(request_id, req.username)
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


@app.get("/api/diagnostics")
def get_diagnostics():
    """
    Detailed diagnostics endpoint for debugging cold-start, crashes, and service state.
    Frontend uses this to show helpful warnings when service is unhealthy.
    """
    now = time.time()
    uptime_seconds = now - _SERVICE_START_TIME
    
    # Define service state based on diagnostics
    if uptime_seconds < 30:
        service_state = "COLD_START"
        reason = "Service was just deployed or restarted. Expect 20-30s latency."
    elif _CRASH_COUNT > 0 and uptime_seconds < 300:
        service_state = "RECOVERING_FROM_CRASH"
        reason = f"Service crashed {_CRASH_COUNT} time(s) recently. Restart reason: {_RESTART_REASON}"
    elif _ACTIVE_REQUEST_ID and len(_WAITING_REQUEST_IDS) >= 2:
        service_state = "BUSY"
        reason = f"Service is running {len(_WAITING_REQUEST_IDS)} queued automations."
    else:
        service_state = "HEALTHY"
        reason = "Service is healthy and ready to accept requests."
    
    return JSONResponse(
        {
            "service_state": service_state,
            "reason": reason,
            "uptime_seconds": int(uptime_seconds),
            "is_cold_start": uptime_seconds < 30,
            "is_recovering": _CRASH_COUNT > 0 and uptime_seconds < 300,
            "crash_count": _CRASH_COUNT,
            "restart_reason": _RESTART_REASON,
            "active_run": _ACTIVE_REQUEST_ID is not None,
            "queued_runs": len(_WAITING_REQUEST_IDS),
            "max_queue_depth": MAX_QUEUE_DEPTH,
            "queue_full": len(_WAITING_REQUEST_IDS) >= MAX_QUEUE_DEPTH,
            "seconds_since_last_request": int(now - _LAST_REQUEST_TIME),
            "recommendations": _get_recommendations(service_state, uptime_seconds),
        }
    )


def _get_recommendations(service_state: str, uptime_seconds: float) -> list[str]:
    """Return actionable recommendations based on service state."""
    recs = []
    
    if service_state == "COLD_START":
        recs.append("Service is initializing. Wait 30-60 seconds before retrying.")
        recs.append("This is normal after a fresh deploy or Render restart.")
    elif service_state == "RECOVERING_FROM_CRASH":
        recs.append("Service recently crashed. If crashes persist, check Render logs.")
        recs.append("Verify in Render UI that 'Always On' is enabled (prevents spin-down).")
        recs.append("Check if service memory is full: look for 'Out of Memory' errors.")
    elif service_state == "BUSY":
        recs.append("Queue is full. Multiple requests are queued ahead of you.")
        recs.append("Each automation takes ~60-120 seconds. Retry in 2-3 minutes.")
    else:
        recs.append("✅ Service is healthy. You should be able to run now.")
    
    if uptime_seconds < 600:
        recs.append("Note: Server has been up for <10 min. May have 5-10s latency.")
    
    return recs
