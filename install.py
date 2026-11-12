#!/usr/bin/env python3
"""The Mothership: one install for Skeleton Base (knowledge base) + Frugal-Bridge (token-saving rules).

Usage
  python3 install.py [install] [--base DIR] [--yes] [--no-frugal] [--watch|--no-watch] [--timer] [--mcp] [--dry-run]
                               [--force]
  python3 install.py check | status            [--base DIR]
  python3 install.py report [DAYS]             token usage of every tool Frugal-Bridge logs (its setup.py report)
  python3 install.py update                     [--base DIR] [--yes] [--force]
  python3 install.py uninstall                  [--base DIR] [--yes] [--keep-backups] [--no-backup] [--backup-dir DIR]
                                                [--purge [--yes-purge-BASENAME]]

uninstall first writes a full backup of the base (.git and dotfiles too) to ~/skeleton-base-backups/
NAME-YYYYmmdd-HHMMSS.tar.gz (mode 600) and prints a restore command; it removes only what the products added and
you did not change. --purge (delete the base) asks you to type the base's folder name, always backs up first.

Python 3.10+ standard library only. Works offline from the vendored copies in components/ (checked against
components.lock before anything is written). Nothing leaves your machine. See README.md and docs/DESIGN.md.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.2.0"
ROOT = Path(__file__).resolve().parent
LOCK = "components.lock"
STATE = ".mothership.json"
DEFAULT_BASE = "~/skeleton-base-home"
SB, FB = "skeleton-base", "frugal-bridge"
COMPONENTS = (SB, FB)
WATCH_UNITS = ["skeleton-base-watch.service", "skeleton-base-collect.timer", "skeleton-base-tidy.timer"]
TIMER_UNITS = ["skeleton-base-collect.timer", "skeleton-base-tidy.timer"]   # tidy: Skeleton Base 1.5.0+ connect
UNIT_DIR = ".config/systemd/user"
PAYLOAD = ("install.py", LOCK, "components", "LICENSE", "README.md", "CHANGELOG.md")
SKIP = {"__pycache__", ".git"}
BASE_START = "<!-- base-folder:start"
FRUGAL_START_RE = re.compile(r"<!-- frugal-bridge:start[^>]*-->")
PATH_RE = re.compile(r"<!-- base-folder:start[^>]*-->.*?^Path: *(.+?) *$", re.S | re.M)
BACKUPS_DIR = "skeleton-base-backups"     # under HOME, outside the base
# files in the base the products own (their removal or rewrite is expected); anything else that a product removed
# is put back from the backup archive. Unmodified kit files are recognised by their bytes.
OWNED = {".kits.json", STATE, "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".gitignore", ".claude/settings.json",
         ".gemini/settings.json", "maps/brain.canvas", "maps/brain.html", ".brain/map.json", ".brain/search.db",
         ".brain/watch.lock", ".brain/collector.lock", ".brain/kick"}
OWNED_PREFIXES = (".brain/pycache/",)
STEPS = ("stage", "base-init", "frugal-project", "connect", "frugal-global", "frugal-kit-key", "claude-access", "reconnect",
         "systemd", "checks")


class Fail(Exception):
    pass


# ------------------------------------------------------------------ small helpers
def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, UnicodeDecodeError):
        return None


def load_json(p, default=None):
    t = read(p)
    if t is None:
        return default
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return default


def dump(obj):
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_if_changed(p, text):
    p = Path(p)
    if read(p) != text:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)


def home():
    return Path(os.path.expanduser("~"))


def mothership_home():
    e = os.environ.get("MOTHERSHIP_HOME")
    if e:
        return Path(e).expanduser()
    x = os.environ.get("XDG_DATA_HOME")
    return (Path(x).expanduser() if x else home() / ".local" / "share") / "the-mothership"


def frugal_home():
    e = os.environ.get("FRUGAL_HOME")
    return Path(e).expanduser() if e else home() / ".frugal-bridge"


def platform_name():
    return os.environ.get("MOTHERSHIP_PLATFORM") or sys.platform


def is_linux():
    return platform_name().startswith("linux")


def sb_tools_table(root=ROOT):
    """Skeleton Base's own tool table (brain.py TOOLS, 1.4.0+) from the vendored copy; {} when it has none."""
    f = Path(root) / "components" / SB / "tools" / "brain.py"
    src = read(f) or ""
    if "\nTOOLS = " not in src:
        return {}
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("mothership_sb_brain", f)
        mod = importlib.util.module_from_spec(spec)
        old = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = old
        return dict(getattr(mod, "TOOLS", {}) or {})
    except Exception:                    # an unreadable table only costs the extra paths below
        return {}


def tool_rules_files():
    """User-level rules files Skeleton Base may connect (used to find an already connected base): every rules file
    of its tool table (all known tools), plus the fixed list older Skeleton Base releases used."""
    e, h = os.environ.get, home()
    c = Path(e("CLAUDE_CONFIG_DIR") or h / ".claude")
    x = Path(e("CODEX_HOME") or h / ".codex")
    m = Path(e("HERMES_HOME") or h / ".hermes")
    out = [c / "CLAUDE.md", x / "AGENTS.md", h / ".gemini/GEMINI.md", h / ".qwen/QWEN.md",
           h / ".config/opencode/AGENTS.md", h / ".codeium/windsurf/memories/global_rules.md",
           h / ".kiro/steering/skeleton-base.md", h / ".openclaw/workspace/AGENTS.md", m / "SOUL.md"]
    roots = {".claude": c, ".codex": x, ".hermes": m}
    for row in sb_tools_table().values():
        for rel, _how in row.get("rules") or ():
            first, rest = (rel.split("/", 1) + [""])[:2]
            f = (roots[first] / rest) if first in roots and rest else h / rel
            if f not in out:
                out.append(f)
    return out


def json_configs():
    """Tool settings files the products merge keys into (JSON has no blocks; they rewrite its formatting)."""
    e, h = os.environ.get, home()
    return [Path(e("CLAUDE_CONFIG_DIR") or h / ".claude") / "settings.json", h / ".gemini" / "settings.json"]


def test_hook(kind, step):
    """Fault injection for the test suite only: MOTHERSHIP_TEST_FAIL / MOTHERSHIP_TEST_KILL = step name."""
    if os.environ.get("MOTHERSHIP_TEST_FAIL") == step and kind == "fail":
        raise Fail(f"test failure injected after step {step}")
    if os.environ.get("MOTHERSHIP_TEST_KILL") == step and kind == "kill":
        sys.stdout.flush()
        os._exit(9)


# ------------------------------------------------------------------ lock and manifests
def iter_files(d):
    d = Path(d)
    for root, dirs, files in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x not in SKIP)
        for f in sorted(files):
            if f.endswith(".pyc"):
                continue
            p = Path(root) / f
            yield p.relative_to(d).as_posix(), p


def manifest_text(d):
    rows = sorted((rel, sha_bytes(p.read_bytes())) for rel, p in iter_files(d))
    return "".join(f"{h}  {rel}\n" for rel, h in rows)


def parse_manifest(text):
    out = {}
    for line in (text or "").splitlines():
        if "  " in line:
            h, rel = line.split("  ", 1)
            out[rel] = h
    return out


def verify_lock(root=ROOT):
    """[] when every vendored file matches components.lock, else one line per problem."""
    root = Path(root)
    lock = load_json(root / LOCK)
    if not isinstance(lock, dict) or not isinstance(lock.get("components"), dict):
        return [f"{LOCK} is missing or not valid JSON ({root / LOCK})"]
    probs = []
    for name in COMPONENTS:
        ent = lock["components"].get(name)
        if not ent:
            probs.append(f"{name}: not listed in {LOCK}")
            continue
        d = root / ent.get("path", f"components/{name}")
        mf = root / ent.get("manifest", f"components/{name}.manifest")
        if not d.is_dir():
            probs.append(f"{name}: vendored copy missing ({d.relative_to(root)}/)")
            continue
        stored = read(mf)
        if stored is None:
            probs.append(f"{name}: manifest missing ({mf.relative_to(root)})")
            continue
        if sha_bytes(stored.encode()) != ent.get("manifest_sha256"):
            probs.append(f"{name}: manifest does not match {LOCK} (manifest_sha256)")
        now = manifest_text(d)
        if now != stored:
            a, b = parse_manifest(stored), parse_manifest(now)
            diff = [f"changed {r}" for r in sorted(a) if r in b and a[r] != b[r]]
            diff += [f"missing {r}" for r in sorted(a) if r not in b]
            diff += [f"extra {r}" for r in sorted(b) if r not in a]
            more = f" (+{len(diff) - 8} more)" if len(diff) > 8 else ""
            probs.append(f"{name}: vendored files do not match the lock: " + ", ".join(diff[:8]) + more)
    return probs


def lock_summary(root=ROOT):
    lock = load_json(Path(root) / LOCK) or {}
    return {n: {k: e.get(k) for k in ("commit", "version", "manifest_sha256")}
            for n, e in sorted((lock.get("components") or {}).items())}


# ------------------------------------------------------------------ snapshots (created folders, backups)
def walk_dirs(root, depth):
    out = set()
    root = Path(root)
    if not root.is_dir():
        return out
    base = len(root.parts)
    for r, dirs, _ in os.walk(root):
        p = Path(r)
        out.add(str(p))
        if len(p.parts) - base >= depth:
            dirs[:] = []
    return out


def chain(p):
    """p and its parents up to (not including) the home folder."""
    out, p, h = [], Path(p), home()
    if h not in p.parents:
        return [p]
    while p != h and p != p.parent and h in p.parents:
        out.append(p)
        p = p.parent
    return out


def dir_roots(base):
    h, e = home(), os.environ.get
    roots = [h / ".claude", h / ".codex", h / ".gemini", h / ".qwen", h / ".config", h / ".hermes", h / ".openclaw",
             h / ".codeium", h / ".kiro", h / ".local/share", frugal_home(), mothership_home()]
    roots += [Path(v) for v in (e("CLAUDE_CONFIG_DIR"), e("CODEX_HOME"), e("HERMES_HOME"), e("OPENCLAW_STATE_DIR"),
                                e("COPILOT_HOME")) if v]
    for v in ((load_json(Path(base) / STATE, {}) or {}).get("options") or {}).get("tool_dirs") or []:
        roots.append(Path(v.partition("=")[2]))      # extra config dirs wired with --tool-dir
    return roots, [Path(base), frugal_home(), mothership_home()]


def dir_snapshot(base):
    roots, chains = dir_roots(base)
    s = set()
    for r in roots:
        s |= walk_dirs(r, 3)
    for c in chains:
        s |= {str(p) for p in chain(c) if p.is_dir()}
    return s


def backup_roots(base):
    return [frugal_home() / "backup", Path(base) / ".brain" / "backups", Path(base) / ".frugal-bridge" / "backup",
            Path(base) / ".base-folder" / "backup"]


def backup_snapshot(base):
    out = set()
    for r in backup_roots(base):
        if r.is_dir():
            out |= {str(x) for x in r.iterdir()}
    return out


def shq(s):
    s = str(s)
    return s if re.fullmatch(r"[A-Za-z0-9_./:@%+=,-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def archive_base(base, dest=None):
    """Write the WHOLE base (dotfiles, .git, everything) to DEST/BASENAME-TIME.tar.gz (mode 600, folder 700),
    outside the base; read it back to prove it is complete. Returns (archive path, number of files)."""
    import io
    import tarfile
    import time
    base = Path(base).resolve()
    dest = Path(os.path.expanduser(str(dest))).resolve() if dest else (home() / BACKUPS_DIR).resolve()
    if dest == base or base in dest.parents:
        raise Fail(f"backup: {dest} is inside the base {base}; pass --backup-dir DIR outside it")
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out, n = dest / f"{base.name}-{stamp}.tar.gz", 2
    while out.exists():
        out, n = dest / f"{base.name}-{stamp}-{n}.tar.gz", n + 1
    tmp = out.with_name("." + out.name + ".part")
    names = []
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as tar:
            tar.addfile(tar.gettarinfo(str(base), arcname=base.name))
            for cur, dirs, files in os.walk(base):
                dirs.sort()
                for name in dirs + sorted(files):
                    pth = Path(cur) / name
                    arc = base.name + "/" + pth.relative_to(base).as_posix()
                    ti = tar.gettarinfo(str(pth), arcname=arc)
                    if ti is None:
                        continue
                    if ti.isreg():
                        data = pth.read_bytes()
                        ti.size = len(data)
                        tar.addfile(ti, io.BytesIO(data))
                        names.append(arc)
                    else:
                        tar.addfile(ti)
                dirs[:] = [d for d in dirs if not (Path(cur) / d).is_symlink()]
            fh.flush()
            os.fsync(fh.fileno())
        with tarfile.open(tmp, "r:gz") as tar:
            got = sorted(m.name for m in tar if m.isreg())
        if got != sorted(names):
            raise Fail("backup: the archive did not read back complete")
        os.replace(tmp, out)
        os.chmod(out, 0o600)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    return out, len(names)


def archive_paths(paths, name, dest=None):
    """Put files/folders (absolute paths) into DEST/NAME-TIME.tar.gz (mode 600), stored under their full path."""
    import tarfile
    import time
    dest = Path(os.path.expanduser(str(dest))).resolve() if dest else (home() / BACKUPS_DIR).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out, n = dest / f"{name}-{stamp}.tar.gz", 2
    while out.exists():
        out, n = dest / f"{name}-{stamp}-{n}.tar.gz", n + 1
    tmp = out.with_name("." + out.name + ".part")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as tar:
            for pth in paths:
                tar.add(pth, arcname=str(pth).lstrip(os.sep))
        with tarfile.open(tmp, "r:gz") as tar:
            tar.getmembers()
        os.replace(tmp, out)
        os.chmod(out, 0o600)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    return out


def restore_line(archive, base):
    base = Path(base).resolve()
    return f"mkdir -p {shq(base.parent)} && tar -xpzf {shq(archive)} -C {shq(base.parent)}"


def file_index(base):
    """rel -> sha256 of every file in the base (symlinks: 'link:target'), .git excluded (never touched)."""
    out, base = {}, Path(base)
    if not base.is_dir():
        return out
    for cur, dirs, files in os.walk(base):
        c = Path(cur)
        if c == base and ".git" in dirs:
            dirs.remove(".git")
        links = [d for d in dirs if (c / d).is_symlink()]
        dirs[:] = [d for d in dirs if d not in links]
        for name in files + links:
            pth = c / name
            rel = pth.relative_to(base).as_posix()
            try:
                out[rel] = "link:" + os.readlink(pth) if pth.is_symlink() else sha_bytes(pth.read_bytes())
            except OSError:
                pass
    return out


def kit_hashes(*roots):
    out = set()
    for r in roots:
        if Path(r).is_dir():
            for _, f in iter_files(r):
                out.add(sha_bytes(f.read_bytes()))
    return out


def kept_report(base):
    base = Path(base)
    if not base.is_dir():
        return []
    lines = [f"Your data is kept in {base}:"]
    for p in sorted(base.iterdir(), key=lambda x: x.name):
        if p.name == ".git":
            n = "?"
            if shutil.which("git"):
                r = subprocess.run(["git", "-C", str(base), "rev-list", "--count", "--all"], capture_output=True,
                                   text=True)
                n = r.stdout.strip() if r.returncode == 0 else "?"
            lines.append(f"  .git/  git repository and history ({n} commits), untouched")
        elif p.is_dir() and not p.is_symlink():
            lines.append(f"  {p.name}/  {sum(1 for f in p.rglob('*') if f.is_file() or f.is_symlink())} file(s)")
        else:
            lines.append(f"  {p.name}")
    return lines


# ------------------------------------------------------------------ the installed products
def kits(base):
    return (load_json(Path(base) / ".kits.json", {}) or {}).get("kits", {}) or {}


def frugal_reg():
    r = load_json(frugal_home() / "global.json")
    return r if isinstance(r, dict) else None


def parse_path_value(v):
    """The folder in a `Path:` line: as it is, or wrapped in one of " ' ` (a path with spaces; no escaping)."""
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'`" and v[0] in v[1:]:
        if v[0] == '"' and v.endswith('"') and v.count('"') > 2:
            try:
                return json.loads(v)          # Skeleton Base's fallback for a path holding all three quotes
            except json.JSONDecodeError:
                pass
        return v[1:v.index(v[0], 1)]
    return v


def connected_base():
    for f in tool_rules_files():
        m = PATH_RE.search(read(f) or "")
        if m:
            d = Path(os.path.expanduser(parse_path_value(m.group(1))))
            if "base-folder" in kits(d):
                return d
    r = frugal_reg()
    if r and r.get("base") and "base-folder" in kits(r["base"]):
        return Path(r["base"])
    return None


def own_frugal_kit():
    """A Frugal-Bridge kit the user has on their own (Skeleton Base looks in the same places)."""
    reg = frugal_reg() or {}
    for c in (os.environ.get("FRUGAL_BRIDGE_KIT"), reg.get("kit"), str(home() / "frugal-bridge")):
        if c and (Path(c).expanduser() / "kit" / "setup.py").is_file():
            return Path(c).expanduser()
    return None


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "")))


def release_in(brain_py):
    m = re.search(r'^RELEASE *= *"([^"]+)"', read(brain_py) or "", re.M)
    return m.group(1) if m else None


def base_release(base):
    """(release, sha256 of tools/brain.py) of the Skeleton Base already in a folder. The release comes from
    .kits.json (kits.base-folder.release, 1.3.2+) or the RELEASE line of its brain.py; None = older or unknown."""
    b = Path(base) / "tools" / "brain.py"
    rel = (kits(base).get("base-folder") or {}).get("release") or release_in(b)
    return rel, (sha_bytes(b.read_bytes()) if b.is_file() else None)


def frugal_reads_quoted_paths(kit_dir):
    """Frugal-Bridge versions that read a quoted `Path:` value (a base path with spaces) have parse_base_path."""
    return "def parse_base_path" in (read(Path(kit_dir) / "kit" / "setup.py") or "")


def lint_lines(out):
    """The problem lines of `brain.py lint` output (its warning lines and the summary line left out)."""
    return [l for l in out.splitlines() if l.strip() and not l.startswith("warning:") and not l.startswith("lint (")]


def systemctl_ok():
    if not shutil.which("systemctl"):
        return False
    try:
        r = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def systemctl(*args):
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as ex:
        return 1, str(ex)


# ------------------------------------------------------------------ runner
class Mothership:
    def __init__(self, args):
        self.a = args
        self.log = []
        self.payload = mothership_home() / "payload"

    def say(self, msg):
        print(msg, flush=True)

    @property
    def sbk(self):
        return self.payload / "components" / SB

    @property
    def fbk(self):
        return self.payload / "components" / FB

    def run(self, cmd, env=None, cwd=None, check=True):
        e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        e.update(env or {})
        cmd = [str(c) for c in cmd]
        r = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=cwd)
        out = (r.stdout + r.stderr).rstrip()
        if self.a.verbose and out:
            self.say("    " + out.replace("\n", "\n    "))
        if check and r.returncode != 0:
            raise Fail(f"command failed ({r.returncode}): {' '.join(cmd)}\n{out}")
        return r.returncode, out

    def py(self, *a, **kw):
        return self.run([sys.executable, *a], **kw)

    # ---- which base
    def resolve_base(self, for_install):
        if self.a.base:
            return Path(os.path.abspath(os.path.expanduser(self.a.base)))
        j = load_json(mothership_home() / "journal.json")
        if j and j.get("base"):
            return Path(j["base"])
        i = load_json(mothership_home() / "installed.json")
        if i and i.get("base"):
            return Path(i["base"])
        if not for_install:
            raise Fail("The Mothership is not installed for this user (no installed.json); pass --base DIR")
        c = connected_base()
        if c:
            self.say(f"found an existing knowledge base: {c} (it will be adopted)")
            return c
        d = Path(os.path.expanduser(DEFAULT_BASE))
        if not self.a.yes and not self.a.dry_run and sys.stdin.isatty():
            ans = input(f"Where should your knowledge base live? [{d}] ").strip()
            if ans:
                d = Path(os.path.abspath(os.path.expanduser(ans)))
        return d

    # ---- install / update
    def install(self, update=False):
        probs = verify_lock(ROOT)
        if probs:
            raise Fail("components.lock check failed, nothing was installed:\n  " + "\n  ".join(probs)
                       + "\nGet a clean copy of The Mothership (or run tools/update-components.py) and retry.")
        base = self.resolve_base(True)
        if "\n" in str(base) or "\r" in str(base):
            raise Fail(f"the base path contains a line break: {base!r}")
        if base.exists() and not base.is_dir():
            raise Fail(f"{base} exists and is not a folder")
        mh = mothership_home()
        jpath = mh / "journal.json"
        journal = load_json(jpath)
        if journal and Path(journal.get("base", "")) != base:
            raise Fail(f"an unfinished install for another base is recorded in {jpath} ({journal.get('base')}); "
                       "run it again with that --base, or uninstall it first")
        prev = load_json(base / STATE)
        if update and not prev:
            raise Fail(f"nothing to update: {base / STATE} not found (run install first)")
        resumed = bool(journal)
        st = journal or prev or {}
        opts = {"frugal": True, "watch": True, "timer": False, "mcp": False}
        opts.update(st.get("options") or {})          # a re-run or update keeps the first install's choices
        if self.a.no_frugal:
            opts["frugal"] = False
        if self.a.watch is not None:
            opts["watch"] = self.a.watch
        if self.a.timer:
            opts["timer"] = True
        if self.a.mcp:
            opts["mcp"] = True                       # kept for re-runs and updates, like the other choices
        tdirs = list(opts.get("tool_dirs") or [])
        for v in (self.a.tool_dir or []) + ["claude-code=" + d for d in (self.a.claude_config_dir or [])]:
            name, eq, d = v.partition("=")
            if not eq or not name or not d:
                raise Fail(f"--tool-dir needs TOOL=DIR (got {v!r})")
            v = f"{name}={os.path.abspath(os.path.expanduser(d))}"
            if v not in tdirs:
                tdirs.append(v)
        if tdirs:
            opts["tool_dirs"] = tdirs                # one more config dir of a tool: kept for re-runs too
        if not is_linux():
            opts["watch"] = opts["timer"] = False
        own = dict(st.get("own") or {})
        k = kits(base)
        found = {"base": "base-folder" in k, "connect": bool((k.get("base-folder") or {}).get("connect")),
                 "frugal_project": "frugal-bridge" in k, "frugal_global": frugal_reg() is not None}
        for part, there in found.items():
            if part not in own:
                if there:
                    own[part] = "adopted"
                elif part in ("base", "connect") or opts["frugal"]:
                    own[part] = "installed"
        fresh = not prev and not resumed and not any(v == "adopted" for v in own.values())
        use_frugal = opts["frugal"] or own.get("frugal_global") == "adopted"
        if use_frugal and re.search(r"[\s\"'`$\\]", str(base)):
            kits_used = [ROOT / "components" / FB] + ([own_frugal_kit()] if own.get("frugal_global") == "adopted"
                                                       and own_frugal_kit() else [])
            old = [str(k) for k in kits_used if not frugal_reads_quoted_paths(k)]
            if old:
                raise Fail(f"the base path contains a space or quote: {base}\nSkeleton Base writes it quoted, but "
                           f"this Frugal-Bridge ({', '.join(old)}) reads the base path only up to the first space and "
                           "would keep a second user file. Pick a path without spaces (for example "
                           f"{home() / 'skeleton-base-home'}) and run again with --base, or use --no-frugal.")
        keep = self.newer_base(base)
        connect_flags = ["--watch"] if opts["watch"] else (["--timer"] if opts["timer"] else [])
        self.connect_extra = (["--mcp"] if opts.get("mcp") else []) + \
            [a for v in opts.get("tool_dirs") or [] for a in ("--tool-dir", v)]
        self.frugal_extra = [a for v in opts.get("tool_dirs") or [] for a in ("--tool-dir", v)] \
            if "--tool-dir" in (read(self.fbk / "kit" / "setup.py") or "") else []

        plan = self.plan(base, opts, own, connect_flags, keep)
        if self.a.dry_run:
            self.say("dry run: nothing is written. The install would:")
            for i, line in enumerate(plan, 1):
                self.say(f"  {i}. {line}")
            return 0

        old_components = (prev or {}).get("components") or {}
        st = {"mothership": VERSION, "base": str(base), "frugal_home": str(frugal_home()), "data": str(mh),
              "options": opts, "own": own, "kit_key": st.get("kit_key") or {"set": False},
              "systemd": st.get("systemd") or {"units": [], "enabled_by_us": []},
              "created_dirs": list(st.get("created_dirs") or []), "backups": list(st.get("backups") or []),
              "platform": "linux" if is_linux() else platform_name(),
              # what existed before: from the journal when resuming (the killed run may have made folders)
              "dirs_before": (journal or {}).get("dirs_before") or sorted(dir_snapshot(base)),
              "backups_before": (journal or {}).get("backups_before") or sorted(backup_snapshot(base)),
              # folders already in the base: never removed by uninstall or rollback, even when empty
              "base_dirs_before": st["base_dirs_before"] if "base_dirs_before" in st else
              [] if prev or not base.is_dir() else sorted(str(Path(r)) for r, _, _ in os.walk(base)),
              "originals": st["originals"] if "originals" in st else self.save_originals(),
              "claude_access": dict(st.get("claude_access") or {}),
              "base_kept": keep,
              # user-level rules files that did not exist yet: removed on uninstall when only whitespace is left
              "absent_before": st["absent_before"] if "absent_before" in st else
              sorted(str(f) for f in tool_rules_files() if not f.exists()),
              "done": list((journal or {}).get("done") or [])}
        self.st, self.base = st, base
        self.pre_archive = None
        if fresh and base.is_dir() and any(base.iterdir()):
            try:
                self.pre_archive, n = archive_base(base, self.a.backup_dir)
            except OSError as ex:
                raise Fail(f"could not back up the existing folder {base} first ({ex}); nothing was installed")
            self.say(f"- backup of the existing folder before installing: {self.pre_archive} ({n} files, mode 600)\n"
                     f"    restore: {restore_line(self.pre_archive, base)}")
        self.say(("resuming an interrupted install" if resumed else "updating" if update else "installing")
                 + f" The Mothership {VERSION} -> base {base}")
        self.save_journal()
        try:
            self.steps(base, opts, own, use_frugal, connect_flags, keep)
        except Fail as ex:
            if fresh:
                self.say(f"ERROR: {ex}\nrolling back what this install did ...")
                self.rollback()
                self.say("rolled back: nothing of this install is left (see above for any note).")
            else:
                self.say(f"ERROR: {ex}\nyour earlier install is kept as it was; fix the cause and run again "
                         f"(progress is in {jpath}).")
            return 3
        report = self.checks(base, quiet=True)
        self.finish()
        self.summary(base, report, old_components)
        return 0 if not report else 1

    def newer_base(self, base):
        """None, or what is kept: the base's Skeleton Base is newer than the vendored one (never downgraded
        unless --force)."""
        if "base-folder" not in kits(base):
            return None
        have, have_sha = base_release(base)
        vend_brain = ROOT / "components" / SB / "tools" / "brain.py"
        vend = release_in(vend_brain) or (load_json(ROOT / LOCK, {}) or {}).get("components", {}).get(SB, {}) \
            .get("version")
        if not have or have_sha == sha_bytes(vend_brain.read_bytes()) \
                or version_tuple(have) <= version_tuple(vend):
            return None
        if self.a.force:
            self.say(f"--force: Skeleton Base {have} in the base is replaced by the vendored {vend}")
            return None
        return {"release": have, "brain_sha256": have_sha, "vendored": vend}

    def plan(self, base, opts, own, flags, keep=None):
        p = [f"check {LOCK} against the vendored components", f"copy itself to {self.payload}"]
        if keep:
            p.append(f"keep Skeleton Base {keep['release']} in {base}: newer than the vendored {keep['vendored']} "
                     "(--force installs the vendored one)")
        else:
            p.append(("adopt and refresh" if own.get("base") == "adopted" else "install")
                     + f" Skeleton Base in {base} (brain.py init --frugal=no)")
        if opts["frugal"]:
            p.append(f"install Frugal-Bridge into the base (kit/setup.py install {base})")
        p.append("connect the base for this user and every AI tool found (Skeleton Base's tool table: one pointer "
                 "block per tool, the base on each tool's own allow list, Claude Code hooks"
                 + (", the base's MCP server in each tool's MCP config" if opts.get("mcp") else "")
                 + (", systemd user units (watcher + daily timer)" if flags == ["--watch"] else
                    ", a daily systemd user timer" if flags else "") + ")")
        if opts["frugal"]:
            p.append("install Frugal-Bridge for this user and every AI tool found (kit/setup.py install --global "
                     "--hosts auto: its hosts table; rules after the base block, hooks / plugins, helper tiers "
                     "model + effort), using the base as its user file")
        if is_linux() and flags:
            p.append("enable the units with systemctl --user (--yes) or print the command")
        elif not is_linux():
            p.append("no systemd on this system: the watcher is skipped (hooks still collect)")
        p.append("run checks (brain.py check + lint, Frugal-Bridge check, block order)")
        p.append(f"record everything in {base / STATE}")
        return p

    def save_originals(self):
        """Keep an exact copy of each existing JSON settings file (outside the base, mode 600). Uninstall puts these
        bytes back when the products' undo leaves the same JSON in a different layout."""
        out = {}
        d = mothership_home() / "originals"
        for i, f in enumerate(json_configs()):
            if f.is_file():
                d.mkdir(parents=True, exist_ok=True)
                os.chmod(d, 0o700)
                c = d / f"{i}-{f.parent.name.lstrip('.')}-{f.name}"
                c.write_bytes(f.read_bytes())
                os.chmod(c, 0o600)
                out[str(f)] = {"copy": str(c), "sha256": sha_bytes(f.read_bytes())}
        return out

    def restore_originals(self, originals):
        differs = []
        for f, info in sorted((originals or {}).items()):
            f, c = Path(f), Path(info["copy"])
            if not (f.is_file() and c.is_file()):
                continue
            orig, now = c.read_bytes(), f.read_bytes()
            if orig == now:
                continue
            try:
                same = json.loads(orig) == json.loads(now)
            except ValueError:
                same = False
            if same:
                f.write_bytes(orig)
                self.say(f"- {f}: your original layout restored (same settings)")
            else:
                differs.append(str(f))
                self.say(f"- {f}: differs from before the install (changed since?); left as it is")
        return differs

    def save_journal(self):
        write_if_changed(mothership_home() / "journal.json", dump(self.st))

    def track(self, step):
        """After each step: remember new folders and new backups, mark the step done (crash-safe)."""
        base = self.base
        now_dirs = dir_snapshot(base)
        new = sorted(set(self.st["created_dirs"]) | (now_dirs - set(self.st["dirs_before"])))
        self.st["created_dirs"] = new
        nb = backup_snapshot(base) - set(self.st["backups_before"])
        self.st["backups"] = sorted(set(self.st["backups"]) | nb)
        if step not in self.st["done"]:
            self.st["done"].append(step)
        self.save_journal()
        test_hook("kill", step)
        test_hook("fail", step)

    def steps(self, base, opts, own, use_frugal, flags, keep=None):
        # Frugal-Bridge's skill files in the base that you changed (compared with the kit that put them there,
        # before the new one is staged): its install would copy its own over them
        mine_sk = self.skill_edits(base, self.fbk if self.fbk.is_dir() else ROOT / "components" / FB)
        self.stage()
        self.track("stage")
        probs = verify_lock(self.payload)
        if probs:
            raise Fail("the staged copy does not match the lock:\n  " + "\n  ".join(probs))

        if keep:
            self.say(f"- Skeleton Base in the base: {keep['release']} is newer than the vendored {keep['vendored']}; "
                     "kept as it is (--force installs the vendored one)")
        else:
            self.say(f"- Skeleton Base: init {base}")
            self.py(self.sbk / "tools" / "brain.py", "init", base, "--frugal=no")
        self.track("base-init")

        if opts["frugal"]:
            k = kits(base).get("frugal-bridge") or {}
            if own.get("frugal_project") == "adopted" and str(k.get("version", "0")).isdigit() \
                    and int(k.get("version", "0")) > int(self.frugal_version()):
                self.say("- Frugal-Bridge in the base: a newer version is installed there; kept as it is")
            else:
                self.say("- Frugal-Bridge: install into the base")
                # its own default hosts minus "hermes": a project install for Hermes writes into the user's Hermes
                # home; the user-level install below covers Hermes properly (rules block + plugin)
                self.py(self.fbk / "kit" / "setup.py", "install", base, "--hosts", "claude-code,gemini")
                for f, data in mine_sk.items():
                    if not f.is_file() or f.read_bytes() != data:
                        f.parent.mkdir(parents=True, exist_ok=True)
                        f.write_bytes(data)
                        self.say(f"- kept your edited {f.relative_to(base)} (the kit's new version was not "
                                 "copied over it)")
        self.track("frugal-project")

        kit = self.frugal_kit_for_base(own)
        env = {"FRUGAL_BRIDGE_KIT": str(kit)} if (use_frugal and kit) else {}
        extra = getattr(self, "connect_extra", [])
        self.say("- Skeleton Base: connect for this user and every tool found " + " ".join(flags + extra))
        self.py(base / "tools" / "brain.py", "connect", "--base", base, *flags, *extra, env=env)
        self.track("connect")

        if opts["frugal"]:
            if own.get("frugal_global") == "adopted" and kit != self.fbk:
                self.say(f"- Frugal-Bridge for this user: already installed (its own kit {kit}); re-run by connect")
            else:
                self.say("- Frugal-Bridge: install for this user and every tool found (--global --hosts auto)")
                self.py(self.fbk / "kit" / "setup.py", "install", "--global", *self.frugal_hosts_arg(),
                        *getattr(self, "frugal_extra", []))
        self.track("frugal-global")

        self.set_kit_key(own)
        self.track("frugal-kit-key")

        self.claude_access(base)
        self.track("claude-access")

        self.py(base / "tools" / "brain.py", "connect", "--base", base, *flags, *extra, env=env)
        rc, out = self.py(base / "tools" / "brain.py", "map", "--root", base, check=False)   # redraw (import)
        if rc:                                       # a map file of yours is left alone: a note, not a failure
            self.say("- map: " + " ".join(l for l in out.splitlines() if "left alone" in l))
        self.track("reconnect")

        self.systemd(base, opts, flags)
        self.track("systemd")

    def claude_access(self, base):
        """Tool folder access is Skeleton Base's job since its 1.3.5: `connect` adds the base to every tool's own
        allow list (Claude Code permissions.additionalDirectories, Codex writable_roots, ...), records it and removes
        it on disconnect. An entry The Mothership 1.0.5 or older added itself is handed over: removed here, so the
        reconnect step right after adds it again as the base's own (one entry, one owner)."""
        if (self.st.get("claude_access") or {}).get("added"):
            self.claude_access_undo(self.st)
            self.say("- Claude Code access: now kept by Skeleton Base's connect (handed over)")
        self.st["claude_access"] = {}

    def claude_access_undo(self, st):
        ca = st.get("claude_access") or {}
        if not ca.get("added"):
            return
        f = Path(ca["file"])
        t = read(f)
        try:
            data = json.loads(t) if t and t.strip() else None
        except json.JSONDecodeError:
            self.say(f"- {f} is not valid JSON; remove {ca['dir']} from permissions.additionalDirectories by hand")
            return
        if not isinstance(data, dict):
            return
        perms = data.get("permissions") or {}
        lst = perms.get("additionalDirectories")
        if isinstance(lst, list) and ca["dir"] in lst:
            lst.remove(ca["dir"])
            if not lst and ca.get("created_list"):
                perms.pop("additionalDirectories")
            if not perms and ca.get("created_permissions"):
                data.pop("permissions", None)
            write_if_changed(f, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            self.say("- Claude Code: base removed from permissions.additionalDirectories")

    def frugal_hosts_arg(self):
        """`--hosts auto` when the vendored Frugal-Bridge has its hosts table (kit/hosts.py: every tool it knows,
        installed ones only); older kits pick their tools themselves."""
        return ["--hosts", "auto"] if (self.fbk / "kit" / "hosts.py").is_file() else []

    def frugal_version(self):
        m = re.search(r'^VERSION *= *"?(\d+)', read(self.fbk / "kit" / "setup.py") or "", re.M)
        return m.group(1) if m else "0"

    def frugal_kit_for_base(self, own):
        if own.get("frugal_global") == "adopted":
            return own_frugal_kit() or self.fbk
        return self.fbk

    def set_kit_key(self, own):
        """Skeleton Base's watcher re-runs Frugal-Bridge's setup when a new tool appears; it finds the kit
        through global.json "kit". Point it at the stable payload copy (only when nothing else is set)."""
        p = frugal_home() / "global.json"
        reg = frugal_reg()
        kk = self.st["kit_key"]
        if reg is None:
            return
        if own.get("frugal_global") == "adopted" and not kk.get("set"):
            if own_frugal_kit():
                return
            kk.update({"set": True, "previous": reg.get("kit")})
        elif not kk.get("set"):
            kk.update({"set": True, "previous": None})
        if reg.get("kit") != str(self.fbk):
            reg["kit"] = str(self.fbk)
            write_if_changed(p, json.dumps(reg, indent=2) + "\n")

    def stage(self):
        dst = self.payload
        if dst.resolve() == ROOT:
            return
        want = {}
        for name in PAYLOAD:
            src = ROOT / name
            if src.is_dir():
                for rel, p in iter_files(src):
                    want[f"{name}/{rel}"] = p
            elif src.is_file():
                want[name] = src
        for rel, src in want.items():
            t = dst / rel
            b = src.read_bytes()
            if not t.is_file() or t.read_bytes() != b:
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_bytes(b)
                shutil.copymode(src, t)
        if dst.is_dir():
            for rel, p in list(iter_files(dst)):
                if rel not in want:
                    p.unlink()
            for r, dirs, files in sorted(os.walk(dst), reverse=True):
                if r != str(dst) and not os.listdir(r):
                    os.rmdir(r)

    def systemd(self, base, opts, flags):
        if not flags:
            if not is_linux():
                self.say("- watcher: skipped (no systemd on this system). Hooks still collect at session end; to run "
                         f"the watcher by hand: python3 {base / 'tools' / 'brain.py'} watch")
            return
        units = WATCH_UNITS if flags == ["--watch"] else TIMER_UNITS
        # enable what this base's connect wrote (an older vendored base writes no tidy timer)
        units = [u for u in units if (home() / UNIT_DIR / u).is_file()] or units[:1]
        sd = self.st["systemd"]
        sd["units"] = sorted(set(sd["units"]) | set(units))
        cmd = "systemctl --user daemon-reload && systemctl --user enable --now " + " ".join(units)
        if not systemctl_ok():
            self.say(f"- systemd: systemctl --user is not available here. When it is, run:\n    {cmd}")
            return
        go = self.a.yes
        if not go and sys.stdin.isatty():
            go = input(f"Start the watcher now ({' '.join(units)})? [Y/n] ").strip().lower() in ("", "y", "yes")
        if not go:
            self.say(f"- systemd: not started. To start it:\n    {cmd}")
            return
        for u in units:
            if u not in sd["enabled_by_us"]:
                rc, out = systemctl("is-enabled", u)
                if rc == 0 and out.strip() == "enabled":
                    continue      # it was on before: not ours to switch off later
                sd["enabled_by_us"].append(u)
        rc, out = systemctl("daemon-reload")
        rc2, out2 = systemctl("enable", "--now", *units)
        if rc or rc2:
            self.say(f"- systemd: could not enable ({out or out2}); run by hand:\n    {cmd}")
        else:
            self.say(f"- systemd: enabled {' '.join(units)}")

    def finish(self):
        st = dict(self.st)
        for k in ("done", "dirs_before", "backups_before"):
            st.pop(k, None)
        st["components"] = lock_summary(self.payload)
        write_if_changed(self.base / STATE, dump(st))
        write_if_changed(mothership_home() / "installed.json", dump({"base": str(self.base)}))
        j = mothership_home() / "journal.json"
        if j.exists():
            j.unlink()

    def summary(self, base, report, old):
        new = lock_summary(self.payload)
        self.say("")
        for n, e in new.items():
            o = (old.get(n) or {}).get("commit")
            ch = f" (was {o[:12]})" if o and o != e["commit"] else ""
            self.say(f"{n} {e.get('version')} @ {str(e.get('commit'))[:12]}{ch}")
        keep = self.st.get("base_kept")
        if keep:
            self.say(f"note: the base keeps its newer Skeleton Base {keep['release']} (brain.py sha256 "
                     f"{str(keep['brain_sha256'])[:12]}); the vendored {keep['vendored']} was not installed over it "
                     "(--force does)")
        for line in self.tool_lines(base):
            self.say(line)
        self.say("checks: " + ("all OK" if not report else f"{len(report)} problem(s)"))
        for r in report:
            self.say("  FAIL " + r)
        self.show_warnings()
        self.say(f"\nYour knowledge base: {base}\n  open {base / 'hot.md'} (what matters now)\n"
                 f"  open {base / 'maps' / 'brain.html'} in a browser (mind map, offline)\n"
                 "  then ask any AI tool: \"interview me and fill wiki/me/, one question at a time\"\n"
                 f"  check: python3 {self.payload / 'install.py'} check   uninstall: python3 "
                 f"{self.payload / 'install.py'} uninstall")

    def tool_lines(self, base):
        """Which AI tools each product set up (from their own records)."""
        out = []
        conn = (kits(base).get("base-folder") or {}).get("connect") or {}
        if conn.get("blocks"):
            out.append("Skeleton Base connected: " + ", ".join(f"~/{r}" for r in sorted(conn["blocks"]))
                       + (" (+ MCP server)" if conn.get("mcp") or getattr(self, "connect_extra", None) else ""))
        reg = frugal_reg()
        if reg is not None:
            tools = sorted((reg.get("tools") or {}))
            if tools:
                out.append("Frugal-Bridge for: " + ", ".join(tools))
            nu = reg.get("needs_user") or {}
            if nu:
                out.append("Frugal-Bridge needs you for: " + ", ".join(sorted(nu)) + " (see its install output)")
        return out

    # ---- rollback / uninstall
    def rollback(self):
        st = dict(self.st)
        st["own"] = {k: v for k, v in st["own"].items() if v == "installed"}
        self.undo(st, keep_backups=False, rollback=True, archive=getattr(self, "pre_archive", None))

    def uninstall(self):
        base = self.resolve_base(False)
        st = load_json(mothership_home() / "journal.json")
        if not st or Path(st.get("base", "")) != base:
            st = load_json(base / STATE)
        if not st:
            raise Fail(f"no install record in {base / STATE}; nothing to remove")
        self.base = base
        name = base.name
        if self.a.purge:
            if st["own"].get("base") != "installed":
                raise Fail(f"{base} existed before The Mothership; --purge refuses to delete it. Remove it yourself.")
            if self.a.no_backup:
                raise Fail("--purge always writes a full backup first; it cannot be used with --no-backup")
            ok = self.a.yes_purge == name or bool(self.a.confirm_purge) and (
                Path(os.path.abspath(os.path.expanduser(self.a.confirm_purge))) == base or self.a.confirm_purge == name)
            if not ok and sys.stdin.isatty():
                ok = input(f"--purge deletes {base} with ALL your files (a full backup is written first).\n"
                           f"Type the folder name ({name}) to confirm: ").strip() == name
            if not ok:
                raise Fail(f"--purge needs confirmation: type the folder name ({name}) when asked, or pass "
                           f"--yes-purge-{name}. Nothing was changed.")
        sd = st.get("systemd") or {}
        if sd.get("enabled_by_us") and systemctl_ok():
            systemctl("stop", *sd["enabled_by_us"])      # the watcher must not write while the backup is taken
        archive = None
        if not base.is_dir():
            self.say(f"- backup: {base} does not exist; nothing to back up")
        elif self.a.no_backup:
            self.say("- backup: skipped (--no-backup)")
        else:
            try:
                archive, n = archive_base(base, self.a.backup_dir)
            except OSError as ex:
                raise Fail(f"backup failed, nothing was uninstalled: {ex}")
            self.say(f"- backup: {archive} ({n} files, mode 600, includes .git and dotfiles)\n"
                     f"    restore: {restore_line(archive, base)}")
        errors = self.undo(st, keep_backups=self.a.keep_backups, rollback=False, archive=archive)
        if self.a.purge and base.exists():
            shutil.rmtree(base)
            self.say(f"- purged {base}")
        elif base.is_dir():
            for line in kept_report(base):
                self.say(line)
            self.say(f"{base} is a plain folder of Markdown files: open it with any AI tool or editor as it is.\n"
                     f"To install again: python3 <the-mothership>/install.py --base {shq(base)}  (or "
                     f"python3 <skeleton-base>/tools/brain.py init {shq(base)}): your files are adopted, never "
                     "overwritten")
        elif not self.a.purge:
            self.say(f"- {base}: nothing of yours was left in it, so its empty folders were removed"
                     + (" (the full backup above has everything)" if archive else ""))
        if archive:
            self.say(f"Full backup from before the uninstall: {archive}\n  restore: {restore_line(archive, base)}")
        self.say("uninstalled" + (f" with {len(errors)} note(s)" if errors else ""))
        return 1 if errors else 0

    def undo(self, st, keep_backups, rollback, archive=None):
        base = Path(st["base"])
        own = st.get("own") or {}
        errors = []
        payload = Path(st.get("data") or mothership_home()) / "payload"
        sbk = payload / "components" / SB if (payload / "components" / SB).is_dir() else ROOT / "components" / SB
        fbk = payload / "components" / FB if (payload / "components" / FB).is_dir() else ROOT / "components" / FB
        bsnap = backup_snapshot(base)
        before = file_index(base)                       # what was in the base before the products' undo
        k0 = kits(base)
        known = kit_hashes(sbk, fbk) | {h for h in ((k0.get("base-folder") or {}).get("created") or {}).values()
                                        if isinstance(h, str) and len(h) == 64} \
            | {h for h in ((k0.get("frugal-bridge") or {}).get("template_hashes") or {}).values() if isinstance(h, str)}

        def step(label, fn):
            try:
                fn()
                self.say(f"- {label}")
            except (Fail, OSError, json.JSONDecodeError) as ex:
                errors.append(f"{label}: {ex}")
                self.say(f"- {label}: NOTE {ex}")

        sd = st.get("systemd") or {}
        if sd.get("enabled_by_us"):
            if systemctl_ok():
                step("systemd: disabled " + " ".join(sd["enabled_by_us"]),
                     lambda: systemctl("disable", "--now", *sd["enabled_by_us"]))
            else:
                self.say("- systemd: not reachable; if the units still run: systemctl --user disable --now "
                         + " ".join(sd["enabled_by_us"]))

        step("Claude Code access", lambda: self.claude_access_undo(st))
        brain = base / "tools" / "brain.py"
        brain = brain if brain.is_file() else sbk / "tools" / "brain.py"
        env = {"FRUGAL_BRIDGE_KIT": str(own_frugal_kit() if own.get("frugal_global") == "adopted" and own_frugal_kit()
                                        and own_frugal_kit() != fbk else fbk)}

        if own.get("frugal_global") == "installed" and frugal_reg() is not None:
            step("Frugal-Bridge: uninstall --global", lambda: self.py(fbk / "kit" / "setup.py", "uninstall", "--global"))
        if own.get("connect") == "installed" and (kits(base).get("base-folder") or {}).get("connect"):
            step("Skeleton Base: disconnect", lambda: self.py(brain, "disconnect", "--base", base, env=env))
        if (st.get("kit_key") or {}).get("set") and own.get("frugal_global") != "installed":
            reg = frugal_reg()
            if reg is not None and reg.get("kit") == str(fbk):
                prevk = st["kit_key"].get("previous")
                if prevk is None:
                    reg.pop("kit", None)
                else:
                    reg["kit"] = prevk
                write_if_changed(frugal_home() / "global.json", json.dumps(reg, indent=2) + "\n")
                self.say("- Frugal-Bridge: kit path in global.json restored")
        if own.get("frugal_project") == "installed" and "frugal-bridge" in kits(base):
            mine = self.skill_edits(base, fbk)            # Frugal-Bridge removes its skill folders whole
            step("Frugal-Bridge: uninstall from the base",
                 lambda: self.py(fbk / "kit" / "setup.py", "uninstall", base))
            for f, data in mine.items():
                if not f.exists():
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                    self.say(f"- kept {f} (you changed this Frugal-Bridge skill file)")
        if own.get("base") == "installed" and "base-folder" in kits(base):
            # the full backup was just written (or you said --no-backup): no second one
            step("Skeleton Base: uninstall", lambda: self.py(sbk / "tools" / "brain.py", "uninstall", base,
                                                             "--no-backup"))

        for f in (base / STATE,):
            if f.exists():
                f.unlink()
        differs = self.restore_originals(st.get("originals"))
        for f in st.get("absent_before") or []:
            t = read(f)
            if t is not None and not t.strip():
                os.remove(f)
                self.say(f"- removed {f} (empty; it did not exist before)")
        mh0 = Path(st.get("data") or mothership_home())
        if (mh0 / "originals").is_dir():
            if differs:
                self.say(f"- kept {mh0 / 'originals'}: your settings files from before the install (some changed "
                         "since, so they were not put back)")
            else:
                shutil.rmtree(mh0 / "originals")
        dropped = set()
        if not keep_backups:
            made = set(st.get("backups") or []) | (backup_snapshot(base) - bsnap)
            roots = [str(r) for r in backup_roots(base)]
            made = sorted(b for b in made if any(b.startswith(r + os.sep) for r in roots) and os.path.exists(b))
            if made:
                try:
                    arc = archive_paths(made, f"{base.name}-product-backups", self.a.backup_dir)
                except (OSError, Fail) as ex:
                    self.say(f"- kept {len(made)} backup folder(s) the products made in place (could not archive "
                             f"them: {ex})")
                else:
                    for b in made:
                        dropped |= {str(f) for f in ([Path(b)] if os.path.isfile(b) else Path(b).rglob("*"))}
                        shutil.rmtree(b) if os.path.isdir(b) else os.remove(b)
                    self.say(f"- moved {len(made)} backup folder(s) the products made during these runs into {arc} "
                             "(mode 600; --keep-backups leaves them in place)")
        mh = Path(st.get("data") or mothership_home())
        if payload.is_dir():
            shutil.rmtree(payload)       # also when running from it: Python already read this file
        for f in ("journal.json", "installed.json"):
            if (mh / f).exists() and (f != "installed.json" or Path((load_json(mh / f) or {}).get("base", ""))
                                      == base):
                (mh / f).unlink()
        keep_dirs = set(st.get("base_dirs_before") or [])
        if own.get("base") == "installed" and base.is_dir():
            for r, _, _ in sorted(os.walk(base), key=lambda t: -len(Path(t[0]).parts)):
                if ".git" in Path(r).relative_to(base).parts:
                    continue             # a git repository is never touched, not even its empty folders
                if Path(r) != base and str(Path(r)) not in keep_dirs:
                    try:
                        os.rmdir(r)      # only empty folders that were not there before the install
                    except OSError:
                        pass
        self.prune([d for d in (st.get("created_dirs") or []) if d not in keep_dirs])
        self.safety_net(base, before, known, dropped, archive)
        if rollback and base.is_dir():
            left = [p for p in base.rglob("*") if p.is_file()]
            if left:
                self.say(f"- kept {base}: {len(left)} file(s) in it (yours from before, or written by you since)")
        return errors

    def skill_edits(self, base, fbk):
        """Files under the base's .claude/skills/<Frugal-Bridge skill>/ that differ from the kit's: yours."""
        out = {}
        kit = fbk / "kit" / "skills"
        if not kit.is_dir():
            return out
        for sk in sorted(os.listdir(kit)):
            d = base / ".claude" / "skills" / sk
            if not d.is_dir():
                continue
            for f in d.rglob("*"):
                if f.is_file() and not f.is_symlink():
                    k = kit / sk / f.relative_to(d)
                    if not k.is_file() or k.read_bytes() != f.read_bytes():
                        out[f] = f.read_bytes()
        return out

    def safety_net(self, base, before, known, dropped, archive):
        """After the products' undo: a file that was in the base, is gone now and is not one of the products'
        own files is put back from the backup archive (a product must never take your data with it)."""
        now = file_index(base)
        lost = [rel for rel, h in sorted(before.items())
                if rel not in now and rel not in OWNED and not rel.startswith(OWNED_PREFIXES) and h not in known
                and str(base / rel) not in dropped]
        if not lost:
            return
        if not archive:
            for rel in lost:
                self.say(f"- WARNING: {base / rel} was removed by a product's uninstall and there is no backup "
                         "archive to put it back from")
            return
        import tarfile
        with tarfile.open(archive, "r:gz") as tar:
            for rel in lost:
                try:
                    m = tar.getmember(f"{base.name}/{rel}")
                except KeyError:
                    continue
                dst = base / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if m.issym():
                    os.symlink(m.linkname, dst)
                else:
                    dst.write_bytes(tar.extractfile(m).read())
                    os.chmod(dst, m.mode & 0o777)
                self.say(f"- put back {dst} from the backup (a product removed it; it is yours)")

    def prune(self, created):
        for d in sorted(created, key=lambda x: -len(Path(x).parts)):
            try:
                os.rmdir(d)           # only folders this install made, only when empty
            except OSError:
                pass

    # ---- check / status
    def checks(self, base, quiet=False):
        probs = []
        st = load_json(base / STATE) or getattr(self, "st", None) or {}
        for p in verify_lock(ROOT):
            probs.append(f"lock ({ROOT}): {p}")
        if self.payload.is_dir() and self.payload.resolve() != ROOT:
            for p in verify_lock(self.payload):
                probs.append(f"lock ({self.payload}): {p}")
        elif not self.payload.is_dir():
            probs.append(f"payload copy missing: {self.payload} (run install again)")
        if "base-folder" not in kits(base):
            return probs + [f"no Skeleton Base in {base}"]
        brain = base / "tools" / "brain.py"
        if not brain.is_file():
            return probs + [f"{brain} is missing (run install again)"]
        rc, out = self.py(brain, "check", cwd=base, check=False)
        if rc:
            probs.append("brain.py check: " + " | ".join(l for l in out.splitlines() if l and not l.startswith("OK")))
        rc, out = self.py(brain, "lint", cwd=base, check=False)
        self.warnings = []
        if rc:       # lint is about the pages you write: reported, never an install problem
            lines = lint_lines(out)
            summ = [l for l in out.splitlines() if l.startswith("lint (")]
            self.warnings = [f"lint: {l}" for l in lines] or [f"lint: {(summ or [out.strip() or 'failed'])[-1]}"]
        own = st.get("own") or {}
        frugal = (st.get("options") or {}).get("frugal", True)
        if frugal and "frugal-bridge" in kits(base):
            rc, out = self.py(self.fbk / "kit" / "setup.py", "check", base, check=False)
            if rc:
                probs.append("Frugal-Bridge check (base): " + " | ".join(out.splitlines()[1:4]))
        reg = frugal_reg()
        if frugal and reg is not None:
            rc, out = self.py(self.fbk / "kit" / "setup.py", "check", "--global", check=False)
            if rc:
                probs.append("Frugal-Bridge check --global: " + " | ".join(out.splitlines()[1:4]))
            if not reg.get("base") or Path(reg["base"]).resolve() != base.resolve():
                probs.append(f"Frugal-Bridge does not use the base as its user file (global.json base = "
                             f"{reg.get('base')}): run install again")
        elif frugal and own.get("frugal_global"):
            probs.append("Frugal-Bridge for this user is missing (global.json not found): run install again")
        conn = (kits(base).get("base-folder") or {}).get("connect") or {}
        if own.get("connect") and not conn:
            probs.append("the base is not connected for this user: run install again")
        h = Path(conn.get("home") or home())
        frugal_files = {Path(i.get("file")) for i in ((reg or {}).get("tools") or {}).values()}
        for rel in sorted((conn.get("blocks") or {})):
            f = h / rel
            t = read(f)
            if t is None:
                probs.append(f"{f}: missing (pointer block gone): run install again")
                continue
            n = t.count(BASE_START)
            if n != 1:
                probs.append(f"{f}: {n} base pointer blocks (want 1): run install again")
                continue
            m = FRUGAL_START_RE.search(t)
            if f in frugal_files:
                if not m:
                    probs.append(f"{f}: Frugal-Bridge block missing")
                elif m.start() < t.index(BASE_START):
                    probs.append(f"{f}: Frugal-Bridge block comes before the base block (want base first)")
                elif len(FRUGAL_START_RE.findall(t)) != 1:
                    probs.append(f"{f}: more than one Frugal-Bridge block")
        conn = (kits(base).get("base-folder") or {}).get("connect") or {}
        cs = Path(conn.get("home") or home()) / ".claude" / "settings.json"
        if ".claude/CLAUDE.md" in (conn.get("blocks") or {}) and cs.is_file():
            lst = ((load_json(cs, {}) or {}).get("permissions") or {}).get("additionalDirectories") or []
            if not any(isinstance(x, str) and Path(x).expanduser().resolve() == Path(base).resolve() for x in lst):
                probs.append(f"{cs}: the base is not in permissions.additionalDirectories (Claude Code "
                             "cannot read it from other folders): run install again")
        for r in sorted(conn.get("access") or {}):        # the other tools' allow lists (Codex, Gemini, ...)
            f = Path(conn.get("home") or home()) / r
            if f.is_file() and str(base) not in (read(f) or ""):
                probs.append(f"{f}: the base is not in this tool's allowed folders: run install again")
        sd = st.get("systemd") or {}
        if sd.get("enabled_by_us") and systemctl_ok():
            for u in sd["enabled_by_us"]:
                rc, out = systemctl("is-active", u)
                if out.strip() != "active":
                    probs.append(f"{u} is not running ({out.strip() or rc}): systemctl --user enable --now {u}")
        if not quiet:
            for p in probs:
                self.say("FAIL " + p)
        return probs

    def show_warnings(self, limit=20):
        w = getattr(self, "warnings", None) or []
        if not w:
            return
        self.say(f"warnings: {len(w)} lint issue(s) in your own pages (not an install problem; the install is "
                 "fine). Fix them when you like, then run: python3 tools/brain.py lint (in the base)")
        for x in w[:limit]:
            self.say("  WARN " + x)
        if len(w) > limit:
            self.say(f"  ... and {len(w) - limit} more")

    def report(self):
        """Frugal-Bridge's token-usage report (hooks, plugins and proxy logs of every tool) for the last DAYS."""
        kit = self.fbk if (self.fbk / "kit" / "setup.py").is_file() else ROOT / "components" / FB
        setup = kit / "kit" / "setup.py"
        if "report" not in (read(setup) or ""):
            raise Fail(f"this Frugal-Bridge ({setup}) has no usage report")
        cmd = [sys.executable, str(setup), "report"] + ([str(self.a.days)] if self.a.days else [])
        return subprocess.run(cmd, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).returncode

    def check(self):
        base = self.resolve_base(False)
        if not (base / STATE).exists():
            self.say(f"FAIL no install record in {base / STATE}")
            return 1
        probs = self.checks(base)
        self.show_warnings()
        w = len(getattr(self, "warnings", None) or [])
        self.say(f"check: {'OK' if not probs else str(len(probs)) + ' problem(s)'}"
                 + (f", {w} warning(s)" if w else "") + f" ({base})")
        return 1 if probs else 0

    def status(self):
        base = self.resolve_base(False)
        st = load_json(base / STATE)
        if not st:
            self.say(f"not installed in {base}")
            return 1
        self.say(f"The Mothership {st.get('mothership')}")
        self.say(f"base: {base}")
        for n, e in sorted((st.get("components") or {}).items()):
            self.say(f"component {n}: {e.get('version')} @ {e.get('commit')}")
        for part in ("base", "frugal_project", "connect", "frugal_global"):
            if part in st.get("own", {}):
                self.say(f"{part}: {st['own'][part]}")
        o = st.get("options") or {}
        self.say("options: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in sorted(o.items())))
        conn = (kits(base).get("base-folder") or {}).get("connect") or {}
        for rel in sorted(conn.get("blocks") or {}):
            self.say(f"connected: ~/{rel}")
        sd = st.get("systemd") or {}
        for u in sd.get("units") or []:
            state = "enabled by The Mothership" if u in (sd.get("enabled_by_us") or []) else "written, not enabled by it"
            self.say(f"unit {u}: {state}")
        for line in self.tool_lines(base):
            self.say(line)
        self.say(f"user file: {base / 'wiki' / 'me'}/ (one for every tool)")
        return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="install.py", description="The Mothership: Skeleton Base + Frugal-Bridge, "
                                "one install.")
    p.add_argument("command", nargs="?", default="install",
                   choices=("install", "check", "status", "update", "uninstall", "report"))
    p.add_argument("days", nargs="?", type=int, help="report: how many days back (default: Frugal-Bridge's)")
    p.add_argument("--base", help=f"the knowledge base folder (default {DEFAULT_BASE}, or the one already connected)")
    p.add_argument("--yes", "-y", action="store_true", help="no questions; run systemctl --user when available")
    p.add_argument("--no-frugal", action="store_true", help="only Skeleton Base")
    p.add_argument("--watch", dest="watch", action="store_true", default=None, help="watcher service (default on Linux)")
    p.add_argument("--no-watch", dest="watch", action="store_false")
    p.add_argument("--timer", action="store_true", help="daily collect timer (also comes with --watch)")
    p.add_argument("--tool-dir", action="append", metavar="TOOL=DIR",
                   help="one more config dir of a tool (e.g. claude-code=~/worker-claude), wired like its default "
                        "one by both products; repeatable, kept for re-runs")
    p.add_argument("--claude-config-dir", action="append", metavar="DIR", help="same as --tool-dir claude-code=DIR")
    p.add_argument("--mcp", action="store_true", help="also register the base's MCP server (brain.py mcp) in each "
                   "tool's MCP config (Skeleton Base connect --mcp; kept for later runs)")
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    p.add_argument("--force", action="store_true", help="install the vendored Skeleton Base even over a newer one")
    p.add_argument("--keep-backups", action="store_true",
                   help="uninstall: keep every backup folder the products made (by default only the ones whose "
                        "files are all back in place byte for byte are removed)")
    p.add_argument("--no-backup", action="store_true",
                   help="uninstall: do not write the full backup archive of the base first (not with --purge)")
    p.add_argument("--backup-dir", metavar="DIR", help=f"where the backup archive goes (default ~/{BACKUPS_DIR})")
    p.add_argument("--purge", action="store_true",
                   help="uninstall: also delete the base (asks for its folder name; backs it up first)")
    p.add_argument("--confirm-purge", metavar="NAME", help="non-interactive confirmation for --purge: the base's "
                   "folder name or full path (same as --yes-purge-NAME)")
    p.add_argument("--verbose", "-v", action="store_true", help="show the products' own output")
    p.add_argument("--version", action="version", version=f"The Mothership {VERSION}")
    argv = list(sys.argv[1:] if argv is None else argv)
    yes_purge = [x for x in argv if x.startswith("--yes-purge-")]
    argv = [x for x in argv if not x.startswith("--yes-purge-")]
    a = p.parse_args(argv)
    a.yes_purge = yes_purge[-1][len("--yes-purge-"):] if yes_purge else None
    m = Mothership(a)
    try:
        if a.command in ("install", "update"):
            return m.install(update=a.command == "update")
        if a.command == "uninstall":
            return m.uninstall()
        if a.command == "check":
            return m.check()
        if a.command == "report":
            return m.report()
        return m.status()
    except Fail as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted; run the same command again to continue", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
