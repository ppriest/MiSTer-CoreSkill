"""The MiSTer: plink/pscp and the Remote API, limited to the operations the tools offer.

No general shell: commands are built here from checked arguments, and file transfer is limited
to the trees a core session needs.
"""
import json
import os
import re
import shlex
import subprocess
import time
import urllib.request
from pathlib import Path, PurePosixPath

from .cores import NO_WINDOW, ToolError, coretools

ALLOWED = ("/media/fat/_Arcade", "/media/fat/games", "/media/fat/config", "/media/fat/screenshots")
READ_ONLY = ("/tmp/RBFNAME", "/tmp/CORENAME", "/tmp/FULLPATH", "/tmp/STARTPATH")
CORES = "/media/fat/_Arcade/cores"
ZIPS = "/media/fat/games/mame"


def _env(root=None):
    """The board's connection: the environment, then ~/.mister-core.env, never a core's mister.env.
    There is one board, so per-core copies could only drift. Read per call: an edit to the file
    applies at the next call. `root` is accepted and ignored."""
    keys = ("MISTER_HOST", "MISTER_USER", "MISTER_PASSWORD")
    try:
        env = coretools.load_env(path=coretools.machine_env_path(), require=keys)
        env.update({k: os.environ[k] for k in keys if os.environ.get(k)})
        return env
    except SystemExit as e:
        raise ToolError(str(e))


def _putty(name):
    try:
        return coretools.find_putty(name)
    except SystemExit as e:
        raise ToolError(str(e))


def checked_path(p, write=False):
    q = str(PurePosixPath(p))
    if ".." in PurePosixPath(q).parts or not q.startswith("/"):
        raise ToolError(f"{p}: give an absolute path without '..'")
    if not write and q in READ_ONLY:
        return q
    if not any(q == a or q.startswith(a + "/") for a in ALLOWED):
        raise ToolError(f"{p} is outside {', '.join(ALLOWED)}")
    return q


class Board:
    def __init__(self, root=None):
        env = _env(root)
        self.host, self.user, self.pw = env["MISTER_HOST"], env["MISTER_USER"], env["MISTER_PASSWORD"]
        self.api = f"http://{self.host}:8182/api"

    def sh(self, command, timeout=60):
        try:
            p = subprocess.run([_putty("plink.exe"), "-ssh", "-batch", "-pw", self.pw,
                                f"{self.user}@{self.host}", command],
                               capture_output=True, text=True, timeout=timeout, **NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise ToolError(f"no answer from {self.host} in {timeout} s")
        return p.returncode, p.stdout, p.stderr

    def scp(self, src, dst, timeout=300):
        # -scp: pscp otherwise tries SFTP first, which the MiSTer does not serve
        p = subprocess.run([_putty("pscp.exe"), "-scp", "-batch", "-pw", self.pw, src, dst],
                           capture_output=True, text=True, timeout=timeout, **NO_WINDOW)
        if p.returncode:
            raise ToolError(f"pscp failed: {(p.stderr or p.stdout).strip()}")

    def remote(self, path):
        return f"{self.user}@{self.host}:{path}"

    def post(self, path, body=None, timeout=30):
        data = json.dumps(body).encode() if body is not None else b""
        req = urllib.request.Request(self.api + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode(errors="replace")

    def get(self, path, timeout=30):
        with urllib.request.urlopen(self.api + path, timeout=timeout) as r:
            return r.read().decode(errors="replace")

    # ---- reads ----
    def state(self):
        rc, out, _ = self.sh("cat /tmp/RBFNAME; echo; cat /tmp/CORENAME; echo; cat /tmp/FULLPATH", 20)
        ln = [x.strip() for x in out.splitlines()]
        ln += [""] * 3
        return {"rbf": ln[0] or None, "setname": ln[1] or None, "path": ln[2] or None}

    def ls(self, path):
        q = checked_path(path)
        rc, out, err = self.sh(f"ls -la --time-style=+%Y-%m-%dT%H:%M {shlex.quote(q)}")
        if rc:
            raise ToolError(err.strip() or f"ls {q} failed")
        return out

    def rbf_resolution(self, rbf_prefix):
        """Which .rbf the device would launch for <rbf>prefix</rbf>.

        Candidates are <prefix>_* and Arcade-<prefix>_* (both forms are deployed in practice);
        the highest-sorting suffix wins, so a dated release (2026xxxx) beats nothing and a
        deploy number (3xxxxxxx) beats any date. `outranked` is set when files exist from
        deploy.py but something else sorts above them."""
        rc, out, _ = self.sh(f"ls -1 {CORES}")
        pre = rbf_prefix.lower()
        cands = []
        for n in (x.strip() for x in out.splitlines()):
            low = n.lower()
            if not low.endswith(".rbf"):
                continue
            for form in (pre, "arcade-" + pre):
                if low.startswith(form) and low[len(form):len(form) + 1] in ("_", "."):
                    cands.append((low[len(form) + 1:], n))
        cands.sort()
        winner = cands[-1][1] if cands else None
        deployed = [n for suf, n in cands if re.match(r"3\d{7}", suf)]
        forms = {n.lower().startswith("arcade-") for _, n in cands}
        return {"candidates": len(cands), "highest": [n for _, n in cands[-4:]], "launches": winner,
                "outranked": bool(deployed) and winner not in deployed,
                "both_forms": len(forms) > 1,
                "note": "both <name>_ and Arcade-<name>_ files exist; which form the loader "
                        "prefers is not checked here" if len(forms) > 1 else None}

    def missing_zips(self, zips):
        if not zips:
            return []
        q = " ".join(shlex.quote(f"{ZIPS}/{z}") for z in zips)
        rc, out, _ = self.sh(f"for f in {q}; do [ -e \"$f\" ] || echo \"$f\"; done")
        return [PurePosixPath(x.strip()).name for x in out.splitlines() if x.strip()]

    def devmem(self, addr, words=1, width=32):
        if width not in (8, 16, 32):
            raise ToolError("width is 8, 16 or 32")
        a = int(str(addr), 0)
        step = width // 8
        cmd = "; ".join(f"devmem 0x{a + i * step:08x} {width}" for i in range(int(words)))
        rc, out, err = self.sh(cmd)
        if rc:
            raise ToolError(err.strip() or "devmem failed")
        vals = [v.strip() for v in out.splitlines() if v.strip()]
        return [{"addr": f"0x{a + i * step:08x}", "value": v} for i, v in enumerate(vals)]

    # ---- actions ----
    def find_mra(self, name):
        """The real file for an .mra name, as hw.py resolves it: _Arcade/_<folder>/ first, then
        _Arcade/, never a _Organized link (a launch through one returned 200 and left the menu
        up). Symlinks are resolved."""
        q = shlex.quote(name)
        rc, out, _ = self.sh(f"find /media/fat/_Arcade -path /media/fat/_Arcade/_Organized -prune "
                             f"-o -name {q} -print 2>/dev/null")
        hits = [h.strip() for h in out.splitlines() if h.strip()]
        if not hits:
            raise ToolError(f"no {name} on the device outside _Organized")

        def rank(h):
            rel = h[len("/media/fat/_Arcade/"):].split("/")
            return (0 if len(rel) == 2 and rel[0].startswith("_") else 1 if len(rel) == 1 else 2, h)
        best = sorted(hits, key=rank)[0]
        real = self.sh(f"readlink -f {shlex.quote(best)}")[1].strip() or best
        return real, hits

    def launch(self, mra, bounce=True, setname=None, timeout=25):
        """Launch and wait for /tmp/CORENAME to name the game; the API answers 200 either way."""
        if bounce:                       # a relaunch of the same core does not reload the FPGA
            self.post("/launch", {"path": "/media/fat/menu.rbf"})
            time.sleep(2)
        self.post("/launch", {"path": mra})
        deadline = time.time() + timeout
        name = None
        while time.time() < deadline:
            time.sleep(2)
            name = self.sh("cat /tmp/CORENAME 2>/dev/null", 20)[1].strip()
            if name and name.upper() != "MENU" and (not setname or name == setname):
                return name
        raise ToolError(f"launched {mra} but /tmp/CORENAME is still {name!r} after {timeout} s"
                        + (f" (expected {setname})" if setname else ""))

    def screenshot(self, local, native=False, settle=4, timeout=20):
        time.sleep(settle)                  # /tmp/CORENAME names the previous core straight after a launch
        core = self.state()["setname"] or ""
        folder = f"/media/fat/screenshots/{core}"

        def shots():
            return set(self.sh(f"ls -1 {shlex.quote(folder)} 2>/dev/null")[1].split())

        before = shots()
        if native:
            self.sh("echo screenshot > /dev/MiSTer_cmd")
        else:
            self.post("/screenshots")
        deadline = time.time() + timeout
        while time.time() < deadline:
            new = sorted(shots() - before)
            if new:
                time.sleep(1)
                Path(local).parent.mkdir(parents=True, exist_ok=True)
                self.scp(self.remote(f"{folder}/{new[-1]}"), str(local))
                return {"remote": f"{folder}/{new[-1]}", "local": str(local), "setname": core}
            time.sleep(1)
        raise ToolError(f"no new file in {folder} after {timeout} s")


def mra_zips(mra_text):
    return sorted({z for zs in re.findall(r'zip="([^"]+)"', mra_text) for z in zs.split("|")})


def mra_rbf(mra_text):
    m = re.search(r"<rbf>\s*([^<\s]+)\s*</rbf>", mra_text)
    return m.group(1) if m else None
