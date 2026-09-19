# Memory-map documentation across five MiSTer arcade cores

Read-only survey of Psikyo, Fuuki, Seta, JalecoMS32, KonamiGX (top-level trees; `build/` ignored).
All five share one controller lineage: Sorgelig's `sdram.sv` extended to burst-4 (one 8-byte
"granule" per transaction), three fixed-priority ports (0 > 1 > 2), an N-client hold-until-valid
arbiter per port, `sdram_download.sv` for the HPS byte stream, and (all but GX) a DDR3 fast-load
path (`rom_loader.sv`, `.mra` `address="0x30000000"`).

## 1. Who documents what, where, in what form

### Psikyo (fullest; three dedicated docs)

| Doc | Content | Table columns |
|---|---|---|
| `E:\Arcade-Psikyo_MiSTer\docs\phase1_memory_map.md` | 68EC020 base map (:30-48) + per-board overlays sngkace/gunbird (:50-75); Z80/LZ8420M program + I/O maps (:77-116); ADPCM-A bit-swap fixup and where it lives in RTL (:118-174); sprite RAM / VRAM / vreg layouts (:176-265) | `Range \| Size \| Contents \| Access` (base map); `Range \| Contents` (overlays); `Port \| Contents` (I/O); `Offset (bytes) \| Contents` (vregs). Every row cites `psikyo.cpp:` line |
| `E:\Arcade-Psikyo_MiSTer\docs\phase1_ddram_map.md` | SUPERSEDED (header :3-12). DDRAM protocol (:22-62), address map (:82-108), arbiter consumer list (:124-141), throughput failure (:143-167) | `Region \| Base (offset from 0x30000000) \| Size \| Rounded up from` (:93-101) |
| `E:\Arcade-Psikyo_MiSTer\docs\phase1_sdram_map.md` | Why SDRAM (:8-56); SDRAM_* interface + controller semantics (:58-95); 64-bit granule problem (:97-121); address map (:123-144); port partition, original and current (:146-175); measured verification (:177-231); narrow-bridge, byte-order bug and adapter (:233-301) | Map: `Region \| Base \| Size` (:129-137). Ports: `Physical port \| Logical consumers \| Arbitration` (:155-159, :166-170) |
| `E:\Arcade-Psikyo_MiSTer\docs\phase2_sh404.md:117-129` | Re-layout table after Tengai's 4 MB tiles | `Region \| Base \| Size` (third copy of the same map) |
| `E:\Arcade-Psikyo_MiSTer\docs\savestates.md:49-57` | DDR3 collision list: rotator `0x24000000` 3x8 MB, loader window, proposed `0x3E000000` | prose bullets |

What Psikyo records that the others do not: *why* each region is the size it is ("Rounded up
from" column, largest clone set named); per-port measured latency/contention numbers; the byte-order
seam and which clients must / must not go through `gfxrom_byte_reorder.sv` (:280-283).
What it does not record: `.mra` form per region, fill byte, client address unit, bus width.

### Fuuki (no map doc; ROADMAP + RTL header)

| Where | Content | Form |
|---|---|---|
| `E:\Arcade-Fuuki_MiSTer\docs\ROADMAP.md:257-282` | Main CPU map, FG-2/FG-3 differences inline | `Address \| Size \| Contents` |
| `...\ROADMAP.md:284-303` | Tilemap VRAM banks | `Bank \| Offset \| Layer` |
| `...\ROADMAP.md:305-336` | Video registers | code block |
| `...\ROADMAP.md:816-835` | FG-3 SDRAM map (FG-2 map is only in RTL) | `offset \| size \| region`; states sizes are `ROM_REGION` declarations incl. holes |
| `E:\Arcade-Fuuki_MiSTer\docs\gfx_layouts.md:12-19, 96-113` | Region -> gfx layout; byte order measured (`_SWAP` wins on all five ROMs) | `Region \| FG-2 \| FG-3`; `ROM \| Region \| swapped \| not swapped` |
| `E:\Arcade-Fuuki_MiSTer\rtl\memory\fuuki_sdram_top.sv:1-19` | Port assignment with deadline rationale and an unmeasured bandwidth estimate; "This module is the authority" | header comment |

### Seta (no map doc; per-game CPU map lives in RTL)

| Where | Content | Form |
|---|---|---|
| `E:\Arcade-Seta_MiSTer\docs\ROADMAP.md:631-660` | Group C/D 68000 map only; notes Group A/B "use the same regions at different base addresses" | `range \| contents` |
| `...\ROADMAP.md:662-676` | ROM inventory per set | `set \| maincpu \| sprites \| layer 1 \| layer 2 \| X1-010 \| total` |
| `...\ROADMAP.md:259-262` | LAYOUT_A prose ("the only map defined so far" -- stale, seven layouts exist) | prose |
| `...\ROADMAP.md:252-257`, `:777-782` | Port assignment by deadline | prose |
| `E:\Arcade-Seta_MiSTer\docs\LESSONS_LEARNED.md:380-387` | Byte order fixed at the seam with an adapter | lesson |
| `E:\Arcade-Seta_MiSTer\rtl\memory\seta_sdram_top.sv:1-19` | Ports; seven layouts A-G in one-line prose each | header comment |

### JalecoMS32 (HARDWARE_NOTES + ROADMAP + RTL header)

| Where | Content | Form |
|---|---|---|
| `E:\Arcade-JalecoMS32_MiSTer\docs\ROADMAP.md:202-224` | V70 map | `region \| window \| physical size \| width` -- the only core whose CPU map records bus width |
| `E:\Arcade-JalecoMS32_MiSTer\docs\HARDWARE_NOTES.md:31-52` | V70 map vs Charles MacDonald's board measurements: mirrors, widths, unmapped reads | `Note \| Core \| Status` (matches/changed/differs) |
| `...\ROADMAP.md:520-538` | Memory plan: which region on SDRAM / DDR3 / BRAM and why | `what \| where \| why` |
| `E:\Arcade-JalecoMS32_MiSTer\docs\phase1_video.md:21-24, 76-77` | DDRAM traffic and latency numbers; SDRAM bytes per tile row | table rows |
| `E:\Arcade-JalecoMS32_MiSTer\rtl\memory\ms32_sdram_top.sv:6-24` | SDRAM map as a comment table: name, base, size, contents, interleave, decrypt-on-the-way-in | header comment |
| `...\ms32_sdram_top.sv:26-35` | Ports, with a measured failure that drove the partition (YMF271 missed ~5% of ticks with sprites on port 1) | header comment |

### KonamiGX (ROADMAP + generated RTL)

| Where | Content | Form |
|---|---|---|
| `E:\Arcade-KonamiGX_MiSTer\docs\ROADMAP.md:538-566` | 68EC020 Type 2 map | `region \| window \| size \| notes` |
| `...\ROADMAP.md:735-752` | Memory plan (SDRAM / DDR3 / BRAM) + the packed `maincpu` window | `what \| where \| why` + prose |
| `...\ROADMAP.md:378-392` | Image layout in prose (5-byte rows spread to 8), per-set layout statement | prose |
| `E:\Arcade-KonamiGX_MiSTer\rtl\memory\gx_sdram_top.sv:1-32` | Ports; image layout in prose; the 5->8 spread formula | header comment |
| `E:\Arcade-KonamiGX_MiSTer\rtl\gx_board_cfg.sv:5-12` | "The SDRAM image ... bases and four-byte part sizes are what build_mra.py derives" | header comment |
| `E:\Arcade-KonamiGX_MiSTer\docs\WORKFLOW.md:345-358` | Rule: "SDRAM offsets come from the RTL's own address map, never duplicated into the generator" | rule list |

DDRAM: `E:\Arcade-KonamiGX_MiSTer\KonamiGX.sv:32` ties every `DDRAM_*` output to 0. No DDRAM use, no
fast load, no rotator.

## 2. Where the map lives in code

### SDRAM region bases

| Core | File:line | Shape | Width | Column meanings |
|---|---|---|---|---|
| Psikyo | `E:\Arcade-Psikyo_MiSTer\rtl\memory\psikyo_sdram_top.sv:144-154` | `localparam logic [24:0] <REGION>_BASE = 25'h...` (MAINCPU, AUDIOCPU, SPRITES, TILES, SPRITELUT, ADPCMA) | 25-bit byte, 32 MB | comment :137-143 gives the sizing rule and "they and this table must change together" |
| Fuuki | `E:\Arcade-Fuuki_MiSTer\rtl\memory\fuuki_sdram_top.sv:99-107` (FG2), `:109-120` (FG3), `:122-129` board mux | `localparam logic [25:0] FG{2,3}_BASE_<REGION> = 26'h...;   // <size>` | 26-bit byte, 64 MB | trailing comment = reserved size; :110-112 hole rationale; `BOARD_FG2/FG3` = mod byte bit 0 |
| Seta | `E:\Arcade-Seta_MiSTer\rtl\memory\seta_sdram_top.sv:105-154` | `BASE_<REGION>_<LAYOUT>` per layout A-G, then wires `BASE_GFX1..X1SND` muxed by `layout` (:131-150), `SIZE_GFX1` (:159-164) | 26-bit | trailing comment = size; :152 "localparams, not wires, so build_mra.py can read them"; layout index from `seta_board_cfg.sv:83-84` |
| MS32 | `E:\Arcade-JalecoMS32_MiSTer\rtl\memory\ms32_sdram_top.sv:103-113` | `BASE_<REGION>` + `MASK_TX/BG/ROZ` (engines mask to region; `.mra` repeats ROM to region size) | 26-bit | sizes only in the header table :13-20 and in `build_mra.py` `MAP` |
| KonamiGX | `E:\Arcade-KonamiGX_MiSTer\rtl\gx_board_cfg.sv:34-45` | `case(game)` arms: `tile_base, obj_base` (26-bit byte) + `tile_size4, obj_size4` (bytes in the four-byte part); `gx_sdram_top.sv:85` only `BASE_MAINCPU` | 26-bit | arms are GENERATED (`build_mra.py --cfg`, markers :34/:45); per set, not per board |

### Client address units (all region-local; base added in `*_sdram_top`)

- Psikyo: mixed -- gfxrom byte offsets, spritelut/maincpu WORD addresses, audiocpu bytes; conversion in `psikyo_sdram_top.sv:22-28, 201-371`.
- Seta: granule addresses `[23:3]` for gfx, word `[23:1]` for CPU, bytes for X1-010/sub (`seta_sdram_top.sv:54-91`).
- MS32: region-local bytes with `MASK_*`; V70 fetch `[20:3]` granules (`ms32_sdram_top.sv:74-91`).
- Fuuki: region-local, added at `fuuki_sdram_top.sv:181-183`.
- GX: row index / half-row index; base passed as a port into `gx_rom_port.sv:31` per client.

### CPU address map in code

- Seta: `E:\Arcade-Seta_MiSTer\rtl\cpu\maincpu.sv:13-44` `board_t` (21 maps) and `:231-262` default base table + `case(board)` overrides; comment `:14` "Must agree with scripts/mame_capture.py's FAMILIES table" (agreement not machine-checked -- unverified). Selected by `seta_board_cfg.sv` `map_board`.
- Others: decode is inline in each core's bus wrapper; not surveyed further.

### Chip-level address split, refresh, banks

- `rtl/memory/sdram/sdram.sv` in each repo: row/column split reversed from upstream so a burst-4 stays in one row (GX/MS32/Seta/Psikyo `:323-341`, Fuuki `:256-264`); A10 auto-precharge, A9 = byte bit 25 on a 64 MB chip; refresh interval comment (`:165-169`, Fuuki `:130-132`). `SDRAM_BA` "two banks" (`:34`). No doc records which byte-address bits select the bank; GX ROADMAP `:385-386` notes the sprite region landing in "bank 2" of the chip model. Bank bit derivation not checked here.

### DDRAM addresses (only in module parameters)

| Core | Window | File:line |
|---|---|---|
| all but GX | fast-load ROM image at `0x30000000 + 0` (HPS DMA), length = SDRAM map end | Psikyo `rom_loader.sv:20` `LENGTH 28'h1280000`; MS32 `ms32_rom_loader.sv:21` `28'h1FC_0000`; Fuuki `Fuuki.sv:451` `board ? 28'h3880000 : 28'h1180000`; Seta computed from `BASE_*` at `seta_sdram_top.sv:221-229` |
| all but GX | HDMI rotator, `0x24000000`, 3x8 MB | `rtl/video/screen_rotate_two.sv:59,65,73` (identical in four repos) |
| MS32 | sprite frame buffer, 2 banks x 0x40000 at window byte `0x2000000`; pixel formula | `E:\Arcade-JalecoMS32_MiSTer\rtl\video\ms32_sprite_fb.sv:32-39` |
| MS32 | object RAM copy at window byte `0x2100000` | `E:\Arcade-JalecoMS32_MiSTer\rtl\video\ms32_objram.sv:13-17, 39` |
| MS32 | one-port sharing (core burst jobs vs rotator FIFO) | `E:\Arcade-JalecoMS32_MiSTer\rtl\memory\ms32_ddram_mux.sv:1-20` |
| Psikyo | proposed savestates at `0x3E000000` | `docs\savestates.md:57` |

## 3. Cross-checks between doc, RTL and `.mra`

| Core | Mechanism | File:line | What it asserts |
|---|---|---|---|
| Seta | `read_sdram_map()` regex-parses every `localparam ... BASE_\w+` from the RTL; `sys.exit` if any layout's name is missing | `E:\Arcade-Seta_MiSTer\scripts\build_mra.py:177-190`, LAYOUTS `:78-105`, docstring `:36-38` | `.mra` offsets == RTL; whole image re-read via `mra.py` and compared (`:20-29`); clone region sizes == parent (`:216-240`) |
| Fuuki | same regex on `FG[23]_BASE_\w+`; exits if missing; prints the map | `E:\Arcade-Fuuki_MiSTer\scripts\build_mra.py:19-20, 408-431, 697-702` | `.mra` offsets == RTL; byte-for-byte re-read (`:7-16`) |
| MS32 | `MAP` list REPEATS bases+sizes; `check_map()` asserts each `BASE_<NAME>` in the RTL equals the list; region start position must equal map base | `E:\Arcade-JalecoMS32_MiSTer\scripts\build_mra.py:48-58, 192-195` | duplicated table cannot drift silently; sizes are NOT checked against RTL (RTL has no size localparams) |
| KonamiGX | direction reversed: `layout()` derives bases from `ROM_START`; `rtl_arm()` parses the generated case arm; build refuses if they differ; `--cfg` prints arms to paste | `E:\Arcade-KonamiGX_MiSTer\scripts\build_mra.py:100-142, 293-298` | RTL arm == ROM_START-derived layout |
| KonamiGX | sim: stream the `.mra` image into `gx_sdram_top` + chip model, read every region back via the board's port, compare to MAME region images | `E:\Arcade-KonamiGX_MiSTer\scripts\check_gx_sdram.py:1-24` | download transform + byte order end to end |
| Seta | hardware: JTAG probe of the last gfx2 granule vs `build_region.py` image; single-granule check | `E:\Arcade-Seta_MiSTer\scripts\sdram_check.py:1-30`, `check_granule.py:1-24` | SDRAM content at address, on the board |
| Fuuki / Seta | screenshot-decoded 256-word read-back vs program image | `scripts\sdram_dump_check.py:1-20` (Seta copy "NOT yet exercised", `:22-26`) | CPU path content |
| Psikyo | none for the map. `validate_mra.py` checks XML well-formedness, stray text, `<switches>` byte count, `<setname>`, `<rotation>` only | `E:\Arcade-Psikyo_MiSTer\scripts\validate_mra.py:19-33` | not the offsets |
| Psikyo | `verify_rom_trace.py`: hardware ROM-read trace vs zip, brute-forces interleaves | described at `E:\Arcade-Seta_MiSTer\docs\LESSONS_LEARNED.md:192-198` | content at traced addresses, not reach |

`.mra` headers: GX (`releases\Crazy Cross (ver EAA).mra:10-12`), MS32 (`:1-3`) and each Fuuki/Seta file
cite the RTL file that owns the map and say the file is generated. Psikyo's are hand-written with
`<part repeat="0x...">FF</part>` padding and no citation.

## 4. TEMPLATE for a new core

Three files. Each table names the RTL symbol that owns the number; prose never repeats a number
the table has.

### `docs/memory_map.md` -- the game's own address spaces

```markdown
# Memory map -- <board name(s)>

Scope: <sets / machine configs>. Source: <driver>.cpp at MAME <commit>; every row cites a line.

## Clocks
| Signal | <board A> | <board B> |

## <main CPU> address map (base, shared)
| Range | Size | Contents | Width | Access | Mirror | Backing | MAME line |
|---|---|---|---|---|---|---|---|
| `000000-1fffff` | 2 MB | Program ROM | 16 | R | -- | SDRAM `MAINCPU` | psikyo.cpp:254 |
(Backing = BRAM name, SDRAM region name from sdram_map.md, register block, or "unmapped: reads N")

### <board B> overlay
| Range | Contents | Differs from base how |

## <sound CPU> address map / I/O ports
| Range | Contents |           | Port | Contents |

## RAM layouts the video/sound engines read
(sprite table, display list, control words, VRAM cell format, vreg offsets: `Offset | Contents | Bits`)

## Per-game flags that change the map
| Flag | mod byte bit | Sets | Effect |

## Divergences from MAME / hardware notes
| Note | Core | Status |            (MS32 HARDWARE_NOTES form: matches / changed / differs + why)
```

### `docs/sdram_map.md` -- the download image and who reads it

```markdown
# SDRAM map

Chip: MT48LC16M16 (32 MB) [or 64 MB via A9]; controller rtl/memory/sdram/sdram.sv (burst-4, one
8-byte granule per transaction); address width <25|26> bits. Authority: rtl/memory/<core>_sdram_top.sv.

## Regions (per <board|layout|set>; one table per variant)
| Region | RTL symbol | Base | Size | Sized from | MAME region / parts | .mra form | Fill | Download transform | Read width | Byte order at seam |
|---|---|---|---|---|---|---|---|---|---|---|
| tiles | `TILES_BASE` | `0x0A40000` | 4 MB | tengai `ROM_REGION` | `gfx2` u33,u34 | `interleave 16 map=12` | `FF` pad | none | 64 | `gfxrom_byte_reorder` |
Columns:
- Sized from: the set or ROM_REGION that fixes the size (Psikyo's "Rounded up from"); say if holes
  inside the declared region are addressable (Fuuki FG-3 sprites).
- .mra form: bare part / interleave+map / repeat-to-size (MS32 wrap semantics).
- Fill: pad byte (00 vs FF) or "repeat".
- Download transform: swizzle (Seta gfx1), decrypt (MS32 tx/bg), row spread 5->8 (GX), bit swap
  (Psikyo ADPCM-A), inversion -- and whether the fast-load path applies the same transform.
- Byte order at seam: which adapter sits between sdram.sv's native little-endian granule and the
  consumer; list clients that must NOT pass through it.
Total used / map end: `0x...` = rom_loader length (derive from the last BASE + size, not a literal).

## Ports and clients
| Port | Priority | Clients (arbiter N) | Address unit given to sdram_top | Deadline / lead | Measured (bench, latency, contention) |
|---|---|---|---|---|---|
| 0 | highest | tilemap L0, L1 (N=2) | byte, region-local | scanline, no lead | tb_..., 0/12720 mismatches |
State the rule used to assign ports (deadline, not convenience) and any partition that was tried
and measured worse.

## Sync
- The RTL localparams are the authority. scripts/build_mra.py parses `localparam ... <PREFIX>BASE_\w+`
  and refuses to run if a name the region order needs is missing; it re-reads the written .mra and
  compares the image byte for byte.
- Every .mra header comment cites the RTL file and says it is generated.
- The loader length and any `in_<region>` window in RTL are expressions over BASE_* (Seta
  seta_sdram_top.sv:221-229), not literals.
- This doc's Base/Size columns are regenerated by `build_mra.py --print-map` (Fuuki prints it at
  :697-702); do not edit them by hand.
- A sim check streams a real .mra image through the download path and reads every region back
  against MAME's region images (KonamiGX scripts/check_gx_sdram.py); a hardware probe compares one
  granule (Seta scripts/check_granule.py).
```

### `docs/ddram_map.md` -- the HPS DDR3 window

```markdown
# DDRAM map

Interface: sys/emu_ports.vh DDRAM_* (64-bit, 8-byte granules, BURSTCNT, BUSY/DOUT_READY); latency
unbounded (MiSTer docs) -- no hard-real-time consumer goes here (LESSONS_LEARNED).

| Window | Byte address | Size | Owner module (param) | Access | Active when | Shares the port via |
|---|---|---|---|---|---|---|
| Fast-load ROM image | `0x30000000` + 0 | = SDRAM map end | rtl/memory/rom_loader.sv `LENGTH` | 8-byte reads | download only | mux on `ldr_active` |
| HDMI rotator | `0x24000000` | 3 x 8 MB | screen_rotate_two.sv `MEM_BASE` | single-beat writes | runtime | FIFO / mux |
| <sprite FB> | `0x30000000 + 0x2000000` | 2 x 0x40000 | ms32_sprite_fb.sv `BASE` | 80-beat bursts | runtime | ms32_ddram_mux |
| <savestates> | `0x3E000000` | ... | planned | | | |
Collision check: list every module that drives DDRAM_ADDR and show the windows are disjoint
(Psikyo docs/savestates.md:49-57 is the form). Record BUSY-handling per master (rotator ignores it).
Measured traffic per frame and the latency the design was verified at (MS32 phase1_video.md:21-24).
```

## 5. Disagreements between cores

1. Map granularity. Psikyo and MS32: one fixed map for every set. Fuuki: one per board (FG-2/FG-3,
   `fuuki_sdram_top.sv:16-18` gives the reason). Seta: seven layouts by game group (`seta_sdram_top.sv:9-16`).
   KonamiGX: per set, generated (`gx_board_cfg.sv:34-45`).
2. Region sizing. Psikyo/MS32: largest set in the family. Fuuki/GX: the set's `ROM_REGION`
   declaration, holes included (`fuuki_sdram_top.sv:110-112`, `build_mra.py:101-103` GX). Seta: per layout.
3. Padding. Psikyo pads with `FF`; Seta/GX pad with `00`; MS32 repeats ROM data to the region size
   so tile numbers wrap like MAME (`ms32_sdram_top.sv:6-10`).
4. Authority direction. Seta/Fuuki/MS32: RTL localparams are parsed by the generator. GX: generator
   derives from `ROM_START` and the RTL arms are pasted from `--cfg`; the build refuses on drift.
   Psikyo: three hand-copied tables (two docs + phase2) and the RTL block, with a comment asking for
   them to change together and no check.
5. Where the SDRAM map is written. Psikyo: dedicated docs. Fuuki: RTL + a ROADMAP table for one
   board only. Seta/MS32/GX: RTL header comment (+ prose or `what|where|why` plan in ROADMAP).
6. Byte order. Recorded as a doc section by Psikyo (`phase1_sdram_map.md:254-283`), Fuuki
   (`gfx_layouts.md:96-113`, measured) and Seta (LESSONS `:380-387`). MS32 and GX record only the
   `.mra` interleave form in the RTL header; no byte-order statement for the read seam.
7. Bus width in the CPU map: only MS32 has a `width` column (`ROADMAP.md:204`).
8. Address width: Psikyo 25-bit (32 MB); the other four 26-bit with A9 = bit 25 (Fuuki uses it).
9. Download port placement: MS32 puts the download and object-RAM writes on port 1 and sprites on
   port 2 (`ms32_sdram_top.sv:27-35`, with a measured reason); Psikyo/Fuuki/Seta/GX put the download
   on port 2 with the CPU.
10. Loader length: a literal duplicating the map end in Psikyo (`rom_loader.sv:20`), MS32
    (`ms32_rom_loader.sv:21`) and Fuuki (`Fuuki.sv:451`); derived from `BASE_*` in Seta.
11. DDRAM use: GX none; Seta/Fuuki/Psikyo staging + rotator only; MS32 has runtime consumers with
    bases in module parameters across four files and no consolidated table.
12. Client address unit handed to `*_sdram_top`: Psikyo mixes byte and word addresses per client;
    Seta hands granule addresses; MS32 region-local bytes with masks; GX row indices with the base
    passed in per client (`gx_rom_port.sv:31`).
13. Stale prose: Seta `ROADMAP.md:259` still says LAYOUT_A is "the only map defined so far";
    Psikyo `phase1_sdram_map.md:155-159` keeps a superseded port table above the current one.

Unverified: which address bits `sdram.sv` maps to `SDRAM_BA`; whether Seta's `maincpu.sv` board
table and `scripts/mame_capture.py` FAMILIES actually agree (the comment asks for it, nothing checks).
