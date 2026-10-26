# Writing a CPU core from MAME's interpreter

For a CPU with no usable open RTL. Worked example: the Hyperstone E1-16/E1-32
(`Arcade-Vamphalf_MiSTer`, `rtl/e1/e1_cpu.sv`). Everything here was learned there; evidence is in that
repository's `docs/` and commit history.

Check first that none exists: ask which boards carry the chip and whether any core was built for
them (LESSONS_LEARNED, "A web search returning nothing is not evidence that nothing exists"). The
coverage data in `MiSTer-MAME-Coverage/docs/data/coverage.json` lists every MAME driver by CPU and
whether a core covers it.

## Source of truth

- **Read the whole interpreter, not the opcode file alone.** The per-instruction work is in the
  `*op.hxx`, but the architecture lives in the CPU `.cpp`: reset, `execute_run`, exceptions,
  interrupts, `set_global_register`, delay-slot handling. The E1's `execute_run` has a block *after*
  the opcode switch (ILC and P update on every instruction, trace exception) that the opcode file
  does not show; missing it showed up as the first SR mismatch.
- **MAME runs a dynamic recompiler by default.** Reference traces must come from the interpreter:
  run MAME with `-nodrc`, and the debugger instruction hook only fires there.
- **Transcribe the quirks and mark them.** Examples that were wrong in the manual's terms and right
  in MAME's: a first-instruction ILC computed once from a table, a halfword count subtracted from a
  byte PC in the delay-slot exception path, a source register read after a pointer update, a flag
  that sets P on every instruction except RET. Each gets a `MAME:` comment so a later reader does not
  fix it.
- Keep the version question open: the source tree may be newer than the binary. `git log` the CPU
  directory between the binary's tag and HEAD and record whether behaviour changed.

## Verification, in this order

1. **A per-instruction trace from MAME** (debugger `trace` with a `tracelog` action plus memory taps),
   state before every instruction: PC, SR, every register, and each bus access tagged with the
   instruction index. Write the format down (`docs/E1_TRACE_FORMAT.md` there).
2. **A bench that replays it** (Verilator, own `main.cpp`): serve instruction fetches from the words
   in the trace, replay data reads in order, check every write and read the RTL issues against the
   trace, compare the full register state after every instruction. Run it with 0 and a few wait
   states; handshake bugs show only there. The bench must detect the interrupts MAME took (the trace
   shows the PC jumping to the vector) and raise the line itself.
3. **Do not stop at the boot trace.** 1,000,000 instructions of the game's boot executed 76 of 256
   opcodes. A seeded random-program generator that covers every opcode (all operand forms, extension
   words, delay slots, exceptions, user and trace modes, spill/fill, interrupts) with MAME as the
   oracle found three real RTL differences and a missing opcode group that the boot never touched. Build
   it as soon as the boot trace passes: generator, scratch ROM with the bad checksum (MAME runs it),
   trace, bench, summary grouped by mnemonic. The generator needs care for MAME's own traps (a
   trap handler that is a bare return loops on trace exceptions).
4. Report coverage as "N of M primary opcodes executed", from the traces.

Bench pitfalls met: a `// verilator ...` banner comment is parsed as a pragma; a custom `main.cpp`
needs `double sc_time_stamp()`; a debugger-driven MAME trace occasionally credits an instruction with spurious reads, so
the regression re-traces once before calling it a failure.

## Structure that synthesizes

The first version (tasks called at every site, direct array writes everywhere) matched MAME and did
not fit: the fitter reported 196,629 combinational nodes against 83,820 in the device. Cause: every
call site of a register-write task is its own decoder and data mux into the register arrays, and every
indexed read is its own mux. What to do from the start:

- **One write path.** Instructions push register writes into a small queue; one `commit_one` at the
  end of the cycle writes one entry per clock into the arrays. That single write site is also what
  lets Quartus infer RAM (MLAB or M10K) instead of flip-flops. Double-register results cost one extra
  clock; no instruction needed more than five.
- **Push the queue under constant indices.** The E1's push was `q[cnt] = v; cnt = cnt + 1;` in a task,
  twice in one clock (a CALL's return address and SR). Verilator kept both; on the board the first
  never arrived, the first RET jumped to 0 and the screen stayed black through every simulation.
  Write each entry from a `case` on the count, and keep the queue out of RAM (`ramstyle "logic"`;
  Quartus had also made it a one-write-port altsyncram).
- **One exception/trap/interrupt entry.** Sites request (`req_exc(trapno)`), a single state applies
  the frame. Anything that continues after an exception in MAME (a return that refills the register
  window with the new frame pointer) is sequenced explicitly.
- **One completion path.** Instructions set `fin_req`; the common tail runs the post-instruction
  update, the trace-exception check and the retire pulse, after the write queue has drained.
- **Fixed read ports**, not an index expression at every use: source, source+1, destination,
  destination+1, and one absolute-index port.
- Share one adder, one shifter, one multiplier among instructions by selecting operands, not by
  instantiating per opcode. (Not yet done in the E1; measure first.)
- Keep a blocking-variable style inside a single clocked block if you want the interpreter's
  statement order; compute the next state in a blocking variable and assign `state <=` once at the
  bottom.

Run `quartus_map` on the bare CPU (`scripts/synth_check.py`, virtual pins, the clock constraint)
before writing the rest of the core. Phase 0 criterion 4 is this number.

## Other notes

- A mixed-sign conditional (`c ? $signed(x) >>> n : x >> n`) makes the whole expression unsigned and
  turns the arithmetic shift into a logical one. Use functions with a signed local.
- Bring the timer in with an explicit `tick` input, not instruction counts; MAME's timer is driven
  by cycles and a trace has none. State that the bench ties it low.
- Gaps go in `docs/HACKS.md` the day they are written (unmodelled power-down, timer approximation).
- Speed: a multi-cycle design at 5.2 clocks per instruction (boot trace, zero-wait bus) is the
  correctness baseline, not the target. Decide the clock plan from the measured instruction rate the
  game needs, not from MAME's icount.

## Timing and CPI, in the order they paid off (E1)

Standalone fit of the CPU alone, Cyclone V slow 100C corner, 56 MHz constraint:

| Step | Fmax |
|---|---|
| first working version (writes and reads expanded at every call site) | did not fit |
| write queue, one exception entry, MLAB register file | 40.4 MHz |
| commit moved to the cycle after the instruction | 45.7 MHz |
| operand read in its own state, multiplies in two registered stages | 67.7 MHz (7.15 clk/instr) |
| fetch folded into the end of EXEC, prefetch, bypass: CPI to 2.71, Fmax fell to 51-55 MHz | |
| each remaining path cut (below) | 58.5 MHz (2.71 clk/instr) |

What the long paths turned out to be, so the next CPU can avoid them from the start:

- **Anything that writes an architectural register at the end of one state and is read by the next
  state's logic in the same Verilog block is one combinational path.** The synthesizer sees the
  merged next-state net, not the state the code is in. The cuts that worked: split the commit into a
  start-of-cycle part (register file) and an end-of-cycle part (global registers); read the queue head
  into variables at the top of the cycle, before the instruction pushes; give the privilege check to
  the write that causes it instead of the commit; keep PC writes inline.
- **Starting the next fetch in the cycle an instruction ends** (the biggest CPI win, about 1 clock)
  puts the fetch address behind the whole instruction logic. Keep the fetch start in the
  instruction's own branch of the state machine, and do not make it wait for the exception decision:
  start it, and if an exception follows, let the read finish as a prefetch and take the frame from
  copies of the instruction's op and length captured at operand read.
- **Interrupts are sampled where the instruction is committed to run** (operand read), not at a
  separate boundary state. A bench that injects the line then has to raise it while the previous
  instruction executes, from a one-record lookahead of the trace (`execute_int` leaves FL=2 and sets I;
  a trap instruction to the same address leaves FL=6).
- **A 64-entry register file with five read ports is five MLAB copies**; one write port forces the
  write queue. One pending local write can be bypassed at operand read; two cannot without breaking
  the retire ordering the bench relies on. Pointer-update writes pushed at the start of a load, not
  after its data, removed the two-entry case from post-increment loads.
- Measure CPI by state with a per-state cycle count in the bench, and by queue depth at operand read;
  the two-entry case showed up as one mnemonic (LDW.P).
