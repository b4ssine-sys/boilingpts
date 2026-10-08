"""Build the browser version of the game for static hosting (Vercel).

    python scripts/build_web.py            stage the game, run pygbag, write public/
    python scripts/build_web.py --stage    only stage it (no network needed) and report

pygbag compiles Pygame to WebAssembly. It packages the whole folder it is given, so
this script first stages just what the game needs at runtime: main.py and the
modules it imports, strings.json and assets/. Tests, spikes, docs and this script
stay out of the download. The staged folder is named after the game because
pygbag takes the page and package names from it.
"""
import argparse
import ast
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "main.py"
DATA = ("strings.json", "assets")
APP_NAME = "tower-defense"
TITLE = "Tower Defense"          # same generic title as the desktop window until the real one is locked
STAGE_DIR = os.path.join(ROOT, "build", "stage", APP_NAME)
OUT_DIR = os.path.join(ROOT, "public")


def local_imports(entry=ENTRY, root=ROOT):
    """Every project module reachable from `entry`, as file names relative to root."""
    seen, todo = set(), [entry]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        with open(os.path.join(root, name), encoding="utf-8") as f:
            tree = ast.parse(f.read(), name)
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if os.path.isfile(os.path.join(root, m + ".py")):
                    todo.append(m + ".py")
    return seen


def stage(dest=STAGE_DIR, root=ROOT):
    """Copy the runtime files into `dest` (emptied first). Returns the staged file list."""
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for name in sorted(local_imports(ENTRY, root)):
        shutil.copy2(os.path.join(root, name), os.path.join(dest, name))
    for item in DATA:
        src = os.path.join(root, item)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, item), ignore=shutil.ignore_patterns("__pycache__", ".gitkeep"))
        else:
            shutil.copy2(src, os.path.join(dest, item))
    return sorted(os.path.relpath(os.path.join(d, f), dest) for d, _, fs in os.walk(dest) for f in fs)


def build():
    files = stage()
    size = sum(os.path.getsize(os.path.join(STAGE_DIR, f)) for f in files)
    print(f"staged {len(files)} files, {size / 1e6:.1f} MB, in {os.path.relpath(STAGE_DIR, ROOT)}")
    cmd = [sys.executable, "-m", "pygbag", "--build", "--title", TITLE, STAGE_DIR]
    print("running:", " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
    subprocess.run(cmd, check=True)
    built = os.path.join(STAGE_DIR, "build", "web")
    if not os.path.isfile(os.path.join(built, "index.html")):
        raise SystemExit(f"pygbag finished but {built}/index.html is missing")
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    shutil.copytree(built, OUT_DIR)
    print(f"wrote {os.path.relpath(OUT_DIR, ROOT)}/:", ", ".join(sorted(os.listdir(OUT_DIR))))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", action="store_true", help="only stage the files and print them")
    args = ap.parse_args()
    if args.stage:
        for f in stage():
            print(f)
    else:
        build()
