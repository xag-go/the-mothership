#!/usr/bin/env python3
"""Re-vendor the components and rewrite components.lock.

  python3 tools/update-components.py                       # both, from their public GitHub repos, default branch
  python3 tools/update-components.py --only skeleton-base --ref v1.3.1
  python3 tools/update-components.py --source frugal-bridge=/path/to/a/checkout   # local git checkout (committed
                                                            # files at --ref, default HEAD) or a plain folder
  python3 tools/update-components.py --check                # only verify the vendored files against the lock
  python3 tools/update-components.py --relock               # re-hash the trees as they are (after a local patch)
  python3 tools/update-components.py --exclude-words FILE   # leave out upstream files that contain a word from FILE
                                                            # (default: $MOTHERSHIP_BLOCKED_WORDS); listed in the lock
  python3 tools/update-components.py --upstream https://github.com/OWNER   # where the component repos live

The lock names each repo as https://github.com/<owner>/NAME, where <owner> is the owner of this repository's own
`origin` remote (or --upstream).

Needs git for GitHub and local checkouts. Standard library only. Review `git diff` before you commit.
"""
import argparse
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mothership_install", ROOT / "install.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

OWNER = "<owner>"
REPO_TEMPLATE = "https://github.com/" + OWNER + "/{name}"


def upstream_prefix(explicit=None):
    """https://github.com/OWNER of this repository's origin remote (components live next to it)."""
    if explicit:
        return explicit.rstrip("/")
    r = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True)
    m = re.search(r"github\.com[:/]([^/]+)/", r.stdout.strip())
    if r.returncode or not m:
        raise SystemExit("cannot tell where the component repositories live: no GitHub origin remote here; "
                         "pass --upstream https://github.com/OWNER or --source NAME=PATH")
    return f"https://github.com/{m.group(1)}"


def word_rx(w):
    return re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(w).replace(r"\ ", r"[\s_\-]+") + r"(?![A-Za-z0-9])")


def exclude_files(d, words_file):
    """Remove files whose path or text contains a listed word. Returns their paths."""
    words = [word_rx(l.strip()) for l in Path(words_file).read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    out = []
    for rel, p in list(M.iter_files(d)):
        text = rel + "\n" + p.read_bytes().decode("utf-8", errors="replace")
        if any(w.search(text) for w in words):
            p.unlink()
            out.append(rel)
    return sorted(out)


def git(*a, cwd=None):
    r = subprocess.run(["git", *a], capture_output=True, cwd=cwd)
    if r.returncode:
        raise SystemExit(f"git {' '.join(a)} failed: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def version_of(name, d):
    if name == "skeleton-base":
        m = re.search(r"^## *v?(\d+\.\d+(?:\.\d+)?)", M.read(d / "CHANGELOG.md") or "", re.M)
    else:
        m = re.search(r'^VERSION *= *"?([\w.]+)', M.read(d / "kit" / "setup.py") or "", re.M)
    return m.group(1) if m else "unknown"


def fetch(name, source, ref, dest, upstream=None):
    """Fill dest with the component's tracked files at ref. Returns (commit, vendored_from)."""
    with tempfile.TemporaryDirectory() as tmp:
        if source is None or re.match(r"^(https?|git|ssh)://|^git@", source):
            url = source or f"{upstream_prefix(upstream)}/{name}"
            git("clone", "--quiet", url, str(Path(tmp) / "repo"))
            repo, origin = Path(tmp) / "repo", "github" if source is None else "url"
        else:
            repo, origin = Path(source).expanduser().resolve(), "local"
            if not (repo / ".git").exists():
                shutil.copytree(repo, dest, ignore=shutil.ignore_patterns(*M.SKIP, "*.pyc"))
                return "unversioned-local-copy", origin
        commit = git("rev-parse", f"{ref or 'HEAD'}^{{commit}}", cwd=repo).decode().strip()
        data = git("archive", "--format=tar", commit, cwd=repo)
        dest.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(dest)
        return commit, origin


def lock_entry(name, d, commit, origin, repo, excluded=()):
    mf = M.manifest_text(d)
    (ROOT / "components" / f"{name}.manifest").write_text(mf, encoding="utf-8")
    return {"repo": repo, "commit": commit, "vendored_from": origin, "version": version_of(name, d),
            "path": f"components/{name}", "manifest": f"components/{name}.manifest",
            "manifest_sha256": M.sha_bytes(mf.encode()), "files": len(mf.splitlines()),
            "excluded": list(excluded)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=M.COMPONENTS)
    p.add_argument("--ref", help="branch, tag or commit (default: the default branch / HEAD)")
    p.add_argument("--source", action="append", default=[], metavar="NAME=PATH_OR_URL")
    p.add_argument("--check", action="store_true")
    p.add_argument("--relock", action="store_true")
    p.add_argument("--exclude-words", default=os.environ.get("MOTHERSHIP_BLOCKED_WORDS"), metavar="FILE")
    p.add_argument("--upstream", metavar="URL")
    a = p.parse_args(argv)
    if a.check:
        probs = M.verify_lock(ROOT)
        print("\n".join(probs) if probs else "components.lock: OK")
        return 1 if probs else 0
    lock = M.load_json(ROOT / M.LOCK) or {"lock_version": 1, "components": {}}
    sources = dict(s.split("=", 1) for s in a.source)
    for name in ([a.only] if a.only else M.COMPONENTS):
        d = ROOT / "components" / name
        old = lock["components"].get(name) or {}
        if a.relock:
            if not d.is_dir():
                raise SystemExit(f"{d} missing")
            commit = old.get("commit", "unknown")
            if not commit.endswith("+local-patch") and M.manifest_text(d) != (M.read(ROOT / old.get("manifest", "x"))
                                                                                 or ""):
                commit += "+local-patch"
            lock["components"][name] = lock_entry(name, d, commit, old.get("vendored_from", "local"),
                                                  old.get("repo", REPO_TEMPLATE.format(name=name)),
                                                  old.get("excluded", ()))
        else:
            with tempfile.TemporaryDirectory() as tmp:
                new = Path(tmp) / name
                commit, origin = fetch(name, sources.get(name), a.ref, new, a.upstream)
                excluded = exclude_files(new, a.exclude_words) if a.exclude_words else []
                if d.exists():
                    shutil.rmtree(d)
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(new, d, symlinks=True)
            lock["components"][name] = lock_entry(name, d, commit, origin, REPO_TEMPLATE.format(name=name), excluded)
        e = lock["components"][name]
        print(f"{name}: {e['version']} @ {e['commit']} ({e['files']} files, from {e['vendored_from']})"
              + (f"; was {old.get('commit')}" if old.get("commit") and old.get("commit") != e["commit"] else "")
              + (f"; left out: {', '.join(e['excluded'])}" if e.get("excluded") else ""))
    (ROOT / M.LOCK).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    probs = M.verify_lock(ROOT)
    print("components.lock: " + ("OK" if not probs else "PROBLEMS\n" + "\n".join(probs)))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
