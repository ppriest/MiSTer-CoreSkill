"""MCP server for MiSTer arcade core work: builds, simulation, MAME and the board.

One stdio process per Claude session. What sessions share lives on disk: jobs under
%LOCALAPPDATA%/mister_mcp/jobs and hwlock's JTAG markers, which the core's own scripts take.
Every tool takes `core` (repository directory, short name or path) where a core is involved.
"""
import functools
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import board as B
from . import cores as C
from . import jobs as J
from . import reports as R
from .cores import ToolError

server = MCPServer(name="mister", instructions=(
    "Tools for MiSTer arcade cores. Long runs (build_start, sim_run, mame_*) are jobs: they wait "
    "up to wait_s seconds (at most 240), then return a job id for jobs_status. JTAG (probe_*) and Quartus/ModelSim "
    "exclude each other machine-wide; locks_status says who holds what. Use Bash for anything "
    "these tools do not cover."))

RO = ToolAnnotations(readOnlyHint=True)
ACT = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


CALLS = J.BASE.parent / "calls.jsonl"
CALLS_MAX = 10 * 1024 * 1024                  # then calls.jsonl -> calls.1.jsonl


def _record(entry):
    """Append one call to calls.jsonl, opening and closing the file each time: a handle held
    open by the boot task's process was never seen to reach the disk (server.log)."""
    try:
        if CALLS.exists() and CALLS.stat().st_size > CALLS_MAX:
            CALLS.replace(CALLS.with_name("calls.1.jsonl"))
        with open(CALLS, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass                                  # the log must never fail a call


def tool(annotations=ACT):
    """Register a tool. Every failure reaches the caller as text: the SDK hides an unexpected
    exception's message, and coretools reports missing settings with sys.exit. Every call is
    recorded in calls.jsonl (calls_log reads it)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapped(*a, **kw):
            t0 = time.time()
            entry = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": fn.__name__, "args": kw}
            try:
                out = fn(*a, **kw)
                entry["ok"] = True
                if isinstance(out, dict):
                    entry.update({k: out[k] for k in ("id", "state", "returncode") if k in out})
                return out
            except ToolError as e:
                entry.update(ok=False, error=str(e))
                raise
            except SystemExit as e:
                msg = str(e.code) if e.code not in (None, 0) else "exited"
                entry.update(ok=False, error=msg)
                raise ToolError(msg) from None
            except Exception as e:
                entry.update(ok=False, error=f"{type(e).__name__}: {e}")
                raise ToolError(f"{type(e).__name__}: {e}") from e
            finally:
                entry["s"] = round(time.time() - t0, 2)
                if fn.__name__ != "calls_log":
                    _record(entry)
        return server.tool(annotations=annotations)(wrapped)
    return deco


def _job(kind, root, script, args, wait_s, meta=None, result=None):
    argv, env, tpl = C.command(root, script, *args)
    jid = J.start(kind, root.name, argv, root, env, dict(meta or {}, script=script, template=tpl))
    st = J.wait(jid, wait_s)
    if result and st["state"] not in ("starting", "running"):
        st["result"] = result(jid)
    return st


# ---------------------------------------------------------------- jobs, locks

@tool(RO)
def cores_list() -> dict:
    """Core repositories and their paths, from MiSTer-Cores and MiSTer-Devel (MISTER_CORES_DIR)."""
    return {"cores_dirs": [str(d) for d in C.cores_dirs()], "cores": C.list_cores()}


@tool(RO)
def calls_log(limit: int = 50, tool: str = "", errors_only: bool = False, since: str = "") -> dict:
    """Recent tool calls from every session, newest last: time, tool, arguments, seconds,
    ok/error, and the job id and state where the tool returned one. Filter by tool name
    (substring), errors_only, or since ("YYYY-MM-DD HH:MM:SS" prefix, e.g. "2026-10-31 10:4")."""
    rows = []
    for p in (CALLS.with_name("calls.1.jsonl"), CALLS):
        if p.exists():
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if tool and tool not in r.get("tool", ""):
                    continue
                if errors_only and r.get("ok", True):
                    continue
                if since and r.get("t", "") < since:
                    continue
                rows.append(r)
    return {"path": str(CALLS), "calls": rows[-limit:]}


@tool(RO)
def jobs_list(active_only: bool = False, limit: int = 20) -> dict:
    """Jobs from every session, newest first."""
    return {"jobs": J.listing(limit, active_only)}


@tool(RO)
def jobs_status(job: str, wait_s: int = 0, log_lines: int = 20) -> dict:
    """A job's state, return code and log tail; waits up to wait_s for it to end. Ended jobs
    carry `result` (parsed timing, sim summary or capture manifest) where the kind has one."""
    st = J.wait(job, wait_s) if wait_s else J.status(job)
    st["log_tail"] = J.status(job, log_lines)["log_tail"]
    if st["state"] not in ("starting", "running"):
        fn = RESULTS.get(st["kind"])
        if fn:
            st["result"] = fn(job)
    return st


@tool(RO)
def jobs_log(job: str, grep: str = "", lines: int = 200) -> str:
    """A job's log: the last `lines` lines, or the lines matching the regex `grep`."""
    text = J.log(job).splitlines()
    if grep:
        rx = re.compile(grep, re.I)
        text = [ln for ln in text if rx.search(ln)]
    return "\n".join(text[-lines:])


@tool(ACT)
def jobs_cancel(job: str) -> dict:
    """Kill a job's whole process tree (quartus_fit, vsimk, mame)."""
    return J.cancel(job)


@tool(RO)
def locks_status() -> dict:
    """JTAG marker, queued JTAG sessions, running Quartus/ModelSim processes, active jobs."""
    import hwlock
    held = hwlock.read_marker()
    return {"jtag_held": {"pid": held[0], "what": held[1]} if held else None,
            "jtag_waiting": [{"pid": p, "what": w} for p, w in hwlock.waiting_sessions()],
            "quartus_modelsim": hwlock.quartus_processes(),
            "active_jobs": [{k: j[k] for k in ("id", "kind", "core", "elapsed_s")}
                            for j in J.listing(50, active_only=True)]}


# ---------------------------------------------------------------- builds

def _rev(root, rev):
    return C.coretools.revision(root, rev or None)


def _build_result(jid):
    m = J.meta(jid)
    root = C.resolve(m["cwd"])
    return R.build_summary(root, m["meta"]["rev"])


@tool(ACT)
def build_start(core: str, rev: str = "", seed: int | None = None, allow_dirty: bool = False,
                wait_s: int = 5) -> dict:
    """Full staged Quartus compile (scripts/build_staged.py) as a job. Refuses while JTAG is held,
    as the script does. Builds take tens of minutes; poll jobs_status."""
    root = C.resolve(core)
    r = _rev(root, rev)
    args = ["--rev", r] + (["--seed", seed] if seed is not None else []) + \
        (["--allow-dirty"] if allow_dirty else [])
    return _job("build", root, "build_staged.py", args, wait_s, {"rev": r}, _build_result)


@tool(RO)
def build_report(core: str, rev: str = "") -> dict:
    """The last build's commit, setup/hold slack and TNS per clock, fit resources, .rbf path."""
    root = C.resolve(core)
    return R.build_summary(root, _rev(root, rev))


@tool(ACT)
def build_worst_paths(core: str, rev: str = "", wait_s: int = 300) -> dict:
    """quartus_sta with scripts/report_worst_paths.tcl on the compiled database (no recompile).
    Writes output_files/worst_paths_<rev>.rpt."""
    root = C.resolve(core)
    r = _rev(root, rev)
    tcl, _ = C.script(root, "report_worst_paths.tcl")
    db = root / "build" if (root / "build" / "db").is_dir() else root
    sta = C.coretools.quartus_bin(root) / "quartus_sta.exe"
    argv = [str(sta), "-t", str(tcl), r]
    env = dict(os.environ, CORE_ROOT=str(root))
    jid = J.start("sta", root.name, argv, db, env, {"rev": r, "db": str(db)})
    st = J.wait(jid, wait_s)
    if st["state"] == "done":
        st["result"] = _sta_result(jid)
    return st


def _sta_result(jid):
    m = J.meta(jid)
    p = Path(m["meta"]["db"]) / "output_files" / f"worst_paths_{m['meta']['rev']}.rpt"
    if not p.exists():
        return None
    text = p.read_text(errors="replace")
    slacks = re.findall(r"^; (-?\d+\.\d+)\s*;\s*(\S+)\s*;\s*(\S+)\s*;", text, re.M)
    return {"report": str(p), "paths": [{"slack": float(s), "from": f, "to": t} for s, f, t in slacks[:15]]}


@tool(ACT)
def build_floorplan(core: str, rev: str = "", reuse: bool = False, wait_s: int = 600) -> dict:
    """scripts/floorplan.py: placement image by hierarchy from the compiled database."""
    root = C.resolve(core)
    args = (["--rev", rev] if rev else []) + (["--reuse"] if reuse else [])
    return _job("floorplan", root, "floorplan.py", args, wait_s)


# ---------------------------------------------------------------- simulation

@tool(RO)
def sim_list(core: str) -> dict:
    """Testbenches under sim/, with which simulators each has a file list for."""
    root = C.resolve(core)
    out = []
    for d in sorted((root / "sim").glob("*_tb")) if (root / "sim").is_dir() else []:
        out.append({"bench": d.name, "verilator": (d / "verilator.files").exists()})
    return {"benches": out}


def _sim_result(jid):
    st = J.status(jid, 0)
    return R.sim_summary(J.log(jid), st["returncode"])


@tool(ACT)
def sim_run(core: str, bench: str, simulator: str = "modelsim", args: list[str] | None = None,
            tag: str = "", wait_s: int = 120) -> dict:
    """One testbench: scripts/run_sim.sh (ModelSim; fresh library, one at a time per core) or
    scripts/run_verilator.sh. `args` go through (+plusargs, -Gparam=, --threads=N). Verilator:
    `tag` builds in obj_verilator/<bench>[params]-<tag>/, so two runs of one bench (different
    sets) can go at once; two runs that would share a build directory are refused. The result
    flags $readmem warnings, which mean empty ROMs rather than an RTL fault."""
    root = C.resolve(core)
    args = list(args or [])
    if simulator not in ("modelsim", "verilator"):
        raise ToolError("simulator is modelsim or verilator")
    running = [j for j in J.listing(50, True) if j["kind"] == "sim" and j["core"] == root.name
               and j["meta"].get("simulator") == simulator]
    if simulator == "modelsim":
        if tag:
            raise ToolError("tag is for Verilator; run_sim.sh rebuilds one work library per core")
        if running:
            raise ToolError(f"ModelSim job {running[0]['id']} is running on this core; run_sim.sh "
                            "rebuilds one shared work library, so wait or cancel it")
    else:
        if tag:
            path, _ = C.script(root, "run_verilator.sh")
            if "--tag=" not in path.read_text(errors="replace"):
                raise ToolError(f"{path} has no --tag option; copy the skill's run_verilator.sh")
            args.append(f"--tag={tag}")
        # the build directory is named from the bench, the -G and --threads arguments and the tag
        build = (bench, tuple(sorted(a for a in args if a.startswith(("-G", "--threads=", "--tag=")))))
        clash = [j for j in running if j["meta"].get("build") == list(build[1])
                 and j["meta"].get("bench") == bench]
        if clash:
            raise ToolError(f"Verilator job {clash[0]['id']} is building or running the same "
                            f"model ({bench}, {list(build[1]) or 'no -G/--threads/--tag'}); pass "
                            "a different tag to run alongside it")
    script = "run_sim.sh" if simulator == "modelsim" else "run_verilator.sh"
    meta = {"bench": bench, "simulator": simulator}
    if simulator == "verilator":
        meta["build"] = list(build[1])
    return _job("sim", root, script, [bench, *args], wait_s, meta, _sim_result)


@tool(ACT)
def sim_compare_boot(core: str, set: str, cmd: str = "compare", wait_s: int = 300) -> dict:
    """scripts/compare_boot_trace.py replay|compare <set>: the RTL's boot against MAME's trace."""
    root = C.resolve(core)
    if cmd not in ("replay", "compare"):
        raise ToolError("cmd is replay or compare")
    return _job("compare", root, "compare_boot_trace.py", [cmd, set], wait_s)


@tool(ACT)
def sim_sweep(kill: bool = False) -> dict:
    """Orphaned vsim/vsimk processes (no running sim job) and stale work/_lock files.
    kill=True ends the processes and removes the locks."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-Process vsim*,vlog,vcom -ErrorAction SilentlyContinue | "
                        "ForEach-Object { \"$($_.Id) $($_.ProcessName)\" }"],
                       capture_output=True, text=True, **C.NO_WINDOW)
    procs = [ln.split(None, 1) for ln in r.stdout.splitlines() if ln.strip()]
    running = [j for j in J.listing(50, True) if j["kind"] == "sim"]
    locks = [str(p) for ds in C.all_cores().values() for d in ds for p in d.glob("**/work/_lock")
             if "node_modules" not in str(p)]
    out = {"processes": [{"pid": int(p), "name": n} for p, n in procs], "running_sim_jobs":
           [j["id"] for j in running], "stale_locks": locks if not running else [],
           "note": "processes are not killed while a sim job is running" if running else None}
    if kill and not running:
        for p, _ in procs:
            subprocess.run(["taskkill", "/T", "/F", "/PID", p], capture_output=True, **C.NO_WINDOW)
        for lk in locks:
            Path(lk).unlink(missing_ok=True)
        out["killed"] = True
    return out


# ---------------------------------------------------------------- MAME

def _git_describe(path):
    p = Path(path)
    d = p if p.is_dir() else p.parent
    r = subprocess.run(["git", "-C", str(d), "describe", "--tags"], capture_output=True, text=True,
                       **C.NO_WINDOW)
    return r.stdout.strip() or None


@tool(RO)
def mame_version(core: str) -> dict:
    """The MAME binary's version against `git describe` of MAME_SRC. A mismatch means traces
    from the binary do not describe the source being read."""
    root = C.resolve(core)
    exe = C.coretools.mame_exe(root)
    r = subprocess.run([str(exe), "-version"], capture_output=True, text=True, timeout=30,
                       **C.NO_WINDOW)
    binary = r.stdout.strip()
    src = C.coretools.setting("MAME_SRC", None, root)
    tag = _git_describe(src) if src else None
    m = re.match(r"\s*0\.(\d+)", binary)
    want = f"mame0{m.group(1)}" if m else None
    match = None if not (tag and want) else tag.split("-")[0] == want
    past = int(tag.split("-")[1]) if tag and match and "-" in tag else 0
    note = None
    if match is False:
        note = f"binary is {want} but the source is at {tag}: rebuild or re-point MAME_DIR"
    elif past:
        note = (f"source is {past} commits past {want}; the driver being read may differ from "
                f"the binary's (git -C <mame> diff {want} -- <driver>)")
    return {"exe": str(exe), "binary": binary, "mame_src": src, "src_describe": tag,
            "release_match": match, "commits_past_tag": past, "note": note}


def _capture_result(jid):
    m = J.meta(jid)
    out = m["meta"].get("out")
    if not out:
        return None
    o = Path(out)
    err = o / "lua_error.txt"
    return {"out": out, "lua_error": err.read_text(errors="replace").strip() if err.exists() else None,
            "error": (o / "ERROR.txt").read_text(errors="replace").strip()
            if (o / "ERROR.txt").exists() else None,
            "manifest": R.manifest(o), "files": sorted(p.name for p in o.glob("*"))[:60]}


@tool(ACT)
def mame_capture(core: str, set: str, frame: int = 1200, dips: list[str] | None = None,
                 name: str = "", seconds: int | None = None, wait_s: int = 300) -> dict:
    """scripts/mame_capture.py: RAM/region dumps and reference.png at a frame, with a manifest.
    dips are NAME=SETTING. Output in debug/<set>-<name or frame>."""
    root = C.resolve(core)
    args = [set, "--frame", frame] + (["--name", name] if name else []) + \
        (["--seconds", seconds] if seconds else [])
    for d in dips or []:
        args += ["--dip", d]
    out = root / "debug" / f"{set}-{name or frame}"
    return _job("mame", root, "mame_capture.py", args, wait_s, {"out": str(out)}, _capture_result)


@tool(ACT)
def mame_boot_trace(core: str, set: str, n: int, seconds: int = 30, wait_s: int = 120) -> dict:
    """scripts/mame_boot_trace.py <set> <n>: the first n bus accesses from reset."""
    root = C.resolve(core)
    return _job("mame", root, "mame_boot_trace.py", [set, n, "--seconds", seconds], wait_s)


@tool(ACT)
def mame_sys_trace(core: str, set: str, frames: int, seconds: int = 120, wait_s: int = 180) -> dict:
    """scripts/mame_sys_trace.py <set> <frames>."""
    root = C.resolve(core)
    return _job("mame", root, "mame_sys_trace.py", [set, frames, "--seconds", seconds], wait_s)


@tool(ACT)
def mame_run_lua(core: str, set: str, script: str, env: dict[str, str] | None = None,
                 seconds: int = 60, extra_args: list[str] | None = None, wait_s: int = 120) -> dict:
    """Run a Lua script headless under scripts/mame/run.lua, so a Lua error comes back as
    `lua_error` instead of a hidden modal dialog. `script` is a file under scripts/mame/ or a
    path. CORE_OUT is a fresh directory, returned with what the script wrote there."""
    root = C.resolve(core)
    lua_dir = root / "scripts" / "mame"
    run_lua = lua_dir / "run.lua" if (lua_dir / "run.lua").exists() else C.TEMPLATE_SCRIPTS / "mame" / "run.lua"
    sp = Path(script)
    if not sp.is_absolute():
        sp = next((p for p in (lua_dir / script, C.TEMPLATE_SCRIPTS / "mame" / script, root / script)
                   if p.exists()), None)
    if not sp or not sp.exists():
        raise ToolError(f"no Lua script {script}")
    md = C.coretools.mame_dir(root)
    exe = C.coretools.mame_exe(root)
    out = root / "debug" / "lua" / f"{set}-{sp.stem}-{time.strftime('%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    argv = [str(exe), set, "-nodebug", "-nowindow", "-video", "none", "-sound", "none",
            "-skip_gameinfo", "-nothrottle", "-autoboot_delay", "0",
            "-autoboot_script", str(run_lua), "-rompath", C.coretools.rompath(root),
            "-seconds_to_run", str(seconds), *(extra_args or [])]
    e = dict(os.environ, CORE_ROOT=str(root), CORE_SCRIPT=str(sp), CORE_OUT=out.as_posix(),
             **(env or {}))
    jid = J.start("mame", root.name, argv, md, e, {"out": str(out), "script": str(sp)})
    st = J.wait(jid, wait_s)
    if st["state"] not in ("starting", "running"):
        st["result"] = _capture_result(jid)
    return st


@tool(RO)
def mame_listxml(core: str, set: str, element: str = "") -> str:
    """mame -listxml <set>, optionally cut to one element type (rom, chip, display, dipswitch...)."""
    root = C.resolve(core)
    exe = C.coretools.mame_exe(root)
    r = subprocess.run([str(exe), "-listxml", set], capture_output=True, text=True, timeout=120,
                       cwd=C.coretools.mame_dir(root), **C.NO_WINDOW)
    xml = r.stdout
    if element:
        hits = re.findall(rf"<{element}\b.*?(?:/>|</{element}>)", xml, re.S)
        return "\n".join(hits)
    return xml[:60000]


# ---------------------------------------------------------------- the MiSTer

def _local_mra(root, name):
    stem = Path(name).stem
    for p in list(root.glob(f"releases/**/{stem}.mra")) + list(root.glob(f"**/{stem}.mra")):
        if "build" not in p.parts:
            return p
    return None


def _mra_check(b, mra_text):
    rbf = B.mra_rbf(mra_text)
    zips = B.mra_zips(mra_text)
    res = {"rbf_prefix": rbf, "zips": zips, "zips_missing": b.missing_zips(zips)}
    res.update(b.rbf_resolution(rbf) if rbf else {"launches": None})
    res["ok"] = bool(res["launches"]) and not res.get("outranked") and not res["zips_missing"]
    return res


@tool(RO)
def mister_state(core: str = "") -> dict:
    """What the MiSTer is running (/tmp/RBFNAME, CORENAME, FULLPATH) and, given a core, whether it
    is that core's build."""
    root = C.resolve(core) if core else None
    b = B.Board(root)
    s = b.state()
    if root:
        mine = C.coretools.project(root)
        s["is_this_core"] = bool(s["rbf"]) and re.sub(r"^Arcade-|_\d{8}.*$", "", s["rbf"]) == mine
    return s


@tool(RO)
def mister_check_mra(core: str, mra: str) -> dict:
    """Before a launch: which .rbf the .mra's <rbf> prefix resolves to on the device (the highest-
    sorting match, so a stray file can run instead of your deploy), and missing ROM zips."""
    root = C.resolve(core)
    p = _local_mra(root, mra)
    if not p:
        raise ToolError(f"no local {mra}.mra in {root.name}")
    return dict(_mra_check(B.Board(root), p.read_text(errors="replace")), mra=str(p))


def _mra_rbf_tags(root):
    return {B.mra_rbf(p.read_text(errors="replace")) for p in root.glob("releases/**/*.mra")} - {None}


@tool(ACT)
def mister_deploy(core: str, rev: str = "", stem: str = "", mra_only: bool = False,
                  rbf_only: bool = False, allow_timing_miss: bool = False, dry_run: bool = False,
                  wait_s: int = 180) -> dict:
    """scripts/deploy.py: checks the build log, .rbf age and timing, copies the .rbf and .mras.
    The .rbf goes up as <stem>_<next number>.rbf. stem defaults to the script's (the project),
    except that a revision whose name (less _stp) is an <rbf> tag in releases/ deploys under that
    name: a core shipping several bitstreams (KonamiGX, KonamiGXT1, KonamiGXT34) must not put one
    revision's build under another's name."""
    root = C.resolve(core)
    if not stem and rev:
        cand = re.sub(r"_stp$", "", rev)
        tags = {t.lower(): t for t in _mra_rbf_tags(root)}
        if cand.lower() in tags and cand.lower() != C.coretools.project(root).lower():
            stem = tags[cand.lower()]
    if stem:
        path, _ = C.script(root, "deploy.py")
        if "--stem" not in path.read_text(errors="replace"):
            raise ToolError(f"{path} has no --stem option; copy the skill's deploy.py, or deploy by hand")
    args = (["--rev", rev] if rev else []) + (["--stem", stem] if stem else []) +         (["--mra-only"] if mra_only else []) + (["--rbf-only"] if rbf_only else []) +         (["--allow-timing-miss"] if allow_timing_miss else []) + (["--dry-run"] if dry_run else [])
    st = _job("deploy", root, "deploy.py", args, wait_s, {"stem": stem or None})
    st["stem"] = stem or "(script default)"
    return st


@tool(ACT)
def mister_launch(core: str, mra: str, bounce: bool = True, check: bool = True) -> dict:
    """Launch a .mra (name or /media/fat path) through menu.rbf, so the FPGA really reloads, then
    wait until /tmp/CORENAME names the game (its <setname>); an error if it stays at MENU.
    A name resolves to _Arcade/_<folder>/ or _Arcade/, never a _Organized link. check=True first
    refuses when no .rbf matches, another file outranks your deploys, or zips are missing."""
    root = C.resolve(core)
    b = B.Board(root)
    res = {}
    local = _local_mra(root, mra)
    text = local.read_text(errors="replace") if local else ""
    if check and local:
        res["check"] = _mra_check(b, text)
        if not res["check"]["ok"]:
            raise ToolError("not launched: " + json.dumps(res["check"]))
    if mra.startswith("/"):
        path = B.checked_path(mra)
    else:
        name = Path(mra).name if mra.lower().endswith(".mra") else Path(mra).name + ".mra"
        path, hits = b.find_mra(name)
        if len(hits) > 1:
            res["other_copies"] = len(hits) - 1
    m = re.search(r"<setname>\s*([^<\s]+)\s*</setname>", text)
    res["launched"] = path
    res["setname"] = b.launch(path, bounce, m.group(1) if m else None)
    return res


@tool(ACT)
def mister_screenshot(core: str = "", native: bool = False, settle: float = 4) -> dict:
    """Take a screenshot and copy it here. native=True is the core's own resolution (the one to
    compare against MAME); the API's default is scaled."""
    root = C.resolve(core) if core else None
    base = (root / "debug" / "hw") if root else Path(tempfile.gettempdir()) / "mister_mcp"
    local = base / f"shot-{time.strftime('%Y%m%d-%H%M%S')}.png"
    return B.Board(root).screenshot(local, native, settle)


@tool(RO)
def mister_playing() -> str:
    """The Remote API's /games/playing."""
    return B.Board().get("/games/playing")


@tool(ACT)
def mister_osd() -> str:
    """Toggle the OSD (raw keycode 88; the named f12 route returns 200 and does nothing)."""
    B.Board().post("/controls/keyboard-raw/88")
    return "OSD toggled"


@tool(RO)
def mister_ls(path: str = "/media/fat/_Arcade") -> str:
    """ls -la under /media/fat/_Arcade, games, config or screenshots."""
    return B.Board().ls(path)


@tool(RO)
def mister_get(remote: str, local: str = "") -> dict:
    """Copy a file from the device (allowed trees, or /tmp/RBFNAME and the like)."""
    q = B.checked_path(remote)
    dst = Path(local) if local else Path(tempfile.gettempdir()) / "mister_mcp" / Path(q).name
    dst.parent.mkdir(parents=True, exist_ok=True)
    b = B.Board()
    b.scp(b.remote(q), str(dst))
    return {"remote": q, "local": str(dst), "bytes": dst.stat().st_size}


@tool(DESTRUCTIVE)
def mister_put(local: str, remote: str) -> dict:
    """Copy a local file to the device, into _Arcade, games, config or screenshots. Overwrites."""
    q = B.checked_path(remote, write=True)
    if not Path(local).is_file():
        raise ToolError(f"no file {local}")
    b = B.Board()
    b.scp(local, b.remote(q))
    return {"local": local, "remote": q}


@tool(RO)
def mister_devmem(addr: str, words: int = 1, width: int = 32) -> dict:
    """Read HPS physical memory with devmem (DDR3 shared blocks, bridges). Read only."""
    if not 1 <= words <= 256:
        raise ToolError("words is 1..256")
    return {"words": B.Board().devmem(addr, words, width)}


@tool(DESTRUCTIVE)
def mister_reboot(confirm: bool = False) -> str:
    """Reboot the MiSTer. Needs confirm=true."""
    if not confirm:
        raise ToolError("pass confirm=true to reboot the MiSTer")
    B.Board().sh("(sleep 1; reboot) >/dev/null 2>&1 &", timeout=20)
    return "rebooting"


# ---------------------------------------------------------------- probes (JTAG)

def _probe_job(root, script, args, wait_s):
    st = _job("probe", root, script, args, wait_s)
    if st["state"] in ("starting", "running"):
        st["note"] = "waiting for the JTAG lock or quartus_stp; poll jobs_status"
    else:
        st["output"] = J.log(st["id"])[-6000:]
    return st


@tool(ACT)
def probe_read(core: str, instance: str = "", fields: list[str] | None = None,
               wait_s: int = 120) -> dict:
    """scripts/probe.py read: ISSP probes over JTAG under the machine-wide lock (waits for running
    Quartus/ModelSim). Each line is tagged <core>|<build>|<set>| from the device; check it is
    this core."""
    root = C.resolve(core)
    args = ["read"] + (["--instance", instance] if instance else []) + \
        (["--fields", *fields] if fields else [])
    return _probe_job(root, "probe.py", args, wait_s)


@tool(ACT)
def probe_issp(core: str, instance: str, action: str = "", value: str = "",
               wait_s: int = 120) -> dict:
    """scripts/read_issp.py <instance> [clear|set <v>|pulse <v>]: decode an instance, or drive its
    source and leave it (set) or return it to 0 (pulse)."""
    root = C.resolve(core)
    if action not in ("", "clear", "set", "pulse"):
        raise ToolError("action is clear, set or pulse")
    if action in ("set", "pulse") and not value:
        raise ToolError(f"{action} needs a value")
    args = [instance] + ([action] if action else []) + ([value] if value else [])
    return _probe_job(root, "read_issp.py", args, wait_s)


RESULTS = {"build": _build_result, "sim": _sim_result, "mame": _capture_result, "sta": _sta_result}


def main():
    """The machine's one server: streamable HTTP on 127.0.0.1 (MISTER_MCP_PORT, default 8770),
    started at boot by the scheduled task from install_service.ps1. --stdio runs a private copy
    instead (the MCP Inspector, tests)."""
    import argparse
    import logging
    import socket
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdio", action="store_true")
    ap.add_argument("--port", type=int, default=int(C.machine_setting("MISTER_MCP_PORT", "8770")))
    a = ap.parse_args()
    if a.stdio:
        server.run(transport="stdio")
        return
    with socket.socket() as s:                # one instance per machine: the port is the lock
        if s.connect_ex(("127.0.0.1", a.port)) == 0:
            raise SystemExit(f"port {a.port} is already serving; not starting a second server")
    import sys
    J.BASE.mkdir(parents=True, exist_ok=True)
    log = open(J.BASE.parent / "server.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log             # a scheduled task has no console
    logging.basicConfig(stream=log, level=logging.INFO, force=True,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} server starting, pid {os.getpid()}, "
              f"port {a.port}\n")
    log.flush()
    server.run(transport="streamable-http", host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
