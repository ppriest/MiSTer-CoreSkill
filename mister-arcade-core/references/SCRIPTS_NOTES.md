# Scripts

What `assets/core/scripts/` holds, where each came from, and what a new core fills in; and the
scripts that moved into the MCP server (`mcp/mister_mcp/scripts/`), which a core session reaches
only through the tool named beside each. Everything runs from the core's root. Connection and tool
paths come from `~/.mister-core.env`, with the core's `<core>.<KEY>` lines (`core_settings_set`)
first; project name and revision from the `.qpf` (`coretools.py`). Per-core values for the MCP's
scripts sit in `scripts/core.json` and `scripts/issp_fields.tcl`; the scripts that stay in the
core keep theirs under a `# --- core-specific: edit for this core ---` marker; the MAME scripts
share one per-core file, `scripts/mame/regions.json`.

`scripts/core.json` keys: `mra_folder` (default `_<project>`), `held_back_sets`,
`required_instances` (default `["hps_io"]`), `required_macros` (`{macro: what breaks}`),
`stage_copies` (`[[src, dst]]`), `probe_default_instance` (default `F`), `sta_clock` (default the
framework's emu PLL output 0).

## Build and timing

| Script | Does | Source | Per core |
|---|---|---|---|
| `build_staged.py` (MCP: `build_start`, `build_report`) | Quartus build of HEAD in a worktree at `build/`; refuses a dirty tree, gates on slack, writes `build/BUILT_COMMIT` | KonamiGX | `core.json` `required_instances`, block names that must survive to the fit report; `required_macros`; `stage_copies`, files the compile reads from the project directory rather than beside the RTL (fx68k's `microrom.mem` and `nanorom.mem`, which its `$readmemb` looks for where Quartus runs) |
| `build.sh` (MCP server; no tool runs it on the core: the core builds through `build_start`, and `build_project` compiles a standalone project such as `rtl/synth_check` in place) | in-tree compile, `--map`, `--report` | KonamiGX | none |
| `report_worst_paths.tcl` (MCP: `build_worst_paths`) | worst setup paths on the main clock | Psikyo | `core.json` `sta_clock`, if the core's main clock is not the framework PLL output 0 |
| `sta_failing_paths.tcl`, `sta_all_fail.tcl` | the same, run by hand with `quartus_sta -t` | Psikyo | clock name, if the core's main clock is not the framework PLL output 0 |
| `floorplan.py`, `floorplan.tcl` (MCP: `build_floorplan`) | placement PNG coloured by block; `list_depth` prints hierarchy counts | skill | `scripts/floorplan.json` groups (start from `floorplan.example.json`, Fuuki's); without it, automatic groups by instance |
| `coretools.py` | resolves core root, project, revision, tool paths | MiSTer-CoreTools | none |
| `hwlock.py` | refuses JTAG during a Quartus or ModelSim run and the reverse; JTAG has priority, so a waiting probe's reservation blocks new builds; `--status` shows the holder, the queue and what is compiling | KonamiGX | none |

## Hardware

| Script | Does | Source | Per core |
|---|---|---|---|
| `deploy.py` (MCP: `mister_deploy`) | copy `.rbf` (as `<Name>_NNNNNNNN.rbf`, numbered from 30000001 so it outranks dated files) and `.mra` files to the MiSTer, only for a build that met timing | KonamiGX | `core.json` `mra_folder`, `held_back_sets` |
| `hw.py` (MCP: `mister_launch`, `mister_screenshot`, `mister_playing`, `mister_osd`) | MiSTer Remote: launch via `menu.rbf`, native or scaled screenshot, what is playing | Seta, MS32 | `core.json` `mra_folder` |
| `read_issp.py`, `read_issp.tcl` (MCP: `probe_issp`; several steps in one session, `probe_sequence`) | ISSP probe readout under `hwlock` | KonamiGX | `scripts/issp_fields.tcl`, a field table per instance (`set fields_<id> {{name lo hi format} ...}`), matching the RTL's probe bus bit for bit |
| `probe.py` (MCP: `probe_read`) | probe readout, one line per sample, prefixed `<core>\|<build>\|<set>\|` | MiSTer-CoreTools | `core.json` `probe_default_instance` |
| `identity.py` (MCP, internal) | the prefix: core file and set from the device, commit from the machine-wide deploy log `mister_deploy` appends to; warns when the loaded core is not this repository's | skill | none |
| `decode_debug_screenshot.py`, `png_census.py` | decode values encoded in the video output; colour census of a screenshot | Psikyo, Fuuki | none |

## ROMs and `.mra`

| Script | Does | Source | Per core |
|---|---|---|---|
| `extract_romstart.py` | a set's `ROM_START` records for one region, from the driver | Seta | `KINDS`: region names and load kinds |
| `extract_dips.py` | DIP switches from `INPUT_PORTS_START` | KonamiGX | `SETS`, `DSW_PORT` |
| `mra.py` | build the image an `.mra` describes, as mra-tools-c would; parts found by CRC first, then basename, across the zip cascade | Fuuki | none |
| `validate_mra.py` | XML and content checks before deploy; DIP lines within the OSD's 28 columns; no generic button names (`--allow-generic-buttons` for bring-up); `<mameversion>` present and no newer than the installed MAME | Psikyo | `ROTATION_OVERRIDE` |
| `mame_cheats.py` | Pugsy's MAME cheat XML (`cheat.7z`, read with py7zr or libarchive's `tar`) to the `.mra`'s `<cheats>` codes; lists what does not convert and why; `cheats()` and `mra_block()` for the `.mra` generator (`references/cheats.md`) | KonamiGX | `CHEAT_CPU`, `CHEAT_RAM`, `CHEAT_MAX` |

No generic `build_mra.py`: each core's generator encodes its ROM layout. Start from the
nearest sibling's.

## MAME reference

The `.lua` files and `regions.json` stay in the core's `scripts/mame/`; the Python drivers are in
the MCP server. All read `scripts/mame/regions.json`: CPU tag, address space, bus width and endianness,
`read` regions (dumped through the CPU's view), `wtap` regions (write-only registers rebuilt
from writes), `sweep` (regions the write sweep counts), `trace` (address top, I/O range,
vector table, interrupt-mask field, ROM and RAM ranges), `inputs` (field names for play).

| Script | Does | Source |
|---|---|---|
| `mame_capture.py` (MCP: `mame_capture`) + `mame/capture.lua` | state at frame N: dumps, rebuilt registers, screenshot, manifest | KonamiGX; banked-memory tracking left out (see the Lua header) |
| `mame_boot_trace.py` (MCP: `mame_boot_trace`) + `mame/boottrace.lua` | first N bus accesses from reset | KonamiGX, from MS32, from Seta |
| `mame_sys_trace.py` (MCP: `mame_sys_trace`) + `mame/systrace.lua` | writes, I/O reads, vector reads per frame, with interrupt mask | KonamiGX |
| `compare_boot_trace.py` (MCP: `sim_compare_boot`) | RTL boot trace vs MAME's: writes strict, I/O reads in order, ROM reads as a superset; `replay` makes the I/O replay file for the bench | KonamiGX |
| `write_timing.py` (MCP: `mame_write_timing`) + `mame/wtiming.lua` | video writes by scanline relative to vblank; attract or play | Seta |
| `mame/mark_time.lua` | emulated time at two marking writes, for CPI | KonamiGX |
| `parse_mame_trace.py` | debugger trace to an expected-fetch list | Fuuki |
| `mame/run.lua`, `mame/snap_at.lua`, `mame/ports.lua`, `mame/setdip.lua` | error-surfacing wrapper; snapshot at frame N; list input fields; seed DIPs (`mame_capture` `dips`, from Seta) | Fuuki, KonamiGX, Seta |

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
