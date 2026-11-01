"""Copy one file to or from the MiSTer, run as a job by mister_put and mister_get.

    xfer.py put pscp plink user@host local remote
    xfer.py get pscp plink user@host local remote [rm]

The copy goes to <destination>.partial beside the destination; its size is checked against the
source, and only then is it renamed over the destination. A failed or cancelled copy therefore
never leaves a truncated destination. `rm` (get): remove the remote file afterwards. The password
is MISTER_PASSWORD in the environment. The last output line is the result as JSON.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

mode, pscp, plink, target, local, remote = sys.argv[1:7]
rm_after = "rm" in sys.argv[7:]
pw = os.environ["MISTER_PASSWORD"]


def ssh(cmd):
    p = subprocess.run([plink, "-batch", "-pw", pw, target, cmd], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def fail(msg, cleanup):
    cleanup()
    print(f"FAILED: {msg}", flush=True)
    sys.exit(1)


def copy(src, dst):
    # -scp: pscp otherwise tries SFTP first, which is slower on the MiSTer (0.2 against 4 MB/s
    # for 20 MB, measured), and the remote shell then parses the remote path
    p = subprocess.run([pscp, "-scp", "-batch", "-pw", pw, src, dst], text=True)
    return p.returncode


if mode == "put":
    size = Path(local).stat().st_size
    tmp = remote + ".partial"
    clean = lambda: ssh(f"rm -f {shlex.quote(tmp)}")
    print(f"{local} -> {remote}: {size} bytes, via {tmp}", flush=True)
    rc, _, err = ssh(f"mkdir -p {shlex.quote(os.path.dirname(remote))}")
    if rc:
        fail(f"mkdir: {err}", clean)
    if copy(local, f"{target}:{shlex.quote(tmp)}"):
        fail("pscp failed", clean)
    rc, out, err = ssh(f"stat -c %s {shlex.quote(tmp)}")
    if rc or out != str(size):
        fail(f"remote size {out or err!r}, local {size}", clean)
    rc, _, err = ssh(f"mv -f {shlex.quote(tmp)} {shlex.quote(remote)}")
    if rc:
        fail(f"mv: {err}", clean)
    print(json.dumps({"remote": remote, "bytes": size}), flush=True)
else:
    tmp = local + ".partial"
    clean = lambda: Path(tmp).unlink(missing_ok=True)
    rc, out, err = ssh(f"stat -c %s {shlex.quote(remote)}")
    if rc:
        fail(f"remote stat: {err}", clean)
    size = int(out)
    print(f"{remote} -> {local}: {size} bytes, via {tmp}", flush=True)
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    if copy(f"{target}:{shlex.quote(remote)}", tmp):
        fail("pscp failed", clean)
    if Path(tmp).stat().st_size != size:
        fail(f"local size {Path(tmp).stat().st_size}, remote {size}", clean)
    os.replace(tmp, local)
    res = {"remote": remote, "local": local, "bytes": size}
    if rm_after:
        rc, _, err = ssh(f"rm -f {shlex.quote(remote)}")
        res["removed"] = not rc
    print(json.dumps(res), flush=True)
