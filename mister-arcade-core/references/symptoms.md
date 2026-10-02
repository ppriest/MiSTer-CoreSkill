# Symptom to cause

What is seen, what has caused it before, and the check that settles it. Each row is a lesson
in `LESSONS_LEARNED.md` (the section is named) or a finding in another reference. Before any
row below: if the build has negative slack on any clock, nothing seen on the board means
anything ("Timing closure").

## Boot

| Symptom | Cause seen before | Check |
|---|---|---|
| Black screen, no bus activity | memory path held in the core reset; ROM at the wrong base | `compare_boot_trace.py compare` against MAME's first accesses ("MiSTer integration") |
| Boots in simulation, not on the board | negative slack; `initial` on a register array is not a power-up value | `.sta.summary` first; write reset state at reset ("When simulation passes and hardware fails") |
| RAM test fails | an unbacked region reads 0, not garbage; DTACK/ready pulsed instead of held | back every RAM the test walks at the declared size; ready is a level ("Memory transport") |
| ROM test or checksum fails | interleave or byte order wrong in the `.mra` or at the SDRAM seam | prove the interleave against MAME's disassembly offline; CRC-found parts ("ROM loading") |
| EEPROM reported BAD | no default image; `initial`-blanked array | the driver's `.nv` region as the default ("When simulation passes") |
| Sound CPU reset repeatedly, or game reboots | a sound-CPU stand-in echoes a constant; the game watches it change | disassemble every reader of the status register ("When simulation passes") |
| Game waits forever on a flag | an interrupt judged "disabled" that MAME fires every frame; a held IRQ's acknowledge lost | copy MAME's `time_until_pos` arithmetic with the driver's numbers; acknowledge wins ("Debug instrumentation", "When simulation passes") |
| Works at one fitter seed, not another | external SDRAM paths are unconstrained; a clean STA is one placement | rebuild the same commit at another seed before bisecting source ("Timing closure") |
| Wrong bytes, about half of a ROM compare matches, phase-insensitive | a timing violation, not the interface | STA, then discard every measurement taken under it ("Timing closure") |

## Sprites

| Symptom | Cause seen before | Check |
|---|---|---|
| Tearing, a sprite split across two positions | the list is read live while the CPU rewrites it; no snapshot, or one at the wrong point | the write sweep in attract and play; snapshot at the swept point, or the board's DMA (`video_write_sweep.md`, `wickerwaka_irem.md`) |
| Wrong tiles or orientation in motion, right when paused | a buffering fault: list and attributes not snapshotted together | latch list and video registers at one point unless evidence separates them ("Sprite lists") |
| Flicker on alternate frames | a bank swap passed off as a copy | copy, do not ping-pong ("A swap is not a copy") |
| Sprites one line high or low; credit text clipped | 0- vs 1-based raster row in the line interrupt; a double buffer is two lines ahead, not one | establish which row the handler believes it services before shifting anything ("Sprite lists", Fuuki entries) |
| Sprites missing on busy lines, no error anywhere | the per-line scan ran out of time | an overrun counter beside a total counter; drop what the chip dropped ("[GX] A per-line object scan...") |
| The wrong sprites missing when busy | a back-to-front engine stopping on time-out | draw in the chip's order with a budget just below the period ("[Seta] A back-to-front line buffer...") |
| X from one frame and Y from the next | the chip copies part of the record at vblank and reads the rest live | a golden frame after vblank cannot show it; sweep per field ("[Seta] A golden frame...") |
| Raster effect one row off | attributes buffered late, or the line interrupt serviced late | fire the line interrupt every line and buffer into the line renderer ("[Fuuki] For raster effects...") |
| Nearly right picture, shifted | one line or one pixel of pipeline | shift the capture and re-diff before touching RTL ("[Seta] A double buffer...") |
| Paused frame differs from the running one | the game writes scroll or control registers mid-frame | record them per line, replay while paused (`wickerwaka_irem.md`, Pause by replay) |

## Tiles and colour

| Symptom | Cause seen before | Check |
|---|---|---|
| Right shapes, wrong pens | `gfx_layout` plane order: the first plane is the MSB; `TILE_FLIPXY` transposes | check the transcription against the layout without any ROM ("ROM formats") |
| Right shapes, colours a little off in screenshots only | the framework's gamma LUT on the capture path | force `gamma_bus` off under a debug overlay; draw value and inverse, they must XOR to `0xFFFFFF` ("Debug instrumentation") |
| Every Nth tile wrong, or stripes | a registered RAM read consumed a cycle early; a request deasserted late and served twice | give the RAM its latency; deassert on `valid`; hold until acknowledged ("Memory transport") |
| One layer offset from another by a line | the interrupt's line numbering | as the sprite row above |
| A region reads wrong past its first half | base not aligned to size, indexed by masking | index by subtraction ("[Seta] A region whose base...") |

## Memory and SDRAM

| Symptom | Cause seen before | Check |
|---|---|---|
| A read returns the previous request's data | the tracking flag cleared on the data-valid pulse, not the cycle end; data not captured on `valid` | "Memory transport", the contract entries |
| Data wrong, unchanged by the SDRAM phase sweep | not the interface: timing or the core's own glue | revert the diagnostic PLL values; STA ("Hardware bring-up") |
| One byte lane wrong, different per build | a bidirectional bus captured into several lane registers | one I/O register per pin ("[Seta] A bidirectional bus...") |
| A sound chip drops ticks | its port shared with the sprite fetch | its own port or priority (MS32, `sdram_ddr_maps.md`) |
| A fetch that passed every bench fails on the board | the bench's short-latency model | re-run with the production transport ("When simulation passes") |
| Only the CPU's behaviour differs on the board | the bench simulates a different CPU source than Quartus builds (FX68K Verilator port vs upstream) | `PROVENANCE.md` names each tool's source; suspect the pair first ("[BallySente] A vendored CPU may be simulated...") |
| Hard real-time fetch misses under DDR3 | DDR3 latency is not bounded | SDRAM for per-line budgets ("Choose SDRAM over DDRAM...") |

## CPU and sound

| Symptom | Cause seen before | Check |
|---|---|---|
| Game runs slow or fast | clock-enable ratio rounded; a CPU waiting on SDRAM not repaid its enables; a CPI measured on the RAM test | derive the ratio exactly; count stalls ("CPU cores") |
| Odd behaviour after `MOVEC` | TG68K.C ignores ISP/MSP | "[GX] TG68K.C ignores MOVEC" |
| Board differs from ModelSim on a shared net | an open-collector net resolved differently by Quartus | "Do not rely on Quartus resolving an open-collector net" |
| Music stops after the init burst | the chip's timer interrupt never reaches the sound CPU | count register writes over a later window ("A sound CPU that programs the chip once...") |
| Sound CPU locks up after an IRQ is enabled | blind-enabled with no way to see it | expose `halt_n` and PC in the same build ("Do not blind-enable...") |
| A voice starts at a different time than in MAME | inside MAME's own error | judge by ear on the board ("[MS32] MAME is not the oracle for sound timing") |

## Probes and screenshots

| Symptom | Cause seen before | Check |
|---|---|---|
| A counter reads 0 | reset by the reset under investigation | `= 0` with no reset; pair with a total counter ("Debug instrumentation") |
| The same reading at every setting | the probe's step shares a factor with the period | change the step |
| A probe shows a fault on a known-good build | the probe (a combinational tap) | sample registered signals; prove the probe first |
| Every dump is zeros after a load-path change | the debug gate keyed off the old path (`dl_done`) | grep every flag derived from the replaced transport |
| `write_source_data` has no effect | `-value` takes binary | `-value_in_hex`; read every source back |
| A screenshot mismatch | the grab is one frame off; a stale `.rbf` reused by launching an `.mra` over a running core | check the grab time on each side; launch through `menu.rbf` (`tools.md`) |
| A bench differs from a capture that matched before | the capture was taken with different inputs (coin, DIPs, start) | the manifest records the inputs; the comparison refuses a mismatch ("[BallySente] A bench comparison is valid only...") |
| Black and silent on the board, suspect a subsystem | the suspect cannot produce that symptom; the board ran a release `.rbf` instead of the build | break the suspect in simulation first and see whether the symptom matches ("[BallySente] Ask the simulation...") |
| The probe answers for the wrong core | another session's build is loaded | the `core|build|set|` prefix on every line (`identity.py`) |

## Build and tooling

| Symptom | Cause seen before | Check |
|---|---|---|
| "Fitter was successful", board broken | negative slack is not an error to Quartus | `build_staged.py` gates on it; read `.sta.summary` |
| An ALM count that cannot be right | a RAM inferred in logic (asynchronous read on a dual-port, a line buffer in a `generate` loop, a table in LUTs) | fit report RAM-block count; a simple-dual-port module per memory; a standalone synth harness ("Quartus synthesis gotchas") |
| M10K over though the bits fit | blocks are 1024 x 10 whatever the shape | count blocks; remove memory |
| Slack worse after relaxing a constraint | the bottleneck moved | re-read `report_timing` after every change |
| Every worst path inside one vendored module | a constraint proved elsewhere was not copied | move the constraint in the same commit as the measurement |
| Correct RTL, a path that will not close | a guess at the path | `get_timing_paths -setup -npaths 3`, seconds ("[BallySente] Ask the timing analyser...") |
| A bench prints nothing | it did not run: compile killed, or `work/_lock` from a dead run | sweep `vsimk.exe`; fresh `work/` (`run_sim.sh`) |
| Every bench check fails at once | ROMs read as zero: `$readmemh` from the wrong directory | run from the repo root; grep the log for `readmem` |
| Verilator and ModelSim disagree | one of them is wrong, and it is a finding | `run_verilator.sh` vs `run_sim.sh` on the same bench |
| A Verilator snapshot will not reload on Windows | text-mode `open()` | binary mode ("[GX] A Verilator snapshot...") |
| A deploy-then-launch shows the old build | the `.rbf` not flushed | `sync` and a settle gap ("Hardware bring-up") |
| A script edit changes a run in flight | bash reads scripts as it goes | never edit a running script ("[MS32] Do not edit a script...") |
