# Lessons learned

These rules come from building MiSTer arcade cores with this skill, on Quartus 17.0, ModelSim and
Verilator, for the DE10-nano and the MiSTer framework.

Each bullet gives the rule in bold, then the mechanism or evidence that established it. Names in the
evidence (modules, scripts, chips) are examples of where a rule was found, not the scope it is
limited to.

To add a lesson:
- Put it under its section.
- If a bullet already states the rule, add the new evidence to that bullet as a clause. Do not
  add a second bullet.
- Write the rule and the fact that settled it. Leave out the core's name and the story of the
  search.

| If you are about to... | Read |
| --- | --- |
| Vendor a module, or schedule a chip as new work | "Diagnosis discipline", the first three bullets; "CPU cores" |
| Transcribe anything from a MAME driver or device | "Reading MAME" |
| Capture a reference from MAME | "Driving MAME (Lua, debugger, captures)" |
| Write a `.mra` or decode a ROM region | "ROM loading: .mra, byte order, deployment" and "ROM formats" |
| Wire anything to SDRAM, DDR3 or the ioctl port | "Memory transport" and "MiSTer integration" |
| Touch a sprite list, a line buffer or a vblank copy | "Sprite lists, line buffers and snapshots" |
| Instantiate a CPU | "CPU cores" (and `cpu_from_mame.md` to write one) |
| Add a sound chip or sound CPU | "Sound" |
| Write a testbench | "Testbench discipline" |
| Believe a hardware-vs-simulation divergence | "When simulation passes and hardware fails" |
| Add or size a RAM | "Quartus synthesis gotchas" |
| Build the first `.rbf`, or close timing | "Timing closure" |
| Add a probe or a debug switch | "Debug instrumentation" |
| Deploy to the board or read anything back | "Hardware bring-up" |
| Run the tools at all | "Tooling and workflow" |

---

## Diagnosis discipline

- **Suspect your own integration before any vendored module.** TG68K.C, T80, `sdram.sv`, `hps_io`
  and `sys_top` ship in many working cores. One search suspected pins (38/38 correct), SDRAM_CLK
  phase, the burst controller, the interleave and TG68K microcode; the cause was its own glue. Rank
  hypotheses by how many shipping cores would have to be broken for them to be true.
- **Before scheduling a CPU, sound chip or ASIC as new work, ask which boards carry it and whether
  anyone built a core for them.**
  - A web search for the CPU name missed a V60/V70 that two MiSTer cores ship, under `rtl/cpu/`,
    with benches.
  - `gh search repos` matches only names and descriptions, so it said two Taito boards had no core;
    both did.
  - Enumerate instead: `gh api --paginate orgs/MiSTer-devel/repos`, jotego's repositories, and ask
    the user.
  - Grepping a primary opcode table is not a survey of an ISA with escape opcodes.
- **Treat a conspicuous omission in a vendored module as deliberate.** Upstream `sdram.v` has no
  reset port, so a core reset cannot disturb memory; a wrapper that added one created the download
  hazard under "MiSTer integration".
- **Read both halves of a mechanism: the draw loop and the pixel operation.** A loop's direction
  means nothing until the write rule beside it is read: overwrite (last wins) or a priority stamp
  (first wins). Sprite order was inverted twice, once each way, on the loop alone. A line buffer
  that runs out of time must drop what the chip draws last, and which end that is needs both halves.
- **A flag that swaps wiring must be traced to every consumer, acknowledges included.** MAME's
  `set_invert_vblank_lines` swaps which callback fires; the ack handlers call the callbacks by name,
  so under inversion the field ack clears vblank. Moving the acks with the events took ~2,800
  interrupts a frame.
- **Read the framework's source instead of inferring its behaviour.** Two fixes were built on DIPs
  arriving in the status word. `mra_loader.cpp` sends them as an ioctl download with index 254.
- **Copy a driver's register expression with its operators.** `enable(~ctrl & 1)` transcribed as
  `ctrl[0]` is the right bit with the wrong sense, and it passes review. Check every enable bit for
  inversion against the driver.
- **Make the hardware report its own state.** A debug overlay dumping the register RAM showed the
  CPU's control word beside the core's decoded enable in one screenshot. Dump the register, not the
  intent.
- **Prefer a hypothesis that predicts the number exactly.**
  - Tiles were right across exactly 28 of 320 columns. That is 336 fabric clocks over 12: an engine
    stepping per `clk` instead of per pixel enable. Contention would give a ragged boundary.
  - Red exactly 4x and green 2x with blue right is a concatenation three bits too wide, a field
    alignment fault, not arithmetic.
  - A checker error that is a clean multiple of a quantity the checker knows, starting at a phase
    boundary, is the checker's fault.
- **Do not re-guess a sign from the reasoning that produced the wrong one.** A -16 patch that moved
  the wrong way was removed, not flipped; the cause was a handshake bug.
- **Add runtime A/B switches when the alternative is a rebuild per bisection step.** OSD
  render-disable switches isolated an SDRAM starvation in one bitstream.
- **Put the workload in the same sentence as the number.** A CPI of 8.48, near MAME's 8, was the
  power-on RAM test; in play the same CPU ran 20.1. When a measurement beats prior art by 2x, ask
  what ran.
- **Estimate the worst case from what the hardware walks, not from the frames you looked at.**
  Captures said 32-61 sprites a line; the chip walks all 512 entries every line, and the RTL's own
  counter measured 155-544. Instrument the RTL (a four-line worst-line counter).
- **Ask what a table of per-game constants has in common before encoding it.** A mechanism (delay,
  layout, a latch) generalises to sets nobody measured; a table does not.
- **Sanity-check a reported clock against the board's crystal** before believing a timing report.
- **Ask the simulation what the hardware symptom would look like.** Zeroing a suspect CPU's ROM in
  the bench gave the same frame as the normal run, so that CPU could not be the cause of a black
  screen. It took two minutes and moved the search to the load path.
- **A trace that agrees with the reference while a branch goes the other way has missed what the
  CPU consumed.**
  - A peripheral drove read data combinationally, and its read pointer advanced during the access.
    A Z80 samples at the end of the cycle; the trace sampled at chip select and matched MAME on
    1.1 M reads.
  - Latch a peripheral's read data at chip select, and log the latched value.
- **A late divergence can be a wait the reference leaves and the RTL does not.** RAM matched at
  frames 120-600 because both sides were idle, waiting for a reply MAME gives at frame 560. Diff the
  write stream, find where the reference resumes, and read the I/O just before it.
- **"Bisected" is a claim about cause; an intermittent fault cannot support it.** Two builds that
  sampled a collision-dependent fault differently were taken as a bisection onto a chip that touched
  nothing. No proposed mechanism was the warning.
- **The user's description is a measurement.** "Music works, single-shot effects never have" named
  the path (a new voice starting while others stream) after many probe reads had not.
- **When the reference is software, run the software.** Running ymfm on the captured writes found
  three faults at the first differing sample, where side-by-side reading had found none.
- **A cheap metric finds candidates; the render decides.** 1,089 late palette-index writes rendered
  0 different pixels: every index mapped to the same colour. Over indexed colour, a byte metric is
  an upper bound, never a pixel count.
- **When a picture is nearly right, try rigid transforms first:** a one-line or one-pixel shift, the
  four flips. A frame one line late read as sprite dropout until shifted (0 differences).

## Reading MAME

- **Transcribe MAME's device model, not the datasheet.** MAME's `pit8253.cpp` counts on the
  clock's falling edge, samples GATE on the rising edge and remembers a gate rise between edges. A
  datasheet version stalled a self-calibration loop. Peripheral behaviour a driver depends on lives
  in `src/devices/`.
- **Transcribe the integer types and the loop structure.** `s32` and `u32` with a `/` that
  truncates toward zero, modelled with Python's ints and `//`, turned a wrapped subtraction into a
  step of -16.7 M. Write down widths, signedness and division; copy where a loop skips and stops.
- **Take an opcode's encoding from the dispatch `switch` and the disassembler, not a comment
  table.** A comment table put `LD (dst),r` eight opcodes off; the one store using it built the
  Start byte.
- **Check a CPU device's clock divider against its siblings.** MAME's V50 halves its input clock
  and its V53 does not, so a driver's crystal can be right for one part and wrong for another. A
  sound CPU at MAME's clock needed 1.5 ARM cores; at the input over 2 it kept up.
- **`irqN_line_hold` names MAME's input line N, not the CPU's interrupt N.** For the Hyperstone E1,
  line 1 is `INPUT_INT2`. Read the CPU's `INPUT_*` constants and the mask the game writes.
- **A latch MAME documents as behaviour is specification until a board says otherwise.**
  - `syncen` ("ensure each IRQ is triggered at least once after being enabled") is what one game's
    wait loop depends on.
  - The same latch fires where a game has turned the interrupt off, and breaks EEPROM saves in
    MAME too.
  - Model what the game needs, and record the choice in `MAME_KLUDGES.md`.
- **A MAME clock hack during a power-on test points at something the core does not model.** A
  68020 underclocked to 2/3 for 12 s covered its instruction cache being off (CACR, logged per
  frame); the core's ROM cache ignored CACR and the self-tests ran too fast.
- **Devices mapped with `umask` on the halves of a word both see a word access.** The second sound
  chip never started, because its enable was one word write.
- **An input port reads as its `PORT_BIT` mask, not the bit it reports.** A `VBLANK` port with mask
  `0xffffffff` reads all ones in vblank, and a game tested the halfword.
  - `PORT_DIPUNUSED` with `IP_ACTIVE_LOW` defaults the bit to 1.
  - An `IP_ACTIVE_LOW` `PORT_CUSTOM_MEMBER` field is XORed with the port default, which can be
    MAME's own bug; check it against what the game does with it.
- **A bench's idle inputs are the driver's defaults, not all ones.** An all-ones idle value
  disabled a "Sound Enable" DIP that is active low. Build the idle value from `PORT_DIPSETTING`
  defaults and check it against a MAME read.
- **A RAM MAME saves starts as MAME's device fills it.** `nvram_device` fills with ones
  (`DEFAULT_ALL_1`); fill it before the `.nvm` load.
  - MAME's NVRAM images are in host order: a 16-bit serial EEPROM is little-endian words, and a
    32-bit share is its dwords reversed.
  - A game that reads its EEPROM without writing it needs the driver's default `.nv` region in the
    `.mra`. MAME with a blank file shows the same BAD screen.
- **Before taking a `hiscore.dat` entry, look for the game's own score table in NVRAM.** A game
  rebuilt work RAM's table from its EEPROM at boot, so `hiscore.v` and the EEPROM save overwrote
  each other.
- **Compare against a raster position with the driver's declared screen height, not the RTL's.**
  `time_until_pos()` wraps modulo the driver's height. A register parked at `0xFFFE` was read as
  "no interrupt", but MAME fires it every frame, and the game waits on it.
- **A screen declared with `set_refresh_hz` and no vblank time has its vblank at the end of the
  frame.** Read `set_vblank_time` or `set_raw`, and measure the interrupt from the debugger trace.
- **MAME's flip screen can be wrong for a driver.** The reference is the unflipped frame turned 180
  degrees. Flip also moves parked sprites into the visible lines.
- **MAME is not the oracle for sound timing.** A voice starting a sample apart is within MAME's
  error, and its scheduler cuts CPU timeslices at every timer in the machine (a resumed REP costs
  extra cycles). Compare a sound CPU's port in values and order, print the drift separately, and
  judge timing by ear.
- **MAME's MIPS program space is physical.** Reading `0x80000800` returns 0 with no error; kseg0
  code is at `0x800`.
- **The MAME binary must be the version of the source you read, and vanilla, not a fork.** 18
  commits separated two versions of one sound device. Check `<exe> -version` against
  `git describe --tags` at the start.

## Driving MAME (Lua, debugger, captures)

- **Hold every Lua subscription and tap in a global.** Notifiers and taps held in a local of the
  main chunk are collected after about 100 frames and stop silently, exit 0. Check that a capture
  has accesses up to its last frame.
- **An error inside a tap callback is silent.** A frame notifier's error prints and a tap's does
  not, so the tap looks as if it never fired. Wrap every callback in `pcall`, keep a hits counter
  beside a logged counter, and write the first error.
  - `screen:vpos()` and `screen.visible_area` are nil in the 0.286-0.289 binding.
  - The line number is `(frame_period - time_until_pos(0)) / line_period`.
- **Run captures through `run.lua`**, which turns a Lua fault into `lua_error.txt` for the Python
  side. Called directly, a bad tap range became a modal dialog and the runner said only "no trace
  written".
- **Keep `install_*_tap` inside the space's `global_mask`**; an I/O space masked to `0xff` rejects
  `0-0xffff`.
- **Read the binding in `luaengine.cpp`, not the docs, and make every writer count what it
  emitted.**
  - A state entry's name is `symbol`, not `name`.
  - `regions[...]` has no `read_range`, and `read_u64` aborts the callback.
  - Dumps written with absent properties came out well-formed and short.
- **Set a DIP with `field.user_value = raw`, from the autoboot script before the first frame.**
  `set_value` is the pressed state, so it inverted a DIP whose default is non-zero. Before the first
  frame works for DIPs read at boot. Verify through the capture's own register, not the request.
- **For an analog port, log `port:read()`, not the value set.** `set_value` is clamped to
  `PORT_MINMAX`, and a signed range has min above max. It also bypasses sensitivity and reverse.
- **Copy the width and mask of the game's own write before poking from Lua.** A 16-bit write on a
  32-bit bus missed a `umask32(0x0000ffff)` handler.
- **Check a play stimulus by its effect.** Single coin pulses of 1-60 frames gave no credit,
  although the game read the bit, while repeated pulses gave credits. Look at the credit counter.
- **Diff reference captures against each other first.** Four cartridges gave identical sound
  references because each was the sound board's own boot. Insert a coin, press Start, and compare
  after the attract sequence.
- **Know which frame each capture shows.**
  - `screen:pixels()` in a frame notifier is the picture drawn from the previous notifier's state,
    so compare model N with MAME's capture N+1; `snapshot()` matched the RAM dump.
  - A driver without `VIDEO_UPDATE_AFTER_VBLANK` draws in `vblank_begin`, and the notifier runs in
    the same call, so its RAM is the frame's.
  - A trace's `# frame N` marks the frame's start; a capture of N is the state after it.
  - Check every pairing on a moving scene: static attract screens hide all three.
- **Dump a double-buffered RAM where the driver copies it.**
  - A vblank copy is the RAM read in frame N-1's notifier, because the notifier runs after drawing
    and before `screen_vblank`.
  - A copy at vblank start leaves the notifier's dump a frame ahead. Arm a tap at N-1 and dump on
    its first hit.
- **A driver that changes the visible area inside `screen_update` draws each frame with the
  previous frame's area**, and leaves rows outside it stale. Record the previous frame's flip in the
  manifest.
- **Take the visible area from the device that sets it.** A 3D device reconfigured the screen from
  its own registers, 1 pixel from `set_raw`.
- **A MAME screenshot is the screen plus what MAME drew over it**, such as a crosshair for any
  analog axis. A narrow palette gives a check: 4-bit channels make every real pixel a multiple of
  17, so report the rest.
- **A `-snapview native` snapshot of a ROT270 set is the native frame turned 180 degrees; a ROT90
  set's is not.** Compare under the four flips, pin the one that matches, refuse the rest. A MiSTer
  screenshot shows the scaler's input, not the HDMI rotator's output.
- **Take a state image from a frame notifier, never from a tap.** A tap fires mid-cycle; at a
  notifier `PC` equals `CURPC`. A tap may only arm the dump.
- **Debugger traces need `-nodrc`**, because the debugger hook fires only in the interpreter.
  - Print `tracelog` arguments with `%#x`: `0x0a` printed as `a` reads as the 8052's ACC.
  - `trace` and a tap's `tracelog` write to the visible CPU's file; set
    `manager.machine.debugger.visible_cpu` for a second CPU.
  - A trace can repeat one instruction with identical state, so fold consecutive duplicates.
  - Cycles headless: `-debug -debugger none` and `trace <f>,cpu,noloop,{tracelog "%d ",totalcycles}`.
- **MAME takes an interrupt at its scheduler's instruction boundary**: the first boundary at or
  after one cycle before the event. A cycle-exact bench reproduces that rule from the CPU's own
  T-state count, not from simulated time.
- **Sample the registers every frame to find a frame that uses a feature.** Two modes MAME's
  comments attribute to games were set in no frame of 1,500 in five sets.
- **A census taken in play says nothing about boot.** A DMA mode removed on gameplay evidence was
  the boot loader's; run the census from power-on before cutting anything.
- **Check `mame.ini` for `debug 1` before automating**; pass `-nodebug`. Snapshots work under
  `-video none` and land one directory deeper. Read dumps through the CPU's address space
  (`spaces["program"]:read_u16`), handlers included.

## ROM loading: .mra, byte order, deployment

- **A `<dip>`'s `bits` is a range, "first,last".** `mra_loader.cpp` reads it with `sscanf("%d,%d")`,
  so `bits="8,9,10"` is bits 8-9. Check with a script that parses as the loader does, against
  `-listxml`.
- **A `<switches default>` is reliable only in its first four bytes, so keep every DIP in bits
  0-31.** `dip_def |= binary[i] << (i*8)` is an `int` shift: byte 3 of 0x80 or more sign-extends,
  and byte 4 is lost. A fake DIP at bit 32 started On in every set.
- **A correct DIP block still needs `"DIP;"` in CONF_STR**, or the OSD has no page. Verify the end
  the user touches.
- **`.mra` `default=` maps pad buttons to the named buttons only, skipping `-`.**
- **Prove the interleave against MAME's disassembly offline.** Rebuild known words from the ROM
  files and score them (18/18 against 5/18). Every interleave derived by reasoning about byte order
  was wrong.
- **The map digits are mechanical.** mra-tools-c emits bytes in digit order minus one: `map="12"`
  swaps pairs and `map="21"` is verbatim. `ROM_LOAD16_WORD_SWAP` gives `<interleave output="16">`
  with `map="12"`; plain `ROM_LOAD` gives a bare `<part>`.
- **Do not "fix" a loader without hardware evidence of wrong bytes.** One rewrite was tested against
  an SDRAM that was never written, and swapping its maps changed nothing. A hardware-vs-image
  comparison built from the same byte-order assumption cannot find a wrong image. A ROM-trace match
  proves content, not address reach, when the trace address is truncated.
- **List `<rom index="1">` before `<rom index="0">` when a mod byte gates download-time logic.** It
  is sent in file order and powers up 0.
- **Gate every deploy on an XML well-formedness check** (`validate_mra.py`). A stray `-->` made
  MiSTer reject the file with one on-screen "XML parse" and every symptom pointing at the RTL.
- **Publish an `.mra` only with the core it needs, in the same push.**
  - Downloader serves `releases/` at once.
  - Sets broke when an `.mra` gained a control byte the released core misread, or named an
    unreleased `<rbf>`.
  - `check_release_mras.py` in the pre-push hook refuses both.
- **`<rbf>` is a case-insensitive prefix match, and the last by case-sensitive `strcmp` wins
  (`get_rbf`).**
  - The match can pick a release copy, or another collection's core with a lower-case name.
  - Keep `.rbf`s in `/media/fat/_Arcade/cores/` only, with no release copies beside the numbered
    builds. Name the stem uniquely.
  - When only the newest set fails, list that directory first.
- **A missing zip gives no error.** `mra_loader.cpp` logs it and sends the image without the part;
  the CPU runs on filler. Before reading probes on a set new to the board, check
  `/media/fat/games/mame/<set>.zip`.
- **Force a genuine reload when testing an `.mra` change**, by bouncing through `menu.rbf`.
  Relaunching reuses the cached ROM.
- **Do not hand-write a `.CFG`.** It is the whole status word, DIPs included; 16 bytes with one bit
  set zeroed every DIP. Read-modify-write. Make the all-zero configuration the correct one, with the
  OSD order inverted (`On,Off`) where needed.
- **Find a ROM by CRC, not filename**, so the bench and the board accept the same zips.
  - Every `<part>` carries its `crc`.
  - Look up by CRC first, then by name (`zipfile` has each entry's CRC).
  - Match basenames, ignoring directories inside the zip.
  - Name zips as a cascade: `set.zip|parent.zip|bios.zip`.

## ROM formats

- **Read a ROM macro's definition, not its name.** `ROM_LOAD24_*` may be driver-local
  (`ROMX_LOAD` with `ROM_SKIP`, building 3-byte groups).
- **A `gfx_layout` can be checked without any ROM:** `width*height*planes` distinct offsets
  covering `[0, charincrement)`.
- **The first plane listed is the pen's MSB; `TILE_FLIPXY` swaps its two bits.** Ascending planes
  give a recognisable picture with a third of the pixels wrong. Bit 14 is FLIPY and bit 15 FLIPX in
  `TILE_FLIPXY((w & 0xc000) >> 14)`. Ask what the wrong pixels have in common, not which games are
  wrong.
- **A driver init runs on the host-order buffer.** `romload.cpp` byte-swaps a big-endian region
  before `init_*`, so `i & 1` there is the 68000's high byte, not the odd file byte.
- **A `ROM_REGION32_BE` region drawn raw is in host byte order**, every dword reversed from
  ROM_START's layout. Check an image against a MAME frame, not only against ROM_START.
- **Run a region-layout check on two sets of different sizes.** `size4 = (bytes >> 20) / 5 << 22`
  agrees with a 5-byte-row guess only on its own sizes.
- **Size a ROM address bus from the largest region any set in scope declares**, and check the code
  field's width against it. Every capture of the smallest set passed.
- **Compare CRCs across regions before deciding a set does not fit.** Four 16 MB texture regions
  loaded the same ROMs.
- **A packed SDRAM image is shorter than the address space it stands for.**
  - Reads past a region's end return the next region where MAME returns zero.
  - A protection chip that walked pointers there read 65,278 pieces.
  - Answer those reads as the driver's map does.
- **Look for a permutation above byte granularity before touching data.** `RGN_FRAC(1,2)` words
  half a region apart are a free word-address permutation: reads per row 4 to 1.
- Encrypted or scrambled ROMs: `rom_encryption.md`.

## MiSTer integration: reset, download, CONF_STR, DDR3

- **Never hold the memory path in the core reset.** MiSTer holds `RESET` for the whole download.
  `core_reset = reset | ioctl_download` gates CPU and video; the memory backend and any registers a
  download writes keep plain `reset`. Signature: a downstream FSM idle while its trigger pulses.
- **Put the OSD Reset entries before the joystick lines in CONF_STR.** After `J1` they showed and
  never moved `status[0]`. When an entry's bit never moves, count it on the board, and copy a
  working core's order.
- **Measure at the pins.** Only a count of commands on `{nRAS, nCAS, nWE}` showed zero writes;
  delivery and accept counters looked perfect.
- **Reset DDR3 masters with emu `RESET`, synchronised.** `sysmem.sv` resets the bridge with
  `reset_out`, held 20 ms after configuration. A master released on PLL lock lost a read for good.
- **Drain the DDR3 port before reset completes.** A burst cut mid-way hangs the f2sdram port, and
  the hang survives core loads until a reboot: relaunch the last good core before bisecting.
  - Count credits on the condition that issues the command. A drain that skipped an issue left
    128 beats owed, and the board stayed in reset.
- **HBlank must fall on every line, vertical blank included.** `scandoubler.v` counts lines from
  HBlank's fall, so without it VSync never passed and every Scandoubler Fx scrambled the picture.
  - Verilator traps in `sys/`: `arcade_video` leaves `HDMI_FREEZE` unconnected, and
    `video_mixer.sv` uses `R_in/G_in/B_in` outside the generate block that declares them.
- **`crt_adjust`'s picture position depends on the pixel's phase against its enable.** Data and
  enable on the same clock put it a pixel right. Compare On against Off whenever the clock or
  source changes.
- **Check where the fitter put `pll_hdmi`'s output counter.** Main_MiSTer's `setPLL()` writes one
  physical C counter. At `X0_Y7` every mode but 1080p60 showed "Unsupported". Pin
  `PLLOUTPUTCOUNTER_X0_Y5_N1` in the `.qsf`, and read the PLL Usage Summary.
- Running part of the board on the HPS: `hybrid_cores.md`.

## Memory transport: req/valid contracts, latency, byte order

- **Count a RAM port's latency from the primitive's registers and spend it.**
  - Latency is the registers before the RAM, plus `address_reg`, plus `outdata_reg`.
  - Address-then-read in the next state got the previous entry, and a smoothly varying table hid
    it.
  - Benches must serve the same latency. Three benches each serving 0, 1 or 2 cycles passed alone
    and failed composed.
  - Under a clock enable of 1 in N, a registered read completes before the next step, and a wait
    state shifts every capture.
- **Deassert a request combinationally on `valid`**: `req = req_r & ~valid`. `sdram_phy` returns to
  idle on the valid cycle and samples a still-high request again, so every reply landed one request
  late.
- **Hold every request until acknowledged, and make it able to fall.**
  - A pulse arriving while another client is served is lost; two pulsing clients need latches, not
    a priority mux. `ioctl_wr` is a one-shot and needs `ioctl_wait` backpressure.
  - A request derived from `addr != held_addr` never fell when the client moved its address on the
    valid's edge. Register the address with the request, and make the request the in-flight flag
    alone.
- **A toggle-request controller samples its inputs after the toggle.** `sdram.sv` starts when it
  sees `ack != req`, a cycle or more later. Hold address, data and strobes until `ack` catches up.
- **Treat a direct, non-arbitrated connection to a req/valid transport as suspect.** The arbiter
  gives a cycle of margin, and a single client wired straight to the phy got the previous data.
- **Clear a request-tracking flag when the bus cycle ends, not on the data-valid pulse.** A 68000
  holds `AS` after DTACK. Clearing early fires a second request.
- **Capture read data on the valid pulse.** Nothing between `sdram.sv`'s `dout` and the CPU
  registers it. TG68K.C re-capturing every clock hid it by one cycle.
- **DTACK and ready are held levels for any clock-enabled CPU.**
- **A one-cycle handshake into a slower clock-enabled domain must land on that domain's edge.** A
  bench that answers in an even number of clocks hides it; vary the latency's parity
  (`+ROM_JITTER`).
- **Fix byte order at each seam with an adapter**, not by changing a shared convention.
  - MiSTer's DDRAM port puts the byte at the lowest address in bits 7:0.
  - Video benches that each built granules big-endian agreed with each other, and only the first
    bench that crossed the platform boundary disagreed.
  - Define a boundary convention once in shared bench code.
- **A register port without byte enables passes every capture-driven bench.** Captures write whole
  words; the game wrote bytes, and the 68000 drives each byte on both halves of the bus. List the
  game's write masks from MAME's trace.
- **Index a region whose base is not aligned to its size by subtraction, not masking.**
- **A dual-clock FIFO's count back to the writer counts what left the RAM, not what the reader
  took.** A first-word-fall-through head queue still held words. Count takes on the reader's clock.
- **A write queue that may stay full must not hold back another port's writes.** One CPU's posted
  stores starved another CPU's write, and the boot gave up on it. A priority rule is checked by a
  run long enough to saturate the high side, not by random traffic.
- **Two writers to one RAM port in one clock: make the collision impossible, or a simulation
  error.** The later `always_comb` assignment won silently, and only one texture format met it.
- **A kill flag checked when a read completes misses a kill raised in that clock.** Invalidate the
  arriving result as well as the request in flight, and test a cache against a CPU of different
  timing.
- **Choose SDRAM over DDRAM for hard real-time fetches.** DDR3 measured ~26 cycles against a
  16-cycle tile budget; SDRAM ~6-7.
- **Verify a burst extension against a command-decoding chip model, not a latency stub.** It found a
  row/column split that only matters with bursts, ignored DQM and an off-by-one CAS.
- **Size a prefetch buffer for correlated consumers.** Two layers with identical timing request in
  lockstep.
- **A bidirectional bus captured into several lane registers gets one I/O register; the rest is
  untimed and placement-dependent.**
  - A pin has one input register.
  - Capture `SDRAM_DQ` once, unconditionally, and split it into lanes a cycle later.
  - When an inert change breaks the board with clean STA, read "Unconstrained Input Ports" and the
    Packed Register table.

## Sprite lists, line buffers and snapshots

- **Buffer the sprite list and render per line; add a frame buffer only on board evidence.**
  Buffer the list once a frame, build candidates, run a per-scanline engine into a double line
  buffer.
- **A swap is not a copy.** Under ping-pong the CPU's view alternates, so an entry not rewritten
  every frame, the end marker included, reads two frames old.
- **A snapshot is a race with whoever writes what is copied.** Start the copy when the writer is
  quiet, and make it atomic: write-through to the copy behind the cursor. A fault that needs the CPU
  running and is not in the CPU is such a race; golden frames cannot see it.
- **Freeze everything a per-line renderer reads, not just the list.** Records re-read from live RAM
  change tile mid-frame. Latch the list and the video registers at one point from the write sweep,
  and record why if any array differs.
- **A glitch seen only while running, never when paused, is a buffering fault**, not a decode
  fault.
- **A device that buffers some state and reads the rest live needs a two-frame bench.** A golden
  frame after vblank re-renders the wrong pairing. Three reorderings each fixed one game and broke
  another: check the writer's timing against the reference before moving an event relative to it.
- **A double buffer puts the renderer two lines ahead.** The buffer written during L is shown during
  L+1, and `line_start` fires at the end of L-1.
- **Latch the line number at `line_start`.** A `vpos + 1` wire names the next line one clock later.
- **A one-line offset between layers is the interrupt's 0- or 1-based numbering, not its timing.**
  Establish which row the handler services before shifting anything.
- **For raster effects, fire the line interrupt every line and buffer attributes into the line
  renderer** (NeoGeo_MiSTer, jtcps).
- **Latch a CPU-written configuration for the length of the operation that uses it.** A mode
  rewritten mid-line changed words-per-tile between two stages, which hung the video. Give the bench
  a register write mid-operation.
- **A stage that hands a record to the next stage hands a copy.** A row stage read the setup stage's
  live registers and drew the next block's tiles.
- **Build a sequenced address from a committed value**, not from the counter the same cycle resets.
  Three of four layers passed because their scrolls were zero.
- **Put a time budget just below the line period, not at it.** At the period, the cutoff races the
  swap and restarts the engine mid-line.
- **Draw front to back with an index tag per pixel.** A back-to-front engine that runs out of time
  drops the top sprites. Write a pixel only when the new index is lower; overflow then drops the
  bottom ones.
- **A per-line object scan that runs out of time drops sprites silently.** Grep sprite benches for
  "did not finish" and count it as a failure. Look at where a missing sprite sits in the table
  before its attributes.
- **`jtframe_objdraw_gate` with `HFIX=1` needs `hs` across the `hdump` wrap.** Thousands of buffer
  writes and zero pixels out says the fault is on the read side.

## CPU cores

- **Budget for TG68K.C to limit Fmax.** It reached 48.74 MHz at speed grade 7, with all 50 worst
  paths in the kernel's register file.
- **Instantiate `TG68KdotC_Kernel` directly and own the bus.** `TG68K.vhd` assumes `CLK` is the CPU
  clock (falling-edge registers). Gate `clkena_in` as plus_too's `tg68k.v` does.
- **TG68K.C's mode decides its behaviour; measure the one you run.**
  - It ignores `MOVEC` to ISP/MSP, so search the ROM for `4E7B x804/x803`. Fixed with one write
    port and the address muxed (2 M10K).
  - With `CPU="00"`, `MOVEC` is illegal and the interrupt entry is IACK, then PC high at A7+2, PC
    low at A7+4, SR at A7, with no format word.
  - `CLR` reads its operand first, as a 68000 does and MAME's 68020 does not. Check read-side-effect
    addresses against the program.
  - A 68000 boots at interrupt mask 7. Check the mask before calling an IRQ path broken.
- **Derive the clock-enable ratio exactly.** 176/945 by a Bresenham accumulator; /5 is 7.4% fast
  and /6 is 10.5% slow.
- **Do not rely on Quartus resolving an open-collector net as ModelSim does.** `RESET <= ... 'Z'`
  became a selector stuck low. Add a single-driver force port, then check every consumer of the raw
  net.
- **Expose a port for a debug tap**: hierarchical references into VHDL fail in Quartus.
- **Zero-initialise vendored VHDL signals before simulating real programs** (TG68K.C: 123 signals,
  upstream issue #21).
- **Exercise the ISA extensions you depend on** with a spike program before building on them.
- **T80 timing.**
  - Waiting on SDRAM, it is a slow Z80: count each enable that lands on a held read and repay it,
    measured against MAME's time.
  - Derive `WAIT_n` from `T80.vhd`: `TState` freezes and data is taken on the first true edge.
  - With CLKEN it samples DI on the same enable as the read strobe, so drive DI from the peripheral
    during the strobe; a latch there gave the previous read every time.
  - It makes an opcode read in the NMI acknowledge that MAME's Z80 does not, so exclude it
    (`NMICycle`) from bus-trace compares.
- **Read the interrupt vectors before deciding a board's interrupts.** A family's usual config sent
  a level whose vector was the reset entry. An ack address that is also an input acknowledges on
  writes only.
- **A CPU vendored from another core can carry that core's memory map.** Grep it for address
  constants and compare data accesses, not only PCs.
- **When a vendored CPU has a downstream fork, diff its bus logic against the original first, and
  count bus beats.** A doubled store passes a memory-content test. A beat counter or a bus trace
  finds it.
- **A vendored CPU may be simulated from a different source than Quartus builds** (fx68k's
  Verilator port). Record each tool's source in `PROVENANCE.md`, and suspect the pair when only that
  CPU differs on the board.
- **The N64 VR4300 core posts stores; MAME does not.** An acknowledge can still be queued when the
  handler sets IE.
- Writing a CPU from MAME's interpreter: `cpu_from_mame.md`.

## Sound

- **A stand-in for a sound CPU must change state, not echo a value.** A game that sees 16 equal
  status frames resets the sound CPU. Disassemble every reader of the status register.
- **A sound CPU that programs the chip once and goes quiet has a broken interrupt path.** Music is
  sequenced by the chip's timer interrupt. Do not blind-enable that interrupt: expose `halt_n` and
  the PC in the same build.
- **jt6295 restarts a playing voice, while the M6295 ignores the start.** A fade re-sent the start
  every 13.7 ms. Mask busy voices in the wrapper.
- **A vendored sound core that is silent in simulation may only be uninitialised.** jtopl and jt12
  leave envelope pipelines without reset. Use `+initreg=r+0 +initmem=r+0` on those files.
- **A chip select from an address decode alone also takes memory writes.** Qualify it with
  `IORQ_n`.
- **Check a sound engine inside the whole board by replaying the board's own register writes
  through the model.** Compare the write log with MAME's separately for the program flow.
- **A free-running engine emits samples before the bench has configured it.** Load the registers
  with the block in reset and compare from release.

## Testbench discipline

- **A pass on data that cannot fail is no information.**
  - Uniform tiles pass any pixel order, zero scrolls hide index bugs, and uniform content is
    invariant under byte order.
  - A bench that compared mostly zeros passed while the core shipped silent. Print the non-zero
    count beside every pass.
  - Break the feature deliberately and see the comparison fail.
  - Make the model print what each frame exercised, and say what nothing has covered.
  - One game's captures exercise one game's modes, so sweep every set in scope.
- **A hashed fill must reach every address bit.** A pattern blind to bit 27 hid a wrong base on both
  sides. Add a negative control that moves a base.
- **A bench model must give no more than the interface guarantees.** A ROM model raising `ok` every
  clock hid every lost answer; a model accepting on the clock `valid` leaves served stale data. Keep
  a checker comparing every byte handed to the CPU against the ROM.
- **A bench that instantiates a module, or models a memory, cannot see the top level's wiring or
  indexing of it.** Grep the top for every new per-set output. Where a bench substitutes its own
  model, run the real block too.
- **One memory, two address maps: check that the loader's and the reader's agree.** The tell was a
  constant offset in a hardware dump.
- **A bench started from a snapshot cannot see writes that never land in a memory the snapshot
  filled.** End with each writable memory compared to MAME's at a later snapshot. Give the core
  MAME's power-on value for every table the game never writes.
- **A frame bench with the CPU paused has no memory contention.** Drive CPU traffic through its
  port.
- **Compare a CPU against MAME from a restored state, not from reset.**
  - Restore MAME's state at an instruction boundary through the CPU's state port. A 3.9 M-access
    RAM test became minutes.
  - Normalise, do not fail, what differs between two correct 68000s: the order of a long write's
    halves, the interrupted PC in exception frames, and where in the line an interrupt is taken.
  - A state image restores architectural state, not timing, so replay the I/O writes before it.
- **Raise a replayed interrupt where MAME took it, not on the bench's raster.**
  - Use the write count and the last data access before MAME's vector read.
  - Raise it while that access is on the bus, or TG68K takes it an instruction late. Where MAME's
    stacked PC is the access's instruction, raise it at completion.
  - Move the target back by the pushes made before the vector read (`irq_pushes`: 2 on an SH-2).
- **Compare writes per interrupt level once interrupts run**, split by the SR mask, with stack
  writes left out.
- **Two correct cores fetch different words.** Compare reads as a windowed subsequence (~16) with
  repeats collapsed. Large "extra" and "reordered" counts beside zero mismatches are normal.
- **Diff the whole core against MAME, and replay the CPU's trace against the whole board.**
  - A CPU-only bench cannot see a decode, a cache or a RAM size.
  - The whole board diverged at instruction 1,919, in a RAM test.
  - Align with skips on both sides, by a bounded two-pointer walk.
  - Compare the next PC (`retire_npc`).
- **A replay bench pokes state between cycles, into the source an instruction reads**, never into
  its result in the cycle it starts.
- **A bench comparison is valid only against a capture made with the same inputs.** The manifest
  records the coin, DIPs and start presses, and the comparer refuses a mismatch.
- **An out-of-range array index is simulator-dependent.** Verilator wrapped and ModelSim read X.
  Check a vendored model's ranges against this core's images.
- **`+initreg=r+0` turns an unevaluated `always @*` into a confident zero.** ModelSim does not run
  it until an input changes. Apply `+initreg` only to the files that need it; `always_comb` runs at
  time zero.
- **Triage a vendored module's compile warnings before a long run.** A T80 vcom-1275 warning is a
  run-time abort on block I/O.
- **Use `do @(posedge clk); while (sig);`**, never `while (sig) @(posedge clk);`, which races the
  `always_ff`.
- **Under backpressure, assert the write in the same step the wait clears.** An extra edge lost
  every odd word.
- **A bench that fails every check at once has ROMs reading zero.** Grep for `readmem`: paths are
  relative to the simulator's working directory. Write preloaded vectors after `$readmemh`.
- **Confirm which column is address and which data** before blaming a CPU.
- **Do not assert on a sticky error with a benign first trigger.**
- **A block-local variable with an initializer is static**, initialised once before time 0
  (vlog-2244).
- **Never write a literal into a vector that does not start at bit 0.** `[7:1]` numbers from the
  MSB.
- **A behavioural ROM in a bench must speak the transport's byte order.**
- **A liveness test needs a timescale.** Measure against the reference, and fail only on what being
  early cannot explain.
- **Check widths against the largest asset.** An in-range part-select draws no warning, and the
  biggest ROM fails alone.
- **When widening an address, grep for packed buses that carry it as arithmetic** (`[25*k +: 25]`).
- **Do not `force` into the DUT**; drive it as the hardware does.
- **Re-run on a clean stash before debugging a change**, and smoke-test a new top level (elaborate,
  run, check for X) before functional tests.
- **A per-bench verification of a branch is not coverage of it.** A DIP set after reset was not
  acted on and the sweep printed PASS. Verify the effect: fail a frame whose control byte lacks
  the bit.

## When simulation passes and hardware fails

- **Check static timing first** ("Timing closure").
- **Re-run the failing case with the production transport instead of behavioural models.** A
  short-latency ROM model answered between states and hid a duplicate request.
- **Ask of every stimulus whether it has the shape the real system produces.** A one-clock vblank
  hid an acknowledge discarded while the line was high; a bench's own reset never holds RESET
  across a download. Match `irq4_line_hold`: assert on the edge, hold, and acknowledge wins.
- **List what the simulator initialises that the fitter was told it need not.**
  - The template sets `ALLOW_POWER_UP_DONT_CARE ON`.
  - An `initial` array, and a register with no reset, power up as Quartus chooses: an EEPROM read
    BAD, and a copied register froze at 0x04.
  - Write at reset whatever must be known, and turn power-up don't care off.
- **Some constructs Quartus builds differently from Verilator.**
  - Writing an array at a variable index, then changing the index, twice in one clock, lost the
    first push on the board in every build. Write each entry under a constant index.
  - A continuous assignment calling a function that reads module scope is evaluated by ModelSim
    only when its arguments change. Use `always_comb`.
  - When a core runs in simulation and not on the board, build an architectural trace on the
    board (retirements, register writes, bus transfers). Compare it per category with the bench's
    trace of the same RTL. Eleven one-guess builds had not found the fault; one trace build did.
- **Signedness and width.**
  - One unsigned operand makes a comparison unsigned, and so does a concatenation, or a ternary
    with one unsigned branch (`c ? $signed(x) : 0`).
  - Make every operand of a signed expression explicitly signed and wide enough.
  - A check that compares two truncated values cannot see the truncation, so count overflow
    before the cut.
- **Back every RAM a power-on test walks, at the declared size.**
  - An unbacked region reads 0, the test fails and the CPU runs another program correctly.
  - A mirrored block let a RAM test clear the stack, and an `rts` popped zero.
  - Count the `.ram()` lines, not what the game seems to use.
- **A game's starting state can differ from the bench's.** An EEPROM pen calibration on the board
  put clicks off target. Open the game's own test screen, and start the bench from the board's
  `.nvm`.

## Quartus synthesis gotchas

- **Synthesise the core alone, early, and read "Resource Utilization by Entity".** Fits of 1,583%
  and 3,953% of the device were RAMs built from registers, after 98 and 80 minutes. `quartus_map` on
  the core takes seconds to minutes.
- **Write every RAM through one template module per memory: one write port, one read port,
  registered.**
  - Use an explicit `altsyncram` for byte enables or two clocks.
  - These all became registers, mostly with no message:
    - byte-lane writes in the same block as an enabled read;
    - a `case` choosing between arrays inside the registered read;
    - two `always_ff` blocks writing one array;
    - line buffers in a `generate` driving an unpacked output;
    - a packed byte-enabled RAM with two readers.
  - A second read port duplicates the whole array, and a dual-clock pair in two blocks infers two
    copies.
  - A two-clock true dual-port infers only in the write-through form (`if (we) begin mem<=d; q<=d;
    end else q<=mem;`).
  - Check a RAM form in a one-module project first.
- **Infer RAMs at power-of-two depth.** `[0:3071]` stayed in logic. A RAM-block count that drops
  while memory grows is the symptom.
- **A case-statement ROM is built in logic.** Load it from a hex file with
  `(* romstyle = "M10K" *)`.
- **Past ~90% of M10K, count blocks, not bits** (1024 x 10 each). A design can be RAM-bound at 40%
  logic. No memory packs at 100%; remove memory.
- **Verilator-clean is not Quartus-17-clean.** Run `quartus_map --analysis_and_elaboration` before
  the first full build of a Verilator-developed core. Each of these stops a build:
  - `foreach` in `initial`;
  - `for (genvar i ...)`;
  - a loop `generate` without `generate`/`endgenerate`;
  - a net of a typedef'd type;
  - a named struct pattern;
  - a zero-fill past `VERILOG_CONSTANT_LOOP_LIMIT`;
  - VHDL-2008 not set;
  - non-blocking assignment to an `automatic` variable (10959);
  - a function returning a part-select of an unpacked array element (internal error, no file).
- **Multi-driver conflicts on a shared tri-state net are a hard error (13076).**
- **A non-power-of-2 modulo is a slow iterative divider.** Use conditional subtraction.
- **Negative PLL phase shifts are not always legal.** Use `period - |shift|`, rounded to the step
  Quartus names.
- **A PLL's `mimic_fbclk_type` must agree with the compensation mode its `.qip` sets** (`"none"`
  with DIRECT, `"gclk"` with no assignment). Keep what ip-generate wrote.
- **`set_instance_assignment -name RAMSTYLE` aborts project open in 17.0.** Use the attribute.
- **SpinalHDL's `Mem.write(..., enable = e)` ignores the enclosing `when`**, so pass the whole
  condition. Two write calls on one `Mem` give two ports.
- **`quartus_fit` 17.0 can crash or hang for one seed, mostly near full.** Access violation at
  "placement preparation": change the seed, pin it, and bound the build's time. A killed build
  leaves `quartus_fit` and the build marker behind.

## Timing closure

- **Open `.sta.summary` before believing any hardware-vs-simulation divergence.** "Fitter was
  successful" shipped a build at -8.879 ns. Read the Fmax Summary first.
- **Treat "wrong in hardware, reproducible, insensitive to interface tuning, right in simulation" as
  a timing violation.** The placement is fixed per `.rbf`, and the failing paths are internal.
  Discard every measurement taken while a clock failed.
- **Ask the timing analyser which path fails.** Two restructures of a multiplier were guesses; one
  `get_timing_paths -setup -npaths 3` named a `tanh` table in LUTs.

      create_timing_netlist -model slow; read_sdc; update_timing_netlist
      foreach_in_collection p [get_timing_paths -setup -npaths 3 -detail path_only] {
        post_message [format "%s %s -> %s" [get_path_info $p -slack]
          [get_node_info [get_path_info $p -from] -name] [get_node_info [get_path_info $p -to] -name]] }

  Use `report_timing -detail summary -npaths 50` to see which module the failing paths share; use
  `set_operating_conditions 7_slow_1100mv_100c`.
- **A clean STA is a property of one placement.** The stock `.sdc` constrains nothing external. When
  games the diff cannot reach regress, rebuild the same commit at another seed before bisecting.
- **Never let a multicycle touch a posedge-to-negedge path.** Scope it to a single-edge block, and
  remove falling-edge registers from both ends.
- **All worst paths inside one vendored module is a missing constraint.** Move the constraint in the
  same commit as the measurement.
- **Re-read `report_timing` after every constraint change.** Relaxing the old bottleneck measured
  worse.
- **Register a peripheral's CPU interface and spend a cycle; do not multicycle over it.**
- **When a multicycle fails, check its source names still match the SDC.** Retiming renamed one; a
  per-instance retiming OFF was silently ignored, and `(* preserve *)` worked.
- **A task that writes a register, called from many branches, builds a priority chain per call
  site.** Push once, as the clock's last assignment, at a position known at the start of the clock:
  -0.575 ns became +0.867, with fewer ALMs.
- **A clock enable never adjacent to itself makes a two-clock multicycle true.** For jt8051's DIV,
  cover its internal RAM too, and register what leaves the core.
- **A clk1x register sampled on the clk2x edge it shares can miss hold.** Take it on clk2x's
  falling edge, then the rising edge.
- **SDRAM read capture:**
  - A burst takes `-setup 2` alone, without `-hold 1`, because its word changes every clock. Count
    the board trace twice in the input delay.
  - At 125 MHz with an FPGA-made clock at CL2, no phase closes both corners. Work out every
    corner's window before choosing an edge.
  - "Validated at N MHz" on a module means memtest's CL3 and 3-clock tRCD, not yours.

## Debug instrumentation

- **Never reset a debug counter with the reset under investigation**; declare it `= 0`. Pair every
  bad-event counter with a total counter.
- **Sample registered signals, and prove the probe on a known-good configuration first.** A
  combinational tap showed byte skew on a booting design.
- **Never let a probe's step share a factor with the period you measure.** When every setting gives
  the same answer, suspect the step.
- **Capture the full address**, using two buffers on one strobe if needed.
- **An ISSP probe loses constant bits from the middle.** `read_probe_data` pads at the top, so every
  field above the gap shifts. Put possibly constant fields on top; `quartus_eda`'s netlist names
  each `shift_reg[n]`. One `altsource_probe` takes at most 511 bits.
- **`write_source_data -value` is binary; use `-value_in_hex`**, and read every source back.
- **Synchronise an ISSP source before it drives a reset.**
- **Force the framework's gamma off under a debug overlay.** Draw value and inverse in alternating
  bands that must XOR to `0xFFFFFF`.
- **A debug gate keyed off a load path dies when the path changes** (`dl_done` under DDR loading).
  Grep every flag derived from a replaced transport.
- **When reading finds nothing, tag the data and let the hardware say where it went.**
- **Colour-override builds and ISSP pokes answer yes/no questions without a rebuild per
  question.**
- **Read a DDR3 frame buffer with busybox `devmem` over SSH while paused**; `dd` of `/dev/mem`
  fails. This is how to see the rotator's output or a renderer's buffer.

## Hardware bring-up

- **When a new build does not start, load an older known-good one first.** If every core is stuck,
  it is the board: power-cycle it, because a reboot did not clear it.
- **The SDRAM pinout is in `sys/sys.tcl`.** Cross-check `<rev>.pin`; a `.qsf` that restates the
  assignments will override a future `sys.tcl`.
- **Audit an inherited `.srf`**; one hid 15705.
- **Fitter warnings 176250/176251 are usually benign.** Count packing on `SDRAM_DQ`.
- **SDRAM_CLK phase is tuned with the controller's capture point and `clk_sys`.**
  - The MiSTer convention is a -3 ns lead, written as a positive phase.
  - A controller tuned at 96 MHz needed 301.5 degrees at 54 MHz.
  - A sweep with no effect at all says the fault is not at the interface. Revert diagnostic PLL
    values.
- **Take jtframe_sdram64's pin settings with it: `SLEW_RATE 0` on SDRAM outputs.** Without it,
  one fit was black on 4 of 5 launches.
- **`/dev/fb0` is the ARM-side OSD.** Use the screenshot API, and poll
  `/media/fat/screenshots/<core>/`.
- **Remote API** (mrext, port 8182): `POST /api/launch`. Read its Go source.
- **Deploy then launch needs `sync` and a settle gap.**
- **Driving the OSD blind:** the cursor starts at the top on every open; Enter, Space, `+` and `-`
  change an option, and the arrows do not. Prove the position with an option a screenshot shows.
- **`plink`/`pscp` are the non-interactive SSH path on Windows.** Pass `-scp` to `pscp`: SFTP runs
  at ~0.1 MB/s, SCP at 1.8. `MSYS_NO_PATHCONV=1` for POSIX paths.

## Tooling and workflow

- **Working directory does not reliably persist into backgrounded commands.** Use `cd <dir> &&
  <tool>` in one line.
- **Quartus tools are not on `PATH`**: give the full path to the right install. Never run them under
  `nohup ... &`.
- **Never switch branches, or edit a script, source or `.qsf`, while a run reads it.** bash reads
  scripts as it goes. Build from a snapshot (`build/` worktree).
- **Never run duplicate tool instances on one project.** Sweep orphaned `vsimk.exe` at the start of
  a session (`Get-Process vsim,vsimk`, then `Stop-Process -Force`).
- **A bench that prints nothing has not run.** Look for a stale `work/_lock` and recreate the
  library. ModelSim 10.5b's `vlog -quiet` can exit 127 silently, so compile without it.
- **The ModelSim `work` library is at the repo root**, mapped by each bench's `modelsim.ini`.
- **Name the shell.** `bash` on Windows may be WSL's. Read the first failing command's stderr before
  believing a pattern.
- **Pin `*.sh`, `.tcl` and `.lua` to LF in `.gitattributes`.** Vendor from a
  `core.autocrlf=false` clone and compare each file with its blob (36 of 38 had become CRLF).
- **Open repo files with `encoding="utf-8"`**, and never read a file inside the call that truncates
  it. Check `wc -l` after a scripted rewrite; a clean `git status` says nothing about correctness.
- **Two sessions in one working tree share the git index.** Commit with `git commit -- <paths>`, and
  agree first on files both edit.
- **Verilator on Windows:**
  - A comment beginning "Verilator" is a pragma.
  - Set `_fmode = _O_BINARY` before a save.
  - MSYS2 GCC 16.2 cannot link `-Os` C++; use `OPT_GLOBAL=-O2`.
  - A custom `main.cpp` needs `sc_time_stamp()`.
- **MAME's makefile detects Windows only from `OS=Windows_NT`.** Export it inside `bash -lc`.
- **A fine-grained GitHub token cannot run `gh repo create --template`.** Use REST
  `POST repos/<owner>/<template>/generate`.
- **`quartus_map` alone is a fast pre-check** that a change elaborates.
