# Scripts

What `assets/core/scripts/` holds, where each came from, and what a new core fills in.
Everything runs from the core's root. Connection and tool paths come from `mister.env`;
project name and revision from the `.qpf` (`coretools.py`). Per-core constants sit under a
`# --- core-specific: edit for this core ---` marker; the MAME scripts share one per-core file,
`scripts/mame/regions.json`.

## Build and timing

| Script | Does | Source | Per core |
|---|---|---|---|
| `build_staged.py` | Quartus build of HEAD in a worktree at `build/`; refuses a dirty tree, gates on slack, writes `build/BUILT_COMMIT` | KonamiGX | block names that must survive to the fit report |
| `build.sh` | in-tree compile, `--map`, `--report` | KonamiGX | none |
| `report_worst_paths.tcl`, `sta_failing_paths.tcl`, `sta_all_fail.tcl` | worst setup paths on the main clock | Psikyo | clock name, if the core's main clock is not the framework PLL output 0 |
| `coretools.py` | resolves core root, project, revision, tool paths | MiSTer-CoreTools | none |
| `hwlock.py` | refuses JTAG during a Quartus or ModelSim run and the reverse | KonamiGX | none |

## Hardware

| Script | Does | Source | Per core |
|---|---|---|---|
| `deploy.py` | copy `.rbf` (numbered) and `.mra` files to the MiSTer, only for a build that met timing | KonamiGX | `REMOTE_ARCADE`, `HELD_BACK_SETS` |
| `hw.py` | MiSTer Remote: launch via `menu.rbf`, native or scaled screenshot, what is playing | Seta, MS32 | `REMOTE_ARCADE_DIR` |
| `read_issp.py`, `read_issp.tcl` | ISSP probe readout under `hwlock` | KonamiGX | field table per instance, matching the RTL's probe bus bit for bit |
| `probe.py` | probe readout, one line per sample, prefixed `<core>\|<build>\|<set>\|` | MiSTer-CoreTools | `DEFAULT_INSTANCE` |
| `identity.py` | the prefix: core file and set from the device, commit from the machine-wide deploy log `deploy.py` appends to; warns when the loaded core is not this repository's | skill | none |
| `decode_debug_screenshot.py`, `png_census.py` | decode values encoded in the video output; colour census of a screenshot | Psikyo, Fuuki | none |

## ROMs and `.mra`

| Script | Does | Source | Per core |
|---|---|---|---|
| `extract_romstart.py` | a set's `ROM_START` records for one region, from the driver | Seta | `KINDS`: region names and load kinds |
| `extract_dips.py` | DIP switches from `INPUT_PORTS_START` | KonamiGX | `SETS`, `DSW_PORT` |
| `mra.py` | build the image an `.mra` describes, as mra-tools-c would; parts found by CRC first, then basename, across the zip cascade | Fuuki | none |
| `validate_mra.py` | XML and content checks before deploy; DIP lines within the OSD's 28 columns; no generic button names (`--allow-generic-buttons` for bring-up); `<mameversion>` present and no newer than the installed MAME | Psikyo | `ROTATION_OVERRIDE` |

No generic `build_mra.py`: each core's generator encodes its ROM layout. Start from the
nearest sibling's.

## MAME reference

All read `scripts/mame/regions.json`: CPU tag, address space, bus width and endianness,
`read` regions (dumped through the CPU's view), `wtap` regions (write-only registers rebuilt
from writes), `sweep` (regions the write sweep counts), `trace` (address top, I/O range,
vector table, interrupt-mask field, ROM and RAM ranges), `inputs` (field names for play).

| Script | Does | Source |
|---|---|---|
| `mame_capture.py` + `mame/capture.lua` | state at frame N: dumps, rebuilt registers, screenshot, manifest | KonamiGX; banked-memory tracking left out (see the Lua header) |
| `mame_boot_trace.py` + `mame/boottrace.lua` | first N bus accesses from reset | KonamiGX, from MS32, from Seta |
| `mame_sys_trace.py` + `mame/systrace.lua` | writes, I/O reads, vector reads per frame, with interrupt mask | KonamiGX |
| `compare_boot_trace.py` | RTL boot trace vs MAME's: writes strict, I/O reads in order, ROM reads as a superset; `replay` makes the I/O replay file for the bench | KonamiGX |
| `write_timing.py` + `mame/wtiming.lua` | video writes by scanline relative to vblank; attract or play | Seta |
| `mame/mark_time.lua` | emulated time at two marking writes, for CPI | KonamiGX |
| `parse_mame_trace.py` | debugger trace to an expected-fetch list | Fuuki |
| `mame/run.lua`, `mame/snap_at.lua`, `mame/ports.lua`, `mame/setdip.lua` | error-surfacing wrapper; snapshot at frame N; list input fields; seed DIPs | Fuuki, KonamiGX |

Checked on `thunderl` (Seta, 68000) with MAME 0.285: capture, boot trace, system trace and
write sweep all ran; the sweep matched Seta's recorded result (sprite control 2.0 writes a
frame, all within two lines of vblank start). Counting from an early frame shows nothing
while a game is still booting; Seta skips 600 frames.

## Simulation

| Script | Does | Source | Per core |
|---|---|---|---|
| `run_sim.sh <tb>` | ModelSim: fresh `work/`, VHDL from `sim/vhdl.files`, all of `rtl/` through vlog, `tb_*` top found in `sim/<tb>/` | KonamiGX | `sim/vhdl.files` (packages first) |
| `run_verilator.sh <tb>` | Verilator under MSYS2 MinGW64; sources from `sim/<tb>/verilator.files`; C++ clock if `sim/<tb>/main.cpp` exists | KonamiGX, from Seta | optional `scripts/verilator_prep.sh` (e.g. GHDL conversion of a VHDL CPU) |

## Left out

Core-specific, copied only as starting points: per-chip models and checks (Seta `x1_*_model.py`,
KonamiGX `check_gx_*.py`, `render_model.py`), per-core testbench preparation (`prep_*_tb.py`),
KonamiGX `build_rom_image.py` and `regen_mmr.sh`, Psikyo `night_test.sh`, sweeps tied to one
chip (`flip_sweep.py`, `x1_001_sweep.py`).
