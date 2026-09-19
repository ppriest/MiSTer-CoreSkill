# Tools

Every script runs from the core's repository root. Settings come from `mister.env`
(template: `mister.env.example`). MAME scripts read `scripts/mame/regions.json`; see
`SCRIPTS_NOTES.md` for every script and what each core fills in.

## MAME as the reference

Headless run, as `mame_capture.py` does it:

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
| `mame/capture.lua` + `mame_capture.py` | RAM dumps, register files rebuilt from a write tap (write-only chips), screenshot, manifest, at frame N | KonamiGX |
| `mame/boottrace.lua` + `mame_boot_trace.py` | first N main-CPU bus accesses via a read/write tap, not `trace` (which logs instruction starts, not accesses) | KonamiGX, from MS32, from Seta |
| `mame/systrace.lua` + `mame_sys_trace.py` | every write, I/O reads, interrupt-vector reads, per frame, with the interrupt mask | KonamiGX |
| `mame/wtiming.lua` + `write_timing.py` | video-RAM and register writes by scanline relative to vblank | Seta; see `video_write_sweep.md` |

The capture is the reference for testbenches: RAM and register dumps are what the game
wrote and the RTL must hold the same bytes. MAME's rendered frame is weaker where the
driver is `MACHINE_IMPERFECT_GRAPHICS`; log departures in `docs/MAME_KLUDGES.md`.

## MiSTer control

`scripts/hw.py` over MiSTer Remote (wizzomafizzo/mrext, port 8182):

```
python scripts/hw.py launch "Game Title (set 1)"
python scripts/hw.py shot --native --out debug/hw/shot.png
python scripts/hw.py run "Game Title (set 1)"
python scripts/hw.py playing
```

- Launch goes through `menu.rbf` first. Launching a `.mra` while a core runs reuses the
  loaded bitstream and ROM, so a stale build screenshots as success.
- The screenshot trigger is re-sent until a new file appears; about one in two is lost.
- `--native` writes `screenshot` to `/dev/MiSTer_cmd` and gets the core's own resolution.
  The Remote API's screenshot is the scaled output and is unusable for pixel comparison.
- From Git Bash, prefix commands that pass `/media/fat/...` with `MSYS_NO_PATHCONV=1`.

`scripts/deploy.py` copies the `.rbf` and `.mra` files, only for a build that met timing.

## JTAG probe (ISSP)

`_stp` revision only (`DEBUG_ISSP=1`). The probe bus is built in `<Name>.sv`; the field
table in `scripts/read_issp.tcl` must match it bit for bit.

```
python scripts/read_issp.py            # read instance F, takes the hwlock
python scripts/read_issp.py F clear    # read, then zero the counters
python scripts/probe.py --fields frames cpu_accesses
```

SignalTap acquisition is GUI-only in Quartus Lite 17.0; ISSP is the headless path.
`hwlock.py` refuses JTAG during a Quartus compile and the reverse; the combination has
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

MSYS2 MinGW64 at `MSYS2_ROOT` (default `E:/msys64`); the script re-executes itself there from
Git Bash. Sources per bench in `sim/<tb>/verilator.files`. Output in `obj_verilator/<tb>/`.
Two-state and no VHDL: VHDL CPUs come in as GHDL Verilog conversions, made by the core's own
`scripts/verilator_prep.sh` if it has one. A disagreement with ModelSim is a finding. Use for
frame-level benches compared against MAME captures.

## Build

```
python scripts/build_staged.py [--rev <Name>_stp]
bash scripts/build.sh --map        # analysis and synthesis only, in tree
quartus_sta -t scripts/report_worst_paths.tcl <rev>
```

`build_staged.py` compiles HEAD in a worktree at `build/`, refuses a dirty tree, fails on
negative slack on any clock and writes `build/BUILT_COMMIT`.
