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
    "required_macros": {},             # VERILOG_MACRO name -> what breaks without it
    "stage_copies": [],                # [source, destination] copied into build/ before Quartus runs
    "probe_default_instance": "F",     # the ISSP instance probe reads and clears by default
    "sta_clock": "emu|pll|pll_inst|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk",
}


def core_config(root=None):
    """scripts/core.json over CONFIG_DEFAULTS: the per-core values the MCP's scripts read.
    The ISSP field tables are in scripts/issp_fields.tcl (Tcl reads them)."""
    import json
    root = Path(root or core_root())
    cfg = dict(CONFIG_DEFAULTS)
    p = root / "scripts" / "core.json"
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
    if ini.exists():
        for line in ini.read_text(errors="replace").splitlines():
            if line.strip().startswith("rompath"):
                for part in line.split(None, 1)[1].split(";"):
                    part = part.strip()
                    if part:
                        q = Path(part)
                        paths.append(str(q if q.is_absolute() else md / q))
                break
    paths += [str(Path(p.strip())) for p in (setting("MAME_ROMPATH", "", root) or "").split(";") if p.strip()]
    seen, out = set(), []
    for q in paths:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return ";".join(out)


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
