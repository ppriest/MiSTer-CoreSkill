"""Upload one file to the MiSTer, run as a job by mister_put (argv: pscp plink user@host local tmp dest).

The file goes to `tmp`, a hidden name beside the destination's tree root; its size is checked
against the local file, and only then is it renamed over `dest`. A failed or cancelled upload
therefore never leaves a truncated `dest`. The password is MISTER_PASSWORD in the environment.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

pscp, plink, target, local, tmp, dest = sys.argv[1:7]
pw = os.environ["MISTER_PASSWORD"]
size = Path(local).stat().st_size


def remote(cmd):
    p = subprocess.run([plink, "-batch", "-pw", pw, target, cmd], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def fail(msg):
    remote(f"rm -f {shlex.quote(tmp)}")
    print(f"FAILED: {msg}", flush=True)
    sys.exit(1)


print(f"{local} -> {dest}: {size} bytes, via {tmp}", flush=True)
rc, _, err = remote(f"mkdir -p {shlex.quote(os.path.dirname(dest))}")
if rc:
    fail(f"mkdir: {err}")
# -scp: pscp otherwise tries SFTP first, which the MiSTer does not serve
p = subprocess.run([pscp, "-scp", "-batch", "-pw", pw, local, f"{target}:{tmp}"], text=True)
if p.returncode:
    fail(f"pscp exited {p.returncode}")
rc, out, err = remote(f"stat -c %s {shlex.quote(tmp)}")
if rc or out != str(size):
    fail(f"remote size {out or err!r}, local {size}")
rc, _, err = remote(f"mv -f {shlex.quote(tmp)} {shlex.quote(dest)}")
if rc:
    fail(f"mv: {err}")
print(json.dumps({"remote": dest, "bytes": size}), flush=True)
