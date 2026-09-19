# HDMI scaling, rotation, flip screen, audio mix

Standard for every core. Sources: `Seta.sv`, `Fuuki.sv`, `Psikyo.sv`, `MS32.sv` (KonamiGX has
none of this yet: `AUDIO_MIX = 0`, aspect only). Seta and Fuuki are the fullest; copy from them.

## OSD block

Bit numbers are Seta's (`Seta.sv:96-103`); keep them unless they collide with the core's own.
`H5` marks the options that only affect the HDMI scaler; they are hidden under direct video,
where they do nothing (the convention kuze uses in his cores). Flip Screen is not HDMI-only and
stays visible.

```
"H5O[122:121],Aspect ratio,Original,Full Screen,[ARC1],[ARC2];",
"H5O[64:63],Orientation,Auto,Off,CW,CCW;",
"O[65],Flip Screen,Off,On;",
"H5O[68:66],Scale,Normal,V-Integer,Narrower HV-Integer,Wider HV-Integer,HV-Integer;",
"H5O[70:69],Crop,Off,216 lines,224 lines;",
"H5O[75:71],Crop offset,0,1,2,...,15,-16,...,-1;",
"H5O[46:44],Scandoubler Fx,None,HQ2x,CRT 25%,CRT 50%,CRT 75%;",
"O[124:123],Audio mix,Mono,None,25%,50%;",
```

```
wire direct_video;                 // hps_io output
hps_io #(...) hps_io (..., .direct_video(direct_video),
    .status_menumask({10'd0, direct_video, /* H4..H0: the core's own groups */ 5'd0}), ...);
```

Pick a free `H` bit if the core already uses 5. Crop line counts are per core: pick ones that
divide the target HDMI height for the core's visible height (Fuuki: 216 of 240 is exactly 5x on
1080). CRT offset/size options are the opposite case: analog only (Seta hides them with `H3`).

## Aspect and rotation

`Seta.sv:58-72`. "Auto" follows the set's orientation, carried in the `.mra` mod byte
(`game_rot`: 0 none, 1 CW, 2 CCW) so one `.rbf` serves horizontal and vertical games.

```
wire [1:0] rot_sel    = status[64:63];
wire       rotate_en  = (rot_sel == 2'd0) ? (game_rot != 2'd0) : (rot_sel != 2'd1);
wire       rotate_ccw = (rot_sel == 2'd0) ? (game_rot == 2'd2) : (rot_sel == 2'd3);
wire       osd_flip   = status[65];   // to the core's flip logic, not the rotator
wire [11:0] base_arx  = rotate_en ? 12'd3 : 12'd4;   // 4:3, 3:4 rotated
wire [11:0] base_ary  = rotate_en ? 12'd4 : 12'd3;
```

`VIDEO_ARX/ARY` come out of `video_freak`, which applies the aspect-ratio menu to these.

## Scaling and crop: `sys/video_freak.sv`

In `sys/` but not wrapped by `arcade_video.v`: instantiate it explicitly (`Fuuki.sv:640-663`)
with `ARX/ARY` from above, `CROP_SIZE` from the crop menu (0 = off), `CROP_OFF`, `SCALE`.
`VGA_DE_IN` is `arcade_video`'s DE before `video_freak`.

## HDMI rotation: `screen_rotate_two.sv`

Sorgelig's, GPL-2.0, vendored in Fuuki/Seta/MS32 (originally Arcade-SKNS_MiSTer). A tap, not a
filter: analog keeps the native raster; a rotated copy goes to DDR3 and out through the
framework's framebuffer. Needs `MISTER_FB=1` in the `.qsf`. `Fuuki.sv:664-700`:

- `.rotate_ccw(rotate_ccw)`, `.no_rotate(~rotate_en)`, `.flip(1'b0)`, `.two_screen(1'b0)`, and the
  `FB_*` and `DDRAM_*` ports. Its own flip is not used: flip comes from the core (below), so
  HDMI and analog show the same thing.
- **It shares DDR3 with DDR ROM loading.** Mux DDR3 between loader and rotator on the loader's
  active signal and hold `DDRAM_BUSY` high for the loader's whole run. The rotator has no reset
  and infers acceptance from `DDRAM_BUSY`, so shared naively it takes the loader's transactions
  as its own writes and leaves a stale band in the frame (Fuuki).
- If the core also reads ROM from DDR3 at run time, the rotator is another DDR3 client: arbitrate,
  and count its bandwidth in the memory plan.
- Rotation costs BRAM for line buffering; add it to the on-chip RAM budget.

## Audio mix

OSD order Mono, None, 25%, 50% maps to `AUDIO_MIX` 3, 0, 1, 2 (`Seta.sv:54`):

```
assign AUDIO_MIX = (status[124:123] == 2'd0) ? 2'd3 : status[124:123] - 2'd1;
```

Mono first so the default (all zero) is mono. A mono board still offers the menu with its
signal on both channels. `AUDIO_S` is 1 for signed samples.

## Flip screen: one implementation, reachable from the OSD and the DIP

The standard (after kuze): flip is done once, in the core's video logic, and that one flip
serves both outputs. There is no separate HDMI-only flip.

- **Main OSD "Flip Screen"** and **the game's flip DIP** drive the same logic. Either one flips.
- **A game with no flip DIP gets a fake one**: a `.mra` DIP entry (or mod-byte bit) that the
  core reads directly, not the game, so every set can be flipped the same way. Task Force
  Harrier is the case that forced this in kuze's cores.
- **A real DIP is read by the game**, which then sets the board's flip bit itself; the core only
  sees the flip register. So the core's flip is `game_flip ^ osd_flip ^ fake_dip`. Setting the
  OSD option and a DIP together flips twice and cancels; say so in the README.
- The HDMI rotator's `flip` input stays 0 (above).
- A cocktail game's own player-2 flip goes through the same path as the DIP.

### Making the flip correct: per core

What a flip takes is different on every board. Work it out per core and record it:

1. **Find how the board flips.** In the driver: which register bit or DIP drives it, and what
   the video chips do with it (`set_flip`, `flip_screen_set`, per-chip flip bits in `_v.cpp`).
   Some games set it themselves (Seta's `oisipuzl` runs flipped; `set_tilemaps_flip(1)`).
2. **List what must change** for each layer: tilemap scroll origin and direction, sprite X/Y
   arithmetic (the flipped half often has its own offsets), line-buffer read or write direction,
   the tile's own flip bits, and fixed per-game offsets. Expect a few pixels of per-game offset
   that MAME encodes as constants. For `osd_flip`/`fake_dip` on a board whose flip is a chip
   register, force that register's bit in the core rather than inventing a second path.
3. **Get a reference.** Capture with the DIP set (`scripts/mame/setdip.lua`, or Seta's
   `mame_capture.py --dip "Flip Screen=On"`). MAME's own flip can be wrong: the check is that
   the flipped frame equals the unflipped frame of the same state rotated 180 degrees
   (LESSONS_LEARNED, Seta, "Check flip screen against the rotation"). Where MAME's flipped
   output fails that, it goes in `docs/MAME_KLUDGES.md`. For a fake DIP there is no MAME
   reference at all; the rotated unflipped frame is the only check.
4. **Cover both branches in the benches.** Seta's sprite Y sweep ran flipped and unflipped
   input combinations; ordinary captures never exercise the flipped branch because few games
   flip unprompted.
5. **If it cannot be made right yet, say so.** Fuuki left the Flip Screen DIP out of its `.mra`
   files because both MAME drivers get it wrong: a `docs/HACKS.md` entry with what would settle
   it, and a README line.

Record per core, in `docs/HARDWARE_NOTES.md` or the roadmap: the flip source, each layer's
change, the per-game offsets, which sets needed a fake DIP, and how each was verified.
