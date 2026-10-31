"""A job's log over a WebSocket, for Claude Code's Monitor (ws source): one text frame per log
line, then `END {"state": ..., "returncode": ...}` when the job ends, then close.

    ws://127.0.0.1:8770/jobs/<id>/log?grep=<regex>&from=end|start|<line>

`from` defaults to end (only lines written after connecting). Every terminal state ends the
stream: done, failed, cancelled, and lost (the runner died without recording an end).
"""
import asyncio
import json
import re
from urllib.parse import urlparse

from starlette.websockets import WebSocket, WebSocketDisconnect

from . import jobs as J
from .cores import ToolError

POLL = 1.0
LOCAL = {"127.0.0.1", "localhost", "::1"}


def _line_offset(path, n):
    """Byte offset just past the n-th newline (or the end of the file)."""
    off = seen = 0
    with open(path, "rb") as f:
        while seen < n:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            for i, b in enumerate(chunk):
                if b == 10:
                    seen += 1
                    if seen == n:
                        return off + i + 1
            off += len(chunk)
    return off


async def job_log(ws: WebSocket, record=None):
    # No token (local only), but a web page can open a socket to localhost: refuse browser origins
    origin = ws.headers.get("origin")
    if origin and urlparse(origin).hostname not in LOCAL:
        await ws.close(code=1008)
        return
    await ws.accept()
    jid = ws.path_params["id"]
    q = ws.query_params
    try:
        d = J._dir(jid)
        rx = re.compile(q["grep"]) if q.get("grep") else None
    except (ToolError, re.error) as e:
        await ws.send_text(f"ERROR {e}")
        await ws.close(code=1008)
        return
    if record:
        record({"tool": "ws:jobs_log", "args": {"id": jid, **dict(q)}})
    log = d / "log.txt"
    start = q.get("from", "end")
    if start == "start":
        off = 0
    elif start.isdigit():
        off = _line_offset(log, int(start)) if log.exists() else 0
    else:
        off = log.stat().st_size if log.exists() else 0
    rest = b""
    try:
        while True:
            st = await asyncio.to_thread(J.status, jid, 0)
            ended = st["state"] not in ("starting", "running")
            if log.exists():
                with open(log, "rb") as f:
                    f.seek(off)
                    data = f.read()
                off += len(data)
                parts = (rest + data).split(b"\n")
                rest = parts.pop()
                if ended and rest:
                    parts.append(rest)
                    rest = b""
                for p in parts:
                    ln = p.decode("utf-8", errors="replace").rstrip("\r")
                    if not rx or rx.search(ln):
                        await ws.send_text(ln)
            if ended:
                await ws.send_text("END " + json.dumps({"id": jid, "state": st["state"],
                                                        "returncode": st["returncode"],
                                                        "elapsed_s": st["elapsed_s"]}))
                await ws.close()
                return
            await asyncio.sleep(POLL)
    except WebSocketDisconnect:
        return
