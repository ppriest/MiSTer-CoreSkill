#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture machine state from MAME at a chosen frame.

    python scripts/mame_capture.py <set> --frame 1200 --name title
    python scripts/mame_capture.py <set> --frame 1200 --name flip --dip 'Flip Screen=On'

Writes debug/<set>-<name>/: one .bin per `read` region of scripts/mame/regions.json,
one reg_<name>.bin per `wtap` region (rebuilt from writes), MAME's screenshot and a
manifest. See scripts/mame/capture.lua for how each is obtained. --dip seeds a
per-capture cfg/<set>.cfg through scripts/mame/setdip.lua first (seed_dips).

The dumps are the strong reference: they are what the game wrote, and the RTL must
hold the same bytes. reference.png is MAME's rendering; where the driver is
MACHINE_IMPERFECT_GRAPHICS a pixel difference is a question, not a verdict, and is
settled in docs/MAME_KLUDGES.md.

The MAME helpers (regions.json, the command line, run.lua) are in coretools.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("CORE_ROOT") or Path(__file__).resolve().parent.parent)  # the MCP sets CORE_ROOT
LUA_DIR = REPO / "scripts" / "mame"
# The MAME helpers are coretools' (the skill's template, on PYTHONPATH), where a core's own
# scripts import them too; re-exported for the MCP's other MAME scripts.
from coretools import (NO_WINDOW, check_lua_error, extra_read_spec, input_env,  # noqa: E402,F401
                       lua_env, lua_runner_env, mame_cmd, mame_paths, regions, spec)
from coretools import rompath as _rompath  # noqa: E402


def rompath(mame_dir=None):
    return _rompath(REPO)


def seed_dips(exe, mame_dir, game, dips, out):
    """PASS 1 of a --dip capture: have MAME write cfg/<set>.cfg itself.

    MAME applies cfg/<set>.cfg at POWER-ON, before any autoboot script runs,
    and that is the only moment early enough: most games read their switches
    once during initialisation, so a DIP set from capture.lua never reaches
    them (Seta: with the DIP set from the capture script only, thunderl came
    back flipped and six other sets did not, while the sweep printed PASS).

    The cfg directory is per-capture (out/cfg), so the user's own MAME
    configuration is untouched. MAME saves a DIPSWITCH entry only when the
    wanted value is non-zero, so a switch whose "On" is 0 persists nothing;
    the <input> block is rebuilt from the port data setdip.lua reports,
    keeping the mameconfig version MAME itself wrote. Returns the cfg dir.
    """
    cfg_dir = out / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    # setdip.lua is its own error reporter (lua_error.txt, LUAFAIL), so it
    # runs directly rather than through run.lua.
    seed = [str(exe), game, "-nodebug", "-nowindow", "-video", "none", "-sound", "none",
            "-skip_gameinfo", "-nothrottle", "-autoboot_delay", "0",
            "-autoboot_script", str(LUA_DIR / "setdip.lua"),
            "-cfg_directory", cfg_dir.as_posix(),
            "-rompath", rompath(mame_dir), "-seconds_to_run", "10"]
    env = dict(os.environ, CORE_OUT=out.as_posix(), CORE_DIPS=";".join(dips))
    sr = subprocess.run(seed, cwd=mame_dir, env=env, capture_output=True, text=True,
                        timeout=300, **NO_WINDOW)
    for line in (sr.stdout or "").splitlines():
        if line.startswith("SEED") or line.startswith("LUAFAIL"):
            print("  " + line)
    check_lua_error(out)
    written = cfg_dir / f"{game}.cfg"
    info = out / "dipinfo.txt"
    if not written.exists() or not info.exists():
        print((sr.stdout or sr.stderr or "").strip()[-1200:])
        sys.exit(f"the DIP seed pass produced no {written.name} / {info.name}; "
                 f"nothing would be applied at power-on.")

    ports = []
    for line in info.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) == 4:
            tag, mask, defv, val = f[0], int(f[1]), int(f[2]), int(f[3])
            ports.append(f'            <port tag="{tag}" type="DIPSWITCH" '
                         f'mask="{mask}" defvalue="{defv}" value="{val}" />')
    if not ports:
        sys.exit(f"{info} named no ports; the DIP was never applied.")

    text = written.read_text(encoding="utf-8-sig", errors="replace")
    block = "        <input>\n" + "\n".join(ports) + "\n        </input>\n"
    if "<input>" in text:
        head, _, rest = text.partition("        <input>\n")
        _, _, tail = rest.partition("        </input>\n")
        text = head + block + tail
    else:
        anchor = f'<system name="{game}">\n'
        if anchor not in text:
            sys.exit(f"{written} has no <system name=\"{game}\"> element to seed.")
        text = text.replace(anchor, anchor + block, 1)
    written.write_text(text, encoding="utf-8")
    if "DIPSWITCH" not in written.read_text(encoding="utf-8", errors="replace"):
        sys.exit(f"no DIPSWITCH entry ended up in {written}; the capture would run "
                 f"with default switches and look like a success.")
    return cfg_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set", help="MAME set name")
    ap.add_argument("--frame", type=int, default=1200)
    ap.add_argument("--name", default=None, help="output label (default: the frame)")
    ap.add_argument("--seconds", type=int, default=None,
                    help="emulated seconds to run; default frame/60 + 10")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dip", action="append", default=[], metavar="NAME=SETTING",
                    help="set a DIP switch by its MAME field name before the game boots, "
                         "e.g. --dip 'Flip Screen=On'. Repeatable. An unknown name or "
                         "setting is an error, never a silent default.")
    ap.add_argument("--keep-going", action="store_true",
                    help="do not delete a previous capture of the same name")
    ap.add_argument("--coin", type=int, default=0,
                    help="insert a coin at this frame, press Start and play (as write_timing.py)")
    ap.add_argument("--regions", default=None,
                    help="regions profile in scripts/mame/ (default regions.json; sets CORE_REGIONS)")
    a = ap.parse_args()
    if a.regions:
        os.environ["CORE_REGIONS"] = a.regions

    mame_dir, exe = mame_paths()
    r = regions(a.set)
    out = Path(a.out) if a.out else REPO / "debug" / f"{a.set}-{a.name or a.frame}"
    if out.exists() and not a.keep_going:
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    seconds = a.seconds if a.seconds is not None else max(10, a.frame // 60 + 10)

    extra = ["-seconds_to_run", str(seconds)]
    if a.dip:
        extra += ["-cfg_directory", seed_dips(exe, mame_dir, a.set, a.dip, out).as_posix()]
    cmd = mame_cmd(exe, a.set, "capture.lua", mame_dir, extra)
    env = dict(os.environ, **lua_env(r), **lua_runner_env("capture.lua"),
               CORE_OUT=out.as_posix(), CORE_FRAME=str(a.frame),
               CORE_READ=spec(r.get("read", {})), CORE_WTAP=spec(r.get("wtap", {})),
               CORE_READ_EXTRA=extra_read_spec(r.get("read_extra", {})),
               CORE_PREV=spec(r.get("prev", {})), CORE_LINELOG=spec(r.get("linelog", {})),
               CORE_SCANLINE=str(r.get("scanline", "0")).replace("0x", ""),
               CORE_COIN=str(a.coin), **input_env(r))
    print(f"{a.set} frame {a.frame} -> {out}")
    p = subprocess.run(cmd, cwd=mame_dir, env=env, capture_output=True, text=True, **NO_WINDOW)
    blob = p.stdout + p.stderr
    if (out / "ERROR.txt").exists():
        sys.exit(f"capture.lua failed:\n{(out / 'ERROR.txt').read_text(encoding='utf-8')}")
    if "CORE_CAPTURE_OK" not in blob:
        tail = "\n".join(blob.strip().splitlines()[-15:])
        sys.exit(f"capture did not complete (no CORE_CAPTURE_OK).\n{tail}")
    print((out / "manifest.txt").read_text(encoding="utf-8").strip())
    print(f"{len(list(out.glob('*.bin')))} dumps + reference.png in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
