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
then a core's own `<core>.<KEY>=value` lines in that file, then its plain keys, then a probed
default.

## MCP server

`mcp/` is the `mister` MCP server: one per machine, on `http://127.0.0.1:8770/mcp`, started at
boot by a scheduled task. Core sessions use its tools for builds, simulation, MAME, deploys,
the board and probes instead of running the scripts; it runs the same scripts as jobs every
session can see. Install and register it with the steps in [`mcp/README.md`](mcp/README.md);
the tools are listed in [`mcp/TOOLS.md`](mcp/TOOLS.md).

Its status page, `http://127.0.0.1:8770/`, shows the cores and their settings, the JTAG
holder and queue, running and recent jobs with their logs, deploys and recent calls.

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
mcp/                        the mister MCP server and its status page
```
