# Clock plan

Decided **before the first RTL**, in the roadmap's "Clocks" section, because it constrains every
module and is what keeps the video output stable on a CRT, over direct video (DV1) and through a
scaler. From wickerwaka's practice, as he describes starting a core, and TheJesusFish's experience
of two cores (Street Fighter: The Movie, FixEight) whose DV1 problems only showed through an
external scaler.

## Default: 48 MHz, SDRAM not doubled

**Start from `clk_sys` around 48 MHz, with the SDRAM on that same clock**, and move off it only
for a reason written in the roadmap. "Around" means the nearest value that gives an exact pixel
clock: ZAP (Andrea Bogazzi) runs all his cores at 48, 49.152 or 52.3 MHz, without a doubled SDRAM
clock and without DDR3.

- **Higher is not free.** 96 MHz is not harmful in itself, but the clock is a multiple of the
  pixel clock, and when a board's pixel clock forces a higher PLL (a 7.159 MHz video clock), the
  equivalent of 96 MHz becomes 114 MHz and timing gets hard.
- **Fitting at 48 MHz is how the right optimisations are found**: fetch scheduling, sharing a
  memory port, what really has to be read per line. A faster clock hides the design that should
  have been done.
- **For 8- and 16-bit-era boards** (Seta, DownTown class), 96 MHz SDRAM plus DDR3 is a sign
  something is wrong. Our five prior cores all run at 85.9 or 96 MHz; they work, but they are not
  the model for this.
- **Going higher** is for a measured shortfall: the per-line fetch arithmetic in the memory plan
  shows 48 MHz cannot serve every client in a line period, or a CPU cannot catch up its SDRAM
  stalls. Bring those numbers to the user before changing the clock.

## The rules

1. **Work out the clocks first.** From the MAME driver and the PCB notes: the master crystals,
   every derived clock, and the **pixel clock**. Record each with its source line.
2. **`clk_sys` is the video clock.** Keep system and video on one clock: it fits timing best, and
   there is no clock-domain crossing between the renderer and the video output.
3. **`clk_sys` is an integer multiple of the pixel clock, at least 4x.** The pixel then comes from
   a clock enable (`ce_pix`) with a fixed cadence, one pulse every N clocks, every pixel the same.
4. **`clk_sys` is at least as fast as every other clock on the board.** The tilemap and sprite
   hardware usually run at a multiple of the pixel clock anyway; the CPUs and sound chips must fit
   under `clk_sys` too.
5. **Run the main CPU faster than the board did, where it has to stall.** When the CPU waits on
   SDRAM, a faster enable lets it catch up on the cycles it lost, so the game's own timing holds.
   Measure the catch-up; do not assume it.
6. **The SDRAM clock is an integer multiple of `clk_sys`**, and by default that multiple is 1:
   the SDRAM runs on `clk_sys`. Doubling it is a measured decision, not a starting point.
7. **Every component runs at its real clock through fractional clock enables** from `clk_sys`:
   a Bresenham accumulator hits an exact rational rate (Seta: a 68EC020 at 176/945 of
   `clk_sys`, where /5 was 7.4% fast and /6 10.5% slow).

So the search is for the **lowest** `clk_sys` near 48 MHz that is an integer multiple (4x or
more) of the pixel clock and at least as fast as every board clock, with the SDRAM on it. Write
the candidates down with the arithmetic, and the one chosen with why; a choice above ~52 MHz
carries the measurement that forced it.

## Why it matters for CRTs

A pixel clock that is not an exact, steady division of the output clock gives pixels of uneven
width and a line and frame rate that drift from the board's. A CRT tolerates some of that; direct
video (DV1) feeding an external scaler does not, and shows it plainly. It is present, more subtly,
on basic analog output too, and the scandoubler's behaviour over HDMI shows it as well.

## Checks

- **The roadmap's Clocks section** lists every board clock, the pixel clock, the chosen `clk_sys`,
  the multiple of each, the SDRAM multiple, and every fractional enable with its exact ratio.
- **Measure the video output**, don't infer it: line rate, frame rate and pixel count per line
  from the RTL (a counter on the probe) against the driver's `screen.set_raw()`.
- **Test DV1 into a scaler** where one is available; it is the most sensitive check. Without one,
  check the scandoubler over HDMI and the plain analog output.
- **A clock that does not divide exactly** is a `docs/HACKS.md` entry: the error, in ppm, and
  what it does to the line and frame rate.
