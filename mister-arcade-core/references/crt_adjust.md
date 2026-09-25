# CRT Adjust (rmonic79's `crt_adjust.sv`) across the five cores

Survey of the top-level trees (build/ ignored) of Arcade-KonamiGX, -JalecoMS32,
-Seta, -Fuuki, -Psikyo. Read-only. "Unverified" = not checked against a fit
report or hardware; only the source was read.

## 1. Summary

**Standard:** a single always-visible `CRT Adjust,Off,On` toggle; every size and position
parameter is behind an `H` group masked by `~toggle`, and Off bypasses the logic. All four
cores below do this. See `osd_and_peripherals.md` for the full mask layout.

All four cores that have the feature use the same vendored module, rmonic79's
`crt_adjust.sv` (Arcade-Raiden_MiSTer, GPL-3.0-or-later): a 1024x24 ping-pong
line buffer that moves/stretches the CONTENT while HSync/VSync stay native.
Nothing is done in `sys/` (sys_top.v, video_mixer.sv, video_freak.sv are
byte-identical across the five repos and untouched). No core uses a custom
hoffset/voffset input to its own sync generator.

- **Fuuki** is the most complete: H-Size, H-Position, V-Shift, plus V-Size via
  a second vendored module `crt_vsize.sv` (52-line x 320-px ring, ~39-40 M10K),
  with a PVM/Cabinet mode switch. Commit 580e15f (2026-09-13).
- **MS32** is the most recent (commit 188c044, 2026-09-18) and the cleanest
  glue: a wrapper `ms32_crt.sv` that measures the dot period at run time. No
  V-Size. Bypasses `arcade_video` entirely (drives VGA_* directly).
- **Seta** (commit 546242b, 2026-09-13): same wrapper shape as MS32
  (`seta_crt.sv`, MS32 copied it) and the only core with a bench
  (`sim/seta_crt_tb`). It found and fixed a signedness bug in the vendored
  file that Fuuki and Psikyo still carry (section 6).
- **Psikyo**: H-Position and V-Shift only, `hsize` tied to 0, no wrapper.
- **KonamiGX**: nothing. `arcade_video` only, no `video_freak`.

Recommended base for a new core: Seta's `crt_adjust.sv` (has the fix) +
MS32's `ms32_crt.sv` wrapper (measured dot period) + Fuuki's scandoubler
gating and, if BRAM allows, Fuuki's `crt_vsize` wiring.

## 2. Per-core table

| Core | OSD feature | Status bits | Menu mask | Module | Instantiation | Video path after it |
|---|---|---|---|---|---|---|
| MS32 | CRT adjust On/Off | O[94] | H3 = ~status[94] (`MS32.sv:164`) | `rtl/video/ms32_crt.sv` -> `crt_adjust` | the JalecoMS32 core's `MS32.sv:505-514` | direct `VGA_*` assigns `MS32.sv:516-523`; no arcade_video, no gamma, no video_freak |
| | H-Size | O[99:95] signed 5 | | | | |
| | H-Position | O[106:100] idx 0..96 | | | | |
| | V-Shift | O[112:107] signed 6 | | | | |
| Seta | CRT adjust On/Off | O[94] | H3 = ~status[94] (`Seta.sv:171`) | `rtl/video/seta_crt.sv` -> `crt_adjust` | the Seta core's `Seta.sv:785-794` | `arcade_video` (WIDTH 384, GAMMA 1) `Seta.sv:796-817` -> `video_freak` `Seta.sv:824-841` |
| | H-Size / H-Position / V-Shift | same bits as MS32 | | | | |
| | Scale / Crop / Crop offset | O[68:66] / O[70:69] / O[75:71] | | `sys/video_freak.sv` | `Seta.sv:820-841` | |
| Fuuki | CRT Adjust On/Off | O[76] | H2 = ~status[76] (`Fuuki.sv:190`) | `rtl/video/crt_vsize.sv` -> `rtl/video/crt_adjust.sv` (no wrapper; glue inline) | the Fuuki core's `Fuuki.sv:544-611` | `arcade_video` (WIDTH 320) `Fuuki.sv:615-639` -> `video_freak` `Fuuki.sv:648-665` |
| | H-Size | O[96:92] signed 5 | | | | |
| | H-Position | O[83:77] idx 0..96 | | | | |
| | V-Shift | O[89:84] signed 6 | | | | |
| | V-Size | O[100:97] signed 4, x3 lines | | | | |
| | V-Size Mode PVM/Cabinet | O[101] | | | | |
| | Scale / Vertical crop / Crop offset | O[68:66] / O[70:69] / O[75:71] | | `sys/video_freak.sv` | `Fuuki.sv:644-665` | |
| Psikyo | CRT Adjust On/Off | O[64] | H2 = ~status[64] (`Psikyo.sv:228`) | `rtl/video/crt_adjust.sv` (hsize=0) | the Psikyo core's `Psikyo.sv:737-756` | `arcade_video` (WIDTH 320) `Psikyo.sv:762-786`; no video_freak (`Psikyo.sv:96-97`) |
| | H-Position | O[71:65] idx 0..96 | | | | |
| | V-Shift | O[77:72] signed 6 | | | | |
| KonamiGX | none | -- | `status_menumask(16'd0)` `KonamiGX.sv:101` | -- | -- | `arcade_video` (WIDTH 288) the KonamiGX core's `KonamiGX.sv:310-328`; VIDEO_ARX/ARY direct `KonamiGX.sv:56-57` |

## 3. Mechanism

### 3.1 The vendored module

`crt_adjust.sv` (Seta/MS32 copy: 408 lines, md5 b97a9008...; Fuuki/Psikyo
copy: 413 lines, md5 61dd3b20...; they differ only in the header and one
line, section 6).

Ports, the Seta core's `rtl/video/crt_adjust.sv:109-158`:

```
module crt_adjust #(parameter VTOTAL = 263, HTOTAL = 384, HPOS_MODE = `HPOS_CONTENTSHIFT)
( input clk, pxl_cen /*write CE*/, pxl2_cen /*read CE*/, active,
  input signed [4:0] hsize, input signed [8:0] hoffset, input signed [5:0] voffset,
  input [7:0] r_in,g_in,b_in, input hs_in,vs_in,hb_in,vb_in,
  output reg [7:0] r_out,g_out,b_out, output reg hs_out,vs_out,hb_out,vb_out,
  output wire hs_ref_out );
```

Line buffer, `crt_adjust.sv:225`:
`(* ramstyle = "no_rw_check, M10K" *) reg [23:0] mem [0:(1<<AW)-1];` with
`AW = 10` (`:159`), i.e. 1024 x 24 bit = 24,576 bit. The header claims
"~1 M10K ... ~50 ALM, 0 DSP" (`:46`); by capacity (10,240 bit/M10K) it is at
least 3 M10K. Unverified in any fit report.

- H-Position: `hshift_tap` `:193-195`, content-shift window `:320-330`
  (HPOS_MODE 1, which all four cores select).
- V-Shift: VSync delayed through a per-line shift register, `:344-354`;
  content is not moved.
- H-Size: the READ clock enable `pxl2_cen` is supplied by the glue, slower or
  faster than `pxl_cen` (`:52-62`). The glue must restart its rate generator
  on `hs_ref_out` (`:150-155`).

### 3.2 CONF_STR lines

MS32 the JalecoMS32 core's `MS32.sv:91-94` (Seta `Seta.sv:105-108` identical):

```
"O[94],CRT adjust,Off,On;",
"H3O[99:95],CRT H-Size,0,+1,...,+15,-16,...,-1;",
"H3O[106:100],CRT H-Position,0,+1,...,+48,-48,...,-1;",
"H3O[112:107],CRT V-Shift,0,+1,...,+31,-32,...,-1;",
```

Fuuki the Fuuki core's `Fuuki.sv:108-113` adds:

```
"H2O[100:97],CRT V-Size,0,+1,+2,+3,+4,+5,+6,+7,-8,-7,-6,-5,-4,-3,-2,-1;",
"H2O[101],CRT V-Size Mode,PVM,Cabinet;",
```

Psikyo the Psikyo core's `Psikyo.sv:130-132`: On/Off, H-Position, V-Shift only.

### 3.3 Decode (same arithmetic in all four)

H-Position is an INDEX into a 97-entry list, so the negative half wraps at
97, not 128 (`Psikyo.sv:723-725`). H-Size and V-Shift are two's complement.

the Seta core's `rtl/video/seta_crt.sv:26-35` (MS32 `ms32_crt.sv:35-44`, Fuuki `Fuuki.sv:547-551`, Psikyo `Psikyo.sv:726-732`):

```
hsize  <= adjust ? $signed(hsize_idx) : 5'sd0;
hpos   <= adjust ? hpos_idx : 7'd0;
wire signed [8:0] hoffset = (hpos <= 7'd48) ? $signed({2'b00, hpos})
                                            : $signed({2'b00, hpos}) - 9'sd97;
wire signed [5:0] voffset = adjust ? $signed(vshift_idx) : 6'sd0;
```

### 3.4 H-Size read-rate generator (the part the vendored module leaves to the core)

- Seta `seta_crt.sv:37-51`: accumulator in twentieths of a clk; 240 per pixel
  (12 clk/px at 96 MHz), +5 per H-Size step (= quarter clk). Restarted on
  `hs_ref` rise. `pxl2_cen = (hsize == 0) ? ce : tick`.
- MS32 `ms32_crt.sv:46-67`: same, but the dot period is MEASURED between
  enables (`dper`, 12 or 16: the game picks 8 or 6 MHz) so `base = 20*dper`.
- Fuuki `Fuuki.sv:577-593`: quarter-clocks directly: `rd_period = 48 + hsize`,
  accumulator +4 per clk. Same step size, different arithmetic.
- Psikyo: none; `hsize(5'sd0)`, `pxl2_cen(ce_pix)` (`Psikyo.sv:746-748`).

### 3.5 Where the output goes

- MS32 `MS32.sv:516-523`: `CE_PIXEL = crt_on ? crt_ce : ce_pix`, `VGA_DE =
  crt_on ? ~(crt_hb|crt_vb) : ~(hblank|vblank)`, likewise HS/VS/RGB. `gamma_bus()`
  unconnected (`:158`), `VGA_SL = 0` (`:32`). The rotator taps the NATIVE
  raster, not the adjusted one (`:535-537`).
- Seta `Seta.sv:796-817`: `arcade_video` gets `ce_pix(crt_on ? crt_ce :
  core_ce_v)`, RGB/HBlank/VBlank/HSync/VSync muxed on `crt_on`; `fx`,
  `forced_scandoubler`, `gamma_bus` wired. `VGA_DE` goes out as `vga_de_raw`
  into `video_freak` (`:835`), which drives `VGA_DE`, `VIDEO_ARX/ARY` from
  `HDMI_WIDTH/HEIGHT`, `CROP_SIZE` (216/224/0, `:820-822`), `CROP_OFF
  (status[75:71])`, `SCALE (status[68:66])`. `ce_out` is stretched to 2 clk
  (`seta_crt.sv:53-55`) because `arcade_video` runs on `clk_video` = 48 MHz.
- Fuuki `Fuuki.sv:615-665`: identical shape to Seta but always fed from the
  crt_* outputs (no top-level mux; the module bypasses internally when
  `active=0`), `gamma_bus_video` with gamma forced off under the debug overlay
  (`:151-156`).
- Psikyo `Psikyo.sv:762-786`: crt_* straight into `arcade_video`; `VGA_DE`
  direct; no crop/scale.
- `VGA_SCALER = 0` in all five (`KonamiGX.sv:35`, `MS32.sv:34`, `Seta.sv:35`,
  `Fuuki.sv:48`, `Psikyo.sv:60`).

### 3.6 Scandoubler gating

- MS32 `MS32.sv:507` and Seta `Seta.sv:787`: `.adjust(status[94] & ~forced_scandoubler)`.
  `fx != 0` also turns the scandoubler on (`sys/arcade_video.v:116`:
  `wire scandoubler = fx || forced_scandoubler;`) and is NOT checked here.
  MS32 has no arcade_video so only `forced_scandoubler` matters there.
- Fuuki `Fuuki.sv:545-546`: `scandoubled = (status[46:44] != 0) | forced_scandoubler;
  crt_size_en = crt_adj_on & ~scandoubled;` -- only the SIZES are forced to 0,
  H-Position/V-Shift stay live.
- Psikyo: no gating (nothing retimes the pixel rate).

### 3.7 sys/ version

No version string. All five repos: `sys/sys_top.v` header "(c)2017-2020 Alexey
Melnikov"; `sys/hps_io.sv` "Copyright (c) 2017-2026 Alexey Melnikov";
`sys_top.v`, `hps_io.sv`, `video_freak.sv`, `video_mixer.sv`, `arcade_video.v`
byte-identical (md5) across the five. Last commit touching `sys/`:
KonamiGX b9413cd (2026-09-17), Fuuki d82fc2b (2026-09-04). Nothing in `sys/`
was edited for this feature; the "sys-side variant" the module header mentions
(`crt_adjust_sys.sv`, edit sys_top.v) is not used by any core.

### 3.8 The name

The feature is **CRT Adjust**, after the module every core uses, rmonic79's `crt_adjust.sv`, and
that is the OSD label (`"O[94],CRT Adjust,Off,On;"`). Older roadmaps and READMEs call it
"CRT Offset" or a `CRT_OFFSET` helper; no module of that name exists, in `sys/` or anywhere else.
Say "CRT Adjust" in new cores' OSD, README and roadmap.

Existing OSD labels: "CRT adjust" (MS32, Seta), "CRT Adjust" (Fuuki, Psikyo).

## 4. V-Size

Only Fuuki. MS32 states "no V-size" (`ms32_crt.sv:6`, `Readme.md:126`).
Psikyo `README.md:139-141`: "H-Size/V-Size are still not implemented, but the
block RAM that blocked them is now free". Seta: not mentioned.

Module: the Fuuki core's `rtl/video/crt_vsize.sv`, vendored unmodified
from Arcade-Raiden_MiSTer (rmonic79, GPL-3.0-or-later), `:1-10`.

Mechanism (`:17-34`): frame rate fixed; the TOTAL line count per frame is
changed and the line period scaled inversely, so lines spread or squeeze
without any line being repeated or dropped. `vsize > 0` -> more lines/frame ->
smaller picture. Cost is HSync frequency deviation: "height% == HSync
deviation%" (`:29`); PVM/BVM lock a wide range, cabinet chassis ~1-2%.
Self-measuring (frame period, native line count, CE period), no per-core
timing parameters (`:47-51`). Placed BEFORE `crt_adjust` (`:53-55`).

Two modes, `tube_mode` (`:76-77`, `:373-377`): 0 = PVM (retimer, HSync moves),
1 = Cabinet (native timing, "photometric geometry sim"; `:503-508`, needs
clk/pixel >= 8). OSD "CRT V-Size Mode,PVM,Cabinet" = `status[101]`.

Storage, `:175-181`:

```
(* ramstyle = "no_rw_check, M10K" *) reg [23:0] ring [0:RING_LINES*LINE_PX-1];
reg [9:0] meta_px [0:RING_LINES-1];
```

Fuuki instantiates `RING_LINES(52), LINE_PX(320)` (`Fuuki.sv:567`): 52 x 320
x 24 = 399,360 bit. The header says "about 40 M10K" (`crt_vsize.sv:8-9`);
by capacity the floor is 39. Ring sizing rule `:58-61`: `|vsize| <=
RING_LINES/2 - 2`, so 52 lines cover +-24 = the OSD's +-8 steps x 3 lines
(`Fuuki.sv:564`). The one register-per-index read (`:439-452`) is deliberate
so the ring infers as M10K.

Decode `Fuuki.sv:553-562`: one OSD step = 3 lines, negated so "+" is taller:
`crt_vsize <= crt_size_en ? -(step + (step <<< 1)) : 0`. Also forced to 0 under
the scandoubler.

Wiring `Fuuki.sv:567-575`: takes `core_*` and `de_in(~(core_hb|core_vb))`,
`vb_in(core_vb)`; outputs `vz_*` and `vz_ce` (the retimed pixel CE), which feed
`crt_adjust`'s `pxl_cen` and, when H-Size is 0, its `pxl2_cen` (`:592, :603`).

Recorded cost/rationale in docs: none beyond the module header. Fuuki
`README.md:47` (release note), `:120`, `docs/ROADMAP.md:89` ("Untested on
MiSTer at the time of writing"); `docs/LESSONS_LEARNED.md` has no V-Size
entry (the only "PVM" hit, `:754`, is a MiSTer.ini gamma preset). Commit
580e15f body records the design, not a fit delta. Fuuki `README.md:128-134`
gives the whole-core total only: 445/553 M10K (80%), 3,287,455 block-memory
bits. No V-Size bench exists in any repo.

## 5. Checklist for a new core (KonamiGX numbers where they matter)

GX timing (the KonamiGX core's `rtl/video/gx_video.sv:9-13`): 384 x 264
total, 288 x 224 visible, 6 MHz dot = 8 clk at clk_vid 48 MHz.

1. Vendor `rtl/video/crt_adjust.sv` from Seta (it carries the `$signed` fix at
   `:329`; section 6). Add to `files.qip`. Attribution: rmonic79,
   GPL-3.0-or-later (MS32 `THIRD-PARTY.md:82-87`, Seta `README.md:467,489`).
2. Wrapper after `ms32_crt.sv` (measured dot period, one-clk `ce_out`):
   parameters `VTOTAL(264), HTOTAL(384), HPOS_MODE(1)`. `ce_out` width must
   match what the consumer clocks on: 1 clk if `arcade_video` runs on the same
   clock as the wrapper (MS32, Fuuki), 2 clk if on a half-rate clock (Seta
   `seta_crt.sv:53-55`).
3. H-Size rate: 8 clk/px = 160 twentieths base (MS32 form `base = 20*dper`) or
   32 quarter-clocks (Fuuki form `rd_period = 32 + hsize`). Restart on
   `hs_ref_out`, never on raw HSync (`Fuuki.sv:578-579`).
4. CONF_STR: On/Off + H-Size (5b) + H-Position (7b, 97 entries) + V-Shift (6b),
   sub-lines behind an `Hn` mask driven by `~status[on]`. Free status bits in
   KonamiGX: everything except [0], [46:44], [122:121]. Copy Fuuki's lines and
   bits (76, 96:92, 83:77, 89:84, 100:97, 101) or MS32's (94, 99:95, 106:100,
   112:107); the two layouts are incompatible with each other's .CFG files.
5. Decode as section 3.3. Gate as Fuuki: sizes off when
   `(status[46:44] != 0) | forced_scandoubler`, offsets stay.
6. Feed `arcade_video` (`KonamiGX.sv:310-328`): `ce_pix(crt_ce)`, `RGB_in`,
   `HBlank/VBlank/HSync/VSync` from crt_*. Keep `VGA_SCALER = 0`.
7. Optional `video_freak` (crop/integer scale): instantiate as
   `Seta.sv:824-841` between `arcade_video`'s `VGA_DE` and the `VIDEO_ARX/ARY`
   outputs, CONF_STR `O[68:66] Scale`, `O[70:69] Crop`, `O[75:71] Crop offset`.
   `sys/arcade_video.v` does not wrap it (`Psikyo.sv:96-97`, Fuuki
   `docs/ROADMAP.md:670-673`). GX is 224 visible, so only the 216 crop does
   anything.
8. Optional V-Size: vendor `crt_vsize.sv`, `RING_LINES(52), LINE_PX(288)` =
   359,424 bit, >= 36 M10K by capacity (unverified). Wire as `Fuuki.sv:553-575,
   592, 603`. Needs clk/pixel >= 8 for Cabinet mode (GX has exactly 8).
9. Bench: copy the Seta core's `sim/seta_crt_tb/tb_seta_crt.sv`
   (checks every source pixel appears once, in order, and where the picture
   lands for H-Size +10 / H-Position -19 / -8). Include a negative
   H-Position case; that is what caught the signedness bug.
10. Rotator (if any) taps the native raster, not the adjusted one
    (`MS32.sv:535-537`); rotated cores: H-Position moves the HDMI picture
    vertically (`Psikyo.sv:714-716`).

## 6. Where the cores disagree

1. **Signedness fix present in Seta/MS32 only.** Seta
   `docs/LESSONS_LEARNED.md:1241-1244`: `hoff_s = mode ? $signed(hoffset) :
   {(AW+2){1'b0}}` makes the ternary unsigned, so H-Position -N zero-extends to
   512-N and the picture blanks for every negative value; found by
   `sim/seta_crt_tb`. Seta/MS32 `crt_adjust.sv:329` has `$signed({(AW+2){1'b0}})`;
   Fuuki/Psikyo `crt_adjust.sv:334` still has the unsigned literal and their
   headers say "VENDORED, UNMODIFIED". Negative H-Position on Fuuki and Psikyo
   is therefore expected to blank the picture. Unverified on hardware.
2. **Status bit layout** differs three ways (table, section 2). Seta's
   `scripts/cfg.py:90` still says `"crt": (76, 1)` with a "PROVISIONAL" note
   (`:28`); the real Seta bit is 94.
3. **Scandoubler gating**: MS32/Seta disable the whole adjust on
   `forced_scandoubler` only (miss `fx != 0`); Fuuki disables only the sizes
   and also on `fx`; Psikyo does not gate.
4. **Bypass mux**: Seta/MS32 mux crt_* vs native at the top level on `crt_on`;
   Fuuki/Psikyo rely on the module's internal bypass (`active = 0`).
5. **Video path**: MS32 bypasses `arcade_video` (no gamma, no scandoubler,
   `gamma_bus()` open); the other four use it. `video_freak` only in Seta and
   Fuuki.
6. **crt_adjust parameters**: VTOTAL/HTOTAL = 263/384 (MS32), 272/512 (Seta),
   262/456 (Fuuki, Psikyo). HTOTAL only sizes the SYNCSHIFT HSync shift
   register, unused in HPOS_MODE 1; VTOTAL sizes the V-Shift line shift
   register and must cover the real line count.
7. **Naming**: the cores differ in capitalisation of the OSD label and some
   docs say "CRT Offset". The standard is "CRT Adjust" (section 3.8).
8. **Line-buffer cost**: the module header says ~1 M10K; 1024 x 24 bit needs
   >= 3 by capacity. No repo has a fit-report figure for either module.
