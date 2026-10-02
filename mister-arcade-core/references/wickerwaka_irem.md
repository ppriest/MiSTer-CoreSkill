# wickerwaka's Irem cores: the architecture

Read from the MiSTer-devel `Arcade-IremM72_MiSTer`, `Arcade-IremM92_MiSTer` and
`Arcade-IremM107_MiSTer` trees (root, `docs/`, `rtl/` headers and the video and memory modules).
Line references are to those trees. These cores are the working example of the design the
skill asks for: a per-scanline sprite engine on the chip's own cadence, the hardware's DMA as
the sprite snapshot, a cached CPU ROM path, pause by replay, savestates on a section bus, and
a headless simulator.

## Clocks

| Core | `clk_sys` | SDRAM | Pixel | Main CPU |
|---|---|---|---|---|
| M72 | 32 MHz | 96 MHz (3x) | `jtframe_frac_cen` from 32 | V30, frac cen |
| M92, M107 | 40 MHz | 120 MHz (3x) | 6.667 MHz (`n=1, m=3` of 40, with a 13.33 MHz sibling) | V33 at 9 MHz (`n=9, m=20`, with 18 MHz) |

- `clk_sys` is the video clock and an integer multiple of the pixel clock (6x for M92);
  `CLK_VIDEO = clk_sys`, `DDRAM_CLK = clk_sys`. Every chip runs on a `jtframe_frac_cen`
  enable (`m92.sv:136-156`).
- The SDRAM is at **3x `clk_sys`**, CAS 3, burst 4, one 64-bit granule per request, `SDRAM_CLK`
  through `altddio_out` with `datain_h=0, datain_l=1`, i.e. inverted, 180 degrees
  (`rtl/sdram.sv`). This is the other proven answer to the clock question: ZAP keeps the SDRAM
  on `clk_sys` at ~48 MHz; wickerwaka runs it at 3x with a fixed fetch schedule (below). Both
  ship. The skill's default is still ZAP's; this is what a measured shortfall moves to.
- `.sdc` is `derive_pll_clocks` and `derive_clock_uncertainty`, nothing else.
- M72 offers 50, 57 and 60 Hz besides the board's 55.02 Hz by PLL reconfiguration
  (`docs/3[234]mhz_pll.mif`); sound stays at its own rate (`Readme.md`, Video Modes).

## Memory placement

SDRAM (M92 `rtl/m92_pkg.sv:29-45`, `LOAD_REGIONS`): CPU ROM at 0, tiles, sprites (with a
64-bit reorder flag), GA20 samples. BRAM (`bram_cs` regions): sound CPU ROM, decryption table.
Work RAM, VRAM, the sprite RAM and its DMA'd object table, palette and line buffers are BRAM.
M72 moved work RAM from SDRAM to BRAM for savestates and notes the side effect: "CPU RAM accesses
no longer stall the CE train" (`docs/savestates.md`, Known gaps).

The SDRAM controller is Sorgelig's, extended to four channels with fixed priority
(`rtl/sdram.sv`, `STATE_IDLE`): **ch2 sprites, then ch1 tiles, then ch3 CPU ROM and download,
then ch4 samples**, then refresh. The sprite engine asks for refresh in the slots it does not
use (`GA22.sdr_refresh`); an emergency refresh covers download and pause.

CPU ROM goes through `rtl/rom_cache.sv`: a 256-line direct-mapped cache of 64-bit lines, tag
carries a version bumped on reset, the CPU is held (`rom_ready`) on a miss. M107 adds the same
for GA20 samples (`ga20_cache.sv`). So the CPU never waits on SDRAM for RAM, and waits on a
cache miss for ROM; the V33's enable runs at the board's 9 MHz, not faster.

## Sprites: GA22 (M92, M107)

`docs/obj_process.md` records the measured hardware: the object counter runs at 13.333 MHz,
848 counts per 63.6 us line, so 211 or 212 objects per line; the line buffer spans X=44 to 467;
111,088 clocks per frame. The engine (`rtl/ga22.sv`) is built on those numbers, not on MAME's
drawing loop:

- One object slot is **four 13.33 MHz ticks**, `count[1:0]`. Phase 1 computes the row and
  issues one 64-bit SDRAM fetch (a 16-pixel row, 4 bpp). Phase 0 of the next slot writes those
  16 pixels into the line buffer and loads the next object from the 64-bit-wide object RAM
  (`objram_q64`). The SDRAM has three ticks, 225 ns, 27 cycles at 120 MHz, and the top-priority
  channel; there is no state waiting on it.
- Objects that do not fit the line are not drawn, as on the board. Nothing drops "the right
  sprites"; the cadence is the hardware's.
- The line buffer (`rtl/ga22_linebuffer.sv`) is a double buffer of two 12-bit banks, odd and even
  pixels, so a write lands two pixels per clock; the scan-out side writes zero behind the read,
  so the buffer clears itself.
- The sprite list snapshot is the chip's own DMA (`rtl/ga21.sv`: copy pointer, copy mode, "Initiate
  transfer", `DMA_BUSY`). M72's `rtl/sprite.sv` does the same with `DMA_ON`/`TNSL`, defers CPU
  writes to sprite RAM until the DMA ends (`MWR & BUFDBEN & TNSL`) and READY-stalls the CPU
  meanwhile. Where the hardware copies its list, the write sweep is confirmation, not design.

## Tilemaps: GA23

Three layers (`rtl/ga23.sv`, `ga23_layer.sv`). Each layer fetches one 8-pixel tile row, 32
bits, per `load` at pixel cadence; a per-layer `ga23_shifter` turns it into pixels with the
fine scroll. `ga23_sdram.sv` multiplexes the three layers onto one SDRAM channel. Row scroll is
read from VRAM during hblank at fixed cycle numbers (`rs_cyc`). Priority is resolved per pixel
in `ga23.sv:266-272`.

## Pause by replay

The game writes scroll, control and row-scroll registers mid-frame, so a paused frame drawn
from the final register values is wrong. GA23 saves the three layers' registers **per line** at
the end of hblank (`control_save_N[vcnt]`, `ga23.sv:292-300`) and replays them while
`paused`. The README says so: pause is not a hardware feature and "certain parts of the
graphics state need to be saved and replayed during the paused frame". M72 goes further: pause
is acquired only when the bus is idle and no SDRAM request is in flight (`docs/savestates.md`).

## Savestates (M72)

`docs/savestates.md` is the design; it is from Arcade-IGSPGM.

- Every block exposes its state as a numbered section on `ssbus_if` (`rtl/savestates.sv`);
  `rtl/memory_stream.sv` streams the sections to a DDR3 window (4 slots x 4 MB at
  `0x3E000000`), which the host persists (OSD slots on the board, `.m72state` files in the
  simulator).
- Save requires the V30 bus quiet and the sprite DMA idle, so every RAM port the streamer
  borrows is inert. Restore scatters back, drains, resets the bus adapter, and resumes when the
  beam reaches the saved position.
- The V30 is a microcode core that exposes its register file; the Z80 and jt51 get their
  savestate logic generated by jotego's `state_module.py` (`tv80_auto_ss.sv`, `jt51_auto_ss.sv`),
  with two local jt51 patches that must survive an update and a generator failure mode that is
  silent (a parse error skips the file).
- Line buffers and filter state are transient and not saved. The file layout is documented and
  "can be parsed/patched externally", which the doc names as a way to inject a hand-built sprite
  table.
- Status at the time of reading: R-Type only, FPGA untested.

## Simulator (M72 `sim/`)

Verilator plus ImGui/SDL2, ported from Arcade-IGSPGM. Loads games from the release `.mra`
and zips by CRC. Headless mode is a JSON server, one object per line: `sim.load_game`,
`sim.run_frames`, `sim.run_until` with a condition tree on signals or the CPU PC,
`video.screenshot`, `signal.read` by hierarchical name, `memory.*`, `input.*`,
`state.save/load`, `trace.*` (FST), `audio_capture.*`. Beside it: a custom MAME build
(`util/irem_emu`) for comparison, and homebrew V30 test ROMs with a PicoROM debug link.
This is the shape the skill's simulation cheatsheet should take.

## Other features

- Cheats: an MRA `<cheats>` block; a read-override engine (`cheatengine_32_16`) that replaces
  values as the CPU reads them, so a disabled cheat leaves no trace (M92 README).
- Hiscore via the usual module, reading work RAM through a second port.
- DDR3: the ROM download adaptor, the rotator, and the savestate streamer share the pins through
  `ddr_mux` with `acquire` priority to the streamer (M72) or `rom_load_busy` (M92).
- Debug: `dbg_solid_sprites`, `dbg_en_layers` per layer.
- M72 carries a `CLAUDE.md`: architecture by module, build rules (`files.qip`), the `sys/`
  boundary, simulator notes, and "preserve the schematic names rather than modernising them".

## What the skill takes from it

1. The sprite engine's schedule is the chip's slot cadence, measured and written in `docs/`
   first; the memory system is then sized to meet it. That is the concrete form of "not MAME's
   loop as an FSM".
2. A DMA'd sprite list on the board is the snapshot. Run the write sweep to confirm the copy
   point, not to invent one.
3. CPU ROM through a small direct-mapped cache, work RAM in BRAM: the CPU's enable stays at the
   board's rate.
4. Pause replays per-line register state when the game writes video registers mid-frame.
5. 3x SDRAM with a fixed fetch schedule is the proven move when ~48 MHz on `clk_sys` is short.
6. Savestates as a section bus with generated adaptors for vendored chips; the state file
   parsable so synthetic state can be injected into a bench.
7. The simulator is a headless server with `run_until` on signals, screenshots and state files.
