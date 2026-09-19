# Original-PCB video as a reference

Optional. Use when MAME and the core disagree and neither is known to be right, or when
a human needs a side-by-side of the real board.

## What it is good for

- Human visual comparison: layer order, blend/shadow appearance, sprite flicker, raster
  effects, colour depth, screen geometry and overscan, attract-mode sequence.
- Gross timing: scroll speed in pixels per second, frames per animation step, how long
  a fade takes. Count over a run of seconds, not single frames.

## What it cannot give

- Exact refresh rate or line count. YouTube re-encodes to 30 or 60 fps and drops or
  duplicates frames, so 57.5 Hz and 60 Hz look the same. Take `screen.set_raw()` from the
  MAME driver, the PCB manual, or a published hardware measurement instead; a video can
  only corroborate.
- Pixel-exact colour. Capture chains (supergun, OSSC, capture card, YouTube compression)
  each alter it.

## Finding footage

Search with WebSearch, then open results in the browser pane. Queries that work:

- `"<game>" PCB gameplay`, `"<game>" arcade board`, `"<game>" original hardware`
- `"<game>" jamma supergun`, `"<game>" OSSC`, `"<game>" 基板` (Japanese uploads are often
  real boards)
- add `-MAME -MiSTer -FPGA -emulator -longplay` to cut emulator captures

Accept a video as PCB footage only when the title, description or visible setup says so
(board on a bench, supergun, capture-card mention). Uncertain provenance goes in the log as
uncertain.

## Using it

- Prefer viewing in the browser and stepping with `,` and `.` over downloading. Downloading
  a video is a file download: ask the user first, name the file and source. If approved,
  `yt-dlp` then `ffmpeg -ss <t> -frames:v 1` for single frames.
- Compare against `scripts/hw.py shot --native` output at the same scene; note that the
  MiSTer screenshot is the core's raw frame, the video is a scaled capture.
- Record every video used in `docs/REFERENCE_VIDEO.md`: URL, timestamp, what it shows, what
  was concluded, how confident. Link, never re-host or transcribe the content.
