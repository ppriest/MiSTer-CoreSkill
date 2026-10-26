# Hybrid cores: a subsystem on the HPS

A hybrid core runs part of the board as a Linux process on the DE10-nano's ARM (the HPS), beside
Main_MiSTer, from MAME's code. Two cores do it, both for the sound board, through one shared server:
`ppriest/MiSTer_ArcadeSoundServer` (`arcsnd`).

| Core | Board on the HPS | Why |
|---|---|---|
| `Arcade-KonamiHornet_MiSTer` | 68000 (Musashi), K056800, RF5C400 | no room for fx68k: 41,568 of 41,910 ALMs, 553 of 553 M10K |
| `Arcade-HyperNG64_MiSTer` | V53A (MAME's NEC core), L7A1045 | the user's decision (`docs/ROADMAP.md` Phase 4) |

Before you choose it:
- It is the user's decision, and it goes in the roadmap.
- Choose it only when the subsystem does not fit, with the fit report as the evidence.
- Hybrid is MiSTer Frontier's model, not MiSTer-devel's: the core must still run without it.

## What it costs

- **Latency.** HNG64's sound is about 80 ms behind the picture, kept as a fixed lead over a model of
  the playback buffer; Hornet replays its commands 2 ms after their stamps.
- **Speed follows the wall clock, not the game.** The process plays at 48 kHz. Game speed and pause
  do not change the pitch. Time the ARM falls behind is a gap, not a delay.
- **CPU.** The Cortex-A9 is two cores, and Main_MiSTer holds one.
  - MAME's NEC core ran at about 220 ARM cycles an emulated instruction, 29 times slower than an x86
    desktop.
  - The A9 has no divide instruction.
  - HNG64's sound took 57 to 95% of a core and still has gaps in sams64's and the drive sets' heavy
    passages.
  - The Zaparoo daemon took 42% of a core in `top` (HNG64 LESSONS_LEARNED, "Measure an ARM-side
    emulator").
- **A second deliverable.** Users install the server separately: a release zip, or the Downloader
  database, then a Scripts menu entry (`arcade_hybridsoundserver`) or `linux/user-startup.sh`. The
  core's README says so in its Sound section.

## Shape

- **One shared block of DDR3 per core**, at `0x3F200000` physical (inside the cores' window from
  `0x30000000`). It is written by a bridge in the FPGA and mapped by the server through `/dev/mem`.
  - The layout is a table in the bridge's header, copied to the server's `docs/PROTOCOL.md` with a
    version number.
  - A magic and version at +0x00 name the board.
- **DDR3 is not cleared between cores.** The server takes the block as live only while the bridge's
  beat or count moves, not because the magic is there.
- **The server writes a reply word**:
  - a flag byte (`0xA5`), a running bit and a heartbeat;
  - the bridge uses the replies only while the heartbeat moves (0.1 s on HNG64);
  - otherwise the core's own stand-in answers the main CPU's handshake, so the game runs, silent;
  - the stand-in changes state as the real CPU would (LESSONS_LEARNED, "Sound").
- **What crosses depends on what the main CPU does.** Measure it in MAME first
  (`scripts/mame_sound_trace.py` in HNG64).
  - **HNG64.** The main CPU writes the whole sound program before it enables the sound CPU and
    sends one command a frame, so the bridge mirrors sound RAM (2 MB) and the latches.
    - The enable count goes out only after the mirror's queue is empty, so the server never copies
      a sound RAM older than the enable.
  - **Hornet.** Each host-register write becomes a ring entry stamped in microseconds, and the
    server replays the stamps' spacing 2 ms later.
  - **Both.** ROMs the board reads (samples, the 68000 program) are where the `.mra` load put them
    in DDR3. The server copies them once at start.
- **Session control.**
  - The server watches `/tmp/CORENAME`, which holds the `.mra`'s `<setname>` (Main_MiSTer
    `user_io.cpp`).
  - It runs the session whose `<board>_claims(setname)` accepts it.
  - It stops within 200 ms of the beat stopping (a core load, the core held in reset), the magic
    going, or `CORENAME` being rewritten.
- **Audio** goes out through the framework's ALSA path, not the core's audio port:
  - the process writes 48 kHz S16 to `/dev/MrAudio`;
  - `sys/alsa.sv` reads it from DDR3 and `audio_out` mixes it with the core's.

## Rules learned

- **`/dev/MrAudio` does not block.** The writer paces itself on a model of the buffer's level: frames
  written, less 48 kHz since. `alsa.sv` plays up to 0.53% faster as its buffer fills. A writer paced
  on the wall clock that makes up lost time therefore adds lag that never drains (HNG64
  LESSONS_LEARNED).
- **One copy only.** Two writers interleave on `/dev/MrAudio`. On HNG64, a stale debug build beside
  the real one was heard as noise and seconds of lag. Take a lock at start, and kill by pattern
  (`ps | grep`), not `pidof` or BusyBox `pkill -x`, which missed renamed copies.
- **Never `SCHED_FIFO`.** Two copies at FIFO 50 that had fallen behind their clock never slept
  again. They took both cores, and ssh stopped answering until they were killed. Use a nice level,
  a cap on how far behind the process may chase, and a sleep every 20 ms of work.
- **Measure on the board, loaded.**
  - Profile there: gprof works with a static armhf build.
  - Time it under the daemons a user runs: Main_MiSTer and Zaparoo.
  - On HNG64, 18.2 s of sound took 21.98 s contended, 14.73 s under `chrt -f 50`, 13.07 s with
    profile feedback, and 10.75 s with Zaparoo stopped.
  - What was faster on x86 was slower on the A9: a switch dispatch with the handlers inlined took
    34.1 s, against 26.7 s for a member-function table.
- **Check the emulated clock before porting it.** On HNG64, MAME's V53A clock was the input crystal,
  not the input over 2. Ported as MAME had it, it needed 1.5 ARM cores; at 16 MHz it fits and keeps
  up (HNG64 LESSONS_LEARNED, "Check a MAME CPU device's clock divider"; `MAME_KLUDGES.md`).
- **Write audio in batches.** Writing 5 ms at a time cut the time outside the emulator from 9% to
  3-4% of the CPU (HNG64 `ROADMAP.md` Phase 4).
- **The DDR3 port is shared with the core's other masters.** Reset must drain it.
  - A burst cut by the core's reset hung the f2sdram port (`sys/f2sdram_safe_terminator.sv`).
  - The hang survived core loads: every core loaded after it hung, until a reboot.
  - When DDRAM hangs, relaunch the last good core before bisecting (Hornet LESSONS_LEARNED, "Drain
    the DDR3 port on reset", "A broken f2sdram port survives core loads").
- **Build the bench before the board.**
  1. Build the server's emulator natively.
  2. Drive it from a MAME capture: the RAM at the enable, the main CPU's writes and their times,
     the ROMs.
  3. Compare its output with MAME's `-wavwrite`.
  4. Then test the bridge in `sim/`, then the board.

  For fatfurwa, the HNG64 bench matched MAME on the first 91,391 sound-CPU I/O accesses and on all
  94 mailbox values; its 10 ms level envelopes correlated 0.9996 with MAME's or better
  (`scripts/snd_compare.py`).

## Adding a board to the server

The server's README, "Adding a board":
1. A session is `<board>_claims(setname)` and `<board>_run(mem, verbose)` in `src/server.cpp`'s
   dispatch.
2. Give the board a magic and a version in `docs/PROTOCOL.md`.
3. Keep `src/common/` (the `/dev/mem` mapping, the core-name watch, audio pacing) shared.
4. Record each MAME file and what was changed in `PROVENANCE.md`.
5. Releasing the server is a release like a core's: a dated zip in `releases/`, then the Downloader
   database update.
