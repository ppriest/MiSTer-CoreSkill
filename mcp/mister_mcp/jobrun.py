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
    rc = p.wait()
write(state="cancelled" if (d / "cancelled").exists() else "done" if rc == 0 else "failed",
      returncode=rc, runner_pid=os.getpid(), child_pid=p.pid, ended=time.time())
