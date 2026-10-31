"""The status page: http://127.0.0.1:8770/ shows the cores, their settings, the JTAG and
Quartus/ModelSim state, jobs, deploys and recent calls; logs download from it.

    /                         the page (status.html)
    /api/state                everything on the page, as JSON
    /api/board                read what the MiSTer is running now (/api/state has the monitor's last reading)
    /api/jobs/<id>            a job's status and log tail
    /download/jobs/<id>/log.txt, /download/<file>   files, as attachments

Read-only. Requests whose Host or Origin is not this machine are refused, so a web page
elsewhere cannot read this one through DNS rebinding.
"""
import hashlib
import json
import os
import subprocess
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from . import cores as C
from . import jobs as J
from .cores import ToolError
from .link import MONITOR

LOCAL = {"127.0.0.1", "localhost", "::1", "[::1]"}
PAGE = Path(__file__).with_name("status.html")
STARTED = time.time()
CALLS_TAIL = 256 * 1024                      # bytes of calls.jsonl the page reads: ~800 calls


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", str(C.SKILL.parent), *args],
                           capture_output=True, text=True, timeout=10, **C.NO_WINDOW)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _commit():
    return _git("log", "-1", "--format=%h %s")


# What this process has loaded: a change here needs a restart. The page itself is read per
# request, and the job runners and the core scripts start fresh for every job. Compared by
# content against what was on disk at start, committed or not.
RUNNERS = {"jobrun.py", "qproject.py", "issp_seq.py"}
LOADED = sorted([p for p in Path(__file__).parent.glob("*.py") if p.name not in RUNNERS]
                + [C.TEMPLATE_SCRIPTS / "coretools.py", C.TEMPLATE_SCRIPTS / "hwlock.py"])
STARTED_COMMIT = _commit()


def _digest(p):
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return None


AT_START = {p: _digest(p) for p in LOADED}


def _changed_since_start():
    """Loaded files whose content differs from what this process started with."""
    root = C.SKILL.parent
    return [str(p.relative_to(root)).replace("\\", "/") for p in LOADED if _digest(p) != AT_START[p]]


def _local(request):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    origin = request.headers.get("origin")
    return host in LOCAL and (not origin or urlparse(origin).hostname in LOCAL)


def _guard(fn):
    def endpoint(request):
        if not _local(request):
            return PlainTextResponse("not a local request", status_code=403)
        try:
            return fn(request)
        except ToolError as e:
            return PlainTextResponse(str(e), status_code=404)
    return endpoint


def _branch(root):
    """The checked-out branch from .git/HEAD (a worktree's .git is a file naming its gitdir)."""
    g = root / ".git"
    try:
        if g.is_file():
            g = Path(g.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, IndexError):
        return None
    return head.rsplit("/", 1)[-1] if head.startswith("ref:") else head[:10]


def _calls(path, n):
    rows = deque(maxlen=n)
    if path.exists():
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - CALLS_TAIL))
            for ln in f.read().decode("utf-8", "replace").splitlines():
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    pass                      # the first line is usually cut
    return list(rows)


def _deploys(n):
    p = J.STATE / "mister_deployed.tsv"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
        f = (ln.rstrip("\r").split("\t") + [""] * 4)[:4]
        out.append(dict(zip(("rbf", "core", "commit", "t"), f)))
    return out[::-1]


def _snapshot(path, name):
    """The file as it is now, as an attachment. Logs and calls.jsonl grow while they are sent,
    and a FileResponse would then send more than the Content-Length it declared."""
    size = path.stat().st_size

    def body():
        left = size
        with open(path, "rb") as f:
            while left > 0:
                chunk = f.read(min(left, 1 << 20))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk
    return StreamingResponse(body(), media_type="text/plain; charset=utf-8", headers={
        "Content-Length": str(size), "Content-Disposition": f'attachment; filename="{name}"'})


PATH_KEYS = ("MAME_DIR", "MAME_SRC", "QUARTUS_BIN", "MODELSIM_BIN")


def _checked(settings):
    """Mark settings that name a path which does not exist (a pruned MAME worktree, say)."""
    for k in PATH_KEYS:
        v = settings.get(k, {}).get("value")
        if v:
            settings[k]["exists"] = Path(v).exists()
    d, exe = settings.get("MAME_DIR", {}).get("value"), settings.get("MAME_EXE", {}).get("value")
    if d:
        settings.setdefault("MAME_EXE", {"value": None, "from": "unset"})["exists"] = \
            (Path(d) / (exe or "mame.exe")).exists()
    return settings


def routes(core_settings, calls_path):
    """core_settings(root) and the calls.jsonl path come from server.py, which imports this."""
    import hwlock
    files = {"calls.jsonl": calls_path, "calls.1.jsonl": calls_path.with_name("calls.1.jsonl"),
             "server.log": J.BASE.parent / "server.log",
             "mister_deployed.tsv": J.STATE / "mister_deployed.tsv"}

    def state(request):
        calls = _calls(calls_path, 150)
        last = {}
        for c in calls:
            core = (c.get("args") or {}).get("core")
            if core:
                last[core] = c["t"]
        jobs = J.listing(60)
        active = {}
        for j in jobs:
            if j["state"] in ("starting", "running"):
                active.setdefault(j["core"], []).append(f'{j["kind"]} {j["id"]}')
        cores = []
        for name, paths in C.all_cores().items():
            for root in paths:
                s = core_settings(root)
                short = s["core"]
                cores.append({
                    "name": name, "short": short, "path": str(root), "duplicate": len(paths) > 1,
                    "branch": _branch(root), "settings": _checked(s["settings"]),
                    "own_scripts": (root / "scripts" / "coretools.py").exists(),
                    "active": active.get(name, []),
                    "last_call": max((last.get(k, "") for k in (name, short, str(root))), default="") or None})
        held = hwlock.read_marker()
        return JSONResponse({
            "now": time.strftime("%Y-%m-%d %H:%M:%S"),
            "server": {"pid": os.getpid(), "port": request.url.port,
                       "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(STARTED)),
                       "uptime_s": round(time.time() - STARTED), "commit_at_start": STARTED_COMMIT,
                       "commit_now": _commit(), "restart_for": _changed_since_start(),
                       "state_dir": str(J.STATE),
                       "machine_env": str(C.coretools.machine_env_path()),
                       "cores_dirs": [str(d) for d in C.cores_dirs()]},
            "locks": {"jtag_held": {"pid": held[0], "what": held[1]} if held else None,
                      "jtag_waiting": [{"pid": p, "what": w} for p, w in hwlock.waiting_sessions()],
                      "quartus_modelsim": hwlock.quartus_processes()},
            "board": MONITOR.snapshot(), "jobs": jobs, "cores": cores, "deploys": _deploys(30), "calls": calls[::-1],
            "files": {k: {"size": p.stat().st_size} for k, p in files.items() if p.exists()}})

    def board(request):
        """Read the board now (the monitor reads it every POLL seconds anyway)."""
        try:
            MONITOR.read()
        except (ToolError, SystemExit, OSError) as e:
            MONITOR.error = str(e) or type(e).__name__
        return JSONResponse(MONITOR.snapshot())

    def job(request):
        jid = request.path_params["id"]
        return JSONResponse(J.status(jid, int(request.query_params.get("lines", 200))))

    def job_log(request):
        jid = request.path_params["id"]
        p = J._dir(jid) / "log.txt"
        if not p.exists():
            raise ToolError(f"job {jid} has no log yet")
        return _snapshot(p, f"{jid}.log.txt")

    def download(request):
        name = request.path_params["name"]
        if name not in files or not files[name].exists():
            raise ToolError(f"no file {name}")
        return _snapshot(files[name], name)

    def page(request):
        return FileResponse(PAGE, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    return [Route("/", _guard(page)), Route("/api/state", _guard(state)),
            Route("/api/board", _guard(board)), Route("/api/jobs/{id}", _guard(job)),
            Route("/download/jobs/{id}/log.txt", _guard(job_log)),
            Route("/download/{name}", _guard(download))]
