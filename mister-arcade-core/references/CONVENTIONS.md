# Conventions

What every core repository in this family shares. Terse by design; the reasons are in
`docs/WORKFLOW.md` and `docs/LESSONS_LEARNED.md`.

## Naming

- Repository: `Arcade-<Name>_MiSTer`. `<Name>` is alphanumeric, starts with a letter, and is the
  Quartus project name and the top-level revision name.
- Project files share the stem: `<Name>.qpf`, `<Name>.qsf`, `<Name>.sv`, `<Name>.sdc`,
  `<Name>.srf`. The Quartus 13 project files from the template are deleted.
- Two revisions in `<Name>.qpf`: `<Name>_stp` (instrumented) and `<Name>` (release).
  `<Name>_stp.qpf` and `<Name>_stp.qsf` exist alongside. The two `.qsf` files are identical above
  a final commented block that adds `VERILOG_MACRO "DEBUG_ISSP=1"` to `_stp`. Both pin `SEED`.
- The top-level module is `emu`, in `<Name>.sv`, `` `include "sys/emu_ports.vh" ``. CONF_STR
  starts `"<Name>;;"`.
- Deployed cores on the device: `<Name>_NNNNNNNN.rbf` in `/media/fat/_Arcade/cores/`, number
  incrementing per deploy (`scripts/deploy.py`). Released cores: `releases/Arcade-<Name>_YYYYMMDD.rbf`.
- Every `.mra` carries `<mameversion>NNNN</mameversion>`: the MAME release its set definitions
  and CRCs came from, written by the generator from `mame -version`, never typed.
- `.mra` files are named by MAME's description, one primary per game in `releases/`, the rest in
  `releases/_alternatives/_<game name>/`, as the contribution guidelines require and as Seta and
  Fuuki do. KonamiGX omits the leading underscore; that is a defect in that core, not an option. `<rbf><Name></rbf>`: the `.mra` names the core file **without** the
  `Arcade-` prefix, while the released bitstream keeps it, so the README's install step says to
  drop the prefix when copying the `.rbf` to the device. `deploy.py` already installs it under the
  un-prefixed name. The released bitstream keeps the prefix the guidelines ask for,
  `releases/Arcade-<Name>_YYYYMMDD.rbf`, so the README's install step tells the user to drop it
  when copying to the device. KonamiGX instead puts `Arcade-KonamiGX` in the `<rbf>` tag; that is
  wrong, and a new core follows Seta and Fuuki. Changing the stem of an already-deployed core means
  deleting the files under the old stem from the device in the same change; MiSTer ignores them, so
  they only mislead.

## Files and directories

- `files.qip` lists every source file the project compiles, grouped by block with a comment per
  group saying where it came from and which files carry local changes. The `.qsf` ends
  `source sys/sys.tcl`, `source sys/sys_analog.tcl`, `source files.qip`. Generated modules are
  listed with a "regenerate rather than hand-edit" note.
- `sys/` is the MiSTer framework, vendored from Template_MiSTer, never edited. Build-time
  behaviour changes are `VERILOG_MACRO` settings in the `.qsf`.
- `rtl/` is the core. Every vendored subdirectory carries a `PROVENANCE.md` (upstream repository,
  exact commit, licence as stated in the files, every local change). `rtl/debug/` holds the probe,
  counters, tracer and pause control. `rtl/synth_check/` is a standalone Quartus project for
  measuring one block.
- `sim/<bench>/` per testbench, with a `files.f`; `sim/common/` shared models.
- `scripts/` build, deploy, capture and verification tooling (`docs/WORKFLOW.md`, "Script
  inventory"). `scripts/mame/*.lua` for MAME capture.
- `tools/` vendored generators (source committed, binaries gitignored).
- `docs/`: `ROADMAP.md`, `WORKFLOW.md`, `RELEASE_PROCESS.md`, `LESSONS_LEARNED.md`,
  `MAME_KLUDGES.md`, `HACKS.md`, `screenshots/<set>/`, plus per-subsystem design notes named
  `phaseN_<subsystem>.md` or `<subsystem>.md`.
- Root: `README.md` (upper case), `LICENSE`, `THIRD-PARTY.md`, `.gitignore`, `.gitattributes`,
  `clean.bat`, `mister.env` (gitignored), `CLAUDE.md`, `.claude/settings.json`.
- `roms/` your MAME sets, gitignored. `debug/` MAME reference captures, gitignored. `build/` the
  staged-build worktree, gitignored.

## `.gitignore`

Template_MiSTer's Quartus block, kept in step with it, then: `!sim/**/files.f` (bench file lists
are source), `build/`, `quartus_*.log`, `q_*.log`, `sta*.log`, `worst_*.rpt`, ModelSim (`work/`,
`transcript`, `vsim.wlf`, `modelsim.ini`, `*.vstf`, `sim/**/*.{log,bin,lst,hex,raw,trace,dec}`),
Verilator (`obj_verilator/`, `simout/`), vendored cores' simulation dumps (`/*.raw`,
`sim/**/*.lxt`, `sim/**/*.vcd`), `roms/`, `/debug/` (anchored — a bare `debug/` swallows
`rtl/debug/`), `/*.png`, `/*.txt`, `scratch_*`, `cfg.bin`, `outfile.bin`, MAME's `cfg/`, `nvram/`,
`snap/`, `sta/`, `mister.env`, `releases/*.rbf` (add a verified one with `git add -f`),
`compile.log`, `worst.tcl`, `tools/<gen>/<binary>`, editor and Python scratch.

## `.gitattributes`

`*.sh text eol=lf`; `scripts/**/*.tcl` and `scripts/**/*.lua` likewise (scoped so `sys/*.tcl` is
left alone); one `<vendored dir>/** -text` line per vendored directory.

## `mister.env`

Gitignored; `mister.env.example` committed. Keys: `MISTER_HOST`, `MISTER_USER`, `MISTER_PASSWORD`,
`MAME_DIR`, `MAME_EXE`, optionally `QUARTUS_BIN`, `MODELSIM_BIN`. Sourced with
`set -a; . ./mister.env; set +a`. Absolute MiSTer paths need `MSYS_NO_PATHCONV=1` under Git bash.

## `THIRD-PARTY.md`

States the project licence and why; one section per dependency with upstream URL, commit, licence
as stated in the files, what was taken, what was modified and what the licence obliges; a section
for reference material that is not code (MAME); any licence question still open, with the issue
link; a release checklist (PROVENANCE current, change notices present, SPDX header on every file
of ours, `sys/` unmodified, `LICENSE` text matches, open questions answered).

## OSD and CONF_STR

Order: aspect ratio, scandoubler, rotation/flip, scale/crop, CRT adjust (hidden behind its own
enable bit), audio mix, hiscore autosave, `DIP;`, the `H1P1` Debug page (every line `H1`-prefixed,
every switch worded so 0 = normal), `T[0],Reset;` and `R[0],Reset and close OSD;` **before** the
joystick lines, `J1,...` (padded to a fixed button count, agreeing with the `.mra` `<buttons>`),
`jn,...`, `v,0;`, `V,v`. `status[0]` is Soft Reset and nothing else. `status_menumask` bit 1
tracks `DEBUG_ISSP`.

## Documents

- A doc names its provenance in its first paragraph when it was ported from a sibling.
- Every number says where it came from: MAME file and line, a bench run, a build report, a commit.
  "Verified" means a check was run. Otherwise say "unverified".
- No dates unless load-bearing; then take the date from the commit. No invented durations.
- Progress sections are kept current: strike through closed items while the history matters,
  delete them when it does not.
- `LESSONS_LEARNED.md` entries have three parts: the rule, the mechanism that made the wrong
  assumption plausible, and the evidence that settled it. Mark each with the core that
  established it. Never edit an earlier core's entry to say something this core found.

## Comments

- A comment earns its place by saying something the code cannot: why, what it was measured
  against, which MAME line it transcribes, which other file must be kept in step with it.
- Terse. Delete a comment when the thing it explains is gone. A stale comment is a bug.
- Vendored files: append to upstream's header, never replace it. GPLv3 §5(a) notices carry a
  date; that is the one place a date is required.
- Every file of ours starts with `// SPDX-License-Identifier: <licence>` and a copyright line.
- No `*` or `/` in new RTL outside comments (WORKFLOW §14).

## Branching

`develop` carries granular commits, squashed onto `master` at milestones. Commit messages state
what changed and the evidence; no narration of wrong turns that left no trace.
