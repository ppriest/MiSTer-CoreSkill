# Savestates, state dumps, and replaying state in simulation

Optional to ship, but **designed for from the first RTL**, because retrofitting it is what makes it
expensive. Two deliverables, and the second is worth more during development than the first:

1. **Savestates** through the MiSTer API: save and restore a running game on the board.
2. **A state dump to a file on disk**, in a format the simulators can load, so a bug seen on
   hardware is reproduced in a bench at the exact frame it went wrong.

The worked study behind this is the Psikyo core's `docs/savestates.md` (302 lines): a per-core
feasibility analysis with a verdict, tiers and a phasing table. Write the same document for a new
core before starting, and keep the verdict honest.

## Design for it from the start

None of this needs implementing early. It needs the state to be *reachable*:

- **Every RAM is read and written through a port the engine can borrow.** The pause-and-borrow
  pattern is already proven by `hiscore.v`, which pauses the CPU and uses the CPU's own port; a
  savestate engine is that generalised to every RAM. Register the read data beside the RAM or the
  mux lands on the critical path (Psikyo: ~300 failing endpoints otherwise).
- **State that survives a frame is named, and listed as it is written.** Keep a running
  `docs/STATE.md` inventory: every RAM with its size, every register or FSM that is not re-derived
  each frame, and the ones deliberately skipped (ROM tables from the `.mra`, snapshots regenerated
  at `frame_start`). Written as you go it costs minutes; reconstructed later it is a hunt.
- **Prefer a vendored module that already has a state port.** T80 exposes its whole architectural
  state (`REG` out, `DIR`/`DIRSet` in); the N64 core's VR4300 carries `SS_*` ports. Where a module
  has none, the wrapper does the work, not a fork: for a 68k, halt at an instruction boundary and
  substitute an instruction stream that makes the CPU dump its own registers (`MOVEM`, `MOVEC`, an
  exception frame for PC and SR), restoring through the mirror ending in `RTE`. Snapshot RAM
  *before* running such a stub: the exception frame perturbs the stack.
- **A chip written from MAME keeps its state in a register file, not in circulating shift
  registers.** This is the one decision that cannot be undone cheaply. jt12 circulates per-slot FM
  state through shift registers so one operator pipeline serves every slot, which is excellent
  hardware and unaddressable state: dumping it means forking three modules of a battle-tested core.
  When writing a chip yourself, an addressable array costs nothing now and decides whether exact
  audio restore is ever possible.
- **Save the double-buffer phase**, not just the buffers: restore the wrong bank and the first frame
  after load shows the previous frame's sprites.

## What "meaningful" means: MAME's own save lists

MAME saves in three places, and they map onto the difficulty gradient:

| MAME | The core's equivalent | Difficulty |
|---|---|---|
| `save_item` in the driver's `machine_start` | named registers and FSMs | trivial |
| automatically registered memory shares | RAM walks | easy, precedent exists |
| each device's own save list | CPU and sound-chip internals | the actual work |

The driver's `save_item` list is a ready-made checklist, and where the RTL was written from MAME's
model it is often 1:1 with it. It tells you *which chip facts* matter (envelope phase, step index,
accumulator); it does not tell you where a vendored module keeps them.

## The framework API

Thinner than the name suggests, per the MiSTer developer docs
(<https://mister-devel.github.io/MkDocs_MiSTer/developer/savestates/>):

- The core declares `SS<base>:<size>` in `CONF_STR`, base conventionally in the DDR3 range.
- **Four slots**, a firmware limit.
- Each slot opens with a 64-bit control word: the low half is a change detector the core pokes to
  have the slot persisted, the high half is the size in 32-bit words.
- **It reserves and persists a DDR3 region and serialises nothing.** There is no scan chain and no
  helper in `sys/`; all capture and restore logic is the core's.

DDR3 is already contended: the HDMI rotator owns a region, the ROM loader borrows the bus, and
savestates are a third master, so the two-way mux becomes a real arbiter. Check the collisions and
record them in the memory-map document (`sdram_ddr_maps.md`).

Payload size is usually modest because SDRAM holds only ROM and is read-only at run time: Psikyo's
whole inventory is about 200 KB, dominated by work RAM.

## The dump file, and why it is the useful half

One format, three consumers: the DDR3 slot on hardware, a file on the PC, and the simulators.

- **Self-describing.** A header with a magic number, format version, core name, set name, the build
  commit and the frame number, then a manifest of sections: name, kind (`ram`, `regfile`, `regs`),
  element width, depth, byte order. Then the payload. A state whose provenance is unknown is a
  liability; a state that names the commit it came from can be rejected when the RTL has moved on.
- **A script pulls and pushes it** (`scripts/state.py`, per core, not yet in this skill): dump from
  a running core over the existing debug path, or read the persisted slot back off the device, and
  push a modified one in. Nothing new is needed on the RTL side beyond the engine itself.
- **Round-trip it as a test:** dump, restore, dump again, and compare. A section that differs is
  either missing from the manifest or captured at the wrong moment, and this finds it before a
  player does.

## Loading state into the simulators

This is the payoff during development: a hardware bug becomes a deterministic bench.

- **Generate per-section fixtures.** `state.py --to-sim <dir>` writes one `.hex` per section in the
  width the RTL declares, plus a small `state.f` listing them. ModelSim benches load them with
  `$readmemh` at time 0, exactly as the ROM fixtures already do (paths resolve against the
  simulator's working directory, so run from the repo root).
- **Restore the registers through the same port the engine uses**, driven by the bench rather than
  by DDR3. The bench asserting a `ss_restore` sequence is the same logic the board runs, which keeps
  one implementation rather than a simulation-only back door.
- **Verilator reads the blob directly.** A bench with its own `main.cpp` parses the manifest and
  fills each model memory before the first clock, then runs N frames. Pair it with Verilator's own
  save/restore (`--savable`) to fast-forward: restore state, run to the frame before the glitch,
  snapshot the model, and iterate on that in seconds.
- **Compare both directions.** A bench can also *write* the format, so a state dumped in simulation
  and a state dumped from the board at the same frame are diffable section by section. That is the
  cheapest way to localise a divergence to one RAM.
- **Aim restore at a frame boundary** in benches as on hardware, or the first frame differs for
  reasons that have nothing to do with the bug.

## Verification and honesty

- **A deliberate save, restore and compare test in simulation**, not only by playing. Savestates
  amplify correctness errors: state nobody saved is invisible until a player loads and something is
  subtly wrong ten seconds later.
- **A/B driver-level fields against a MAME savestate** of the same moment.
- **Exit criterion:** save mid-game, reset the core, load, and continue with score, lives and enemy
  positions intact, on every supported set.
- **Tiers are legitimate; hiding them is not.** Where a vendored sound core cannot be dumped, Tier 1
  restores the chip's register file and replays it as the game's own driver would after a reset:
  notes held across the save point re-attack, so the player hears a fraction of a second of wrong
  audio. Say so in the README, or it is reported as a bug, reasonably. Bit-exact continuity (Tier 2)
  is what rewind and netplay would need.
- **Budget a timing pass.** A savestate engine adds a wide mux on every BRAM port and another DDR3
  master. Expect the seed lottery to get worse before it gets better.
