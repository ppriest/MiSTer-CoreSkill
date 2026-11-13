"""Detached runner for one job directory: run job.json's argv, log it, record how it ended."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

d = Path(sys.argv[1])
job = json.loads((d / "job.json").read_text(encoding="utf-8"))
status = d / "status.json"


def write(**kw):
    status.write_text(json.dumps(kw), encoding="utf-8")


def job_object(proc):
    """A Windows job object holding the child and everything it starts. taskkill /T follows
    parent PIDs, which MSYS bash -> make -> the test bench breaks (the bench kept running after
    a cancel and locked its exe); a job object does not care. None if it cannot be made."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = ctypes.c_void_p
        k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        h = k.CreateJobObjectW(None, None)
        if not h or not k.AssignProcessToJobObject(h, int(proc._handle)):
            return None
        return lambda: k.TerminateJobObject(h, 1)
    except Exception:
        return None


with open(d / "log.txt", "w", encoding="utf-8", errors="replace") as log:
    try:
        p = subprocess.Popen(job["argv"], cwd=job["cwd"], env=os.environ.copy(), stdout=log,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except Exception as e:
        log.write(f"could not start: {type(e).__name__}: {e}\n")
        write(state="failed", returncode=None, runner_pid=os.getpid(), ended=time.time())
        sys.exit(1)
    write(state="running", runner_pid=os.getpid(), child_pid=p.pid)
    kill_all = job_object(p)
    while True:
        rc = p.poll()
        if rc is not None:
            if kill_all and (d / "cancelled").exists():     # jobs_cancel's taskkill took the
                kill_all()                                  # direct tree; this takes the rest
            break
        if kill_all and (d / "cancelled").exists():
            kill_all()
        time.sleep(0.5)
write(state="cancelled" if (d / "cancelled").exists() else "done" if rc == 0 else "failed",
      returncode=rc, runner_pid=os.getpid(), child_pid=p.pid, ended=time.time())
