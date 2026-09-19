# Vendored and reused modules

What the five cores vendored or ported, from where, under what licence, and how each was
proved. Source: each core's `docs/ROADMAP.md` "Component reuse map" and, for KonamiGX and MS32,
`THIRD-PARTY.md`. Per-module `PROVENANCE.md` files live in each core's `rtl/` and hold the exact
commit and local changes; read the one for a module before copying it.

## Rules the cores converged on

- **Copy from the sibling core that last proved the module**, not from upstream, unless
  upstream has a fix the sibling lacks. The sibling copy carries integration fixes (Seta's
  SDRAM `dq_in` capture fix, for one).
- **Every vendored directory gets a `PROVENANCE.md`**: upstream URL, commit, licence as stated
  in the files, every local change. A pristine `*_upstream_reference.*` copy beside a modified
  file makes the diff checkable.
- **Run the module's own testbench, unchanged, before editing it.** It is the regression for
  every later change.
- **Verify against MAME before wiring it to anything.** Where module and MAME disagree, record
  it in `docs/MAME_KLUDGES.md` and keep the module until one side is shown to be the chip.
- **Instantiate the CPU kernel directly and own the bus interface.** TG68K.vhd, the async
  68000-bus wrapper, is deliberately unused in every 68k core.
- **Licence of the core follows its strictest dependency.** GPL-3.0 dependencies make the core
  GPL-3.0; see KonamiGX `THIRD-PARTY.md`, "Why GPL-3, and why it is one-way".

## CPUs

| CPU | Module | Licence | Used by | Notes |
|---|---|---|---|---|
| 68000 / 68010 / 68EC020 | TobiFlex/TG68K.C (VHDL) | LGPL-3.0-or-later | Psikyo, Fuuki, Seta, KonamiGX | `CPU` port selects 68000 (`00`) or 68020 (`11`) at runtime (Fuuki runs both boards from one kernel). Psikyo proved it at 16 MHz including `MOVEC`/`CACR`. Kernel instantiated directly, clock-enabled. Verilator gets it as a GHDL conversion. |
| 68000, cycle-accurate | ijor/fx68k (SystemVerilog) | GPLv3 | Seta, KonamiGX (sound) | ModelSim needs `-suppress 7061`. |
| Z80 | T80 (Daniel Wallner, VHDL) | BSD-style | Psikyo, Fuuki, MS32 | Also used for Z80-compatible parts (Psikyo treats LZ8420M as T80). |
| V60/V70 | meathax/s32 `s32_v60`, `IS_V70=1` | GPL-3.0-or-later | MS32 | Came with 37 unit benches and a differential harness against a Python V60 model and a MAME tracing patch; reused as-is. New 32-bit bus adapter. |
| VR4300 (MIPS III) | MiSTer-devel/N64_MiSTer `rtl/cpu*.vhd` | GPL-3.0 | candidate (HyperNG64) | Separate entity; memory port partly generic, partly N64 RDRAM/DDR3-specific. Runs at 93.75 MHz in the N64 core. |
| Small MCUs (PIC16C57 etc.) | Not emulated as a CPU | | Psikyo | Reimplemented as an RTL FSM from MAME's high-level simulation, as MAME itself does. Log as a hack. |

## Sound

| Chip | Module | Licence | Used by |
|---|---|---|---|
| YM2610 | jotego jt10 | GPL-3.0 | Psikyo |
| YM2203 | jotego jt03 (jt12 repo) | GPL-3.0 | Fuuki |
| YM3812 (OPL2) | jotego jtopl2 | GPL-3.0 | Fuuki |
| OKI M6295 | jotego jt6295 | GPL-3.0 | Fuuki |
| YMF262 (OPL3) FM | gtaylormb/opl3_fpga | LGPL-3.0 | Fuuki (OPL4 FM half) |
| YMF278B (OPL4) PCM | written from scratch in Psikyo | project's | Psikyo, Fuuki; structure reused for MS32's YMF271 |
| K054539 | furrtek/SiliconRE Verilog | GPL-2.0, version ambiguity | KonamiGX |
| X1-010, TMS57002 | from scratch, MAME as spec | project's | Seta, KonamiGX |

`ymfm` (BSD-3) is MAME's C++ model of the Yamaha chips: a reference, not synthesisable.

## Video

- Custom RTL in every core; MAME's video file is the spec, built against a software model.
- jotego jtcores Konami chips (`jt053246`, `jt054338`, `jtk053252`, `jt05415x`) ported in
  KonamiGX, GPL-3.0. `jt05415x` did not fit (4 VRAM pages, no pixel path) and was replaced by
  RTL from the software model; decide by reading the module against the driver, not by name.
- Pipeline shape to copy: Psikyo's per-scanline sprite path (buffered sprite RAM, per-frame
  candidate list, per-scanline engine, double-buffered line buffer) and its
  `tilemap_line_engine` (prefetch ring, `ce_pix` display side, req/valid gfx fetch).
- Cave (Chisel) and other cores: design references only when the language or pipeline differs.

## Framework and infrastructure

| Block | Source | Licence |
|---|---|---|
| Template, `sys/` | MiSTer-devel/Template_MiSTer | GPL-2.0-or-later |
| SDRAM controller, arbiters, HPS download | Sorgelig `sdram.sv`, extended in Psikyo; take Seta's copy (`dq_in` fix) | GPL-3.0-or-later as adapted |
| DDR3 backend | Psikyo `ddram_phy` / `ddram_arbiter` / `ddram_download` | project's |
| Screen rotation | Sorgelig `screen_rotate_two.sv` (a DDR3 tap, not a filter) | GPL-2.0 |
| Video out | `sys/arcade_video.v`; `sys/video_freak.sv` instantiated explicitly for crop/scale | GPL-2.0-or-later |
| CRT offset | rmonic79 `crt_adjust.sv` | GPL-3.0-or-later |
| High scores | JimmyStones/Hiscores_MiSTer `hiscore.v` | GPLv3 |
| Pause | Fuuki `pause_control.sv` | project's |
| Debug probe, tracer, counters | Seta `rtl/debug/` (`issp_probe.sv`, `debug_tracer.sv`, `debug_counter.sv`), header comments intact | project's |
| EEPROM 93C46 | jotego `jt5911.sv` | GPL-3.0 |

## Finding a module

Enumerate the boards that use the chip in MAME (`grep -rl <device> $MAME_SRC/src/mame`), then
look for those boards' MiSTer cores and jotego's jtcores, rather than searching for the chip
number. Record every candidate looked at in the reuse map, including the ones rejected and why.
