"""MCP server for MiSTer arcade core work: builds, simulation, MAME and the board.

One HTTP server for the machine (README). What sessions share lives on disk under ~/.mister:
jobs, the call log and hwlock's JTAG markers, which the core's own scripts take.
Every tool takes `core` (repository directory, short name or path) where a core is involved.
"""
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import board as B
from . import cores as C
from . import jobs as J
from . import registry as REG
from . import reports as R
from .cores import ToolError
from .link import MONITOR, POLL as MONITOR_POLL

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


CORE_KEYS = ("MAME_DIR", "MAME_EXE", "MAME_SRC", "MAME_ROMPATH", "MAME_MEAS_EXE", "QUARTUS_BIN", "MODELSIM_BIN")


@tool(RO)
def core_settings(core: str) -> dict:
    """A core's tool settings as the tools resolve them, and where each comes from: env (the
    server's environment), core (<core>.<KEY> in ~/.mister-core.env, set with core_settings_set),
    machine (~/.mister-core.env) or unset."""
    return _core_settings(C.resolve(core))


def _core_settings(root):
    own = C.coretools.core_settings(root)
    machine = C.coretools._read_env_file(C.coretools.machine_env_path())
    out = {}
    for k in CORE_KEYS:
        for src, d in (("env", os.environ), ("core", own), ("machine", machine)):
            if d.get(k):
                out[k] = {"value": d[k], "from": src}
                break
        else:
            out[k] = {"value": None, "from": "unset"}
    return {"core": C.coretools.core_name(root), "settings": out,
            "file": str(C.coretools.machine_env_path())}


@tool(ACT)
def core_settings_set(core: str, key: str, value: str = "") -> dict:
    """Set one of a core's tool settings in ~/.mister-core.env as <core>.<KEY>=value, which wins
    over the machine-wide value (e.g. a core whose MAME build carries local driver work on a
    branch rebased onto master: MAME_DIR, MAME_EXE, MAME_SRC). An empty value removes it.
    Directories and files must exist."""
    root = C.resolve(core)
    if key not in CORE_KEYS:
        raise ToolError(f"key is one of {', '.join(CORE_KEYS)}")
    value = value.strip()
    if value:
        p = Path(value)
        if key.endswith(("_DIR", "_BIN", "_SRC")) and not p.exists():
            raise ToolError(f"{value} does not exist")
        if key.endswith("_EXE"):
            d = Path(C.coretools.core_settings(root).get("MAME_DIR") or C.coretools.setting("MAME_DIR", "", root))
            if not (p if p.is_absolute() else d / p).exists():
                raise ToolError(f"{value} is not in MAME_DIR ({d}); set MAME_DIR first")
    name = f"{C.coretools.core_name(root)}.{key}"
    path = C.coretools.machine_env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [ln for ln in lines if ln.split("=", 1)[0].strip() != name]
    if value:
        kept.append(f"{name}={value}")
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return {"set": name, "value": value or None, "file": str(path),
            "now": _core_settings(root)["settings"][key]}


@tool(ACT)
def core_register(core: str) -> dict:
    """Register the core's parameters with the server: scripts/core.json (.mra folder, held-back
    sets, required instances and macros, stage copies, default probe instance, STA clock),
    scripts/issp_fields.tcl (probe field tables) and scripts/issp_hooks.tcl (the core's own
    probe_issp commands, `proc hook_<name> {idx args}`). Validates them and stores a copy;
    build_start, mister_deploy, probe_* and build_worst_paths run from that copy and refuse while
    any file differs from it. Call it after every change to one. Returns what was registered and
    any warnings; refuses, registering nothing, on a problem."""
    root = C.resolve(core)
    return REG.register(root, branch=_git_branch(root))


@tool(RO)
def core_config(core: str) -> dict:
    """The core's registered parameters, when they were registered, and which of scripts/core.json,
    scripts/issp_fields.tcl and scripts/issp_hooks.tcl changed since (stale: call core_register).
    files_now: what the files would register as now, with problems and warnings, without
    registering."""
    root = C.resolve(core)
    st = REG.status(root)
    cfg, tables, problems, warnings = REG.validate(root)
    hooks = cfg.pop("_hooks")
    st["files_now"] = {"config": cfg, "tables": {k: len(v) for k, v in tables.items()}, "hooks": hooks,
                       "problems": problems, "warnings": warnings}
    return st


def _git_branch(root):
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                       text=True, **C.NO_WINDOW)
    return r.stdout.strip() or None


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


@tool(RO)
def jobs_stream_url(job: str, grep: str = "", start: str = "end") -> dict:
    """The WebSocket URL that streams a job's log, for Claude Code's Monitor tool
    (Monitor(ws={url}, ...)): one frame per log line matching the regex `grep`, then
    `END {state, returncode}` on every terminal state, then close. start: end (new lines only),
    start, or a line number."""
    J._dir(job)
    try:
        re.compile(grep)
    except re.error as e:
        raise ToolError(f"grep: {e}")
    from urllib.parse import urlencode
    port = int(C.machine_setting("MISTER_MCP_PORT", "8770"))
    qs = urlencode({k: v for k, v in (("grep", grep), ("from", start)) if v})
    return {"url": f"ws://127.0.0.1:{port}/jobs/{job}/log" + (f"?{qs}" if qs else ""),
            "state": J.status(job, 0)["state"]}


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
                allow_negative_slack: bool = False, wait_s: int = 5) -> dict:
    """Full staged Quartus compile (scripts/build_staged.py) as a job. Refuses while JTAG is held,
    as the script does. Fails on negative slack on any clock unless allow_negative_slack (a debug
    revision only; a release must close timing). Builds take tens of minutes; poll jobs_status."""
    root = C.resolve(core)
    r = _rev(root, rev)
    args = ["--rev", r] + (["--seed", seed] if seed is not None else []) + \
        (["--allow-dirty"] if allow_dirty else []) + \
        (["--allow-negative-slack"] if allow_negative_slack else [])
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
    tcl, shared = C.script(root, "report_worst_paths.tcl")
    db = root / "build" if (root / "build" / "db").is_dir() else root
    sta = C.coretools.quartus_bin(root) / "quartus_sta.exe"
    argv = [str(sta), "-t", str(tcl), r]
    env = dict(os.environ, CORE_ROOT=str(root))
    if shared:
        env["STA_CLOCK"] = REG.config(root)["sta_clock"]
    jid = J.start("sta", root.name, argv, db, env, {"rev": r, "db": str(db)})
    st = J.wait(jid, wait_s)
    if st["state"] == "done":
        st["result"] = _sta_result(jid)
    return st


def _qpf_revision(qpf):
    m = re.search(r'PROJECT_REVISION\s*=\s*"([^"]+)"', qpf.read_text(errors="replace"))
    return m.group(1) if m else qpf.stem


def _project_result(jid):
    m = J.meta(jid)["meta"]
    o = Path(m["work"]) / "output_files"
    res = {"work": m["work"], "rev": m["rev"]}
    s, f = o / f"{m['rev']}.sta.summary", o / f"{m['rev']}.fit.summary"
    if s.exists():
        res["sta"] = R.sta(s)
        setup = [b["slack"] for b in res["sta"] if "Setup" in b["type"]]
        res["worst_setup"] = min(setup) if setup else None
    if f.exists():
        fit = R.fit(f)
        res["fit"] = {k: v for k, v in fit.items() if k.startswith(("Logic utilization", "Total"))}
    return res


@tool(ACT)
def build_project(core: str, project: str, rev: str = "", seed: int | None = None,
                  clocks: dict[str, float] | None = None, tag: str = "", wait_s: int = 5) -> dict:
    """Compile a standalone Quartus project in the core (a synth harness such as rtl/synth_check,
    not a revision of the core) as a job, under the hwlock rule. `project` is its .qpf or
    directory, relative to the core. With no seed or clocks it compiles in place. With either,
    it compiles a copy in build/<project dir>/<tag or s<seed>>/: the .qsf's paths outside the
    project are made absolute, SEED is set, and each create_clock named in `clocks` (clock -name
    or port; "*" for all) gets that -period in ns. Result: slack per clock and fit totals."""
    root = C.resolve(core)
    p = (root / project).resolve()
    qpf = p if p.suffix == ".qpf" else next(iter(sorted(p.glob("*.qpf"))), None) if p.is_dir() else None
    if not qpf or not qpf.exists() or root not in qpf.parents:
        raise ToolError(f"no .qpf at {project} in {root.name}")
    if qpf.parent == root:
        raise ToolError("that is the core's own project; use build_start")
    r = rev or _qpf_revision(qpf)
    dest = None
    if seed is not None or clocks:
        name = tag or "_".join([f"s{seed}" if seed is not None else "s-"] +
                               [f"{k}{v:g}".replace("*", "all") for k, v in (clocks or {}).items()])
        dest = root / "build" / qpf.parent.name / re.sub(r"[^\w.-]", "_", name)
    work = dest or qpf.parent
    for j in J.listing(limit=50, active_only=True):
        if j["kind"] == "project" and j["meta"].get("work") == str(work):
            raise ToolError(f"job {j['id']} is already compiling {work}")
    tpl = C.TEMPLATE_SCRIPTS
    scripts = [str(d) for d in (root / "scripts", tpl) if d.is_dir()]
    spec = {"root": str(root), "scripts": scripts, "qpf": str(qpf), "rev": r,
            "dest": str(dest) if dest else None, "seed": seed, "clocks": clocks or {}}
    sp = Path(tempfile.mkdtemp(prefix="qproject_")) / "spec.json"
    sp.write_text(json.dumps(spec), encoding="utf-8")
    argv = [C.python_exe(), str(Path(__file__).with_name("qproject.py")), str(sp)]
    env = dict(os.environ, **C.coretools.core_settings(root), CORE_ROOT=str(root), PYTHONIOENCODING="utf-8",
               PYTHONUNBUFFERED="1")
    jid = J.start("project", root.name, argv, root, env, {"rev": r, "work": str(work), "qpf": str(qpf)})
    st = J.wait(jid, wait_s)
    if st["state"] not in ("starting", "running"):
        st["result"] = _project_result(jid)
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
def build_floorplan(core: str, rev: str = "", reuse: bool = False, list_depth: int = 0,
                    wait_s: int = 600) -> dict:
    """scripts/floorplan.py: placement image by hierarchy from the compiled database (build/),
    grouped by the core's scripts/floorplan.json; debug/floorplan/<rev>.png and <rev>_groups.md.
    list_depth=N prints the hierarchy to that depth with resource counts instead, to write the
    groups from. reuse: the last atom dump, no Quartus run."""
    root = C.resolve(core)
    args = (["--rev", rev] if rev else []) + (["--reuse"] if reuse else [])
    args += ["--list", "--depth", int(list_depth)] if list_depth else []
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
def sim_compare_boot(core: str, set: str, cmd: str = "compare", sys_trace: bool = False,
                     rtl: str = "", wait_s: int = 300) -> dict:
    """scripts/compare_boot_trace.py replay|compare|dups <set>: the RTL's boot against MAME's trace.
    sys_trace: against mame_sys_trace's debug/<set>-sys/<set>_sys.trace instead of the boot trace.
    rtl: the RTL trace, relative to the core (default <set>_rtl.trace beside MAME's). dups counts
    the RTL's writes repeated back to back."""
    root = C.resolve(core)
    if cmd not in ("replay", "compare", "dups"):
        raise ToolError("cmd is replay, compare or dups")
    args = [cmd, set] + (["--sys"] if sys_trace else [])
    if rtl:
        p = (root / rtl).resolve()
        if not p.is_relative_to(root.resolve()) or not p.is_file():
            raise ToolError(f"no RTL trace {rtl} in {root.name}")
        args += ["--rtl", str(p)]
    return _job("compare", root, "compare_boot_trace.py", args, wait_s)


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

def _git(path, *args):
    p = Path(path)
    d = p if p.is_dir() else p.parent
    r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, **C.NO_WINDOW)
    return r.stdout.strip() if r.returncode == 0 else None


def _mamedev_master(path):
    """The remote-tracking ref of mamedev/mame's master in the checkout holding path, if any."""
    for line in (_git(path, "remote", "-v") or "").splitlines():
        name, url = line.split()[:2]
        if "mamedev/mame" in url:
            return f"{name}/master"
    return None


@tool(RO)
def mame_version(core: str) -> dict:
    """The MAME binary against MAME_SRC. Both must be MAME master: the binary a git build (its
    version names a commit) of the commit MAME_SRC is at, and MAME_SRC a checkout of mamedev
    master no further behind it than the last fetch shows. A release binary, a different commit
    or a stale checkout means traces do not describe current MAME."""
    root = C.resolve(core)
    exe = C.coretools.mame_exe(root)
    r = subprocess.run([str(exe), "-version"], capture_output=True, text=True, timeout=30,
                       **C.NO_WINDOW)
    binary = r.stdout.strip()
    src = C.coretools.setting("MAME_SRC", None, root)
    m = re.search(r"-g([0-9a-f]{7,})", binary)
    bin_commit = m.group(1) if m else None
    head = _git(src, "rev-parse", "HEAD") if src else None
    upstream = _mamedev_master(src) if src else None
    behind = int(_git(src, "rev-list", "--count", f"HEAD..{upstream}") or 0) if upstream else None
    ahead = int(_git(src, "rev-list", "--count", f"{upstream}..HEAD") or 0) if upstream else None
    notes = []
    if not bin_commit:
        notes.append("binary is a release build: build MAME master and point MAME_DIR at it")
    elif head and not head.startswith(bin_commit):
        notes.append(f"binary is built from {bin_commit}, MAME_SRC is at {head[:11]}: rebuild")
    if src and not upstream:
        notes.append("MAME_SRC's checkout has no mamedev/mame remote")
    elif behind:
        notes.append(f"MAME_SRC is {behind} commits behind {upstream} as last fetched: "
                     "pull (or rebase local driver work onto it) and rebuild")
    if ahead:
        notes.append(f"MAME_SRC has {ahead} commits not on {upstream}: local driver work")
    return {"exe": str(exe), "binary": binary, "binary_commit": bin_commit, "mame_src": src,
            "src_head": head, "upstream": upstream, "behind_master": behind,
            "ahead_of_master": ahead, "note": "; ".join(notes) or None}


def _capture_result(jid):
    m = J.meta(jid)
    out = m["meta"].get("out")
    if not out:
        return None
    o = Path(out)
    err = o / "lua_error.txt"
    res = {"out": out, "lua_error": err.read_text(errors="replace").strip() if err.exists() else None,
           "error": (o / "ERROR.txt").read_text(errors="replace").strip()
           if (o / "ERROR.txt").exists() else None,
           "manifest": R.manifest(o), "files": sorted(p.name for p in o.glob("*"))[:60]}
    if m["meta"].get("fail_on"):
        rx = re.compile(m["meta"]["fail_on"])
        res["fail_lines"] = [ln for ln in J.log(jid).splitlines() if rx.search(ln)][:50]
    return res


@tool(ACT)
def mame_capture(core: str, set: str, frame: int = 1200, dips: list[str] | None = None,
                 name: str = "", seconds: int | None = None, coin: int = 0, regions: str = "",
                 wait_s: int = 300) -> dict:
    """scripts/mame_capture.py: RAM/region dumps and reference.png at a frame, with a manifest.
    dips are NAME=SETTING. coin: insert a coin at this frame, press Start and play (regions.json
    "inputs" name the ports). regions: a profile in scripts/mame/ other than regions.json.
    Output in debug/<set>-<name or frame>."""
    root = C.resolve(core)
    if regions and not re.fullmatch(r"[\w.-]+\.json", regions):
        raise ToolError("regions is a file name in scripts/mame/, e.g. regions_de156.json")
    args = [set, "--frame", frame] + (["--name", name] if name else []) + \
        (["--seconds", seconds] if seconds else []) + (["--coin", coin] if coin else []) + \
        (["--regions", regions] if regions else [])
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
def mame_write_timing(core: str, sets: list[str], skip: int = 600, frames: int = 1800, coin: int = 0,
                      extra: str = "", tag: str = "", wait_s: int = 300) -> dict:
    """scripts/write_timing.py: when each set writes video RAM and registers relative to vblank,
    counted per scanline over `frames` frames after `skip` (regions.json "sweep", plus extra
    name:hexlo:hexhi,...). coin: frame to insert a coin at (0 none). Results in
    debug/wtiming/<set><tag>.txt; the report is the job's log."""
    root = C.resolve(core)
    if not sets:
        raise ToolError("name at least one set")
    args = [*sets, "--skip", skip, "--frames", frames, "--coin", coin]
    args += ["--extra", extra] if extra else []
    args += ["--tag", tag] if tag else []
    return _job("mame", root, "write_timing.py", args, wait_s)


@tool(ACT)
def mame_run_lua(core: str, set: str, script: str, env: dict[str, str] | None = None,
                 seconds: int = 60, extra_args: list[str] | None = None, out: str = "",
                 clean: bool = False, nvram: str = "", debug: bool = False, fail_on: str = "",
                 wait_s: int = 120) -> dict:
    """Run a Lua script headless under scripts/mame/run.lua, so a Lua error comes back as
    `lua_error` instead of a hidden modal dialog. `script` is a file under scripts/mame/ or a
    path; `env` reaches the script (CORE_FRAMES, CORE_EVENTS...). CORE_OUT is `out` (a directory
    in the core, e.g. debug/<set>-boot, emptied first if `clean`) or else a fresh one.
    NVRAM and cfg are fresh per run, in CORE_OUT/nvram and /cfg; `nvram` seeds the NVRAM from a
    directory (its <set>/ if it has one), also kept as CORE_OUT/nvram_start. `debug` runs with
    -debug -debugger none, for scripts that use the debugger. `fail_on` is a regex: matching log
    lines come back as `fail_lines`. `seconds` is MAME's -seconds_to_run, with no cap."""
    root = C.resolve(core)
    lua_dir = root / "scripts" / "mame"
    run_lua = lua_dir / "run.lua" if (lua_dir / "run.lua").exists() else C.TEMPLATE_SCRIPTS / "mame" / "run.lua"
    sp = Path(script)
    if not sp.is_absolute():
        sp = next((p for p in (lua_dir / script, C.TEMPLATE_SCRIPTS / "mame" / script, root / script)
                   if p.exists()), None)
    if not sp or not sp.exists():
        raise ToolError(f"no Lua script {script}")
    try:
        re.compile(fail_on)
    except re.error as e:
        raise ToolError(f"fail_on: {e}")
    md = C.coretools.mame_dir(root)
    exe = C.coretools.mame_exe(root)
    if out:
        o = (root / out).resolve()
        if root not in o.parents:
            raise ToolError(f"out must be inside {root.name}")
        for j in J.listing(limit=50, active_only=True):
            if j["kind"] == "mame" and j["meta"].get("out") == str(o):
                raise ToolError(f"job {j['id']} is already writing {out}")
        if clean and o.exists():
            shutil.rmtree(o)
        out = o
    else:
        out = root / "debug" / "lua" / f"{set}-{sp.stem}-{time.strftime('%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    # NVRAM and cfg are the run's own, so MAME's installed ones are neither read nor written
    for d in ("nvram", "nvram_start", "cfg"):
        if (out / d).exists():
            shutil.rmtree(out / d)
    if nvram:
        src = Path(nvram) if Path(nvram).is_absolute() else root / nvram
        if not src.is_dir():
            raise ToolError(f"no NVRAM directory {nvram}")
        src = src / set if (src / set).is_dir() else src
        shutil.copytree(src, out / "nvram" / set)
        shutil.copytree(src, out / "nvram_start")
    argv = [str(exe), set, *(["-debug", "-debugger", "none"] if debug else ["-nodebug"]),
            "-nowindow", "-video", "none", "-sound", "none",
            "-skip_gameinfo", "-nothrottle", "-autoboot_delay", "0",
            "-autoboot_script", str(run_lua), "-rompath", C.coretools.rompath(root),
            "-nvram_directory", (out / "nvram").as_posix(), "-cfg_directory", (out / "cfg").as_posix(),
            "-seconds_to_run", str(seconds), *(extra_args or [])]
    e = dict(os.environ, CORE_ROOT=str(root), CORE_SCRIPT=str(sp), CORE_OUT=out.as_posix(),
             **(env or {}))
    jid = J.start("mame", root.name, argv, md, e, {"out": str(out), "script": str(sp),
                                                   "fail_on": fail_on})
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
def mister_state(core: str = "", live: bool = False) -> dict:
    """What the MiSTer is running (/tmp/RBFNAME, CORENAME, FULLPATH) and, given a core, whether it
    is that core's build. The server reads it every 10 s on its one SSH connection, and this
    returns that reading (`checked`, `age_s`; `since` is when this core was first seen) without
    touching the board. live=True reads the board now."""
    root = C.resolve(core) if core else None
    snap = MONITOR.snapshot()
    if live or snap["age_s"] is None or snap["age_s"] > 3 * MONITOR_POLL:
        MONITOR.read()                        # no monitor (--stdio) or stale: read now
        snap = MONITOR.snapshot()
    s = {k: snap[k] for k in ("rbf", "setname", "path", "checked", "age_s", "since")}
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
    MONITOR.poke()
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


def _xfer(mode, local, remote, wait_s, extra=(), meta=None):
    """mister_get / mister_put: xfer.py as a job, whose result line is merged into the status."""
    b = B.Board()
    argv = [sys.executable, str(Path(__file__).with_name("xfer.py")), mode, B._putty("pscp.exe"),
            B._putty("plink.exe"), f"{b.user}@{b.host}", str(local), remote, *extra]
    env = dict(os.environ, MISTER_PASSWORD=b.pw, PYTHONIOENCODING="utf-8")
    jid = J.start(mode, "", argv, Path(local).resolve().parent, env,
                  dict(meta or {}, local=str(local), remote=remote))
    st = J.wait(jid, wait_s)
    if st["state"] in ("starting", "running"):
        st["note"] = "still copying; poll jobs_status (the log has pscp's progress)"
    else:
        log = J.log(jid)
        st["output"] = log[-2000:]
        for ln in reversed(log.splitlines()):
            if ln.startswith("{"):
                st.update(json.loads(ln))
                break
    return st


@tool(RO)
def mister_get(remote: str, local: str = "", keep: bool = False, wait_s: int = 120) -> dict:
    """Copy a file from the device (allowed trees, /tmp/RBFNAME and the like, or a mister_memdump
    file). A job: the copy goes to <local>.partial and is renamed into place once its size matches
    the board's. Waits up to wait_s (at most 240); a large file returns a job id, and jobs_status
    reports the result (about 2.5 MB/s sustained, the board's SSH is the limit; copies at the same
    time slow each other). A mister_memdump file is deleted from the board after the copy (/tmp is
    its RAM) unless keep=True; unread ones expire after 10 minutes. Done: local, bytes."""
    q = B.checked_path(remote)
    dst = Path(local) if local else Path(tempfile.gettempdir()) / "mister_mcp" / Path(q).name
    dst.parent.mkdir(parents=True, exist_ok=True)
    return _xfer("get", dst.resolve(), q, wait_s, ["rm"] if B.DUMP.match(q) and not keep else [])


@tool(DESTRUCTIVE)
def mister_put(local: str, remote: str, wait_s: int = 60) -> dict:
    """Copy a local file to the device, into _Arcade, games, config or screenshots. Overwrites.
    A job: the file is uploaded to `remote`.partial, its size checked against the local file,
    then renamed over `remote`, so a failed or cancelled upload leaves `remote` as it was.
    Waits up to wait_s (at most 240); a large file returns a job id, and jobs_status reports the
    result and the log has pscp's progress (about 2.5 MB/s sustained alone; uploads at the same
    time slow each other, so send large files one at a time). Missing directories are created."""
    q = B.checked_path(remote, write=True)
    if not Path(local).is_file():
        raise ToolError(f"no file {local}")
    return _xfer("put", Path(local).resolve(), q, wait_s)


@tool(DESTRUCTIVE)
def mister_install_main(name: str, local: str = "", restore: bool = False) -> dict:
    """Install an alternate Main binary, /media/fat/<name> (MiSTer_<something>, the file a
    MiSTer.ini section's main= names; never MiSTer itself). local: a 32-bit ARM ELF; it is
    uploaded to a temporary name, its md5 checked on the board, the old binary kept as
    <name>.prev and the new one renamed over it. restore=True puts <name>.prev back instead.
    Returns the md5 on the board and the Main binaries running before. Main re-execs the binary
    when the running one's path differs from the core's main= (user_io.cpp), and a replaced
    running binary reads as '<path> (deleted)', so the next launch of a core in that section
    starts the new one."""
    b = B.Board()
    if restore:
        return b.restore_main(name)
    if not local:
        raise ToolError("give local, the binary to install, or restore=True")
    return b.install_main(local, name)


@tool(RO)
def mister_devmem(addr: str, words: int = 1, width: int = 32) -> dict:
    """Read HPS physical memory with devmem (DDR3 shared blocks, bridges). Read only."""
    if not 1 <= words <= 256:
        raise ToolError("words is 1..256")
    return {"words": B.Board().devmem(addr, words, width)}


@tool(ACT)
def mister_memdump(ranges: list[dict[str, str]], timeout_s: int = 120) -> dict:
    """Copy physical-memory ranges (DDR3: state dumps, VRAM), concatenated in the order given,
    into a new file on the MiSTer; fetch it with mister_get(remote), which then deletes it.
    ranges: [{"addr": "0x34000000", "size": "0x2620000"}, ...], addresses page-aligned (4 KB),
    all below 0x40000000. Uses mmap (read() on /dev/mem fails above the kernel's memory). Returns
    the file's path, each range's offset in it, and expires_min: an unread dump is deleted after
    that. Refuses when /tmp lacks the room."""
    try:
        pairs = [(int(str(r["addr"]), 0), int(str(r["size"]), 0)) for r in ranges]
    except (KeyError, TypeError, ValueError):
        raise ToolError('ranges: [{"addr": "0x...", "size": "0x..."}, ...]')
    if not pairs:
        raise ToolError("no ranges")
    return B.Board().memdump(pairs, timeout=max(10, min(int(timeout_s), 600)))


@tool(DESTRUCTIVE)
def mister_reboot(confirm: bool = False) -> str:
    """Reboot the MiSTer. Needs confirm=true."""
    if not confirm:
        raise ToolError("pass confirm=true to reboot the MiSTer")
    B.Board().sh("(sleep 1; reboot) >/dev/null 2>&1 &", timeout=20)
    MONITOR.poke()
    return "rebooting"


# ---------------------------------------------------------------- probes (JTAG)

def _probe_job(root, script, args, wait_s):
    st = _job("probe", root, script, args, wait_s)
    if st["state"] in ("starting", "running"):
        st["note"] = "waiting for the JTAG lock or quartus_stp; poll jobs_status"
    else:
        st["output"] = J.log(st["id"])[-6000:]
    # the whole output, for a core script that turns a long read (a hook's dump) into a file
    st["log_path"] = str(J._dir(st["id"]) / "log.txt")
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
    """scripts/read_issp.py <instance> [clear|set <v>|pulse <v>|<hook> <args>]: decode an instance,
    or drive its source and leave it (set) or return it to 0 (pulse). Any other action is one of
    the core's registered hooks (scripts/issp_hooks.tcl, `proc hook_<action>`), run in the same
    session after the decode; value is its arguments, space-separated. `output` is the last 6000
    characters; `log_path` is the whole output, for a core script to convert (KonamiGX's memdump)."""
    root = C.resolve(core)
    if action not in ("", "clear", "set", "pulse"):
        hooks = REG.status(root).get("hooks") or []
        if action not in hooks:
            raise ToolError(f"action is clear, set, pulse or a registered hook ({', '.join(hooks) or 'none'})")
        if not re.fullmatch(r"[\w .:+-]*", value):
            raise ToolError("hook arguments: letters, digits and . : + - only")
        return _probe_job(root, "read_issp.py", [instance, action, *value.split()], wait_s)
    if action in ("set", "pulse") and not value:
        raise ToolError(f"{action} needs a value")
    args = [instance] + ([action] if action else []) + ([value] if value else [])
    return _probe_job(root, "read_issp.py", args, wait_s)


def _sequence_result(jid):
    for ln in reversed(J.log(jid).splitlines()):
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except ValueError:
                break
    return None


@tool(ACT)
def probe_sequence(core: str, steps: list[dict], wait_s: int = 120) -> dict:
    """ISSP steps in one quartus_stp session, under the machine-wide JTAG lock, so a clear, a
    timed run and a read are one measurement. Steps, in order: {"clear": id}, {"set": id,
    "value": n}, {"pulse": id, "value": n}, {"sleep": seconds}, {"read": id}. Each read returns
    t_ms (since the session started), the raw bits, and fields decoded with the instance's table
    in the core's scripts/issp_fields.tcl. `tag` is <core>|<build>|<set>| from the device."""
    root = C.resolve(core)
    if not steps or len(steps) > 1000:
        raise ToolError("steps: 1 to 1000")
    for s in steps:
        k = next((k for k in ("read", "set", "pulse", "clear", "sleep") if k in s), None)
        if not k or (k in ("set", "pulse") and "value" not in s):
            raise ToolError(f"bad step {s}")
        if k != "sleep" and not re.fullmatch(r"\w+", str(s[k])):
            raise ToolError(f"bad instance id in {s}")
    # field tables: the core's own read_issp.tcl if it still has one, else its registered issp_fields.tcl
    tcl, shared = C.script(root, "read_issp.tcl")
    if shared:
        tcl = REG.env(root).get("ISSP_FIELDS", "")
    spec = {"root": str(root), "scripts": [str(d) for d in (root / "scripts", C.TEMPLATE_SCRIPTS, C.MCP_SCRIPTS)
                                           if d.is_dir()],
            "tcl": str(tcl), "here_tcl": str(Path(__file__).with_name("issp_seq.tcl")), "steps": steps}
    sp = Path(tempfile.mkdtemp(prefix="issp_seq_")) / "spec.json"
    sp.write_text(json.dumps(spec), encoding="utf-8")
    argv = [C.python_exe(), str(Path(__file__).with_name("issp_seq.py")), str(sp)]
    env = dict(os.environ, **C.coretools.core_settings(root), CORE_ROOT=str(root), PYTHONIOENCODING="utf-8",
               PYTHONUNBUFFERED="1")
    jid = J.start("probe_seq", root.name, argv, root, env, {"steps": len(steps)})
    st = J.wait(jid, wait_s)
    if st["state"] in ("starting", "running"):
        st["note"] = "waiting for the JTAG lock or quartus_stp; poll jobs_status"
    else:
        st["result"] = _sequence_result(jid)
    return st


RESULTS = {"build": _build_result, "sim": _sim_result, "mame": _capture_result, "sta": _sta_result,
           "project": _project_result, "probe_seq": _sequence_result}


def merge_deploy_log(old=None):
    """Fold %LOCALAPPDATA%/mister_deployed.tsv into ~/.mister/mister_deployed.tsv: lines from
    both, once each, in time order (identity.lookup takes the last match). Repeating it is
    harmless, so it runs at every start and catches a core whose identity.py still writes there."""
    old = Path(old) if old else Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "mister_deployed.tsv"
    new = J.STATE / "mister_deployed.tsv"
    if not old.exists():
        return 0
    rows = []
    for p in (new, old):
        if p.exists():
            rows += [ln.rstrip("\r") for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()]
    seen, out = set(), []
    for ln in rows:
        if ln.strip() and ln not in seen:
            seen.add(ln)
            out.append(ln)
    out.sort(key=lambda ln: (ln.split("\t") + ["", "", "", ""])[3])
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(out)


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
    merge_deploy_log()
    log = open(J.BASE.parent / "server.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log             # a scheduled task has no console
    logging.basicConfig(stream=log, level=logging.INFO, force=True,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} server starting, pid {os.getpid()}, "
              f"port {a.port}\n")
    log.flush()
    import uvicorn
    from starlette.routing import WebSocketRoute
    from .stream import job_log
    from . import web
    app = server.streamable_http_app(host="127.0.0.1")
    app.router.routes.append(WebSocketRoute("/jobs/{id}/log", lambda ws: job_log(ws, _ws_record)))
    app.router.routes.extend(web.routes(_core_settings, CALLS))
    MONITOR.start()
    uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=a.port, log_level="info")).run()


def _ws_record(entry):
    _record({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": True, **entry})


if __name__ == "__main__":
    main()
