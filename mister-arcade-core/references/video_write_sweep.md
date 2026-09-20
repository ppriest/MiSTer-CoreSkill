# Video write sweep: recording when a game writes its video chips, in MAME

Survey of the Seta core (primary), cross-checked against Fuuki, Psikyo,
JalecoMS32 and KonamiGX. `build/` ignored. All pointers absolute `file:line`.

Scope note: `scripts/mame_subtrace.py`, `scripts/flip_shots.py` and
`scripts/phase_sweep.py` were read as asked but are not part of this topic
(6502 trace census, MiSTer flip screenshots, SDRAM phase eye). `flip_sweep.py`
touches it only through `vregs()` (reads a `_writes.log`). Not covered further.

---

## 1. What the sweep records

Three Seta tools, one per question. All are MAME Lua autoboot scripts driven by
a Python wrapper; regions come from `mame_capture.py`'s `FAMILIES` table.

### 1a. `write_timing.py` + `mame/wtiming.lua` — histogram of writes by scanline

**Regions.** Seven named ranges, filtered from the family's region map:
the Seta core's `scripts/write_timing.py:23`
```
REGIONS = ("sprylow", "sprctrl", "sprcode", "l0vram", "l1vram", "l0ctrl", "l1ctrl")
```
Tap string built at `write_timing.py:35-37`:
```
regions = FAMILIES[GAMES[game]][0]
taps = ",".join(f"{r}:{lo:06x}:{lo + ln - 1:06x}" for r, (lo, ln) in regions.items() if r in REGIONS)
```
A family without one of the names (Group A has no layers) simply does not tap it.

Example address map (one family), the Seta core's `scripts/mame_capture.py:86-92`:
```
"l0vram":    (0x800000, 0x004000),
"l1vram":    (0x880000, 0x004000),
"l0ctrl":    (0x900000, 0x000006),
"l1ctrl":    (0x980000, 0x000006),
"sprylow":   (0xa00000, 0x000600),
"sprctrl":   (0xa00600, 0x000008),
"sprcode":   (0xb00000, 0x004000),
```
Other families at `mame_capture.py:138-144, 154-160, 178-182, 192-197, 207-211, 220-222, 228-230, 238-240, 247-249, 257-259, 266-268, 281-283`.

**Tap install**, the Seta core's `scripts/mame/wtiming.lua:60-68`:
```lua
local tap = prog:install_write_tap(lo, hi, "wt_" .. name, function(offset, data, mask)
    if counting then
        local l = cur_line()
        hist[name][l] = (hist[name][l] or 0) + 1
        frame_last[name] = l
    end
    return data
end)
_G.__wt_taps[#_G.__wt_taps + 1] = tap
```
`prog` is `mach.devices[":maincpu"].spaces["program"]` (`wtiming.lua:21-22`).
The tap is kept in a global so the GC does not collect it (`scripts/README.md:146-148`).

**Scanline source.** Not `screen:vpos()` — MAME 0.286's Lua screen binding has
no `vpos()`/`hpos()`; calling them inside a tap raises an error MAME swallows
(the Seta core's `scripts/mame/capture.lua:157-164`). Derived from
`time_until_pos` instead, `wtiming.lua:31-41`:
```lua
local frame_period = 1.0 / scr.refresh
local line_period
for _ = 1, 64 do
    local d = scr:time_until_pos(1) - scr:time_until_pos(0)
    if d > 0 and (line_period == nil or d < line_period) then line_period = d end
end
local vtotal = math.floor(frame_period / line_period + 0.5)
local function cur_line()
    return math.floor((frame_period - scr:time_until_pos(0)) / line_period + 0.5) % vtotal
end
```
`vtotal` comes out as MAME's declared height (256), not the RTL's 272
(`capture.lua:172-175`).

**Vblank start.** Not read from MAME; taken as the mode of `cur_line()` sampled
in `frame_done` over frames 11..SKIP (`wtiming.lua:43-48, 92-102`).
`time_until_vblank_start` from an autoboot script crashed MAME 0.285
(`wtiming.lua:46`).

**Frame / vblank phase.** No hpos, no per-write frame number. Counting starts at
frame SKIP and ends at SKIP+FRAMES (`wtiming.lua:96, 110`). Per frame, the last
write line of each region is binned separately (`wtiming.lua:103-109`).
Optional coin/Start/P1-Right/Button-1 stimulus (`wtiming.lua:84-91`).

**Raw output** `debug/wtiming/<set><tag>.txt` (`wtiming.lua:112-121`):
```
vtotal 256
vbstart 240
frames 1800
hist <region> c0,c1,...,c255      -- writes per MAME line, absolute line numbers
last <region> c0,c1,...,c255      -- frames whose last write to the region fell on that line
```
(one `hist` and one `last` row per region; verified against `debug/wtiming/madshark.txt`).

**MAME command line**, the Seta core's `scripts/write_timing.py:40-47`:
```
MAME_EXE <game> -skip_gameinfo -nodebug -nothrottle -sound none -video none -nowindow
    -autoboot_delay 0 -autoboot_script scripts/mame/wtiming.lua
    -rompath <rompath> -snapshot_directory debug/wtiming/snap<tag> -snapview native
env: WT_OUT WT_TAPS WT_SKIP WT_FRAMES WT_COIN WT_SNAP=1
```
`cwd=MAME_DIR`, `timeout=3600`. A snapshot is taken at the last counted frame
(`wtiming.lua:111`) so the report can say what scene the count ended in.

### 1b. `sprctrl_scan.py` + `mame/sprctrl.lua` — the four X1-001 control bytes

One tap on the 8-byte control block, the Seta core's `scripts/mame/sprctrl.lua:45-61`:
```lua
_G.__sc_tap = prog:install_write_tap(BASE, BASE + 7, "sprctrl", function(offset, data, mask)
    local idx = math.floor((offset - BASE) / 2)
    local d = data & 0xff
    if mask & 0xff == 0 then d = (data >> 8) & 0xff end
    if counting then
        nwrite = nwrite + 1
        vals[idx][d] = (vals[idx][d] or 0) + 1
        if idx == 1 and (d & 0x20) ~= 0 and ctrl[1] ~= nil
           and ((d ~ ctrl[1]) & 0x40) ~= 0 then
            local l = cur_line()
            flips[l] = (flips[l] or 0) + 1
            nflip = nflip + 1
        end
    end
    ctrl[idx] = d
    return data
end)
```
Same `cur_line()` derivation (`sprctrl.lua:25-34`). Records: value histogram per
byte, frames with byte 1 bit 5 set (copy disabled), and every write that flips
bit 6 (the drawn half) with bit 5 set, by scanline.

Raw output `debug/sprctrl/<set>.txt` (`sprctrl.lua:74-92`):
```
vtotal 256
frames 601
writes 2296
flips 574
bit5frames 601
val <byte> <hex> <count>
flip <line> <count>
```
(verified against `debug/sprctrl/stg.txt`: `flip 113 574`.)
Command line at the Seta core's `scripts/sprctrl_scan.py:32-37` (same as
1a without snapshot options; env `SC_OUT SC_BASE SC_SKIP SC_FRAMES SC_COIN`).

### 1c. `mame_capture.py --wlog` + `mame/capture.lua` — per-write log with PC

Per-write, not a histogram. Tap at the Seta core's `scripts/mame/capture.lua:213-224`:
```lua
local tap = prog:install_write_tap(lo, hi, "setawr", function(offset, data, mask)
    tap_hits = tap_hits + 1
    local ok, err = pcall(function()
        wlog:write(string.format("%d\t%d\t%06X\t%04X\t%08X\n",
            scr:frame_number(), cur_line(), offset, data & 0xFFFF,
            cpu.state["PC"].value))
    end)
    if ok then tap_logged = tap_logged + 1
    elseif not tap_err then tap_err = tostring(err) end
    return data
end)
```
Columns (`capture.lua:203`): `# frame\tscanline\taddr\tdata\tpc`. Header line
`# vtotal N, derived from time_until_pos` (`capture.lua:201`). Every callback is
`pcall`-wrapped with hits and logged counters, because a tap error is swallowed
(`capture.lua:208-212`; `scripts/README.md:150-154`). Default taps are the
family's control registers only; `--tap LO:HI` adds ranges
(`mame_capture.py:354-358`). Output `debug/<name>/<set>_writes.log`.

`debug/stg-sprlog/stg_writes.log` is one such log (header verified). No script
in the repo turns it into the 8-line-per-column strip quoted in
`docs/MAME_DIVERGENCE.md:170-175`; that rendering step is not in the tree.

### 1d. `mame/vread.lua` — does the game read VRAM back?

Read and write taps per range, with PC histogram on reads,
the Seta core's `scripts/mame/vread.lua:18-27`. Output
`<name> reads N writes M` + `  pc XXXXXX k` (`vread.lua:33-37`). Env
`VR_OUT VR_RANGES VR_FRAMES`. No Python driver found in `scripts/*.py`; run by
hand with `-autoboot_script`. Its result is cited at
`docs/MAME_DIVERGENCE.md:247-249` (Blandia: 12288 reads a layer at boot,
PCs 0x20f2-0x217e).

---

## 2. How it is visualised

Text only. No PNG/plot script exists for any of these outputs.

**`write_timing.py report()`**, the Seta core's `scripts/write_timing.py:63-86`.
Per region, one line:

| column | meaning (from `report()` docstring `:63-68` and code `:78-85`) |
|-|-|
| `/frame` | writes per frame |
| `+0..1` | % of the region's writes in the 2 lines after vblank start |
| `vblank` | % inside MAME's vblank (`vtotal - vbstart` lines) |
| `+0..23` | % in the first 24 lines after vblank start (the core's 272-line frame has 24 lines of vblank) |
| strip | 32 columns of 8 lines each, x axis = lines from vblank start (rotated so column 0 is vbstart); glyph = share of the region's writes: ` ` none, `.` <1%, `0`-`9` tenths, `#` >90% |

The `last` rows are parsed (`:51-60`) but not printed.

The docstring's parenthetical "where the core copies and snapshots sprites"
for `+0..1` predates the current RTL snapshot placement (section 4); read it as
"first two lines after vblank start".

**`sprctrl_scan.py report()`**, `sprctrl_scan.py:54-62`: one line per set —
frames, frames with copy off, flip count, sorted flip lines; then the byte-1
value histogram.

**Hand-drawn strip** for the per-write log: `docs/MAME_DIVERGENCE.md:170-175`
(64 columns of one line each, four rows of 64 lines, digit = writes a frame per
scanline). Produced outside the repo; unverified how.

---

## 3. Observations recorded

### From `docs/write_timing_mame.txt`

Run parameters, the Seta core's `docs/write_timing_mame.txt:1-3`:
```
Attract: write_timing.py --skip 600 --frames 1800 (no coin).
Play: write_timing.py --coin 600 --skip 1500 --frames 1800 --tag _play
```
Six play runs ended out of play (`:4-7`: extdwnhl, jjsquawk, rezon, wrofaero,
blockcar, wits).

Representative rows (attract):

- Group 1, list in the first lines after vblank start — `madshark` `:206-214`:
  `sprylow 543.1 25.6% 99.9% 99.9% |#...|`, `sprctrl 3.0 0.0% 99.9% 99.9% |#0..|`,
  `l0ctrl/l1ctrl 3.0 ... 99.8% |#0..|`. `msgundam` `:113-120`: `sprylow 512.0 23.4% 99.2%`,
  `l0ctrl/l1ctrl 2.0 98.7% 99.6%` (scroll written in the first two lines after vblank).
  `thunderl` `:11-15`: `sprctrl 2.0 100.0%` in the first two lines.
- Group 2, list around line 112, nowhere near vblank — `stg` `:61-67`:
  `sprylow 504.6 0.0% 0.0% 0.0% |               45.  |`, `sprctrl 3.9 ... |               #  |`
  (column 15 = lines 120-127 from vbstart 248 = MAME lines 112-119);
  `gundhara` `:160-168`: l0ctrl/l1ctrl/sprylow/sprctrl all `#` at column 15,
  `l0vram 39.3` and `l1vram 33.8` spread across the whole frame.
  `daioh` `:85-93`, `jjsquawk` `:180-186`, `zombraid` `:226-234` same shape.
- Group 3, `blandia` `:216-224`: `sprylow 520.0 2.8% ... |0   ...   #|` (column 31 =
  the 8 lines before vbstart), `sprctrl`, `l0ctrl`, `l1ctrl` also column 31,
  `sprcode 377.3` columns 2-7 (16-63 lines after vblank start), `l0vram 348.7`.
  Intro run `:520-530`: `sprcode ... |..240.....0000...|`.
- `sprcode` (code/X words) is written across the frame in nearly every set
  (e.g. `rezon :101 |00000000000000000000000000000000|`), unlike Y and control.
- Play vs attract: `stg_play :320-326` `sprcode 177.1 2.4% 8.2% 18.3%` — codes
  straddle vblank in play; `gundhara_play :417-423` `sprcode 737.1 1.5% 7.0% 26.9%`.
- Vblank start is 248 for most sets, 240 for eightfrc, oisipuzl, madshark,
  metafox, arbalest (`:122, :131, :206, :252, :260`).

### From `docs/MAME_DIVERGENCE.md`

- Summary table of the three groups, the Seta core's `docs/MAME_DIVERGENCE.md:452-456`:
  first 24 lines after vblank start, 96-100% (15 sets); around line 112 (14 sets);
  Blandia's Y/control in the 8 lines before vblank, codes after.
- `:458-463`: "Mad Shark, for one, writes over 90% of its Y in the first 8 lines.
  No per-line measurement of the core yet (probe G gives only the last write line)."
- `:401-418` (evidence for board order): Quiz Kokology writes Y, control and
  codes around line 112; Blandia Y/control in the 8 lines before vblank, codes
  after (intro 16-39 lines after; play lines 48-192); Mobile Suit Gundam 23% of
  Y in the first 2 lines; Strike Gunner's codes in play 2.4% first 2 lines, 18%
  first 24; in the ship scene "3942 writes a half in the first 2 lines, frames 300-700".
- Strike Gunner per-write log, `:167-180`: "About 1000 words a frame: sprite Y
  from line 113 to 240, codes on nearly every line, 3-6 a line through vblank
  (192-255) and on into 0-27. The two quiet spans are mid-frame, lines 83-112
  and 139-165. A snapshot takes about a line, so at any fixed line it copies a
  half-written list."
- `sprctrl_scan` result, `:182-196`: stg sets bit 5 and flips bit 6 at line 113
  on 2882 of 3000 frames; 26 of 31 parents flip their own page once a frame;
  table of flip lines (mid-frame: stg 113, zombraid 112, daioh 117/132/229,
  gundhara 118 ...; in vblank: madshark 246-255, downtown 254, thunderl 249 ...).
- Gundhara tile VRAM, `:238-239`: "writes its layers' scroll at lines 112-119
  and tile VRAM right across the frame (MAME, `scripts/write_timing.py gundhara`:
  about 73 words a frame)".
- Reading sprite RAM live was tried and fails on this core, `:221-231`
  (control live: a line of garbage; Y live: lower half a mess; codes live:
  corrupt quarter — "across 3000 frames 322 frames wrote [the displayed half],
  30-62 words at lines 47-76").
- `:146`: "Daioh and Eight Forces write scroll and their sprite list from the
  line-112 handler; rendered live that tore the middle of every frame".

### From RTL comments (Downtown board, not in write_timing_mame.txt)

the Seta core's `rtl/downtown/downtown_board_cfg.sv:249-253` (calibr50):
"flipped at line 249 every frame, Y written from 248 through line 15 (MAME,
900 frames). The usual snapshot at 267 took Y two-thirds rewritten".
`:269-275` (tndrcade): "one sprite list, written from line 248 (Y) through
about line 100 (codes) -- MAME, 900 frames (scripts/write_timing.py tndrcade)".
The `debug/wtiming/calibr50.txt` output exists; these rows are not in the docs file.

### Docs elsewhere

`README.md:35` (26 of 31 flip their own page, copied at the flip);
`README.md:449` points to `MAME_DIVERGENCE.md` and `write_timing_mame.txt`.
`docs/WORKFLOW.md` and `scripts/README.md` do not mention `write_timing.py`
or `sprctrl_scan.py` (grep: no matches); `scripts/README.md:95-96` mentions
only the capture pipeline's scanline-tagged writes.

---

## 4. How the observations fed decisions, and where the RTL implements them

### 4a. Line buffer vs frame buffer — decided BEFORE the sweep, by arithmetic

the Seta core's `docs/ROADMAP.md:763-788`: per-scanline worst case
(512 sprite rows + 2 layers = ~4300 clk of 6144 at 96 MHz) fits; "**double line
buffers** (384 × 9 bits × 2 ≈ 7 Kbit, negligible) rather than a frame buffer
(... 1.7 Mbit, 30% of the device's block RAM)". Contingent on 96 MHz closing.
Acceptance test: the line-buffer overrun counter (`ROADMAP.md:846-851`);
`scripts/video_sweep.py` runs the RTL with the 6100-cycle budget and reports
`line overruns` / `lines cut short` (`video_sweep.py:14-21, 111-117`).
The write sweep did not inform this choice; it informed *when the inputs to
the line renderer are sampled*.

RTL: the Seta core's `rtl/video/x1_001.sv:381-410` (two 512-entry
`{written, pen}` line buffers, `render_bank`/`disp_bank`);
`rtl\video\x1_012.sv:212-229` (tile layer's pair); swap at `line_start`,
rendering two lines ahead (`seta_video_timing.sv:25-28, 43-46, 67-70`;
`docs/LESSONS_LEARNED.md:798-817`). Front-to-back with a written bit so a
cutoff drops the bottom-most sprites (`LESSONS_LEARNED.md:873-889`;
`x1_001.sv:6-9`; `ROADMAP.md:173-175`).

### 4b. Sprite RAM: snapshot timing per board, from the sweep

Principle, `docs/MAME_DIVERGENCE.md:137-140`: MAME draws at vblank from the
state then; the core renders line by line, so every input is held at its
vblank value. Table `:144-150`.

| observation (sweep) | RTL structure | where |
|-|-|-|
| unbuffered boards, list written in first ~24 lines after vblank start | snapshot 5 lines before the frame wraps (`snap_start`), after the handler has written | `seta_video_timing.sv:75-76`; `x1_001.sv:80-81, 268-270` |
| `setac_eof` boards, draw-then-copy (drgnunit, stg, qzkklogy, qzkklgy2, msgundam) | snapshot on the line before vblank (`snap_pre`, 5120 cycles), copy at vblank | `seta_video_timing.sv:77-79`; `x1_001.sv:178-184, 199-223, 268-270`; `MAME_DIVERGENCE.md:378-391` |
| Blandia: Y/control in the 8 lines before vblank, codes after (copy-then-draw, `VIDEO_UPDATE_AFTER_VBLANK`) | copy at vblank, then snapshot (`copy_then_draw`, `eof_done`) | `x1_001.sv:69-70, 185-186, 208, 270`; `seta_board_cfg.sv` (`copy_then_draw`), `MAME_DIVERGENCE.md:383-385` |
| game sets ctrl byte 1 bit 5 and flips bit 6 itself (26 of 31; `sprctrl_scan`) | `page_flip`/`own_flip`: codes copied at the flip from the selected half into the spare shadow (`codesh_lo/hi`, `rbuf`/`wbuf`); Y and control taken at the usual snapshot; engine moves to the new codes when that snapshot lands | `x1_001.sv:225-243, 245-302, 325-343, 345-356`; `MAME_DIVERGENCE.md:198-219` |
| Y written across the whole frame (stg 113-240) | Y is single-buffered and copied at the usual snapshot, never at the flip | `x1_001.sv:233-236, 358-368` |
| list written from vblank start across ~100 lines with no flip / no eof (tndrcade); flip at 249 with Y rewritten through vblank (calibr50) | fixed snapshot line = MAME's draw line (`spr_snap_line` 240 / 248), overriding the usual trigger | `downtown_board_cfg.sv:249-253, 269-275`; `seta_video.sv:166-170, 212`; `x1_001.sv:71-78, 268` |
| CPU write during the copy | hold the snapshot a cycle and re-read (`snap_hold`); write-through to the shadow for the half being copied | `x1_001.sv:249-250, 257, 345-356` |

Verification cited: hardware build table `MAME_DIVERGENCE.md:421-427`
(order per board fixed both Quiz Kokology and Blandia at e92059d); Strike
Gunner attract right at 9d830c7 (`:149`); Mad Shark and Gundhara under slowdown
(`:209-216`).

### 4c. Scroll / bank / mixer registers: latched at vblank (or per line on raster boards)

| observation | RTL | where |
|-|-|-|
| Daioh, Eight Forces, Gundhara write layer scroll from the line-112 handler; live it tore mid-frame | `vctrl[0..2]` latched at `vblank_rise` | `x1_012.sv:59-60, 179-186`; `MAME_DIVERGENCE.md:146` |
| vregs (layer order, sprite-before-top) | `vregs_lat` at `vblank_rise` | `seta_video.sv:348-350` |
| calibr50 writes scroll per line on purpose (MAME comment: chip reads scroll every scanline) | `raster` boards latch at every `line_start` and a scroll/bank write releases queued VRAM writes | `x1_012.sv:61-67, 150-154, 181`; `downtown_board_cfg.sv:246` (`tile_raster = 1`) |

Internal inconsistency in Seta's docs: `MAME_DIVERGENCE.md:31-32` says
"`x1_001.sv` and `x1_012.sv` latch scroll at `line_start`", but `:146` and
`x1_012.sv:181` say vblank_rise unless `raster`. The `:31` text is stale.

### 4d. Tile VRAM: writes queued to vblank

| observation | RTL | where |
|-|-|-|
| Gundhara: scroll at 112-119, VRAM across the frame (~73 words/frame) → wrong tiles under old scroll | 128-deep write queue applied at `vblank_rise`; past 128 the rest go live in order | `x1_012.sv:111-159`; `MAME_DIVERGENCE.md:233-255` |
| Blandia reads VRAM back at boot (12288 reads a layer; `vread.lua`) | a CPU read drains the queue first, DTACK held | `x1_012.sv:120-124, 134, 137`; `MAME_DIVERGENCE.md:245-251` |

---

## 5. Repeatable procedure for a new core

Steps 1-2 use the skill's scripts (`write_timing.py`, `mame/wtiming.lua`, sharing
`scripts/mame/regions.json`). Steps 3-5 use Seta tools the skill does not ship; port them from
the Seta core's `scripts/` when needed.

1. **Transcribe the address map** from the MAME driver into `scripts/mame/regions.json`: sprite
   RAM, tile VRAM, scroll/zoom RAM and video registers as `read` (CPU-readable) or `wtap`
   (write-only) regions, one name each, and list the ones to count under `sweep`. Split
   sprite RAM by field where the chip does (Seta: `sprylow`, `sprctrl`, `sprcode`); the
   fields turned out to be written at different times. Guessed addresses count zero in
   silence. If a range is `writeonly()` in the driver, `install_write_tap` on it can abort
   the script at load; tap the driver's share instead
   (the Fuuki core's `scripts/mame/capture.lua`:54-58`).

2. **Histogram, attract and play**:
   ```
   python scripts/write_timing.py <set> --skip 600 --frames 1800
   python scripts/write_timing.py <set> --coin 600 --skip 1500 --frames 1800 --tag _play
   python scripts/write_timing.py <set> --reuse        # re-print from debug/wtiming/
   ```
   Skip past boot: counting from an early frame shows nothing while the game is still in
   its RAM test (checked on `thunderl`: nothing at `--skip 120`, Seta's result at 600).
   Check the closing snapshot in `debug/wtiming/snap<tag>/` shows the scene wanted. Paste
   the tables into `docs/write_timing_mame.txt`.

3. **Sprite control semantics** (double-buffer ownership): Seta's `sprctrl_scan.py` +
   `mame/sprctrl.lua` log each control-byte value and the line of each page flip. Adapt the
   bit tests (`sprctrl.lua:52-53`) to the new chip's control word.

4. **Per-write detail for a problem set**, with PC: Seta's `mame_capture.py --wlog` writes
   `frame scanline addr data pc` per write. Use it to find the ISR that writes, which half
   is written, and the quiet spans.

5. **Read-back check** (does the game read VRAM/sprite RAM?): Seta's `mame/vread.lua`. A
   non-zero read count on a queued or shadowed RAM means the RTL must drain or bypass it.

6. **Scanline source**: keep `time_until_pos` (`wtiming.lua:31-41`). Reduce by
   the driver's declared height, never the RTL's frame
   (the KonamiGX core's `docs/LESSONS_LEARNED.md:1613-1617`). Keep every
   tap in a global; `pcall` every callback with hits/logged counters
   (Seta `capture.lua:204-222`).

7. **What to look for in the table**:
   - Where the `#` sits for `sprylow`/`sprctrl`/`l*ctrl` relative to vblank
     start: column 0-2 → written in the vblank handler; column ~14-15 → a
     mid-frame (line-112) handler; column 31 → the lines before vblank.
   - Whether `sprcode`/`l*vram` are spread (`0000...`) — written across the
     frame — or concentrated.
   - `+0..1` and `vblank` for `sprylow`: high means a snapshot AT vblank start
     catches a half-written list; low means the list is settled by vblank.
   - Attract vs play differing (stg's codes: 0% vs 18% in first 24 lines).
   - `sprctrl_scan`: copy-off frames ≈ all frames + one flip a frame → the game
     owns the double buffer; flip line mid-frame → no vblank-based copy point
     is clean for both halves.

8. **Decision table** (observation → RTL):

   | observation | structure |
   |-|-|
   | per-line worst case fits in a line period at the chosen clock | double line buffer, engine two lines ahead, overrun counter (`ROADMAP.md:763-788, 846-851`; `LESSONS_LEARNED.md:798-830`) |
   | it does not fit at the chosen clock | re-check the clock, the fetch width and the candidate list first; per-line is the shape the hardware had. Take the arithmetic to the user before changing shape |
   | the board itself has a frame buffer (a frame-buffer RAM region or a 3D renderer in the driver) | frame buffer, cited in the roadmap — and see Psikyo (section 6): swap at the frame boundary, never at end-of-render |
   | list written entirely inside vblank, before line X | snapshot at line X or later, before active video (`snap_start`) |
   | list written mid-frame, chip has a hardware copy (`setac_eof`) | snapshot at end of visible, copy at vblank; per-board copy/draw order from the driver's `VIDEO_UPDATE_AFTER_VBLANK` |
   | game flips its own page (copy off + drawn-half bit toggles) | copy the selected half's codes at the flip; keep single-buffered fields (Y) at the usual point; move the engine when both are ready |
   | list written across the frame, no flip, no copy | fixed snapshot at MAME's draw line (`spr_snap_line`) |
   | scroll/mixer written mid-frame by a periodic handler, not a raster effect | latch at `vblank_rise` |
   | scroll written per line on purpose (raster) | latch at `line_start`; release VRAM queue on the write |
   | VRAM written across the frame while scroll is vblank-latched | queue VRAM writes to vblank; go live past the queue depth |
   | game reads that RAM back | drain the queue on read (DTACK held) or serve from the live copy |

---

## 6. Disagreements between Seta, Psikyo, Fuuki (and MS32 / KonamiGX)

1. **Only Seta and MS32 tag writes with a scanline.** Seta and MS32 derive it
   from `time_until_pos` (`wtiming.lua:31-41`;
   the JalecoMS32 core's `scripts/mame/capture.lua:78-92`). Fuuki's vreg
   log tags each write with the *raster register in force* (`read_u16(0x8c001c)`),
   not a line (the Fuuki core's `scripts/mame/capture.lua:82-97`), and
   `vregs_frames.lua:9-17` samples registers once per frame. KonamiGX's capture
   taps accumulate the last byte per address with no timing at all
   (the KonamiGX core's `scripts/mame/capture.lua:99-126`). Psikyo has no
   write-timing sweep: `flip_capture.lua:54-57` taps one bank register for its
   value; `mame_flip_capture.py` dumps regions at fixed frames and diffs
   DIP-off vs DIP-on (`:6-15`).

2. **Histogram vs per-write log.** Seta's `write_timing.py` is the only
   histogram-by-line tool; the others (Seta `--wlog`, Fuuki vreg log, MS32
   `_writes.log`) are per-write logs with PC. MS32 adds a `mask` column
   (`capture.lua:103`).

3. **Frame buffer vs line buffer: opposite orders of discovery.** Seta chose
   the line buffer from bandwidth arithmetic before any RTL (`ROADMAP.md:763-788`).
   Psikyo built a 1.7 Mbit frame buffer first, found it tore mid-scanout and
   its clear overlapped the next pass (the Psikyo core's `docs/sprite_buffering.md:27-38`),
   tried and removed a line buffer (`:183-195`), then reinstated the line path
   as the only one (`:128-181`). Seta's LESSONS notes the reversal
   (the Seta core's `docs/LESSONS_LEARNED.md:110-115`). Fuuki's engines
   also run two lines ahead (`raster_bands.py:20-21`).

4. **Where the sprite list is frozen.** Seta: per board, from the sweep — before
   vblank, late in vblank, at the game's flip, or at a fixed line (section 4b).
   Psikyo: MAME-exact two-generation buffering — `get_sprites()` then
   `m_spriteram->copy()` at vblank, table one generation old, displayed the
   following frame (`sprite_buffering.md:164-166, 242-262`). Fuuki: one
   snapshot at the frame boundary for records *and* the registers that qualify
   them (the Fuuki core's `docs/LESSONS_LEARNED.md:784-791`). MS32
   (capture side): dump sprite RAM at the driver's own copy moment, caught as
   the first write after vblank (`capture.lua:131-165`). Seta's "every input at
   its vblank value" (`MAME_DIVERGENCE.md:137-140`) and Fuuki's rule agree;
   Seta then departs from it per board where the sweep showed vblank was not a
   clean moment.

5. **Live vs latched game-control bits.** Psikyo keeps the game's global
   sprite-enable live, per MAME's renderer author (`sprite_buffering.md:224-232`).
   Seta latches control bytes with the snapshot (`x1_001.sv:296-300`) because
   live control gave "a line of garbage where bit 6 flipped mid-frame"
   (`MAME_DIVERGENCE.md:225`). Different chips; not a contradiction, but the
   default differs.

6. **Raster effects.** Fuuki treats mid-frame register writes as a first-class
   requirement and measures band boundaries on hardware with a per-line display
   record (the Fuuki core's `docs/ROADMAP.md:408-424`, 164-177`;
   `raster_bands.py`). Seta latches at vblank by default and enables per-line
   latching only for the calibr50 board (`x1_012.sv:61-67`;
   `downtown_board_cfg.sv:246`); `MAME_DIVERGENCE.md:35-37` marks raster
   support unproven in scope.

7. **Tile VRAM.** Seta queues VRAM writes to vblank (`x1_012.sv:111-159`).
   Psikyo's tilemaps "read VRAM live" (`sprite_buffering.md:239`). Fuuki: not
   checked here (unverified).

Unverified items in this survey: how the `MAME_DIVERGENCE.md:170-175` strip was
produced; Fuuki's tile VRAM policy; whether `vread.lua` has ever been run other
than for the Blandia figure.
