import asyncio
import os
import re
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, field_validator

app = FastAPI(title="LMS Auto-Feedback API", version="1.0.0")

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


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ── SSE generator ──────────────────────────────────────────────────────────────
async def _run_bot_generator(username: str, password: str):
    env = os.environ.copy()
    env["LMS_USERNAME"]    = username
    env["LMS_PASSWORD"]    = password
    env["PYTHONUNBUFFERED"] = "1"      # no output buffering
    env["NO_COLOR"]         = "1"      # suppress Rich / logging ANSI
    env["FORCE_COLOR"]      = "0"
    env["TERM"]             = "dumb"

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "main.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        cwd=str(PROJECT_ROOT),
    )

    try:
        assert process.stdout is not None

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = _strip_ansi(line.decode("utf-8", errors="replace")).strip()
            if text:
                yield f"data: {text}\n\n"

        await process.wait()

        if process.returncode != 0:
            yield f"data: [ERROR] Process exited with code {process.returncode}\n\n"
            yield "data: [FAILED]\n\n"
        else:
            yield "data: [DONE]\n\n"

    except asyncio.CancelledError:
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception:
            process.kill()
        raise


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/health")
@app.head("/")
@app.head("/health")
def health():
    """Health check — used by Render and uptime monitors."""
    return JSONResponse({"status": "ok", "service": "lms-auto-feedback"})


@app.post("/api/run")
async def run_bot(req: RunRequest):
    """
    Accepts credentials, spawns main.py, and streams its stdout as SSE.
    The frontend reads the stream and renders each line in the live terminal.
    """
    headers = {
        "Cache-Control":    "no-cache, no-store",
        "X-Accel-Buffering": "no",          # stop Nginx from buffering SSE
        "Connection":        "keep-alive",
        "Content-Type":      "text/event-stream",
    }
    return StreamingResponse(
        _run_bot_generator(req.username, req.password),
        media_type="text/event-stream",
        headers=headers,
    )
