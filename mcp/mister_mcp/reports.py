"""Quartus, simulation and MAME output as fields."""
import re
from pathlib import Path


def output_dirs(root):
    """build_staged.py's worktree first, then build.sh's in-place outputs."""
    return [d for d in (root / "build" / "output_files", root / "output_files") if d.is_dir()]


def find_output(root, rev, suffix):
    for d in output_dirs(root):
        p = d / f"{rev}{suffix}"
        if p.exists():
            return p
    return None


def sta(path):
    """[{type, clock, slack, tns}] for every block in .sta.summary."""
    out = []
    lines = path.read_text(errors="replace").splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"Type\s*:\s*(\S+(?: \S+)?) '(.*)'", ln)
        if not m or i + 2 >= len(lines):
            continue
        try:
            slack = float(lines[i + 1].split(":", 1)[1])
            tns = float(lines[i + 2].split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        out.append({"type": m.group(1), "clock": m.group(2), "slack": slack, "tns": tns})
    return out


def fit(path):
    """Key/value lines of .fit.summary."""
    out = {}
    for ln in path.read_text(errors="replace").splitlines():
        if " : " in ln:
            k, v = ln.split(" : ", 1)
            out[k.strip()] = v.strip()
    return out


def built_commit(root):
    for p in (root / "build" / "BUILT_COMMIT", root / "BUILT_COMMIT"):
        if p.exists():
            parts = p.read_text(errors="replace").split()
            return {"commit": parts[0] if parts else None, "built": parts[1] if len(parts) > 1 else None,
                    "extra": " ".join(parts[2:]), "path": str(p)}
    return None


def build_summary(root, rev):
    res = {"rev": rev, "commit": built_commit(root)}
    s = find_output(root, rev, ".sta.summary")
    if s:
        blocks = sta(s)
        res["sta_path"] = str(s)
        res["timing"] = blocks
        fails = [b for b in blocks if b["slack"] < 0]
        res["timing_met"] = not fails
        res["failing"] = fails
        res["sta_mtime"] = s.stat().st_mtime
    else:
        res["timing"] = None
        res["timing_met"] = None
    f = find_output(root, rev, ".fit.summary")
    if f:
        kv = fit(f)
        keep = ("Fitter Status", "Logic utilization (in ALMs)", "Total registers", "Total pins",
                "Total block memory bits", "Total RAM Blocks", "Total DSP Blocks", "Total PLLs")
        res["fit"] = {k: kv[k] for k in keep if k in kv}
        res["fit_path"] = str(f)
    rbf = find_output(root, rev, ".rbf")
    res["rbf"] = str(rbf) if rbf else None
    return res


ERROR_RE = re.compile(r"^\s*(\*\* Error|Error|%Error|FATAL|# \*\* Error|# \*\* Fatal)", re.I)
FAIL_RE = re.compile(r"\b(FAIL(ED)?|MISMATCH)\b")
PASS_RE = re.compile(r"\bPASS(ED)?\b")


def sim_summary(text, rc):
    lines = text.splitlines()
    errors = [ln.strip() for ln in lines if ERROR_RE.match(ln)]
    readmem = [ln.strip() for ln in lines if "readmem" in ln.lower()
               and re.search(r"warn|error|not found|cannot", ln, re.I)]
    fails = [ln.strip() for ln in lines if FAIL_RE.search(ln)]
    passes = [ln.strip() for ln in lines if PASS_RE.search(ln)]
    return {"returncode": rc, "passed": rc == 0 and not errors and not fails,
            "errors": errors[:10], "error_count": len(errors),
            "fail_lines": fails[:10], "fail_count": len(fails), "pass_lines": passes[-5:],
            "readmem_warnings": readmem[:10],
            "note": ("$readmem warnings: ROMs may be empty, which fails every check at once"
                     if readmem else None)}


def manifest(path):
    p = Path(path) / "manifest.txt"
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.exists() else None
