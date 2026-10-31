# Tools

Builds, deploys, the board, probes and the MAME captures and traces are the `mister` MCP
server's tools (`SKILL.md`, "The `mister` MCP server", has the task-to-tool table; arguments in
the server's `mcp/TOOLS.md`). The scripts behind them live in the server, which runs a core's own
copy of a script where it has one. The scripts still in the core run from its repository root.
Settings come from the environment, the core's `<core>.<KEY>` lines in `~/.mister-core.env`
(set with `core_settings_set`), then the rest of that file (template: `mister-core.env.example`
in the skill). MAME tools read `scripts/mame/regions.json`; see `SCRIPTS_NOTES.md` for every
script and what each core fills in.

## MAME as the reference

Headless run, as `mame_capture` does it:

```
mame <set> -rompath roms -video none -sound none -nothrottle -skip_gameinfo \
     -seconds_to_run <n> -autoboot_script scripts/mame/<script>.lua
```

Parameters reach the Lua script as environment variables (`CORE_OUT`, `CORE_TAG`,
`CORE_FRAMES`, ...). `scripts/mame/run.lua` wraps a script so Lua errors are printed
instead of silently ending the run.

| Script | Records | From |
|---|---|---|
| `mame/run.lua` | wrapper: surfaces Lua failures | Fuuki, KonamiGX |
| `mame/snap_at.lua` | MAME screenshot at frame N | Fuuki, KonamiGX |
| `mame/ports.lua`, `mame/setdip.lua` | list input ports; set DIPs before boot | Fuuki, KonamiGX |
| `mame/capture.lua` + `mame_capture` | RAM dumps, register files rebuilt from a write tap (write-only chips), screenshot, manifest, at frame N | KonamiGX |
| `mame/boottrace.lua` + `mame_boot_trace` | first N main-CPU bus accesses via a read/write tap, not `trace` (which logs instruction starts, not accesses) | KonamiGX, from MS32, from Seta |
| `mame/systrace.lua` + `mame_sys_trace` | every write, I/O reads, interrupt-vector reads, per frame, with the interrupt mask | KonamiGX |
| `mame/wtiming.lua` + `mame_write_timing` | video-RAM and register writes by scanline relative to vblank | Seta; see `video_write_sweep.md` |

The capture is the reference for testbenches: RAM and register dumps are what the game
wrote and the RTL must hold the same bytes. MAME's rendered frame is weaker where the
driver is `MACHINE_IMPERFECT_GRAPHICS`; log departures in `docs/MAME_KLUDGES.md`.

## MiSTer control

MCP tools over SSH and MiSTer Remote (wizzomafizzo/mrext, port 8182):

```
mister_check_mra(core, "Game Title (set 1)")
mister_launch(core, "Game Title (set 1)")
mister_screenshot(core, native=True)
mister_playing()
mister_state(core)
```

- Launch goes through `menu.rbf` first. Launching a `.mra` while a core runs reuses the
  loaded bitstream and ROM, so a stale build screenshots as success.
- About one screenshot trigger in two is lost; `mister_screenshot` errors when no new file
  appears, so call it again.
- `native=True` writes `screenshot` to `/dev/MiSTer_cmd` and gets the core's own resolution.
  The Remote API's screenshot is the scaled output and is unusable for pixel comparison.
- Files and memory: `mister_ls`, `mister_get`, `mister_put`, `mister_devmem`, `mister_memdump`.

`mister_deploy` copies the `.rbf` and `.mra` files, only for a build that met timing.

## JTAG probe (ISSP)

`_stp` revision only (`DEBUG_ISSP=1`). The probe bus is built in `<Name>.sv`; the field
table in `scripts/issp_fields.tcl` (`set fields_<id> {{name lo hi format} ...}`) must match it
bit for bit.

```
probe_issp(core, "F")                    # read instance F, takes the hwlock
probe_issp(core, "F", action="clear")    # read, then zero the counters
probe_read(core, fields=["frames", "cpu_accesses"])
probe_sequence(core, steps=[{"clear": "F"}, {"sleep": 2}, {"read": "F"}])   # one JTAG session
```

SignalTap acquisition is GUI-only in Quartus Lite 17.0; ISSP is the headless path.
`hwlock.py` refuses JTAG during a Quartus compile and the reverse, and gives JTAG priority: a
probe read that has to wait reserves the Blaster, and no new build starts until it has run
(`locks_status`, or `python scripts/hwlock.py --status`). The combination has
bugchecked the PC.

## ModelSim

```
scripts/run_sim.sh <tb> [+PLUSARG=v ...]
```

Runs from the repo root because `$readmemh` paths resolve against the simulator's working
directory; a wrong one reads all-zero ROMs and looks like an RTL regression. Fresh `work/`
library each run: a killed run leaves `work/_lock` and every later compile hangs. One run at a
time. VHDL is compiled from `sim/vhdl.files` (packages first); all of `rtl/` goes through vlog.
Use for VHDL vendored cores and bus-level benches.

## Verilator

```
scripts/run_verilator.sh <tb> [-GNAME=v ...] [--threads=N] [+plusargs ...]
```

MSYS2 MinGW64 (`MSYS2_ROOT`, else probed); the script re-executes itself there from
Git Bash. Sources per bench in `sim/<tb>/verilator.files`. Output in `obj_verilator/<tb>/`.
Two-state and no VHDL: VHDL CPUs come in as GHDL Verilog conversions, made by the core's own
`scripts/verilator_prep.sh` if it has one. A disagreement with ModelSim is a finding. Use for
frame-level benches compared against MAME captures.

## Build

```
build_start(core[, rev="<Name>_stp"])
build_report(core[, rev])
build_worst_paths(core[, rev])           # quartus_sta on the compiled database, no recompile
build_project(core, "rtl/synth_check")   # a standalone harness project, not the core's own
```

`build_start` compiles HEAD in a worktree at `build/`, refuses a dirty tree, fails on
negative slack on any clock and writes `build/BUILT_COMMIT`. Its gates and stage copies come
from `scripts/core.json`.

## Floorplan

```
build_floorplan(core, list_depth=3)   # instance tree with LUT/FF/MLAB/M10K/DSP counts
build_floorplan(core[, rev])          # debug/floorplan/<rev>.png and <rev>_groups.md
```

Reads `build/`'s post-fit netlist through `quartus_cdb` and the `atoms` Tcl package
(read-only, seconds). Each LAB, M10K and DSP site is painted in the colour of the group
owning most of its atoms, brighter when fuller. Groups are regexes on the instance path in
`scripts/floorplan.json` (copy `floorplan.example.json`); unmatched logic is grouped by
instance automatically, the MiSTer framework is one grey group.
Use it to see whether a failing path's two ends were placed far apart, which block owns
the M10K, and what moved between two builds. The README's Hardware section carries the
release revision's image (`docs/floorplan/<rev>.png`). The script is standalone (no
`coretools.py` needed), so the tool works on older cores as they are.
