# Simulation and reference cheatsheet

Every command runs from the core's repository root. Settings: environment, then the core's
`mister.env`, then `~/.mister-core.env`. Output lands under `debug/` (git-ignored) unless said
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
python scripts/mame_capture.py <set> --frame 1200 [--name title]
    debug/<set>-<name>/: a .bin per regions.json "read" region, reg_<chip>.bin per "wtap"
    region, MAME's screenshot, a manifest. The bench loads these.

python scripts/mame_boot_trace.py <set> 20000
    debug/<set>-boot/<set>_boot.trace: the first N main-CPU bus accesses, read and write.
python scripts/compare_boot_trace.py compare <set>
    diffs the RTL CPU bench's log against it; "replay" feeds the I/O reads back in.

python scripts/mame_sys_trace.py <set> 120
    every write, I/O read and interrupt-vector read for N frames, with the mask.

python scripts/write_timing.py <set> [--skip 600 --frames 1800 --extra name:lo:hi --tag play]
    writes to video RAM and registers by scanline relative to vblank; the sweep behind every
    snapshot decision. Run it again after coining up (--tag play) with inputs scripted.

CORE_SNAP_FRAME=N CORE_SNAP_OUT=dir mame <set> -autoboot_script scripts/mame/snap_at.lua
    MAME's screenshot at frame N
python scripts/mame_capture.py <set> --frame 1200 --name flip --dip "Flip Screen=On"
    pass 1 runs scripts/mame/setdip.lua into a per-capture cfg/, which MAME applies at
    power-on before any script: a game that reads its switches once at boot sees them.
    An unknown field or setting is an error, never a silent default.
mame <set> -debug -log; parse with scripts/parse_mame_trace.py
    expands MAME's instruction-start trace into the fetches a bench records
```

Headless form, as the scripts run it:
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
frame-level benches against `mame_capture.py` output. A disagreement with ModelSim is a
finding. Snapshots on Windows need binary mode; a comment starting "Verilator" is a pragma.

The shape to grow a bench into is wickerwaka's M72 simulator (`wickerwaka_irem.md`): a headless
JSON server with `run_frames`, `run_until` on a signal or PC, `screenshot`, `signal.read`,
`state.save/load`.

## State dumps

`docs/STATE.md` lists every register and RAM; the dump is a file both simulators load
(`savestates.md`). The M72 layout (8-byte slot header, per-chunk `{index, width, count}`
header, packed data, FF terminator) is the model: parsable, so a hand-built sprite table can
be injected into a bench.

## Build and timing

```
bash scripts/build.sh --map                                  # elaborate only, in tree, minutes
python scripts/build_staged.py [--rev <Name>_stp] [--seed N] # worktree at build/, HEAD only, slack-gated
python scripts/hwlock.py --status                            # who holds JTAG, who is building
cd build && quartus_sta -t ../scripts/report_worst_paths.tcl <rev>   # worst clk_sys paths
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
python scripts/deploy.py [--rbf-only | --mra-only] [--dry-run]   # numbered from 30000001, slack-gated
python scripts/validate_mra.py releases/*.mra                     # before every deploy
python scripts/hw.py launch "Game Title (set 1)"                  # through menu.rbf; takes the board
python scripts/hw.py shot --native --out debug/hw/shot.png        # the core's own resolution
python scripts/hw.py run "Game Title (set 1)"                     # launch, settle, shot
python scripts/hw.py playing
python scripts/read_issp.py [F] [clear]                           # holds the hwlock; prefixed core|build|set|
python scripts/probe.py --fields frames cpu_accesses
python scripts/decode_debug_screenshot.py shot.png --mode counters   # VGA-tap builds, no JTAG
```

`MSYS_NO_PATHCONV=1` in front of anything that passes `/media/fat/...`. Non-interactive SSH on
Windows: `echo y | plink.exe -ssh -pw <pw> root@<host> "cmd"`. The Remote API's screenshot is
the scaled output; `--native` is the one for pixel comparison, and about one trigger in two
is lost, so the script re-sends. `/dev/fb0` is the OSD surface, not the FPGA's video. JTAG
pokes through ISSP test a hypothesis on live hardware without a rebuild, with the CPU paused.
