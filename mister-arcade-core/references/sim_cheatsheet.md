# Simulation and reference cheatsheet

With the `mister` MCP server connected, use its tools instead (`build_start`, `sim_run`,
`mame_capture`, `mame_run_lua`, `mister_deploy`, `probe_read`...; the table is in `SKILL.md`);
these are the commands they run. Every command runs from the core's repository root. Settings:
environment, then the core's `<core>.<KEY>` lines in `~/.mister-core.env`, then the rest of that
file. Output lands under `debug/` (git-ignored) unless said
otherwise. What each script needs per core is in `SCRIPTS_NOTES.md`; what the arguments mean
in detail is in each script's header.

## MAME: facts

```
mame -listxml <set> > debug/<set>.xml            # regions, ROM sizes, CRCs, DIPs, screen
mame -listclones <driver>                        # the sets and their parents
mame -version                                    # the .mra <mameversion>
python scripts/extract_romstart.py <set>         # ROM_START records from the driver source
python scripts/extract_dips.py <set>             # INPUT_PORTS from the driver source
mame <set> -autoboot_script scripts/mame/ports.lua   # the live port and field names
```

The driver source is `MAME_SRC`; `mame.exe`, not a fork build.

## MAME: references for benches

```
mame_capture(core, set, frame=1200[, name="title", coin=600, regions="regions_<name>.json"])
    debug/<set>-<name>/: a .bin per regions.json "read" region, reg_<chip>.bin per "wtap"
    region, MAME's screenshot, a manifest. The bench loads these. coin: coin up and play from
    that frame; regions: another profile in scripts/mame/.

mame_boot_trace(core, set, n=20000)
    debug/<set>-boot/<set>_boot.trace: the first N main-CPU bus accesses, read and write.
sim_compare_boot(core, set, cmd="compare"[, sys_trace=True, rtl="path"])
    diffs the RTL CPU bench's log against it; "replay" feeds the I/O reads back in; "dups"
    counts RTL writes repeated back to back. sys_trace: against mame_sys_trace's trace.

mame_sys_trace(core, set, frames=120)
    every write, I/O read and interrupt-vector read for N frames, with the mask.

mame_write_timing(core, sets=[set], skip=600, frames=1800[, extra="name:lo:hi", tag="_play"])
    writes to video RAM and registers by scanline relative to vblank; the sweep behind every
    snapshot decision. Run it again after coining up (coin=600, tag="_play") with inputs scripted.

CORE_SNAP_FRAME=N CORE_SNAP_OUT=dir mame <set> -autoboot_script scripts/mame/snap_at.lua
    MAME's screenshot at frame N
mame_capture(core, set, frame=1200, name="flip", dips=["Flip Screen=On"])
    pass 1 runs scripts/mame/setdip.lua into a per-capture cfg/, which MAME applies at
    power-on before any script: a game that reads its switches once at boot sees them.
    An unknown field or setting is an error, never a silent default.
mame <set> -debug -log; parse with scripts/parse_mame_trace.py
    expands MAME's instruction-start trace into the fetches a bench records
```

Headless form, as the MCP's MAME tools run it:
`mame <set> -rompath roms -video none -sound none -nothrottle -skip_gameinfo -seconds_to_run N -autoboot_script scripts/mame/<x>.lua`.
Lua errors are silent unless the script is wrapped by `scripts/mame/run.lua`. Parameters
reach Lua as `CORE_*` environment variables. A capture of a ROT270 set is landscape and turned
180 degrees, not mirrored.

## ModelSim

```
scripts/run_sim.sh <tb> [+PLUSARG=value ...]      # e.g. scripts/run_sim.sh video_tb +FRAME=1200
```

VHDL from `sim/vhdl.files` (packages first), all of `rtl/` through vlog, a fresh `work/`
each run, one run at a time. Use for VHDL vendored cores and bus-level benches. A bench that
prints nothing did not run; all checks failing at once is `$readmemh` from the wrong directory.
Before a session: `Get-Process vsim,vsimk | Select-Object Id,CPU,StartTime`, then
`Stop-Process -Force` on orphans (`taskkill` fails).

## Verilator

```
scripts/run_verilator.sh <tb> [-GNAME=value ...] [--threads=N] [+plusargs ...]
```

Sources in `sim/<tb>/verilator.files`; output in `obj_verilator/<tb>/`. Two-state, no VHDL:
VHDL CPUs arrive as GHDL conversions from the core's `scripts/verilator_prep.sh`. Use for
frame-level benches against `mame_capture` output. A disagreement with ModelSim is a
finding. Snapshots on Windows need binary mode; a comment starting "Verilator" is a pragma.

The shape to grow a bench into is wickerwaka's M72 simulator (`wickerwaka_irem.md`): a headless
JSON server with `run_frames`, `run_until` on a signal or PC, `screenshot`, `signal.read`,
`state.save/load`.

## State dumps

Sim, MAME and the board are compared from a snapshot, a few frames per run: state at the
frame of interest (MAME's Lua, or the board through the probe) into the bench, a few
frames, compare. Not hundreds of frames from reset: 1,318 s wall time to frame 1500
(BallySente `board_tb`). A bench that cannot load a snapshot gets that added
(`WORKFLOW.md` section 10).

`docs/STATE.md` lists every register and RAM; the dump is a file both simulators load
(`savestates.md`). The M72 layout (8-byte slot header, per-chunk `{index, width, count}`
header, packed data, FF terminator) is the model: parsable, so a hand-built sprite table can
be injected into a bench.

## Build and timing

```
build_start(core[, rev="<Name>_stp", seed=N])                # worktree at build/, HEAD only, slack-gated
build_report(core[, rev])                                    # commit, slack per clock, fit, .rbf path
locks_status()                                               # who holds JTAG, who is building
build_worst_paths(core[, rev])                               # worst clk_sys paths, no recompile
build_floorplan(core[, rev, list_depth=3])                   # placement PNG; list_depth: hierarchy counts
build_project(core, "rtl/synth_check")                       # a standalone harness project, in place
cd build && quartus_sta -t ../scripts/sta_failing_paths.tcl <rev>    # failing paths, detail
cd build && quartus_sta -t ../scripts/sta_all_fail.tcl <rev>         # every failing endpoint, summary
```

`quartus_*` are not on `PATH`: `QUARTUS_BIN`. Never `nohup` Quartus, never switch branches
while it reads the tree, never two instances on one project. Ask the analyser which path
fails:

```tcl
create_timing_netlist -model slow -temperature -40 -voltage 1100
read_sdc <the sdc>; update_timing_netlist
foreach_in_collection p [get_timing_paths -setup -npaths 3 -detail path_only] {
    post_message -type info [format "SLACK %s FROM %s TO %s" [get_path_info $p -slack] \
        [get_node_info [get_path_info $p -from] -name] [get_node_info [get_path_info $p -to] -name]] }
```

## Board

```
python scripts/validate_mra.py releases/*.mra                     # before every deploy
mister_deploy(core[, rbf_only | mra_only, dry_run])               # numbered from 30000001, slack-gated
mister_check_mra(core, "Game Title (set 1)")                      # which .rbf it resolves to, missing zips
mister_launch(core, "Game Title (set 1)")                         # through menu.rbf; takes the board
mister_screenshot(core, native=True)                              # the core's own resolution
mister_playing()
mister_state(core)                                                # what is loaded, and whether it is this core's build
probe_issp(core, "F"[, action="clear"])                           # holds the hwlock; prefixed core|build|set|
probe_read(core, fields=["frames", "cpu_accesses"])
probe_sequence(core, steps=[{"clear": "F"}, {"sleep": 2}, {"read": "F"}])   # one JTAG session
python scripts/decode_debug_screenshot.py shot.png --mode counters   # VGA-tap builds, no JTAG
```

The MCP tools are the only path to the board (`mister_ls`, `mister_get`, `mister_put`,
`mister_devmem`, `mister_memdump` for files and memory). The Remote API's screenshot is
the scaled output; `native=True` is the one for pixel comparison, and about one trigger in two
is lost: `mister_screenshot` sends once and errors when no new file appears, so call it again. `/dev/fb0` is the OSD surface, not the FPGA's video. JTAG
pokes through ISSP test a hypothesis on live hardware without a rebuild, with the CPU paused.
