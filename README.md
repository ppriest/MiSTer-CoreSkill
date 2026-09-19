# MiSTer-CoreSkill

A Claude Code skill for building MiSTer arcade cores: bootstrap from `Template_MiSTer`,
MAME as the reference, the shared tooling and the cumulative lessons from
Arcade-Psikyo, -Fuuki, -Seta, -JalecoMS32 and -KonamiGX.

## Install

The skill is `mister-arcade-core/`. Junction it into the user skills directory so it
triggers from any folder:

```
mklink /J "%USERPROFILE%\.claude\skills\mister-arcade-core" "E:\MiSTer-CoreSkill\mister-arcade-core"
```

## Layout

```
mister-arcade-core/
  SKILL.md               workflow; read first
  scripts/new_core.py    Template_MiSTer -> Arcade-<Name>_MiSTer
  references/            lessons learned, feature guides, tool guides
  assets/core/           copied verbatim into a new core (scripts/, docs/, .gitignore, ...)
```

Requires: Quartus 17.0 Lite with ModelSim, Verilator, MAME, Python 3, `gh` (GitHub CLI).
