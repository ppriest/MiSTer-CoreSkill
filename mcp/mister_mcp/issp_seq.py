"""Job runner for probe_sequence: ISSP steps in one quartus_stp session under hwlock's JTAG lock,
the readings decoded with the field tables of the core's scripts/read_issp.tcl.

    python issp_seq.py <spec.json>

spec: root, scripts (directories to import hwlock, identity, coretools from), tcl (read_issp.tcl
for the field tables), steps ([{"read": id} | {"set": id, "value": v} | {"pulse": id, "value": v}
| {"clear": id} | {"sleep": seconds}]). Prints one JSON object as the last line.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path



def field_tables(tcl):
    """{instance id: [(name, lo, hi, fmt)]} from read_issp.tcl's `set fields_<id> {...}`."""
    text = Path(tcl).read_text(errors="replace") if tcl and Path(tcl).exists() else ""
    out = {}
    for m in re.finditer(r"^set fields_(\w+)\s*\{(.*?)^\}", text, re.S | re.M):
        rows = re.findall(r"\{\s*(\S+)\s+(\d+)\s+(\d+)\s+(\w+)\s*\}", m.group(2))
        out[m.group(1)] = [(n, int(lo), int(hi), f) for n, lo, hi, f in rows]
    return out


def decode(raw, table):
    n = len(raw)
    out = {}
    for name, lo, hi, fmt in table:
        v = 0
        for i in range(hi, lo - 1, -1):
            v = v * 2 + (raw[n - 1 - i] == "1" if n - 1 - i >= 0 else 0)
        if fmt == "sdec" and v >= 32768:
            v -= 65536
        out[name] = bool(v) if fmt == "bit" else f"0x{v:08X}" if fmt == "hex" else v
    return out


def tcl_steps(steps):
    lines = []
    for s in steps:
        if "read" in s:
            lines.append(f"read {s['read']}")
        elif "set" in s:
            lines.append(f"set {s['set']} {int(s['value'])}")
        elif "pulse" in s:
            lines.append(f"pulse {s['pulse']} {int(s['value'])}")
        elif "clear" in s:
            lines.append(f"clear {s['clear']}")
        elif "sleep" in s:
            lines.append(f"sleep {int(float(s['sleep']) * 1000)}")
        else:
            sys.exit(f"bad step {s}")
    return "\n".join(lines) + "\n"


def main():
    root = Path(spec["root"])
    tables = field_tables(spec.get("tcl"))
    with tempfile.TemporaryDirectory() as td:
        sf, of = Path(td) / "steps.txt", Path(td) / "out.txt"
        sf.write_text(tcl_steps(spec["steps"]))
        with jtag_session(f"probe_sequence ({len(spec['steps'])} steps)"):
            r = subprocess.run([str(quartus_stp(root)), "-t", spec["here_tcl"], str(sf), str(of)],
                               cwd=root, capture_output=True, text=True)
        out = of.read_text(errors="replace") if of.exists() else ""
    print((r.stdout + r.stderr)[-4000:], flush=True)
    reads, done = [], 0
    for ln in out.splitlines():
        p = ln.split(" ", 3)
        if p[0] == "READ" and len(p) == 4:
            rec = {"instance": p[1], "t_ms": int(p[2]), "raw": p[3].strip()}
            if p[1] in tables:
                rec["fields"] = decode(rec["raw"], tables[p[1]])
            reads.append(rec)
        elif p[0] == "OK":
            done += 1
    res = {"tag": prefix(root), "steps_done": done, "steps": len(spec["steps"]), "reads": reads,
           "no_table": sorted({x["instance"] for x in reads if "fields" not in x})}
    print(json.dumps(res))
    sys.exit(0 if r.returncode == 0 and done == len(spec["steps"]) else 1)


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for d in reversed(spec["scripts"]):
        sys.path.insert(0, d)
    from coretools import quartus_stp  # noqa: E402  (the core's own copies)
    from hwlock import jtag_session  # noqa: E402
    from identity import prefix  # noqa: E402
    main()
