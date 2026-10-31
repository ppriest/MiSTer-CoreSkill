"""Long runs (builds, simulations, MAME captures) as jobs on disk.

Each job is a directory under ~/.mister/mcp/jobs/<id>: job.json (what and how),
log.txt (stdout and stderr), status.json (written by the runner). The runner is a detached
process, so a job outlives the session that started it and every session sees every job.
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .cores import NO_WINDOW, ToolError, tail

# ~/.mister, as hwlock and identity use: the Claude desktop app's processes see a private copy of
# %LOCALAPPDATA%, so state kept there is not shared with this server or anything it starts
STATE = Path(os.environ.get("MISTER_STATE_DIR") or Path.home() / ".mister")
BASE = STATE / "mcp" / "jobs"
RUNNER = Path(__file__).with_name("jobrun.py")
DETACH = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
          | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0


def start(kind, core, argv, cwd, env, meta=None):
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = BASE / jid
    d.mkdir(parents=True)
    job = {"id": jid, "kind": kind, "core": core, "argv": argv, "cwd": str(cwd),
           "env": {k: v for k, v in env.items() if k in ("CORE_ROOT", "CORE_REV", "PYTHONIOENCODING",
                                                          "MSYS_NO_PATHCONV")},
           "meta": meta or {}, "started": time.time()}
    (d / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    full_env = dict(env)
    # Out of the scheduled task's job object where it allows that, so that stopping the task
    # (a server restart) does not kill a running build; refused breakaway raises, so retry inside
    def spawn(flags):
        subprocess.Popen([sys.executable, str(RUNNER), str(d)], cwd=cwd, env=full_env,
                         creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        spawn(DETACH | (subprocess.CREATE_BREAKAWAY_FROM_JOB if os.name == "nt" else 0))
    except PermissionError:
        spawn(DETACH)
    for _ in range(50):                       # the runner writes status.json at once
        if (d / "status.json").exists():
            break
        time.sleep(0.1)
    return jid


def _dir(jid):
    d = BASE / jid
    if not (d / "job.json").exists():
        raise ToolError(f"no job {jid}")
    return d


def _alive(pid):
    if not pid:
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                       **NO_WINDOW)
    return str(pid) in r.stdout


def _read_status(d):
    return json.loads((d / "status.json").read_text(encoding="utf-8")) if (d / "status.json").exists() \
        else {"state": "starting"}


def status(jid, log_lines=20):
    d = _dir(jid)
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    st = _read_status(d)
    if st.get("state") == "running" and not _alive(st.get("runner_pid")):
        st = _read_status(d)                  # it may have written its end since the first read
        if st.get("state") == "running":
            st["state"] = "lost"              # the runner died without writing its end
    log = (d / "log.txt").read_text(encoding="utf-8", errors="replace") if (d / "log.txt").exists() else ""
    end = st.get("ended") or time.time()
    return {"id": jid, "kind": job["kind"], "core": job["core"], "meta": job["meta"],
            "state": st["state"], "returncode": st.get("returncode"),
            "elapsed_s": round(end - job["started"]), "log_tail": tail(log, log_lines),
            "log_path": str(d / "log.txt")}


def log(jid):
    d = _dir(jid)
    return (d / "log.txt").read_text(encoding="utf-8", errors="replace") if (d / "log.txt").exists() else ""


# Claude Code drops a call that sends nothing for 300 s, so no wait may come near that
MAX_WAIT = 240


def wait(jid, seconds):
    capped = seconds > MAX_WAIT
    deadline = time.time() + min(max(0, seconds), MAX_WAIT)
    while True:
        s = status(jid, log_lines=0)
        if s["state"] not in ("starting", "running") or time.time() >= deadline:
            if capped and s["state"] in ("starting", "running"):
                s["note"] = f"waited the maximum {MAX_WAIT} s; call jobs_status again"
            return s
        time.sleep(2)


def listing(limit=20, active_only=False):
    out = []
    for d in sorted(BASE.glob("*"), reverse=True) if BASE.exists() else []:
        if not (d / "job.json").exists():
            continue
        s = status(d.name, log_lines=0)
        s.pop("log_tail", None)
        if active_only and s["state"] not in ("starting", "running"):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def cancel(jid):
    d = _dir(jid)
    st = _read_status(d)
    if st.get("state") not in ("starting", "running"):
        return {"id": jid, "state": st.get("state"), "note": "not running"}
    (d / "cancelled").touch()                 # the runner records "cancelled", not the exit code
    # /T takes the tree: quartus_sh -> quartus_fit, vsim -> vsimk, mame
    pid = st.get("child_pid") or st.get("runner_pid")
    r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, text=True,
                       **NO_WINDOW)
    return {"id": jid, "state": wait(jid, 10)["state"], "taskkill": (r.stdout + r.stderr).strip()}


def meta(jid):
    return json.loads((_dir(jid) / "job.json").read_text(encoding="utf-8"))
