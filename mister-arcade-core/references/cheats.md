# Cheats

The pattern is wickerwaka's, from the Irem M92 core: cheats listed in the `.mra`, chosen in the
OSD, applied by a **read-override** engine. A code names an address, an optional compare value
and a value to replace, OR or AND; the engine substitutes it as the CPU reads that address and
writes nothing, so a cheat switched off leaves no trace in memory. Worked example:
`Arcade-KonamiGX_MiSTer` (`rtl/cheat/`, `scripts/mame_cheats.py`, `docs` in its README).

## The pieces

| Piece | What |
|---|---|
| `.mra` | `<cheats size="16" max="N">` with `<cheat name="...">` elements, each one or more 16-byte codes in hex |
| OSD | `"C,Cheats;"` in CONF_STR: Main_MiSTer lists the `.mra`'s cheats there |
| Download | Main_MiSTer sends the enabled cheats' codes, concatenated, on **ioctl index 255**; two zero bytes when none is on |
| Engine | `cheatengine_32_16` (Arcade-IremM92_MiSTer `rtl/cheatengine.sv`, GPL-2.0-or-later, after Kitrinx) on the CPU's read data |
| Codes | `scripts/mame_cheats.py`: Pugsy's MAME cheat XML (mamecheat.co.uk) to `<cheats>` |

A code, big-endian: `flags address compare data`, flags = `method << 8 | size << 4 | compare`
(method 0 replace, 1 OR, 2 AND; size 1, 2 or 4; compare 1 = only while memory holds `compare`).
`max` must not exceed the engine's `MAX_CODES`: Main_MiSTer stops enabling cheats at `max`.

## Wiring

- **Loader**: shift each download byte into a 128-bit code; on the 16th byte raise bit 128 and
  hold it until the next byte, so an engine on another clock sees every code. Clear the engine
  while the download is at address 0.
- **Do not reset on index 255.** A core that holds reset during every `ioctl_download` resets the
  game whenever a cheat is switched. Exclude index 255 from the reset (and from any SDRAM
  writer that does not already filter on its own index).
- **Engine placement**: on the read data of the RAM the cheats address (work RAM; ROM too if the
  cheats patch code). Reads by save-state or debug masters must bypass it, or a saved state
  holds cheated values.
- **Byte lanes follow the CPU's endianness.** The upstream engine is little-endian (V33/V35: the
  byte at an even address is bits 7:0). On a big-endian 68000-family 16-bit bus it is bits 15:8,
  and a long's high word is at the lower address; the code-loading table changes accordingly.
- **A 4-byte compare on a 16-bit bus** must compare only the half each read carries; the
  upstream engine compares 32 bits with the other half zero, and so never matches.
- Verilator wants `data_out` declared `logic` and, in a `--savable` model, the code struct
  `packed`.

The engine's area grows with `MAX_CODES` (every code is a comparator and a stage of the read
mux); 16 held Konami GX's useful cheats.

## Converting MAME's cheats

`scripts/mame_cheats.py <set>` lists what converts and why the rest does not; `--mra` prints the
block; a core's `.mra` generator imports it (`cheats()`, `mra_block()`). Set `CHEAT_CPU`,
`CHEAT_RAM` and `CHEAT_MAX` per core. What converts: constant stores (`pb/pw/pd@addr=value`),
`|`/`&` with a constant, parameter item lists (one cheat per item). A once-only MAME cheat
(`state="on"`, a starting stage) is held while it is on, which can hold the value for good:
tell players to switch it off once it has taken effect. Cheats on during power-on tests can make
them fail. Credit Pugsy in the README.

mamecheat.co.uk sits behind a bot check: the user downloads it (`cheatNNNN.zip`, holding
`cheat.7z`). Put `cheat.7z` beside the MAME executable, still packed: py7zr reads it, or without
py7zr libarchive's `tar` (Windows' own `tar.exe`, `bsdtar` elsewhere), one set at a time.
