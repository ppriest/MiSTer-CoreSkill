"""Run builds of one core, one seed each, a few at a time; stop the rest at the first that meets timing.

Run as a job by build_sweep: argv is one JSON document,
    {"jobs": [{"seed": 4, "stage": "build_seed4", "argv": [...], "env": {...}, "cwd": "..."}, ...],
     "max_parallel": 3}
Each child is build_staged.py in its own stage, so they do not share a worktree. A child that exits 0
met timing and passed the design checks; the others are killed (whole process tree) and the
seeds not yet started are skipped. The last line printed is the result as JSON.
"""
import json
import os
import subprocess
import sys
import threading
import time

spec = json.loads(sys.argv[1])
pending = list(spec["jobs"])
limit = max(1, int(spec.get("max_parallel", 3)))
running = {}                      # seed -> (job, Popen)
results = {}


def pump(seed, proc):
    for ln in proc.stdout:
        print(f"[seed {seed}] {ln.rstrip()}", flush=True)


def start(job):
    env = dict(os.environ, **job.get("env", {}))
    p = subprocess.Popen(job["argv"], cwd=job["cwd"], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    threading.Thread(target=pump, args=(job["seed"], p), daemon=True).start()
    running[job["seed"]] = (job, p)
    print(f"[sweep] started seed {job['seed']} in {job['stage']}", flush=True)


def kill(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        p.kill()


winner = None
while (pending or running) and winner is None:
    while pending and len(running) < limit:
        start(pending.pop(0))
    time.sleep(3)
    for seed, (job, p) in list(running.items()):
        rc = p.poll()
        if rc is None:
            continue
        del running[seed]
        results[seed] = "met timing" if rc == 0 else f"failed (exit {rc})"
        print(f"[sweep] seed {seed}: {results[seed]}", flush=True)
        if rc == 0 and winner is None:
            winner = job

for seed, (job, p) in running.items():
    kill(p)
    try:                                      # killed with /F, so its finally did not remove this
        os.remove(os.path.join(job["cwd"], job["stage"], ".build_running"))
    except OSError:
        pass
    results[seed] = "stopped: another seed met timing"
for job in pending:
    results[job["seed"]] = "skipped: another seed met timing"
print(json.dumps({"winner": winner["seed"] if winner else None, "stage": winner["stage"] if winner else None,
                  "seeds": {str(k): v for k, v in sorted(results.items())}}), flush=True)
sys.exit(0 if winner else 1)
