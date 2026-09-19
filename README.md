# MiSTer-CoreSkill

A Claude Code skill for building MiSTer arcade cores: bootstrap from `Template_MiSTer`,
MAME as the reference, the shared tooling and the cumulative lessons from five finished
cores (Psikyo, Fuuki, Seta, Jaleco MegaSystem 32, Konami System GX).

## Install

The skill is `mister-arcade-core/`. Link it into the user skills directory so it triggers
from any folder (Windows, command prompt, adjust the path to this clone):

```
mklink /J "%USERPROFILE%\.claude\skills\mister-arcade-core" "<this-clone>\mister-arcade-core"
```

On Linux or macOS, `ln -s <this-clone>/mister-arcade-core ~/.claude/skills/mister-arcade-core`
(but see Platform below). To scope it to one project instead, link it into that repo's
`.claude/skills/`.

## Settings

Copy `mister-arcade-core/mister-core.env.example` to `~/.mister-core.env` and fill in what
applies. Nothing in the skill hardcodes a machine: paths and names come from the environment,
then a core's own gitignored `mister.env`, then that per-machine file, then a probed default.
A new core needs no `mister.env` of its own unless it overrides something.

Requires: Quartus 17.0 Lite with ModelSim, Verilator, MAME (binary and source), Python 3,
`gh` (GitHub CLI), and a MiSTer on the network for hardware work.

## Platform

Developed and used on Windows. The scripts call `.exe` tools, hide console windows, sweep
stray simulator processes with PowerShell, clean with `clean.bat`, and take Verilator from
MSYS2 MinGW64. A Linux user must change the tool lookups, those Windows-only helpers and
`capture.lua`'s `mkdir`.

## Layout

```
mister-arcade-core/
  SKILL.md                  workflow; read first
  mister-core.env.example   per-machine settings template
  scripts/new_core.py       Template_MiSTer -> Arcade-<Name>_MiSTer
  references/               lessons learned, feature guides, tool guides
  assets/core/              copied verbatim into a new core (scripts/, docs/, .gitignore, ...)
```
