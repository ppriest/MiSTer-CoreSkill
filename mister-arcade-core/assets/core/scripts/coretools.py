#!/usr/bin/env python3
"""What every script in this directory needs to know about its core.

The core root is the parent of this scripts/ directory (or CORE_ROOT). From it:

    project()    the Quartus project name: the stem of the one .qpf there
                 (Fuuki.qpf -> "Fuuki"). Names the MiSTer artefacts too:
                 <project>_NNNNNNNN.rbf (from 30000001), /media/fat/_Arcade/_<project>.
    revision()   the Quartus revision to build: CORE_REV, else the one .qsf,
                 else the last PROJECT_REVISION the .qpf lists. A core with
                 several revisions (X and X_stp) picks with CORE_REV or --rev.
    load_env()   settings: ~/.mister-core.env (or MISTER_CORE_ENV), one file for the
                 whole machine. There is no per-core settings file.

Tool locations, in order: the environment, the core's own keys in the per-machine
file (<core>.<KEY>=..., e.g. Gaelco3D.MAME_EXE=gaelco3d.exe; <core> is the repository
name without Arcade- and _MiSTer; the MCP's core_settings_set writes them), the
per-machine file, then a default.

    QUARTUS_BIN    .../intelFPGA_lite/17.0/quartus/bin64
    MODELSIM_BIN   defaults to <quartus root>/modelsim_ase/win32aloem
    MAME_DIR       directory holding the MAME executable (required to use MAME)
    MAME_EXE       executable name inside it (default mame.exe)
    MAME_SRC       the MAME driver source this core follows (extract_dips.py,
                   extract_romstart.py, validate_mra.py)

`python scripts/coretools.py` prints what it resolved.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

QUARTUS_DEFAULT = r"C:\intelFPGA_lite\17.0\quartus\bin64"

# NO CONSOLE WINDOW for a spawned mame.exe: from a process with no console of
# its own Windows gives it a visible one, even with -video none -nowindow.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def core_root():
    """The core being worked on: CORE_ROOT, else the parent of scripts/."""
    root = Path(os.environ.get("CORE_ROOT") or Path(__file__).resolve().parent.parent)
    if not list(root.glob("*.qpf")):
        sys.exit("not a core root (no .qpf here): %s" % root)
    return root


def project(root=None):
    """The Quartus project name: the stem of the .qpf in the root.

    A core with X.qpf and X_stp.qpf has two; the shorter stem is the project."""
    root = root or core_root()
    qpfs = sorted(root.glob("*.qpf"), key=lambda p: len(p.stem))
    if not qpfs:
        sys.exit("no .qpf in %s" % root)
    return qpfs[0].stem


def revision(root=None, override=None):
    """The Quartus revision to build/report on."""
    root = root or core_root()
    if override:
        return override
    if os.environ.get("CORE_REV"):
        return os.environ["CORE_REV"]
    qsfs = sorted(root.glob("*.qsf"))
    if len(qsfs) == 1:
        return qsfs[0].stem
    # several revisions: the .qpf lists them, last one current
    revs = []
    for qpf in sorted(root.glob("*.qpf")):
        for ln in qpf.read_text(errors="replace").splitlines():
            if ln.startswith("PROJECT_REVISION"):
                revs.append(ln.split("=", 1)[1].strip().strip('"'))
    if revs:
        return revs[-1]
    sys.exit("cannot determine the revision in %s: %d .qsf files and no "
             "PROJECT_REVISION in the .qpf; set CORE_REV or pass --rev"
             % (root, len(qsfs)))


CONFIG_DEFAULTS = {
    "mra_folder": None,                # the .mra folder under /media/fat/_Arcade; default _<project>
    "held_back_sets": [],              # .mra stems built but not copied to the device
    "required_instances": ["hps_io"],  # blocks that must survive to the fitted netlist
    "required_instances_by_rev": {},   # revision -> its own required_instances (a test harness)
    "required_macros": {},             # VERILOG_MACRO name -> what breaks without it
    "stage_copies": [],                # [source, destination] copied into build/ before Quartus runs
    "probe_default_instance": "F",     # the ISSP instance probe reads and clears by default
    "sta_clock": "emu|pll|pll_inst|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk",
}


def core_config(root=None):
    """scripts/core.json over CONFIG_DEFAULTS: the per-core values the MCP's scripts read.
    Under the MCP, CORE_CONFIG names the copy the core registered (core_register), which is
    read instead. The ISSP field tables are in scripts/issp_fields.tcl (Tcl reads them)."""
    import json
    root = Path(root or core_root())
    cfg = dict(CONFIG_DEFAULTS)
    p = Path(os.environ["CORE_CONFIG"]) if os.environ.get("CORE_CONFIG") else root / "scripts" / "core.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    cfg["mra_folder"] = cfg["mra_folder"] or "_" + project(root)
    return cfg


def machine_env_path():
    """The per-machine settings file: MISTER_CORE_ENV, else ~/.mister-core.env.

    Tool paths and the MiSTer connection; per-core values are <core>.<KEY> keys in it.
    The environment wins over it.
    """
    p = os.environ.get("MISTER_CORE_ENV")
    return Path(p) if p else Path.home() / ".mister-core.env"


def _read_env_file(path):
    env = {}
    if Path(path).exists():
        for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_env(root=None, path=None, require=()):
    """KEY=VALUE pairs from the per-machine file. `root` is accepted and ignored."""
    path = Path(path or machine_env_path())
    env = _read_env_file(path)
    for k in require:
        if not env.get(k):
            sys.exit("%s is not set in %s" % (k, path))
    return env


def core_name(root=None):
    """The name per-core keys use: Arcade-Gaelco3D_MiSTer -> Gaelco3D."""
    return re.sub(r"_MiSTer$", "", re.sub(r"^Arcade-", "", Path(root or core_root()).name))


def core_settings(root=None):
    """This core's own keys in the machine file, <core>.<KEY>=VALUE, as {KEY: VALUE}.

    They keep a core's settings (its MAME build, say) with the machine's rather than in a
    per-repository file; a copy of this module that predates them ignores the dotted keys."""
    pre = core_name(root) + "."
    return {k[len(pre):]: v for k, v in _read_env_file(machine_env_path()).items()
            if k.startswith(pre) and v}


def setting(name, default=None, root=None):
    """A setting: environment, then the core's keys in the machine file, then the machine
    file, then the default."""
    if os.environ.get(name):
        return os.environ[name]
    v = core_settings(root).get(name) or load_env(root).get(name)
    return v if v else default


def quartus_bin(root=None):
    return Path(setting("QUARTUS_BIN", QUARTUS_DEFAULT, root))


def quartus_stp(root=None):
    return quartus_bin(root) / "quartus_stp.exe"


def modelsim_bin(root=None):
    v = setting("MODELSIM_BIN", None, root)
    if v:
        return Path(v)
    return quartus_bin(root).parent.parent / "modelsim_ase" / "win32aloem"


def mame_dir(root=None):
    v = setting("MAME_DIR", None, root)
    if not v:
        sys.exit("MAME_DIR is not set: put MAME_DIR=<directory of the MAME "
                 "executable> (and MAME_EXE=<name>, if not mame.exe) with the MCP's "
                 "core_settings_set, or in ~/.mister-core.env")
    return Path(v)


def mame_exe(root=None):
    return mame_dir(root) / setting("MAME_EXE", "mame.exe", root)


def mame_version(root=None):
    """The installed MAME as an .mra <mameversion> string ("0.289 (mame0289)" -> "0289"),
    or None when MAME is not configured or does not answer."""
    import re
    try:
        exe = mame_exe(root)
        r = subprocess.run([str(exe), "-version"], capture_output=True, text=True,
                           timeout=30, **NO_WINDOW)
    except (Exception, SystemExit):
        return None
    m = re.match(r"\s*0\.(\d+)", r.stdout)
    return "%04d" % int(m.group(1)) if m else None


def mame_src(root=None):
    v = setting("MAME_SRC", None, root)
    if not v:
        sys.exit("MAME_SRC is not set: put MAME_SRC=<path to the MAME driver "
                 ".cpp this core follows> with the MCP's core_settings_set, or in ~/.mister-core.env")
    return Path(v)


def rompath(root=None):
    """This core's gitignored roms/ FIRST, then whatever mame.ini already had, then
    MAME_ROMPATH (';'-separated).

    -rompath REPLACES the ini value rather than adding to it, so the ini's own
    entries are read and appended. A core's own MAME build (its <core>.MAME_DIR)
    usually has no mame.ini, so MAME_ROMPATH is what finds the sets there."""
    root = root or core_root()
    md = mame_dir(root)
    paths = [str(root / "roms")]
    ini = md / "mame.ini"
    lines = ini.read_text(errors="replace").splitlines() if ini.exists() else []
    ini_paths = next((ln.split(None, 1)[1] for ln in lines
                      if ln.strip().startswith("rompath") and len(ln.split(None, 1)) == 2), "roms")
    for part in ini_paths.split(";"):               # MAME's own default is roms/ beside it
        part = part.strip()
        if part:
            q = Path(part)
            paths.append(str(q if q.is_absolute() else md / q))
    paths += [str(Path(p.strip())) for p in (setting("MAME_ROMPATH", "", root) or "").split(";") if p.strip()]
    seen, out = set(), []
    for q in paths:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return ";".join(out)


# --- running MAME headless: shared by the MCP's MAME scripts and a core's own -----------
# Every Lua script runs under scripts/mame/run.lua, which names the real one in CORE_SCRIPT.
# Without it MAME reports a Lua error as a MODAL DIALOG and the process sits there: the
# output directory looks untouched and nothing says why. run.lua writes lua_error.txt.

def mame_paths(root=None):
    """(MAME_DIR, the executable in it); exits when it is not there."""
    exe = mame_exe(root)
    if not exe.exists():
        sys.exit(f"MAME not found at {exe}; set MAME_DIR/MAME_EXE with core_settings_set "
                 f"or in ~/.mister-core.env")
    return exe.parent, exe


def lua_dir(root=None):
    return (root or core_root()) / "scripts" / "mame"


def regions(game=None, root=None):
    """scripts/mame/regions.json, or the profile CORE_REGIONS names (regions_<name>.json), with
    its "sets" entry for `game` laid over the top level."""
    p = lua_dir(root) / os.environ.get("CORE_REGIONS", "regions.json")
    r = __import__("json").loads(p.read_text(encoding="utf-8"))
    return {**r, **r.pop("sets", {}).get(game or "", {})}


def spec(table, names=None):
    """{"name": [lo, hi]} -> "name:lo:hi,..." for the Lua side."""
    return ",".join(f"{n}:{int(lo, 16):x}:{int(hi, 16):x}"
                    for n, (lo, hi) in table.items() if names is None or n in names)


def extra_read_spec(table):
    """regions.json "read_extra" ({name: {cpu, space, range}}): reads in another CPU's space,
    as CORE_READ_EXTRA = name:cpu:space:lo:hi,..."""
    return ",".join(
        f"{name}:{e['cpu'].lstrip(':')}:{e.get('space', 'program')}:"
        f"{int(e['range'][0], 16):x}:{int(e['range'][1], 16):x}"
        for name, e in table.items())


def lua_env(r):
    """The main CPU's tag, space, bus width and endianness from regions.json, for the Lua."""
    return {"CORE_CPU": r["cpu"], "CORE_SPACE": r["space"],
            "CORE_BYTES": str(r["bus_bytes"]), "CORE_BIG": "1" if r["big_endian"] else "0"}


INPUT_DEFAULTS = {"coin": "Coin 1", "start": "1 Player Start", "hold": "P1 Right", "pulse": "P1 Button 1"}


def input_env(r, prefix="CORE_IN_"):
    """regions.json "inputs" over INPUT_DEFAULTS, as <prefix><NAME>: the port fields a Lua
    presses to coin up and play (coin, start, hold, pulse) and any others it reads."""
    return {prefix + k.upper(): v for k, v in {**INPUT_DEFAULTS, **r.get("inputs", {})}.items()}


def lua_runner_env(lua, root=None):
    """Merge into the MAME process's environment: run.lua runs `lua` (in scripts/mame/)."""
    return {"CORE_SCRIPT": str(lua_dir(root) / lua)}


def check_lua_error(out):
    """Exit with the Lua error run.lua wrote to <out>/lua_error.txt, if there is one."""
    err = Path(out) / "lua_error.txt"
    if err.exists():
        sys.exit("Lua failed: " + err.read_text().strip())


def mame_cmd(exe, game, lua, mame_dir=None, extra=(), root=None):
    """The headless MAME command line running scripts/mame/<lua> under run.lua.

    -nodebug/-nowindow explicit: a mame.ini with `debug 1` halts in the debugger while the
    autoboot script still loads and prints, so it looks alive. regions.json "mame_args" adds
    per-core options: -nodrc where the main CPU has a recompiler, because its fastram paths
    bypass the Lua write taps. `lua` is unused (run.lua reads CORE_SCRIPT) and kept so the
    call names the script it runs; mame_dir is unused (rompath() finds it)."""
    return [str(exe), game, "-nodebug", "-nowindow", "-video", "none", "-sound", "none",
            "-skip_gameinfo", "-nothrottle", "-autoboot_delay", "0",
            "-autoboot_script", str(lua_dir(root) / "run.lua"),
            "-rompath", rompath(root), *regions(game, root).get("mame_args", []), *extra]


def find_putty(name):
    """plink.exe / pscp.exe: PATH, then the standard install."""
    import shutil
    for c in (name, os.path.join(r"C:\Program Files\PuTTY", name)):
        found = shutil.which(c) or (c if os.path.isfile(c) else None)
        if found:
            return found
    sys.exit("Couldn't find %s. Install PuTTY, or put it on PATH." % name)


if __name__ == "__main__":
    r = core_root()
    print("core root : %s" % r)
    print("project   : %s" % project(r))
    print("revision  : %s" % revision(r))
    print("quartus   : %s" % quartus_bin(r))
    print("modelsim  : %s" % modelsim_bin(r))
    print("mame      : %s" % setting("MAME_DIR", "(not set)", r))
    print("mame src  : %s" % setting("MAME_SRC", "(not set)", r))
