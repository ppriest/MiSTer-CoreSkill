# Plan: MCP servers for MAME, Quartus, simulation and the MiSTer

## Answer

Yes. An MCP server is a local process that offers typed tools to Claude Code (configured in
`.mcp.json` or `~/.claude.json`). Each tool here would be a thin layer over a script the cores
already have, not a rewrite:

| Domain | Today | Wrapped as |
|---|---|---|
| MAME | `mame_capture.py`, `mame_boot_trace.py`, `mame_sys_trace.py`, `mame_cheats.py`, `scripts/mame/*.lua` through `run.lua` | `mame.*` |
| Quartus | `build_staged.py`, `floorplan.py`, `report_worst_paths.tcl`, `sta_failing_paths.tcl`, `quartus_map` | `build.*` |
| Simulation | `run_sim.sh` (ModelSim), `run_verilator.sh`, `compare_boot_trace.py` | `sim.*` |
| MiSTer | `deploy.py`, `hw.py` (Remote API), `probe.py` / `read_issp.tcl` (ISSP over JTAG), `identity.py`, plink/pscp | `mister.*`, `probe.*` |
| Shared | `hwlock.py` (JTAG against Quartus/ModelSim), `coretools.py` (core root, project, revision, env) | the server's own core |

## Shape

**Built as: one stdio server per session, with the shared state on disk** (`mcp/`, see its
README). This replaced the per-PC HTTP daemon proposed here:
- Claude Code starts stdio servers itself, and a daemon would need its own start and recovery.
- The state that sessions must share already lives in machine-wide files: hwlock's JTAG markers,
  and the job records under `%LOCALAPPDATA%/mister_mcp/jobs`.
- Jobs run in a detached runner, so a job outlives the session that started it.

What this gives up: JTAG requests wait inside each script's `jtag_session` (as now) rather than
in one queue the server owns.

Inside it:

- **Jobs.**
  - Builds (15 to 98 minutes in the cores' logs) and long simulations return a job id at once.
  - `jobs.status`, `jobs.log` (tail), `jobs.result` and `jobs.cancel` work on any job.
  - Cancel kills the process tree (`quartus_fit`, `vsimk`), which a killed script does not do
    today.
- **Locks.**
  - `hwlock`'s three rules move into the daemon, with its file markers kept for scripts run
    outside it.
  - It queues rather than refuses: a probe read waits for the running fit to end, and new builds
    stand off.
  - `locks.status` says who holds what and why.
- **Core context.**
  - Every tool takes `core` (a repo name or path) and an optional `rev`.
  - The daemon resolves them with `coretools.py`.
  - It calls that core's own `scripts/`, so each core's local copy stays the truth.
- **Identity.** Every board tool checks the loaded core with `identity.py` first, and reports a
  mismatch instead of reading another core's probes.

## Tools (first cut, about 30)

**`mame.*`**
- `version`: binary against source tag.
- `listxml(set)`: cached.
- `dips(set)`
- `capture(set, frames, dips, inputs, script)`: returns a manifest and paths.
- `boot_trace(set, n)` and `sys_trace(set, frames)`.
- `snapshot(set, frame, view)`: records the orientation.
- `regions(set)`
- `run_lua(set, script, args)`: the escape hatch; always through `run.lua`, with `lua_error.txt`
  returned as the error.

**`build.*`**
- `start(core, rev, seed, allow_dirty)`: becomes a job.
- `report(core, rev)` returns:
  - the commit;
  - setup and hold slack per clock, and TNS;
  - ALMs, M10K and DSP, from the fit;
  - the worst paths;
  - the PLL counter sites.
- `synth_check(core, entity)`: `quartus_map` on one entity, with "Resource Utilization by
  Entity".
- `floorplan(core, rev)`

**`sim.*`**
- `list(core)`
- `run(core, bench, simulator, defines, plusargs)` returns:
  - pass or fail;
  - checks run, and the non-zero count;
  - the first error;
  - a log excerpt.
- `compare_boot(core, set)`
- `sweep()`: orphaned `vsimk`, stale `work/_lock`.

**`mister.*`**
- `deploy(core, rbf, mras)`:
  - refuses an `<rbf>` prefix that another `.rbf` on the device also matches;
  - checks that each `.mra`'s zips are present.
- `launch(mra)`: through `menu.rbf`, so the ROM really reloads.
- `screenshot(native)`
- `playing()`
- `osd(keys)`
- `ls`, `get`, `put`: scp with `-scp`, paths limited to `/media/fat/_Arcade`, `games`, `config`
  and `screenshots`.
- `devmem(addr, words)`
- `reboot()`: needs `confirm=true`.

**`probe.*`**
- `read(core, instance)`: under the lock and the identity check; fields decoded by the core's
  probe map.
- `write_source(core, instance, value)`: hex, read back.

## What it gives over the scripts

1. **One arbiter instead of messages between sessions.**
   - Today, JTAG against Quartus is enforced by marker files, plus sessions telling each other
     "no JTAG for 15 minutes". This conversation received several such messages.
   - A daemon queues the request and answers who holds the board.
2. **The lessons become checks the tools run, not text someone has to remember.** Each of these
   is a lesson that cost a build or a day:
   - refuse a board measurement while the loaded build fails timing;
   - refuse a MAME binary whose version is not the source's;
   - surface a Lua error;
   - refuse a comparison against a capture made with other inputs;
   - report a pass with zero non-zero samples as a non-test;
   - check the `<rbf>` prefix and the zips before a launch.
3. **Structured results.**
   - Slack per clock, pass counts and coverage come back as fields, not as a log for the model to
     grep.
   - Fewer tokens per step, and fewer misread logs. An example from this conversation: the
     floorplan needed a per-revision fit date, which is only in `.fit.summary`.
4. **Fewer invocation failures.** The scripts' failure modes in this conversation and in
   LESSONS_LEARNED were around the call, not inside the tool:
   - bash heredocs eating backslashes;
   - cwd not carried into background commands;
   - Quartus not on `PATH`;
   - `bash` resolving to WSL;
   - `nohup` hiding a run;
   - `pscp` falling back to SFTP.

   Typed arguments remove that layer.
5. **Narrower permissions.** Each tool can be allowed or denied on its own, instead of broad
   `Bash` rules: `mister.reboot` can stay ask-first while `mister.screenshot` is always allowed.
6. **One install for every core.** The scripts are copied into each repo and drift; a sibling
   core's `run.lua` wiring regressed in the skill's copy. The daemon is one copy of the
   orchestration, while each core keeps its own scripts.

## What it costs

- **A component to maintain.** It has to keep up with the scripts' arguments as they change.
  Mitigation: the daemon passes through to `scripts/` and parses their JSON output, so a script
  change needs no daemon change unless its interface does. That means first giving the scripts
  machine-readable output where they print text (`--json`).
- **Less flexibility for one-off work.** Ad hoc Lua, Tcl and `devmem` sessions remain. Keep
  `mame.run_lua`, a `build.tcl` hatch and Bash.
- **A daemon on Windows.** It needs to start, survive Quartus's crashes and recover jobs after its
  own restart. Job records go on disk, and a stale pid is cleared as `hwlock` already does.
- **Context.** About 30 tool schemas are loaded into every session that connects. Keep
  descriptions short, and let sessions that do not touch hardware leave the server off.
- **Credentials.** The MiSTer password moves from `mister.env` into the daemon's environment. Keep
  it bound to localhost only, and give no general `ssh` tool.
- **It fixes no tool.** A fitter that crashes at one seed still crashes. The daemon only makes the
  retry and the lock automatic.

## Phases

Each phase ends with one real core session using the new tools in place of the scripts.

1. **Skeleton.**
   - The daemon, `.mcp.json` registration, core context, jobs and locks (from `hwlock.py`).
   - Tools: `jobs.*`, `locks.status`.
   - Check: a build started from one session and a probe read from another queue correctly.
2. **Board.** `mister.*`, `probe.*`, `identity`. These are the calls made most often, and the ones
   whose mistakes are hardest to see (a release `.rbf` running instead of the build).
3. **Builds.** `build.*`, with `build.report` replacing the hand-reading of `.sta.summary` and the
   fit report.
4. **Simulation.** `sim.*`, giving `run_sim.sh` and `run_verilator.sh` a JSON summary line.
5. **MAME.** `mame.*`, the capture manifest and the input-match check.
6. **Skill.**
   - `SKILL.md` and `WORKFLOW.md` say to use the tools when the server is connected and the
     scripts otherwise.
   - `new_core.py` registers nothing per core; the daemon is per machine.

Measured after phase 2 against the sessions before it: failed or repeated tool calls, permission
prompts, and cross-session coordination messages per session. None of these have been measured
yet.

## Open decisions

- **Implementation:** Python (the official `mcp` SDK, the same language as the scripts) or
  TypeScript. Python is assumed above.
- **Machines:** whether MAME, Quartus and the board all stay on this PC. A second build machine
  would make the daemon a network service, with authentication.
- **Board access:** whether a general SSH command tool is wanted, or only the listed operations.
  Only the listed operations are assumed above.
- **Scope:** whether the coverage site's tooling (`hardware_local.py`, listxml) joins `mame.*`.
