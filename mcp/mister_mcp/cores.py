"""Which core a call is about, and how to run its scripts.

A tool names a core by repository directory (`Arcade-Seta_MiSTer`), short name (`Seta`) or path.
The scripts the tools run (build, deploy, probes, MAME traces) are the server's own, in scripts/
beside this file, run with CORE_ROOT set to the core; they read the core's values from its
scripts/core.json and scripts/issp_fields.tcl. A core that still has its own copy of a script
runs that copy instead: most older cores changed theirs, and those changes are folded in or
dropped core by core. The skill's template scripts (coretools, hwlock, run_verilator.sh) are
the shared library and the per-core sim harness.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "mister-arcade-core"
TEMPLATE_SCRIPTS = SKILL / "assets" / "core" / "scripts"
MCP_SCRIPTS = Path(__file__).resolve().with_name("scripts")
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
    """(path, shared) for scripts/<name>: the core's own copy, else the server's, else the skill's
    template. shared is False only for the core's own copy."""
    own = root / "scripts" / name
    if own.exists():
        return own, False
    for d in (MCP_SCRIPTS, TEMPLATE_SCRIPTS):
        if (d / name).exists():
            return d / name, True
    raise ToolError(f"no scripts/{name} in {root.name}, the server or the skill's template")


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
    # the core's <core>.<KEY> machine settings as environment: its own coretools copy may predate them.
    # Unbuffered: stdout to a file is block-buffered, so a build's log stayed empty until it ended.
    # PYTHONPATH: the server's scripts import coretools and hwlock from the skill's template.
    env = dict(os.environ, **coretools.core_settings(root), CORE_ROOT=str(root), PYTHONIOENCODING="utf-8",
               PYTHONUNBUFFERED="1", MSYS_NO_PATHCONV="1",
               PYTHONPATH=os.pathsep.join(filter(None, [str(TEMPLATE_SCRIPTS), os.environ.get("PYTHONPATH")])))
    from . import registry                       # imports this module
    if tpl and name in registry.USERS:
        env.update(registry.env(root))           # the registered core.json / issp_fields.tcl
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
