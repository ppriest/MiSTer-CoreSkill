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


def cores_dirs():
    """Where core repositories live: MISTER_CORES_DIR (several joined by ';'), else MiSTer-Cores
    (the user's own) and MiSTer-Devel (cores moved to that org) beside this repository, else its
    parent. Looked up per call, so moving a repository needs no server restart."""
    v = machine_setting("MISTER_CORES_DIR")
    if v:
        return [Path(x) for x in v.split(";") if x.strip()]
    found = [d for d in (SKILL.parents[1] / "MiSTer-Cores", SKILL.parents[1] / "MiSTer-Devel")
             if any(d.glob("*_MiSTer/*.qpf"))]
    return found or [SKILL.parents[1]]


def all_cores():
    """{repository name: path} across cores_dirs(); a name in two places maps to a list."""
    out = {}
    for base in cores_dirs():
        for d in sorted(base.glob("*_MiSTer")):
            if any(d.glob("*.qpf")):
                out.setdefault(d.name, []).append(d.resolve())
    return out


class ToolError(_SdkToolError):
    """A refusal or failure reported to the caller as the tool's error text."""


def resolve(core):
    """The core's root directory."""
    if not core:
        raise ToolError("name the core: a repository directory, a short name or a path")
    p = Path(core)
    if p.is_absolute():
        if p.is_dir() and any(p.glob("*.qpf")):
            return p.resolve()
        raise ToolError(f"{p} is not a core (no .qpf)")
    names = {n.lower(): n for n in (core, f"Arcade-{core}_MiSTer", f"{core}_MiSTer")}
    cores = all_cores()
    hits = [(n, d) for n, ds in cores.items() if n.lower() in names for d in ds]
    if len(hits) == 1:
        return hits[0][1]
    if hits:
        raise ToolError(f"'{core}' is in more than one place: " + ", ".join(str(d) for _, d in hits)
                        + "; pass the path")
    raise ToolError(f"no core '{core}' under {', '.join(map(str, cores_dirs()))} (a directory with "
                    "a .qpf); set MISTER_CORES_DIR")


def list_cores():
    return {n: [str(d) for d in ds] if len(ds) > 1 else str(ds[0]) for n, ds in all_cores().items()}


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
    # the core's <core>.<KEY> machine settings as environment: its own coretools copy may predate them
    env = dict(os.environ, **coretools.core_settings(root), CORE_ROOT=str(root), PYTHONIOENCODING="utf-8",
               MSYS_NO_PATHCONV="1")
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
