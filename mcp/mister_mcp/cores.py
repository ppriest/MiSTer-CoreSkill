"""Which core a call is about, and how to run its scripts.

A tool names a core by repository directory (`Arcade-Seta_MiSTer`), short name (`Seta`) or path.
Its own `scripts/` are run when they have the script, so the core's local edits (probe instance,
.mra folder) stay in force; otherwise the skill's template copy runs with CORE_ROOT set to the core.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "mister-arcade-core"
TEMPLATE_SCRIPTS = SKILL / "assets" / "core" / "scripts"
sys.path.insert(0, str(TEMPLATE_SCRIPTS))
import coretools  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError as _SdkToolError  # noqa: E402

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def machine_setting(name, default=None):
    """Environment, then ~/.mister-core.env. coretools.setting() needs a core root."""
    return (os.environ.get(name) or coretools._read_env_file(coretools.machine_env_path()).get(name)
            or default)


def cores_dir():
    """MISTER_CORES_DIR, else MiSTer-Cores beside this repository, else its parent.
    Looked up per call, so moving the repositories needs no server restart."""
    v = machine_setting("MISTER_CORES_DIR")
    if v:
        return Path(v)
    for d in (SKILL.parents[1] / "MiSTer-Cores", SKILL.parents[1]):
        if any(d.glob("*_MiSTer/*.qpf")):
            return d
    return SKILL.parents[1]


class ToolError(_SdkToolError):
    """A refusal or failure reported to the caller as the tool's error text."""


def resolve(core):
    """The core's root directory."""
    if not core:
        raise ToolError("name the core: a repository directory, a short name or a path")
    base = cores_dir()
    p = Path(core)
    cands = [p] if p.is_absolute() else [base / core, base / f"Arcade-{core}_MiSTer",
                                         base / f"{core}_MiSTer"]
    for c in cands:
        if c.is_dir() and any(c.glob("*.qpf")):
            return c.resolve()
    hits = [d for d in base.glob("*_MiSTer") if d.name.lower() == f"arcade-{core}_mister".lower()
            or d.name.lower() == str(core).lower()]
    if hits:
        return hits[0].resolve()
    raise ToolError(f"no core '{core}' under {base} (a directory with a .qpf); set MISTER_CORES_DIR")


def list_cores():
    return sorted(d.name for d in cores_dir().glob("*_MiSTer") if any(d.glob("*.qpf")))


def script(root, name):
    """(path, from_template) for scripts/<name>."""
    own = root / "scripts" / name
    if own.exists():
        return own, False
    tpl = TEMPLATE_SCRIPTS / name
    if tpl.exists():
        return tpl, True
    raise ToolError(f"{root.name} has no scripts/{name} and the skill has no template copy")


def python_exe():
    """The base interpreter, not this venv's: the scripts need Pillow and the like."""
    return machine_setting("PYTHON") or getattr(sys, "_base_executable", None) or sys.executable


def git_bash():
    """Git's bash. A bare `bash` on this machine may be WSL's, which cannot run Windows tools."""
    v = machine_setting("GIT_BASH")
    for c in ([v] if v else []) + [r"C:\Program Files\Git\bin\bash.exe",
                                   r"C:\Program Files\Git\usr\bin\bash.exe"]:
        if c and Path(c).exists():
            return c
    w = shutil.which("bash")
    if w and "system32" not in w.lower() and "windowsapps" not in w.lower():
        return w
    raise ToolError("Git bash not found; set GIT_BASH in ~/.mister-core.env")


def command(root, name, *args):
    """argv and env for running scripts/<name> on this core."""
    path, tpl = script(root, name)
    env = dict(os.environ, CORE_ROOT=str(root), PYTHONIOENCODING="utf-8", MSYS_NO_PATHCONV="1")
    if path.suffix == ".py":
        argv = [python_exe(), str(path), *map(str, args)]
    elif path.suffix == ".sh":
        argv = [git_bash(), str(path), *map(str, args)]
    else:
        raise ToolError(f"do not know how to run {path.name}")
    return argv, env, tpl


def run(root, name, *args, timeout=600):
    """Run a script to completion: (returncode, combined output, from_template)."""
    argv, env, tpl = command(root, name, *args)
    try:
        p = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, **NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ToolError(f"scripts/{name} did not finish in {timeout} s")
    return p.returncode, (p.stdout or "") + (p.stderr or ""), tpl


def tail(text, n=40):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])
