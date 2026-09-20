# OSD groups and extra peripherals

Standard: the OSD shows only what applies to the running game and the current output. Every
optional group sits behind an `H<n>` prefix whose `status_menumask` bit is driven by the core.
Source: `Seta.sv` (CONF_STR lines 80-125, mask at 174, gun and rotary wiring 335-470),
`docs/DOWNTOWN.md` "Loop joysticks".

## Hiding

`hps_io`'s `status_menumask`: bit n set hides every line prefixed `Hn`. Seta's assignment, with the
direct-video group from `video_audio_options.md` added:

| Bit | Group | Hidden when |
|---|---|---|
| H1 | Debug page | release build (`debug_menu_hide`) |
| H2 | Light gun: crosshair, stick mode, mouse | `~gun_game` (from the `.mra` mod byte) |
| H3 | CRT H-Size, H-Position, V-Shift (V-Size) | `~status[94]`, the "CRT adjust" toggle is off |
| H4 | Rotary speed, GRS keystroke mode | `rot_menu_hide` (mod byte: not a rotary game) |
| H5 | Aspect, orientation, scale, crop, scandoubler fx | `direct_video` |

```
.status_menumask({10'd0, direct_video, rot_menu_hide, ~status[94], ~gun_game, debug_menu_hide, 1'b0}),
```

- **CRT offset parameters are hidden until enabled**: `"O[94],CRT adjust,Off,On;"` is always
  shown; the size and position lines are `H3` (`Seta.sv:105-108`). Off also means the offset
  logic is bypassed, not merely hidden.
- **Every peripheral group is per game**: the mod byte (or a board-type field in it) says whether
  the set has a gun, a rotary stick, a trackball, a second screen, and the mask hides the rest.
  Inputs the game does not have are not offered.

## Rotary joysticks: the Ikari Warriors controls

Clone the Ikari Warriors core's controls and settings, as Seta did for DownTown and Caliber 50
(`Seta.sv:85-86, 377-400`; `rtl/downtown/rotary_input.sv`, 65 lines, is the implementation to copy):

- **Rotate Left / Rotate Right** on buttons 3 and 4 of each player's joypad, stepping the stick
  one position per step while held.
- **OSD, `H4`:** `"H4O[114:113],Rotary Speed,Normal,Slow,Fast,Very Fast;"` (step rate while held)
  and `"H4O[115],GRS Super JoyStick (Keystroke Mode),Off,On;"`: the GRS stick sends keystrokes;
  arrow keys for P1, C/V for P2.
- **J1 button names** change with the game: `"J1,Button 1,Button 2,Rotate Left,Rotate Right,..."`
  on rotary sets (Seta selects between two `CONF_J1` defines).
- **The board side is per game**: convert steps into what the game reads. DownTown reads a
  12-position switch (position wraps 0..11); Caliber 50 reads a uPD4701 count, 4 counts a
  position, masked to 16 directions by the game.

## Light-gun games: mouse and synthetic crosshair

As `zombraid` in Seta (`Seta.sv:112-117, 335-470`):

- **Aim sources, all in the game's units** (held positions, not deltas to the game): the left
  analog stick positions absolutely past a small dead zone; a d-pad direction ramps the position
  a few units a frame; the mouse adds its counts, clamped. Axes are independent.
- **OSD, `H2`:**
  ```
  "H2O[86:85],Crosshair,Off,P1,P2,P1+P2;",
  "H2O[88:87],P1 stick,Auto,Aim,D-pad;",
  "H2O[90:89],P2 stick,Auto,Aim,D-pad;",
  "H2O[92:91],Mouse aims,P1,P2,Off;",
  ```
  Stick "Auto": full deflection acts as a d-pad (arcade sticks on gamepad encoders), partial
  deflection aims.
- **Mouse** from `hps_io`'s `ps2_mouse`: bit 24 toggles once per packet, `[15:8]`/`[23:16]` are
  X/Y counts with sign bits 4/5, Y positive up; buttons `[1:0]` map to trigger and the second
  button (`Seta.sv:343-357`).
- **Synthetic crosshair**: the core draws a marker at each enabled player's aim point over the
  final video, on both outputs, so a gun game is playable without a light gun on a flat panel.
  It is an overlay after the mixer, never a game layer. Give each player a distinguishable marker;
  Seta used red for player 1 and blue for player 2 in Zombie Raid, which is that core's choice, not
  a MiSTer convention. Search MiSTer-devel for existing `crosshair` implementations before writing
  one. Keep it separate from any debug overlay that prints the raw aim values.
- Real light guns on a CRT: where the board reads a gun's position from the beam, the same aim
  registers are what a MiSTer light-gun adapter drives; keep that path in mind when choosing the
  units.
