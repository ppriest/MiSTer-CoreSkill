#!/usr/bin/env python3
"""Bootstrap a new MiSTer arcade core repository from MiSTer-devel/Template_MiSTer.

    python new_core.py <Name> [--owner ppriest] [--root E:/] [--public] [--no-github]

Creates <root>/Arcade-<Name>_MiSTer:
  1. private <owner>/Arcade-<Name>_MiSTer generated from the template (gh REST API), cloned
     (or, with --no-github, a plain clone with history dropped)
  2. renames Template.{qpf,qsf,sdc,srf,sv} -> <Name>.*, adds the <Name>_stp revision, GPL-3.0 licence
  3. deletes the Quartus 13 project files
  4. copies this skill's assets/core/ tree (docs, scripts, .gitignore, CLAUDE.md, mister.env.example)
  5. commits
sys/ is never touched.
"""
import argparse, os, re, shutil, stat, subprocess, sys
from pathlib import Path

TEMPLATE = "MiSTer-devel/Template_MiSTer"
SKILL = Path(__file__).resolve().parent.parent
ASSETS = SKILL / "assets" / "core"


def gh_exe():
    for c in (shutil.which("gh"),
              Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/gh.exe",
              *Path(os.environ.get("LOCALAPPDATA", "")).glob("Microsoft/WinGet/Packages/GitHub.cli_*/bin/gh.exe"),
              Path("C:/Program Files/GitHub CLI/gh.exe")):
        if c and Path(c).exists():
            return str(c)
    return None


def run(cmd, cwd=None, check=True):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check)


def sub(path: Path, pattern, repl, count=0):
    s = path.read_text(encoding="utf-8", errors="surrogateescape")
    n, k = re.subn(pattern, repl, s, count=count)
    if k == 0:
        print(f"  warning: no match for {pattern!r} in {path.name}")
    path.write_text(n, encoding="utf-8", errors="surrogateescape")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="project name, e.g. Toaplan2; repo becomes Arcade-<Name>_MiSTer")
    ap.add_argument("--owner", default="ppriest")
    ap.add_argument("--root", default="E:/")
    ap.add_argument("--public", action="store_true", help="default is a private repo")
    ap.add_argument("--no-github", action="store_true", help="local clone of the template only")
    a = ap.parse_args()

    name = a.name
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name):
        sys.exit("name must be alphanumeric, starting with a letter (it becomes the Quartus revision)")
    repo = f"Arcade-{name}_MiSTer"
    root = Path(a.root)
    dest = root / repo
    if dest.exists():
        sys.exit(f"{dest} already exists")

    # 1. create
    gh = gh_exe()
    if a.no_github or not gh:
        if not a.no_github:
            print("gh not found; falling back to a local template clone (no GitHub repo created)")
        run(["git", "-c", "core.longpaths=true", "clone", "--depth", "1",
             f"https://github.com/{TEMPLATE}.git", str(dest)])
        def _rw(func, path, exc):  # git pack files are read-only on Windows
            os.chmod(path, stat.S_IWRITE); func(path)
        shutil.rmtree(dest / ".git", onexc=_rw)
        run(["git", "init", "-q", "-b", "main"], cwd=dest)
    else:
        # REST generate endpoint: `gh repo create --template` uses a GraphQL mutation that
        # fine-grained tokens are refused even with Administration: write.
        full = f"{a.owner}/{repo}"
        if subprocess.run([gh, "repo", "view", full], capture_output=True).returncode == 0:
            print(f"{full} already exists on GitHub; cloning it")
        else:
            r = run([gh, "api", "-X", "POST", f"repos/{TEMPLATE}/generate", "-f", f"owner={a.owner}",
                     "-f", f"name={repo}", "-F", f"private={'false' if a.public else 'true'}", "--silent"],
                    check=False)
            if r.returncode:
                sys.exit("repo creation refused: the gh token needs Administration and Contents "
                         "read/write on all of the owner's repositories, or use `gh auth login --web`")
        # GitHub generates the contents asynchronously; retry until the clone has them
        import time
        for _ in range(20):
            if dest.exists():
                shutil.rmtree(dest, onexc=lambda f, p_, e: (os.chmod(p_, stat.S_IWRITE), f(p_)))
            run(["git", "-c", "core.longpaths=true", "clone", "-q",
                 f"https://github.com/{full}.git", str(dest)], check=False)
            if (dest / "Template.qpf").exists():
                break
            time.sleep(3)
        else:
            sys.exit("template contents never arrived from GitHub")

    # 2. rename project files
    for ext in ("qpf", "qsf", "sdc", "srf", "sv"):
        (dest / f"Template.{ext}").rename(dest / f"{name}.{ext}")
    sub(dest / f"{name}.qpf", r'PROJECT_REVISION = "Template"',
        f'# {name}_stp is the instrumented revision (ISSP probes, OSD debug page); {name} the release.\n'
        f'PROJECT_REVISION = "{name}_stp"\nPROJECT_REVISION = "{name}"')
    sub(dest / f"{name}.sv", r'"Template;;"', f'"{name};;"', count=1)
    # GPL-3.0-or-later (assets/core/LICENSE); the template's GPLv2-or-later header allows it
    sub(dest / f"{name}.sv", r"\A//=+\n(?://.*\n)*?//=+\n",
        "// SPDX-License-Identifier: GPL-3.0-or-later\n", count=1)
    sub(dest / "files.qip", r"\bTemplate\.(sdc|sv)\b", rf"{name}.\1")
    stp = (dest / f"{name}.qsf").read_text(encoding="utf-8")
    stp = stp.replace('set_global_assignment -name SEED 1',
                      'set_global_assignment -name SEED 1\nset_global_assignment -name VERILOG_MACRO "DEBUG_ISSP=1"', 1)
    (dest / f"{name}_stp.qsf").write_text(stp, encoding="utf-8")

    # 3. drop the Quartus 13 project
    for p in list(dest.glob("Template_Q13.*")) + [dest / "rtl/pll/pll_0002_q13.qip"]:
        if p.exists():
            p.unlink()
    (dest / "Readme.md").unlink(missing_ok=True)

    # 4. skill assets
    for src in ASSETS.rglob("*"):
        rel = src.relative_to(ASSETS)
        out = dest / rel
        if src.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".template":
            out = out.with_suffix("")
            txt = src.read_text(encoding="utf-8").replace("{{NAME}}", name).replace("{{OWNER}}", a.owner)
            out.write_text(txt, encoding="utf-8")
        else:
            shutil.copy2(src, out)

    shutil.copy2(SKILL / "references" / "LESSONS_LEARNED.md", dest / "docs" / "LESSONS_LEARNED.md")

    # 5. commit
    run(["git", "add", "-A"], cwd=dest)
    run(["git", "commit", "-q", "-m", f"Bootstrap {name} from Template_MiSTer\n\n"
         f"Renamed project files, dropped the Quartus 13 project, added the {name}_stp revision, "
         f"docs/ and scripts/ from the mister-arcade-core skill.\n\n"
         f"Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"], cwd=dest)
    print(f"\n{dest} ready. Next: fill mister.env from mister.env.example, then docs/ROADMAP.md.")


if __name__ == "__main__":
    main()
