"""Per-core parameters a core registers with the server: scripts/core.json and scripts/issp_fields.tcl.

The core keeps the files; core_register validates them and stores a copy in ~/.mister/cores/. The
server's scripts that need them (build, deploy, probes, STA) run from the registered copy, and
refuse while either file differs from what was registered, so an edit takes effect only through
core_register. A core with neither file runs on the defaults without registering.
"""
import hashlib
import json
import re
import time
from pathlib import Path

from . import jobs as J
from .cores import ToolError, coretools
from .issp_seq import field_tables

REG = J.STATE / "cores"
FILES = ("core.json", "issp_fields.tcl")
FORMATS = {"dec", "sdec", "hex", "bit"}
# the server's scripts that read the registered parameters (hw and identity through these)
USERS = {"build_staged.py", "deploy.py", "probe.py", "read_issp.py"}


def _paths(root):
    return {f: root / "scripts" / f for f in FILES}


def _digest(p):
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else None


def _record(root):
    return REG / f"{coretools.core_name(root)}.json"


def validate(root):
    """(config, tables, problems, warnings) from the core's files as they are now."""
    p = _paths(root)
    problems, warnings = [], []
    raw = {}
    if p["core.json"].exists():
        try:
            raw = json.loads(p["core.json"].read_text(encoding="utf-8"))
        except ValueError as e:
            problems.append(f"core.json: {e}")
        if not isinstance(raw, dict):
            problems.append("core.json: not a JSON object")
            raw = {}
    unknown = sorted(set(raw) - set(coretools.CONFIG_DEFAULTS))
    if unknown:
        problems.append(f"core.json: unknown keys {unknown}; known: {sorted(coretools.CONFIG_DEFAULTS)}")
    cfg = dict(coretools.CONFIG_DEFAULTS, **{k: v for k, v in raw.items() if k not in unknown})
    if cfg["mra_folder"] is not None and not (isinstance(cfg["mra_folder"], str)
                                              and re.fullmatch(r"_[^/\\]+", cfg["mra_folder"])):
        problems.append("mra_folder: a folder name starting with _ (or null for _<project>)")
    for k in ("held_back_sets", "required_instances"):
        if not (isinstance(cfg[k], list) and all(isinstance(x, str) and x for x in cfg[k])):
            problems.append(f"{k}: a list of strings")
    if not (isinstance(cfg["required_macros"], dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in cfg["required_macros"].items())):
        problems.append("required_macros: {macro: what breaks without it}")
    sc = cfg["stage_copies"]
    if not (isinstance(sc, list) and all(isinstance(c, list) and len(c) == 2 and all(isinstance(x, str) for x in c)
                                         for c in sc)):
        problems.append('stage_copies: [["source", "destination"], ...], relative to the repository')
    else:
        for s, _ in sc:
            if not (root / s).exists():
                problems.append(f"stage_copies: no {s} in the repository")
    if not (isinstance(cfg["probe_default_instance"], str) and re.fullmatch(r"\w+", cfg["probe_default_instance"])):
        problems.append("probe_default_instance: an ISSP instance id")
    if not (isinstance(cfg["sta_clock"], str) and cfg["sta_clock"]):
        problems.append("sta_clock: the clock name as the STA reports it")
    if cfg["mra_folder"] is None:
        cfg["mra_folder"] = "_" + coretools.project(root)
    releases = {m.stem for m in (root / "releases").rglob("*.mra")} if (root / "releases").is_dir() else set()
    missing = [s for s in cfg["held_back_sets"] if isinstance(s, str) and s not in releases]
    if missing:
        warnings.append(f"held_back_sets: no releases/**/<name>.mra for {missing}")

    tables = {}
    if p["issp_fields.tcl"].exists():
        text = p["issp_fields.tcl"].read_text(encoding="utf-8", errors="replace")
        if text.count("{") != text.count("}"):
            problems.append("issp_fields.tcl: unbalanced braces")
        tables = field_tables(p["issp_fields.tcl"])
        stated = re.findall(r"^\s*set\s+fields_(\w+)\b", text, re.M)
        unparsed = sorted(set(stated) - set(tables))
        if unparsed:
            problems.append(f"issp_fields.tcl: could not read fields_{', fields_'.join(unparsed)} "
                            "(rows are {name lo hi format}; a shared table is `set fields_B $fields_A`)")
        for m in re.finditer(r"^set fields_(\w+)\s*\{(.*?)^\}", text, re.S | re.M):
            written = re.findall(r"\{[^{}]*\}", re.sub(r"#[^\n]*", "", m.group(2)))
            if len(written) != len(tables.get(m.group(1), [])):
                problems.append(f"fields_{m.group(1)}: {len(written)} rows written, "
                                f"{len(tables.get(m.group(1), []))} read as {{name lo hi format}}")
        for tid, rows in tables.items():
            for name, lo, hi, fmt in rows:
                if lo > hi:
                    problems.append(f"fields_{tid} {name}: lo {lo} > hi {hi}")
                if fmt not in FORMATS:
                    problems.append(f"fields_{tid} {name}: format {fmt} is not one of {sorted(FORMATS)}")
        if tables and cfg["probe_default_instance"] not in tables:
            warnings.append(f"probe_default_instance {cfg['probe_default_instance']} has no fields_ table")
    return cfg, tables, problems, warnings


def register(root, branch=None):
    cfg, tables, problems, warnings = validate(root)
    if problems:
        raise ToolError("not registered:\n- " + "\n- ".join(problems))
    p = _paths(root)
    REG.mkdir(parents=True, exist_ok=True)
    name = coretools.core_name(root)
    (REG / f"{name}.core.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    tcl = REG / f"{name}.issp_fields.tcl"
    if p["issp_fields.tcl"].exists():
        tcl.write_bytes(p["issp_fields.tcl"].read_bytes())
    elif tcl.exists():
        tcl.unlink()
    rec = {"core": name, "root": str(root), "registered": time.strftime("%Y-%m-%d %H:%M:%S"),
           "branch": branch, "digests": {f: _digest(q) for f, q in p.items()},
           "config": cfg, "tables": {k: len(v) for k, v in tables.items()}}
    _record(root).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return dict(rec, warnings=warnings)


def status(root):
    """Registered or not, when, and which of the files changed since."""
    p = _paths(root)
    has = [f for f, q in p.items() if q.exists()]
    rec_path = _record(root)
    if not rec_path.exists():
        return {"registered": None, "files": has, "stale": [], "needed": bool(has)}
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    stale = [f for f, q in p.items() if _digest(q) != rec["digests"].get(f)]
    return {"registered": rec["registered"], "files": has, "stale": stale, "needed": bool(stale),
            "config": rec["config"], "tables": rec["tables"]}


def env(root):
    """CORE_CONFIG and ISSP_FIELDS for the server's scripts; refuses when not registered or stale."""
    st = status(root)
    name = coretools.core_name(root)
    if st["registered"] is None:
        if not st["files"]:
            return {}                                   # neither file: defaults, nothing to register
        raise ToolError(f"{name} has scripts/{' and scripts/'.join(st['files'])} but has not registered "
                        "them: call core_register")
    if st["stale"]:
        raise ToolError(f"scripts/{' and scripts/'.join(st['stale'])} changed since {name} registered "
                        f"them ({st['registered']}): call core_register")
    out = {"CORE_CONFIG": str(REG / f"{name}.core.json")}
    tcl = REG / f"{name}.issp_fields.tcl"
    if tcl.exists():
        out["ISSP_FIELDS"] = str(tcl)
    return out


def config(root):
    """The parameters the tools use now: the registered ones, or the defaults for a core with neither file."""
    e = env(root)
    if "CORE_CONFIG" in e:
        return json.loads(Path(e["CORE_CONFIG"]).read_text(encoding="utf-8"))
    return dict(coretools.CONFIG_DEFAULTS, mra_folder="_" + coretools.project(root))
