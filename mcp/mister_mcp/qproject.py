"""Job runner for build_project: compile a standalone Quartus project (a synth harness, not a
revision of the core), in place or as a copy with the seed and clock periods changed.

    python qproject.py <spec.json>

spec: root, scripts (the directories to import hwlock and coretools from, in order), qpf, rev,
and for a copy: dest, seed, clocks ({clock name or port: period ns, "*" for every clock}).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


SKIP = {"db", "incremental_db", "output_files", "qdb", "greybox_tmp", "simulation"}
FILE_ASSIGN = re.compile(r"^(\s*set_global_assignment\s+-name\s+(\w+)\s+)(\"[^\"]*\"|\S+)(.*)$")


def copy_project(src, dest, seed, clocks):
    """Copy src to dest, pointing the .qsf's paths outside src at their absolute location, and
    set the seed and clock periods. Returns what was changed."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=lambda d, names: [n for n in names if n in SKIP])
    changed = []
    for qsf in dest.glob("*.qsf"):
        out = []
        for ln in qsf.read_text(errors="replace").splitlines():
            m = FILE_ASSIGN.match(ln)
            if m and (m.group(2).endswith("_FILE") or m.group(2) == "SEARCH_PATH"):
                v = m.group(3).strip('"')
                p = (src / v)
                if not Path(v).is_absolute() and p.exists() and src.resolve() not in p.resolve().parents:
                    ln = f'{m.group(1)}"{p.resolve().as_posix()}"{m.group(4)}'
            out.append(ln)
        text = "\n".join(out) + "\n"
        if seed is not None:
            if re.search(r"-name SEED \d+", text):
                text = re.sub(r"-name SEED \d+", f"-name SEED {seed}", text)
            else:
                text += f"set_global_assignment -name SEED {seed}\n"
            changed.append(f"{qsf.name}: SEED {seed}")
        qsf.write_text(text)
    found = set()
    for sdc in dest.rglob("*.sdc"):
        lines = sdc.read_text(errors="replace").splitlines()
        for i, ln in enumerate(lines):
            if not ln.lstrip().startswith("create_clock"):
                continue
            name = re.search(r"-name\s+\{?(\S+?)\}?(\s|$)", ln)
            port = re.search(r"\[get_(?:ports|pins)\s+\{?([^\]\}]+)\}?\]", ln)
            keys = {k for k in (name and name.group(1), port and port.group(1).strip()) if k}
            hit = next((k for k in clocks if k in keys), "*" if "*" in clocks else None)
            if hit is None or "-period" not in ln:
                continue
            new = re.sub(r"-period\s+[\d.]+", f"-period {clocks[hit]:.3f}", ln)
            if new != ln:
                lines[i] = new
                found.add(hit)
                changed.append(f"{sdc.relative_to(dest)}: {new.strip()}")
        sdc.write_text("\n".join(lines) + "\n")
    missing = sorted(set(clocks) - found)
    if missing:
        sys.exit(f"no create_clock -period for {', '.join(missing)} in the project's .sdc files")
    return changed


def main():
    qpf = Path(spec["qpf"])
    work = qpf.parent
    if spec.get("dest"):
        work = Path(spec["dest"])
        for c in copy_project(qpf.parent, work, spec.get("seed"), spec.get("clocks") or {}):
            print("changed:", c, flush=True)
    require_no_jtag(f"build_project {qpf.stem} {spec['rev']}")
    print(f"compiling {spec['rev']} in {work}", flush=True)
    r = subprocess.run([str(quartus_bin(Path(spec["root"])) / "quartus_sh.exe"), "--flow", "compile",
                        qpf.stem, "-c", spec["rev"]], cwd=work)
    sys.exit(r.returncode)


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for d in reversed(spec["scripts"]):
        sys.path.insert(0, d)
    from coretools import quartus_bin  # noqa: E402  (the core's own copies)
    from hwlock import require_no_jtag  # noqa: E402
    main()
