---
name: mister-arcade-core
description: Build a new MiSTer FPGA arcade core (DE10-nano, Quartus 17.0) from the MiSTer-devel Template, reusing tested open-source cores and using MAME as the reference for set names, memory maps, graphics chips and CPUs. Use this whenever the user wants to start, port, bring up, debug or finish an arcade core for MiSTer, mentions a Quartus .qpf/.sv core, an .mra, JT* or TG68K/T80 cores, ISSP probes, MAME Lua tracing against an FPGA core, or asks to add the standard feature set (DIPs, inputs, CRT offset, hiscore, DDR ROM loading, HDMI scaling and rotation, flip screen, audio mix) to an Arcade-*_MiSTer repository, even if they do not say "skill".
---

# MiSTer arcade core

One core per repository, `Arcade-<Name>_MiSTer` on `E:\`, from `Template_MiSTer`.
MAME is the reference for everything the hardware does; open-source RTL is reused
wherever a tested module of the same chip exists. The prior cores on `E:\Arcade-*`
are the worked examples; their cost is distilled in `references/LESSONS_LEARNED.md`.

## Prerequisites

| Tool | Where |
|---|---|
| Quartus 17.0 Lite, ModelSim | `C:/intelFPGA_lite/17.0` |
| Verilator, g++, make | MSYS2 MinGW64 at `E:\msys64` (`MSYS2_ROOT`); `scripts/run_verilator.sh` re-executes itself there |
| MAME binary | `MAME_DIR` in `mister.env` |
| MAME source | checkout at `E:\mame` (upstream `github.com/mamedev/mame`, `src/mame/<maker>/`); `git -C E:/mame log -1` for the commit a finding refers to |
| gh | `%LOCALAPPDATA%/Microsoft/WinGet/Packages/GitHub.cli_*/bin/gh.exe` (per-user install; not on PATH in every shell) |
| MiSTer on the LAN | `mister.env` |

## Phases

Each phase ends with a commit. Do not start hardware work before the roadmap is approved.

### 0. Bootstrap

```
python <skill>/scripts/new_core.py <Name> --owner ppriest --root E:/
```

Creates a private GitHub repo from the template (`--public` to override), clones to `E:\Arcade-<Name>_MiSTer`, renames
`Template.*` to `<Name>.*`, adds the `<Name>_stp` instrumented revision, deletes the
Quartus 13 project, copies `assets/core/` (scripts, docs templates, `.gitignore`,
`CLAUDE.md`, `docs/LESSONS_LEARNED.md`), commits. `sys/` is untouched, now and always. Then copy
`mister.env.example` to `mister.env` and fill it in. Move the session into the new repo.

### 1. Research

Output: `docs/HARDWARE_NOTES.md` and the component reuse map in the roadmap.

- MAME driver (`src/mame/<maker>/<driver>.cpp`, `_v.cpp`, device files): CPUs and clocks,
  memory map, video chips and their register maps, sound chips, `screen.set_raw()`
  params, DIP and input ports, `MACHINE_*` flags, kludges and FIXMEs. `mame -listxml
  <set>` for set names, ROM regions and sizes; `extract_dips.py`/`extract_romstart.py`
  in `scripts/`.
- Existing RTL for each chip: jotego's JT* cores, MiSTer-devel and the five prior cores.
  Read `references/cpus_and_vendored.md` for what has already been vendored, from where,
  and the porting notes. A vendored module is copied with a `PROVENANCE.md` and never
  edited silently.
- Where no RTL exists, the chip is written from the MAME model; say so in the roadmap.
- ROM size per set against the SDRAM module (up to 128 MB) and the DDR3 window (256 MB at
  `0x30000000`). Compare region CRCs in `-listxml` first: byte-identical copies need storing
  once.
- **Feasibility, when the board is large** (a 32/64-bit CPU at high clock, 3D, ROM beyond
  SDRAM, several chips with no RTL): write a feasibility section in `HARDWARE_NOTES.md`
  before the roadmap. Name each blocking unknown and the measurement that closes it, compare
  against an existing MiSTer core of similar size where one exists, and take it to the user.
  A roadmap for a board that may not fit is scoped by the user, not by default.
- Fill in `scripts/mame/regions.json` from the driver's address map: the MAME scripts need
  it before the first capture or trace.
- Optional: `references/pcb_video_reference.md` for original-PCB footage.

### 2. Roadmap: stop for approval

Write `docs/ROADMAP.md` from the template (phases, exit criteria, reuse map, standing
rules including "follow MAME, including where MAME is wrong, and log it"). Present it to
the user and wait for approval before executing any phase. Revise it as phases land; it
is the status file, `LESSONS_LEARNED.md` is not.

### 3. Build

Per roadmap phase, typically CPU + ROM path, then video, then sound, then integration.

- Every subsystem gets a testbench before it goes on hardware. Stimulus comes from MAME
  captures (`scripts/mame_capture.py`, `scripts/mame/*.lua`); expected output is MAME's
  frame or trace. Verilator for pixel/frame comparison, ModelSim for bus-level and
  vendored VHDL. `references/tools.md` has the invocations and layout.
- Before wiring line buffers, double buffers or vblank-latched copies, run the video-write
  sweep (`references/video_write_sweep.md`): when the game writes sprite/tile/scroll RAM
  and registers relative to vblank decides the buffering scheme. Do not guess it.
- Read the routing table at the top of `references/LESSONS_LEARNED.md` before starting each
  subsystem, not after it misbehaves.
- Standard features, each with its guide in `references/`: DIPs and inputs
  (`dips_inputs.md`), CRT H/V offset and v-size if BRAM allows (`crt_offset.md`),
  `Hiscore.v` (`hiscore.md`), fast DDR ROM loading (`ddr_rom_loading.md`), HDMI scaling
  and crop, HDMI rotation, flip screen, mono/stereo mix (`video_audio_options.md`). HDMI-only
  options are hidden under direct video. Memory maps are documented per `sdram_ddr_maps.md`.
- Flip screen is one implementation in the core's video logic, serving HDMI and analog, driven
  by the main-OSD option or the game's DIP (a fake DIP where the game has none). What each
  layer needs flipped or offset is a per-core exercise, verified against the unflipped frame
  rotated 180 degrees (`video_audio_options.md`, last section). If it cannot be made right,
  say so in `docs/HACKS.md` and the README.
- Controls include a fake **Pause** input (a `J1` slot) that suspends the main CPU by clock
  enable, shared with the OSD pause and hiscore's pause (`dips_inputs.md`, checklist).
- The OSD shows only what applies: CRT offset parameters hidden until "CRT adjust" is on,
  HDMI-only options hidden under direct video, and every peripheral group (light gun, rotary,
  trackball) hidden unless the running set has it, from the `.mra` mod byte. Rotary games
  clone the Ikari Warriors core's controls and settings; light-gun games support the mouse and
  a synthetic crosshair (`osd_and_peripherals.md`).
- Optional but desirable: savestates and cheats. Plan them in the roadmap after the standard
  set; say in the README which are done.

### 4. Hardware

- Build with `scripts/build_staged.py` (snapshot of HEAD in a worktree, refuses a dirty
  tree, gates on slack). Never compile in the tree.
- `scripts/deploy.py` to the MiSTer; `scripts/hw.py` to launch a game, screenshot, reset.
- ISSP probes only in the `_stp` revision, read through `scripts/read_issp.py`, always
  under `hwlock.py`: JTAG during a Quartus compile has bugchecked the machine.
- Simulation passes and hardware fails: `LESSONS_LEARNED.md`, "When simulation passes and
  hardware fails", before touching the RTL.

### 5. Finish

- `README.md` from the template: sets, status, features, controls, third-party credits.
- `docs/HACKS.md`: every approximation, workaround or "good enough" in the core, with
  what would make it correct. `docs/MAME_KLUDGES.md`: MAME's own kludges reproduced on
  purpose. Both are kept current, not written at the end.
- Release per `docs/RELEASE_PROCESS.md`; `.mra` files in `releases/`.
- Append genuinely new lessons to the core's `docs/LESSONS_LEARNED.md` tagged `[<Name>]`,
  and copy the general ones back into this skill's `references/LESSONS_LEARNED.md`.

## Standing rules

- Comments say what the code cannot; delete them when they go stale. No dates unless
  load-bearing, no invented durations, no narrative.
- `docs/` holds ROADMAP, HARDWARE_NOTES, WORKFLOW, HACKS, MAME_KLUDGES, LESSONS_LEARNED,
  RELEASE_PROCESS, memory maps, screenshots. `references/CONVENTIONS.md` has the full list.
- `roms/` and `mister.env` are never committed. `releases/*.rbf` only when verified on
  hardware, added with `git add -f`.
- Report hardware results with evidence: a screenshot path, a probe readout, a log line.

## References

| Read | When |
|---|---|
| `references/LESSONS_LEARNED.md` | routing table before each subsystem; the named section when stuck |
| `references/WORKFLOW.md` | once at bootstrap; it is copied into the core as `docs/WORKFLOW.md` |
| `references/CONVENTIONS.md` | naming, layout, what goes where |
| `references/tools.md` | MAME Lua, ISSP, MiSTer API, Verilator, ModelSim invocations |
| `references/video_write_sweep.md` | before any video buffering decision |
| `references/cpus_and_vendored.md` | before vendoring or porting a CPU/sound/video module |
| `references/dips_inputs.md`, `crt_offset.md`, `hiscore.md`, `ddr_rom_loading.md`, `video_audio_options.md`, `osd_and_peripherals.md`, `sdram_ddr_maps.md` | the matching feature |
| `references/pcb_video_reference.md` | when a PCB comparison is wanted |
| `references/SCRIPTS_NOTES.md` | what each `scripts/` tool does and which constants are per-core |
