#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Diff the RTL CPU's boot against MAME's. Phase 0.

    python scripts/compare_boot_trace.py replay  <set> [--sys]   # MAME's I/O reads -> replay file
    python scripts/compare_boot_trace.py compare <set> [--sys] [--rtl PATH]
    python scripts/compare_boot_trace.py dups    <set> [--rtl PATH]   # RTL writes made twice in a row

Inputs: debug/<set>-boot/<set>_boot.trace (scripts/mame_boot_trace.py), or with --sys
debug/<set>-sys/<set>_sys.trace (scripts/mame_sys_trace.py: writes and I/O only, for boots too
long to log every access), and <set>_rtl.trace beside it (or --rtl), written by the boot bench in
the same "seq rw addr mask data" format: bus-aligned address, byte-lane mask. Ranges come from
regions.json "trace" (with the set's "sets" overlay), lists of [lo, hi] hex strings, inclusive:

  "rom", "ram"     ROM and work RAM; everything else is I/O and is replayed.
  "internal"       CPU-internal registers MAME's tap sees and the external bus never does (an
                   SH-2's on-chip map); dropped from both traces.
  "vectors"        [lo, hi]: a read there marks an interrupt taken. replay writes the write count
                   at each to <set>_irq.txt, so the bench raises its interrupt where MAME took it.
  "irq_pushes"     writes the exception entry makes before it reads the vector (an SH-2 pushes
                   SR and PC: 2), subtracted from those counts.
  "data_cache"     true for a CPU with a data cache: it reads RAM when it misses and MAME's
                   reads it every time, so RAM reads are checked as a superset, like ROM, and
                   only reads are merged by merge_halves().

Written for a 32-bit bus; merge_halves() handles a CPU that splits accesses in two.

WHAT IS COMPARED, AND WHAT IS NOT

  * WRITES, strictly, in order: address, lanes, and data under the mask. This
    is the strong check. A CPU that executes the same program correctly makes
    the same writes with the same data in the same order, whatever it does
    with the bus in between.
  * NON-ROM READS, in order: these are the replayed I/O reads. A mismatch means
    the RTL asked a peripheral a different question from MAME's CPU. Both sides
    end at the same write.
  * ROM FETCHES, as a superset only. A prefetching CPU core and MAME's do
    not, so two correct CPUs read the same words in different orders and the
    RTL reads words MAME never asks for (LESSONS_LEARNED, "[Seta] Two cores
    that both boot correctly still fetch different words, so compare as a
    subsequence with duplicates collapsed"). What is checked is that every ROM
    word MAME read inside the RTL's window, the RTL also read.

The RTL trace is shorter than MAME's by design; it is compared up to the
number of writes it reached.
"""
import argparse
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("CORE_ROOT") or Path(__file__).resolve().parent.parent)  # the MCP sets CORE_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parent))   # mame_capture beside this one
from mame_capture import regions  # noqa: E402

ROM, RAM, INTERNAL = [], [], []
VEC = (0, 0)
IRQ_PUSHES = 0
DATA_CACHE = False


def set_ranges(game):
    global VEC, IRQ_PUSHES, DATA_CACHE
    t = regions(game).get("trace", {})
    for dst, key in ((ROM, "rom"), (RAM, "ram"), (INTERNAL, "internal")):
        dst[:] = [(int(lo, 16), int(hi, 16)) for lo, hi in t.get(key, [])]
    VEC = tuple(int(v, 16) for v in t.get("vectors", ["0", "0"]))
    IRQ_PUSHES = int(t.get("irq_pushes", 0))
    DATA_CACHE = bool(t.get("data_cache", False))


def load(path):
    rows = []
    for ln in open(path, encoding="utf8"):
        if ln.startswith("#") or not ln.strip():
            continue
        try:                                   # a sys trace adds an ipl column
            seq, rw, a, m, d = ln.split()[:5]
            seq, a, m, d = int(seq), int(a, 16), int(m, 16), int(d, 16)
        except ValueError:
            continue                           # a line cut short by a stopped run; the rest is valid
        if any(lo <= a <= hi for lo, hi in INTERNAL):
            continue
        rows.append((seq, rw, a, m, d & m))
    return rows


def merge_halves(rows):
    """Join two consecutive accesses to the same dword into one.

    A CPU narrower than the bus splits a wide access in two, and MAME's tap may
    report one side split and the other whole (on KonamiGX: instruction fetches
    split, data accesses whole). Unmerged, the traces fall one entry out of step
    at every such access, which also skews the write-count comparison window.
    Both sides are normalised the same way: an adjacent pair with the same
    direction, the same aligned address and disjoint lanes becomes one access.
    With "data_cache", reads only: such a CPU writes a halfword pair as two
    accesses on both sides, and the RTL's pair sits adjacent when the fetches
    between them hit its cache.
    """
    out = []
    for r in rows:
        if out:
            s0, rw0, a0, m0, d0 = out[-1]
            _, rw1, a1, m1, d1 = r
            if rw0 == rw1 and (rw0 == "r" or not DATA_CACHE) and a0 == a1 and not (m0 & m1):
                out[-1] = (s0, rw0, a0, m0 | m1, d0 | d1)
                continue
        out.append(r)
    return out


def is_rom(a):
    return any(lo <= a <= hi for lo, hi in ROM)


def is_ram(a):
    return any(lo <= a <= hi for lo, hi in RAM)


def is_io(a):
    return not is_rom(a) and not (DATA_CACHE and is_ram(a))


def ref_paths(game, sys_trace):
    """(directory, MAME trace)."""
    if sys_trace:
        base = REPO / "debug" / f"{game}-sys"
        return base, base / f"{game}_sys.trace"
    base = REPO / "debug" / f"{game}-boot"
    return base, base / f"{game}_boot.trace"


def cmd_replay(game, sys_trace=False, rtl_path=None):
    """MAME's I/O reads, in order, and with "vectors" the write count at which each interrupt
    was taken (LESSONS, "[Silkroad] Raise a boot bench's interrupt where MAME took it")."""
    base, mame = ref_paths(game, sys_trace)
    out = base / f"{game}_replay.txt"
    irqs = []
    n = writes = 0
    with open(out, "w", encoding="utf8") as f:
        for seq, rw, a, m, d in load(mame):
            if rw == "w":
                writes += 1
            elif VEC[1] > VEC[0] and VEC[0] <= a <= VEC[1]:
                irqs.append(writes - IRQ_PUSHES)
            elif not is_rom(a) and not is_ram(a):
                f.write(f"{a:06X} {m:08X} {d:08X}\n")
                n += 1
    print(f"{n} I/O reads -> {out}")
    if VEC[1] > VEC[0]:
        irq = base / f"{game}_irq.txt"
        irq.write_text("".join(f"{w}\n" for w in irqs), encoding="utf8")
        print(f"{len(irqs)} interrupts -> {irq}")
    return 0


def cmd_compare(game, sys_trace=False, rtl_path=None):
    base, ref = ref_paths(game, sys_trace)
    raw_mame = load(ref)
    raw_rtl = load(rtl_path or base / f"{game}_rtl.trace")
    if not raw_rtl:
        sys.exit("the RTL trace is empty -- did the bench run?")
    mame = merge_halves(raw_mame)
    rtl = merge_halves(raw_rtl)
    print(f"merged split halves: MAME {len(raw_mame)} -> {len(mame)} accesses, "
          f"RTL {len(raw_rtl)} -> {len(rtl)}")

    mw = [(a, m, d) for _, rw, a, m, d in mame if rw == "w"]
    rw_ = [(a, m, d) for _, rw, a, m, d in rtl if rw == "w"]
    rc = 0

    # --- writes, strictly in order
    n = len(rw_)
    first = next((i for i in range(min(n, len(mw))) if rw_[i] != mw[i]), None)
    if first is None and n <= len(mw):
        print(f"WRITES    {n} of {n} match MAME in address, lanes, data and order")
    else:
        rc = 1
        if first is None:
            print(f"WRITES    the RTL made {n} writes, MAME only {len(mw)} in its trace")
        else:
            print(f"WRITES    MISMATCH at write {first + 1} of {n}:")
            for i in range(max(0, first - 3), min(first + 4, n, len(mw))):
                flag = "  <--" if i == first else ""
                a1, m1, d1 = mw[i]
                a2, m2, d2 = rw_[i]
                print(f"    #{i + 1:<6} MAME {a1:06X} {m1:08X} {d1:08X}   "
                      f"RTL {a2:06X} {m2:08X} {d2:08X}{flag}")

    # How far into MAME's trace does the RTL's progress reach? Up to the
    # MAME access that made the RTL's last write.
    wseen = 0
    mame_cut = len(mame)
    for i, (_, rw, *_rest) in enumerate(mame):
        if rw == "w":
            wseen += 1
            if wseen == n:
                mame_cut = i + 1
                break
    window = mame[:mame_cut]

    # --- non-ROM reads, in order. The RTL side also ends at its last write: a CPU spinning on
    # a poll after it would otherwise be compared against a MAME window that stops before it.
    rtl_cut = max((i + 1 for i, r in enumerate(rtl) if r[1] == "w"), default=len(rtl))
    mio = [(a, m, d) for _, rw, a, m, d in window if rw == "r" and is_io(a)]
    rio = [(a, m, d) for _, rw, a, m, d in rtl[:rtl_cut] if rw == "r" and is_io(a)]
    k = min(len(mio), len(rio))
    bad = next((i for i in range(k) if mio[i] != rio[i]), None)
    if bad is None and len(mio) == len(rio):
        print(f"I/O READS {len(rio)} of {len(rio)} match MAME in order")
    else:
        rc = 1
        print(f"I/O READS MAME {len(mio)}, RTL {len(rio)}; first difference at "
              f"{bad + 1 if bad is not None else k + 1}")

    # --- ROM fetches (and with "data_cache" RAM reads), superset
    what, col = ("ROM and RAM", "ROM/RAM") if DATA_CACHE else ("ROM", "ROM")
    mrom = {(a, m) for _, rw, a, m, d in window if rw == "r" and not is_io(a)}
    # Coverage is per BYTE LANE, not per (address, mask) pair: the RTL may have
    # read a whole dword where MAME read one half, or two halves where MAME
    # read the dword, and either way the lanes MAME asked for were read.
    rlanes = {}
    for _, rw, a, m, d in rtl:
        if rw == "r" and not is_io(a):
            rlanes[a] = rlanes.get(a, 0) | m
    def covered(a, m):
        return (m & ~rlanes.get(a, 0)) == 0
    missing = [x for x in mrom if not covered(*x)]
    if missing:
        rc = 1
        missing.sort()
        print(f"{col:9s} {len(mrom) - len(missing)} of {len(mrom)} MAME {what} reads were also "
              f"made by the RTL; first missing: {missing[0][0]:06X} {missing[0][1]:08X}")
    else:
        print(f"{col:9s} every one of MAME's {len(mrom)} distinct {what} reads in the window "
              f"was also made by the RTL")

    print(f"\nwindow: RTL {len(rtl)} accesses, MAME {mame_cut} accesses to the same "
          f"write ({n} writes)")
    return rc


def cmd_dups(game, sys_trace=False, rtl_path=None):
    """Writes the RTL made twice in a row (same address, lanes and data), and what came
    before each pair: a census for a CPU that re-issues a bus beat."""
    base, _ = ref_paths(game, sys_trace)
    rows = load(rtl_path or base / f"{game}_rtl.trace")
    writes = sum(1 for r in rows if r[1] == "w")
    dups = 0
    before = {}
    for i in range(1, len(rows)):
        _, rw, a, m, d = rows[i]
        _, rw0, a0, m0, d0 = rows[i - 1]
        if rw == "w" and rw0 == "w" and (a, m, d) == (a0, m0, d0):
            dups += 1
            prev = rows[i - 2][1] if i >= 2 else "-"
            k = "ram" if is_ram(a) else "rom" if is_rom(a) else "io"
            key = f"{k} write after a {'write' if prev == 'w' else 'read'}"
            before[key] = before.get(key, 0) + 1
    print(f"{writes} writes, {dups} of them an immediate repeat of the previous write")
    for k, n in sorted(before.items()):
        print(f"  {n:7d}  {k}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["replay", "compare", "dups"])
    ap.add_argument("game")
    ap.add_argument("--sys", action="store_true",
                    help="against debug/<set>-sys/<set>_sys.trace (writes and I/O only)")
    ap.add_argument("--rtl", type=Path, help="RTL trace (default <set>_rtl.trace beside MAME's)")
    a = ap.parse_args()
    set_ranges(a.game)
    return {"replay": cmd_replay, "compare": cmd_compare, "dups": cmd_dups}[a.cmd](a.game, a.sys, a.rtl)


if __name__ == "__main__":
    sys.exit(main())
