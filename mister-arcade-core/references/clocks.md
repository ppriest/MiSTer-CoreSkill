# Clock plan

Decided **before the first RTL**, in the roadmap's "Clocks" section, because it constrains every
module and is what keeps the video output stable on a CRT, over direct video (DV1) and through a
scaler. From wickerwaka's practice, as he describes starting a core, and TheJesusFish's experience
of two cores (Street Fighter: The Movie, FixEight) whose DV1 problems only showed through an
external scaler.

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
6. **The SDRAM clock is an integer multiple of `clk_sys`.**
7. **Every component runs at its real clock through fractional clock enables** from `clk_sys`:
   a Bresenham accumulator hits an exact rational rate (Seta: a 68EC020 at 176/945 of
   `clk_sys`, where /5 was 7.4% fast and /6 10.5% slow).

So the search is for one `clk_sys` that is simultaneously an integer multiple (4x or more) of the
pixel clock, at least as fast as every board clock, and a good base for an integer SDRAM
multiple. Write the candidates down with the arithmetic, and the one chosen with why.

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
