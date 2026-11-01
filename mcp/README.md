# mister_mcp

MCP server for MiSTer arcade cores: Quartus builds, ModelSim and Verilator, MAME and its Lua
scripts, the MiSTer (Remote API, one held SSH connection) and ISSP probes. Plan and rationale:
[`docs/MCP_PLAN.md`](../docs/MCP_PLAN.md).

## Scripts and per-core values

The scripts the tools run live here, in `mister_mcp/scripts/` (build_staged, build.sh, deploy,
hw, identity, probe, read_issp, floorplan, report_worst_paths, the MAME capture and trace
scripts, write_timing), and run with `CORE_ROOT` set to the core. They import `coretools` and
`hwlock` from the skill's template (`PYTHONPATH`). What differs per core is in the core:

| File | Keys |
|---|---|
| `scripts/core.json` | `mra_folder` (default `_<project>`), `held_back_sets`, `required_instances` (default `["hps_io"]`), `required_instances_by_rev`, `required_macros`, `stage_copies`, `probe_default_instance` (default `F`), `sta_clock` (default the framework's emu PLL output 0); defaults in `coretools.CONFIG_DEFAULTS` |
| `scripts/issp_fields.tcl` | `set fields_<id> {{name lo hi format} ...}` per probe instance; `set fields_B $fields_A` to share one; `fields_<id>_w<bits>` for a build whose bus has that width |
| `scripts/issp_hooks.tcl` (optional) | the core's own `probe_issp` actions: `proc hook_<name> {idx args} {...}`, run in the read's session after the decode, with `bits_to_int`, `write_src` and `read_probe_data` (KonamiGX's `dump` and `peek`, handshakes over a probe's source) |
| `scripts/floorplan.json`, `scripts/mame/regions.json` | floorplan groups; MAME regions to capture, trace and sweep |

**Registration.** `core_register` validates `core.json` (known keys, types, `stage_copies`
sources exist) `issp_fields.tcl` (every table and row parses, `lo <= hi`, known formats) and `issp_hooks.tcl`
(balanced, defines at least one `hook_<name>`), and
stores a copy in `~/.mister/cores/`. The server's build_staged, deploy, probe and read_issp run
with `CORE_CONFIG`, `ISSP_FIELDS` and `ISSP_HOOKS` naming that copy, `probe_sequence` and `build_worst_paths`
read it, and all of them refuse while either file in the core differs from what was registered
(`registry.py`). A core with neither file runs on the defaults without registering.
`core_config` shows the registered values, what changed since, and what the files would register
as now. The status page's Registered column shows the state per core.

A core that still has its own copy of a script (`scripts/<name>` in the core) runs that copy:
most older cores changed theirs beyond the per-core values, so each is migrated by moving its
values into the files above, folding generic changes into the server's copy, and deleting it.
`run_sim.sh` and `run_verilator.sh` stay per core (they list the core's RTL).

## Install

```bash
python -m venv E:/MiSTer-CoreSkill/mcp/.venv
```

```bash
E:/MiSTer-CoreSkill/mcp/.venv/Scripts/python.exe -m pip install -e E:/MiSTer-CoreSkill/mcp
```

The editable install (`-e`) puts `mister_mcp` on the venv's path whatever the working
directory.

One server serves every session: streamable HTTP on `http://127.0.0.1:8770/mcp`, localhost only,
no token. A scheduled task starts it at Windows boot, as the current user (S4U, no stored
password), and restarts it on failure. Install the task from an elevated PowerShell:

```bash
powershell -ExecutionPolicy Bypass -File E:/MiSTer-CoreSkill/mcp/install_service.ps1
```

Register it once per user:

```bash
claude mcp add --scope user --transport http mister http://127.0.0.1:8770/mcp
```

After changing the server's code, restart it. Whether a running session reconnects by itself
after a server restart is not tested yet; if its calls fail, reconnect with `/mcp`. A new or
renamed tool needs that reconnect in any case:

```bash
powershell -Command "Stop-ScheduledTask mister-mcp; Start-ScheduledTask mister-mcp"
```

Every tool call, from every session, is a line in `~/.mister/mcp/calls.jsonl` (time, tool,
arguments, seconds, ok/error, job id); `calls_log` reads it. The HTTP log is
`~/.mister/mcp/server.log`.

**State lives in `~/.mister` (`MISTER_STATE_DIR`), never `%LOCALAPPDATA%`.** The Claude desktop
app is a packaged (MSIX) app: Windows gives every process it starts, including Claude Code and
whatever a session runs from Bash, a private copy of `AppData\Local`
(`AppData\Local\Packages\Claude_*\LocalCache\Local`). Files written there are invisible to
this server, which runs outside the package, and the reverse for files the session has its own
copy of. The home directory is not redirected.

`mister-mcp.exe --stdio` runs a private copy
over stdio (the MCP Inspector, tests).

Settings come from the same places as the scripts', in order: the environment; the core's own keys
in `~/.mister-core.env`, written `<core>.<KEY>=value` (`Gaelco3D.MAME_EXE=gaelco3d.exe`; set them
with `core_settings_set`, see them with `core_settings`); the rest of
`~/.mister-core.env`. Scripts the server runs get a core's keys as environment variables, so a
core's older `coretools.py`, which ignores dotted keys, still sees them. The exception is the MiSTer connection
(`MISTER_HOST`, `MISTER_USER`, `MISTER_PASSWORD`): the environment or `~/.mister-core.env`
only, read on every call. Beyond the scripts' own (`MISTER_HOST`,
`MISTER_USER`, `MISTER_PASSWORD`, `MAME_DIR`, `MAME_SRC`, `QUARTUS_BIN`...):

| Setting | Default |
|---|---|
| `MISTER_CORES_DIR` | `MiSTer-Cores` and `MiSTer-Devel` beside this repository; several dirs joined by `;`. A core name found in two is refused: pass the path |
| `PYTHON` | the interpreter the venv was made from (the scripts need Pillow) |
| `MISTER_MCP_PORT` | `8770` |
| `MISTER_STATE_DIR` | `~/.mister`: JTAG markers, deploy log, jobs, call log. Read from the environment only (hwlock does not read the settings file) |
| `GIT_BASH` | `C:\Program Files\Git\bin\bash.exe`; never WSL's `bash` |

## How it runs

- **One process for the machine.** A second start exits while the port is served. State is on
  disk, so a server restart loses nothing:
  - jobs in `~/.mister/mcp/jobs/<id>/` (`job.json`, `log.txt`, `status.json`);
  - hwlock's JTAG markers and identity's deploy log in `~/.mister`, which the core scripts
    use themselves.
- **Tools run in a thread pool**, so a call waiting on `wait_s` holds up only its own caller.
- **The core's own `scripts/` run** when it has the script, so per-core edits (probe instance,
  `.mra` folder) hold. Otherwise the skill's template copy runs with `CORE_ROOT` set.
- **Long runs are jobs.** Builds, simulations, MAME runs, STA and probe reads start a detached
  runner, so a job survives the session that started it.
  - The tool waits up to `wait_s` (at most 240 s: Claude Code drops a call silent for 300 s),
    then returns the job id.
  - `jobs_status` gives the state, log tail and parsed `result`.
  - `jobs_cancel` kills the whole process tree.
  - A job's log streams over a WebSocket, `ws://127.0.0.1:8770/jobs/<id>/log?grep=<regex>&from=end|start|<line>`:
    one frame per line, then `END {"state", "returncode"}` on every terminal state, then close.
    `jobs_stream_url` returns it, for Claude Code's `Monitor(ws={url})`. Connections with a
    browser `Origin` that is not localhost are refused.
  - A server restart does not kill running jobs: two builds started by the previous server kept
    running through a `Stop-ScheduledTask`/`Start-ScheduledTask`. Runners also ask to leave the
    task's job object. Sessions see the server as disconnected for a few seconds.
- **One SSH connection to the MiSTer** (`link.py`, paramiko), opened on first use and again
  after it drops; every board command runs on it instead of a `plink` login each. File copies
  still use `pscp` (the MiSTer serves no SFTP). Host key: `~/.mister/known_hosts`, the first
  one seen is kept and a changed one refused.
- **The core on the MiSTer is read every 10 s** on that connection (slower, up to 120 s, while
  the board does not answer). `mister_state` returns that reading with its age, so asking costs
  the board nothing; `live=true` reads now. Launches and reboots trigger a read.
- **Board access is the listed operations only.**
  - No general shell.
  - `mister_get`/`mister_put` are limited to `/media/fat/{_Arcade,games,config,screenshots}`;
    `mister_get` also reads `/tmp/RBFNAME` and the like, and `mister_memdump`'s files.
  - `mister_put` is a job (`xfer.py`): upload to a hidden `.mcp-put-*.part`, size check, rename over
    the destination. A failed upload leaves the destination as it was; a cancelled one or a
    server-side crash can leave the `.part` file (no delete tool exists).
  - `mister_memdump` copies DDR3 ranges (below `0x40000000`, page-aligned) by mmap to a file it
    names, `/tmp/mcp/dump-<time>-<hex>.bin`: 73 MB in 2.3 s; fetching it with `mister_get` took
    12.3 s (`pscp`; a `cat` over the held connection took 11.0 s, so the board's SSH is the limit).
    `/tmp` is the board's RAM (246 MB), so `mister_get` deletes a dump once copied (`keep=true`
    leaves it), and the monitor deletes any in `/tmp/mcp` older than 10 minutes. Nothing else
    writes to `/tmp/mcp`.
  - `mister_install_main` writes only `/media/fat/MiSTer_<name>` (an alternate Main a
    `MiSTer.ini` section's `main=` names), never `/media/fat/MiSTer`. It refuses anything but
    a 32-bit ARM ELF, uploads to `.MiSTer_<name>.new`, checks the md5 on the board, keeps the old
    binary as `.prev` and renames over it; `restore=true` puts `.prev` back. A running copy keeps
    its inode and its `/proc/<pid>/exe` then reads `<path> (deleted)` (checked on the board's
    exFAT), so Main's path comparison (`user_io.cpp`) re-execs the new binary at the next launch
    of a core in that section. 1.3 MB installed in 3.8 s.
  - `mister_reboot` needs `confirm=true`.

## Status page

`http://127.0.0.1:8770/`, refreshed every 5 s (untick "auto refresh" to hold it still).
Read-only; a request whose Host or Origin is not this machine gets 403 (`web.py`).

Hardware sits above four tabs; the open tab is in the URL (`#jobs`, `#calls`, `#deploys`,
`#system`).

| Where | What it shows |
|---|---|
| Hardware | who holds the JTAG cable (USB-Blaster), who is queued for it, running Quartus/ModelSim processes. the core and set the MiSTer has loaded, from the server's 10 s monitor, with when it was read, since when that core has been up and whether the SSH connection is open; hover for the last 20 cores seen. "Read now" reads the board at once |
| Jobs | active jobs, then the last 60 from every session: start time, kind, core, state, elapsed, script. The tab's badge counts the running ones |
| Calls | the last 150 tool calls from every session: how long the call took, status (`error`, `ok`, or for a call that started a job the job's state now; "at return" when the job is older than the jobs list), the job id or the error. "errors only" for failures; the tab's badge counts them |
| Deploys | the last 30 lines of `mister_deployed.tsv` |
| System | server (pid, uptime, commit, state dir) and downloads; then every core: path, branch, running jobs, last tool call, `MAME_DIR`/`MAME_EXE`/`MAME_SRC`/`MAME_ROMPATH` with where each comes from (`core`, `machine`, `env`); a path that does not exist is struck through |

- **A job's log:** click its id (in jobs or calls). The drawer shows the last 400 lines and, while
  the job runs, follows new lines over the WebSocket; untick "follow" to scroll back. "Download
  log" saves the whole file.
- **Downloads:** each job's `log.txt`, `calls.jsonl`, `server.log`, `mister_deployed.tsv`, as
  they are at the moment of the click.
- **A banner** lists the server's own files (its modules, the template's `coretools.py` and
  `hwlock.py`) changed since it started: those need a restart. The page, the job runners and
  the core scripts are read fresh and do not.
- `/api/state` is the page's data as JSON; `/api/jobs/<id>?lines=N` one job with its log tail.

## Tools

Full reference with arguments: [`TOOLS.md`](TOOLS.md); the same as MCP JSON Schema in
[`tools.json`](tools.json). Both are generated by `gen_docs.py`: rerun it after changing a tool.
For interactive calls, use the MCP Inspector. It needs Node.js; open a new terminal after
installing it, so `PATH` has `npx`:

```bash
winget install OpenJS.NodeJS.LTS
```

```bash
npx @modelcontextprotocol/inspector E:/MiSTer-CoreSkill/mcp/.venv/Scripts/mister-mcp.exe --stdio
```

| Group | Tools |
|---|---|
| jobs | `cores_list`, `calls_log`, `jobs_list`, `jobs_status`, `jobs_log`, `jobs_stream_url`, `jobs_cancel`, `locks_status` |
| build | `build_start`, `build_project`, `build_report`, `build_worst_paths`, `build_floorplan` |
| sim | `sim_list`, `sim_run`, `sim_compare_boot`, `sim_sweep` |
| MAME | `mame_version`, `mame_capture`, `mame_boot_trace`, `mame_sys_trace`, `mame_run_lua`, `mame_listxml` |
| MiSTer | `mister_state`, `mister_check_mra`, `mister_deploy`, `mister_launch`, `mister_screenshot`, `mister_playing`, `mister_osd`, `mister_ls`, `mister_get`, `mister_put`, `mister_devmem`, `mister_memdump`, `mister_reboot` |
| probes | `probe_read`, `probe_issp`, `probe_sequence` |

Checks the tools add over the scripts:

- **`mame_version`** compares the binary against `git describe` of `MAME_SRC`, including commits
  past the release tag.
- **`mister_check_mra`** (also run by `mister_launch`) resolves the `.mra`'s `<rbf>` to the file
  the device would launch, and checks the ROM zips.
  - Both the `<name>_` and `Arcade-<name>_` forms are counted.
  - It refuses when nothing matches, when another file outranks the `3xxxxxxx` deploys, or when
    zips are missing.
- **`mame_run_lua`** always runs through `run.lua` and returns `lua_error.txt`. NVRAM and cfg
  are the run's own (in the output directory), never MAME's installed ones; `nvram` seeds them.
- **`build_project`** compiles a standalone harness project (not a core revision), in place or as
  a copy with SEED and `create_clock -period` changed, under the hwlock rule.
- **`probe_sequence`** runs clear/set/pulse/sleep/read steps in one `quartus_stp` session, with
  millisecond times, decoded with the core's `scripts/issp_fields.tcl` (or its own `read_issp.tcl`).
- **`sim_run`** flags `$readmem` warnings, and refuses a second ModelSim job on the same core.

## Tested

Run by hand against this machine, with no compile and no JTAG:
- tool registration;
- `cores_list`, `locks_status`, `build_report` and `sim_list` on BallySente;
- `mame_version`;
- `mister_state`, `mister_ls` and `mister_check_mra` on BallySente and KonamiHornet;
- the path and confirm refusals;
- job start, exit code, cancel;
- the WebSocket stream (grep, `from=start`, `END` on a failed job, origin refusal, unknown job);
- `mame_run_lua` with `out`, `clean`, `nvram`, `debug`, `fail_on` and `env` on BallySente;
- `build_project`'s copy (paths, SEED, clock periods) and `probe_sequence`'s step and field
  decoding, offline.

The status page: `/api/state`, downloads, the Host/Origin refusal, the log drawer following a
running build. The SSH link (connect, commands on the open connection, reconnect after a
dropped connection) and the 10 s monitor, through the boot-task server: `mister_state` answers
from the monitor in 0.01 s, `live=true` in 0.1 s.

Run through the boot-task server: `build_start` on DecoMLC (job done in 917 s, result parsed with
commit, timing and `.rbf`), and kept running through a server restart.

Not run yet: `build_project` and `probe_sequence` against Quartus and the board, `mister_deploy`,
`mister_screenshot`, the other `probe_*` tools.
