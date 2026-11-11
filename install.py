#!/usr/bin/env python3
"""The Mothership: one install for Skeleton Base (knowledge base) + Frugal-Bridge (token-saving rules).

Usage
  python3 install.py [install] [--base DIR] [--yes] [--no-frugal] [--watch|--no-watch] [--timer] [--dry-run]
  python3 install.py check | status            [--base DIR]
  python3 install.py update                     [--base DIR] [--yes]
  python3 install.py uninstall                  [--base DIR] [--yes] [--keep-backups] [--purge [--confirm-purge DIR]]

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

VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parent
LOCK = "components.lock"
STATE = ".mothership.json"
DEFAULT_BASE = "~/skeleton-base-home"
SB, FB = "skeleton-base", "frugal-bridge"
COMPONENTS = (SB, FB)
WATCH_UNITS = ["skeleton-base-watch.service", "skeleton-base-collect.timer"]
TIMER_UNITS = ["skeleton-base-collect.timer"]
PAYLOAD = ("install.py", LOCK, "components", "LICENSE", "README.md", "CHANGELOG.md")
SKIP = {"__pycache__", ".git"}
BASE_START = "<!-- base-folder:start"
FRUGAL_START_RE = re.compile(r"<!-- frugal-bridge:start[^>]*-->")
PATH_RE = re.compile(r"<!-- base-folder:start[^>]*-->.*?^Path: *(.+?) *$", re.S | re.M)
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


def tool_rules_files():
    """User-level rules files Skeleton Base may connect (used to find an already connected base)."""
    e, h = os.environ.get, home()
    c = Path(e("CLAUDE_CONFIG_DIR") or h / ".claude")
    x = Path(e("CODEX_HOME") or h / ".codex")
    m = Path(e("HERMES_HOME") or h / ".hermes")
    return [c / "CLAUDE.md", x / "AGENTS.md", h / ".gemini/GEMINI.md", h / ".qwen/QWEN.md",
            h / ".config/opencode/AGENTS.md", h / ".codeium/windsurf/memories/global_rules.md",
            h / ".kiro/steering/skeleton-base.md", h / ".openclaw/workspace/AGENTS.md", m / "SOUL.md"]


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
    roots += [Path(v) for v in (e("CLAUDE_CONFIG_DIR"), e("CODEX_HOME"), e("HERMES_HOME")) if v]
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
    return [frugal_home() / "backup", Path(base) / ".brain" / "backups", Path(base) / ".frugal-bridge" / "backup"]


def backup_snapshot(base):
    out = set()
    for r in backup_roots(base):
        if r.is_dir():
            out |= {str(x) for x in r.iterdir()}
    return out


# ------------------------------------------------------------------ the installed products
def kits(base):
    return (load_json(Path(base) / ".kits.json", {}) or {}).get("kits", {}) or {}


def frugal_reg():
    r = load_json(frugal_home() / "global.json")
    return r if isinstance(r, dict) else None


def connected_base():
    for f in tool_rules_files():
        m = PATH_RE.search(read(f) or "")
        if m:
            d = Path(os.path.expanduser(m.group(1).strip()))
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
        if re.search(r"\s", str(base)):
            raise Fail(f"the base path contains a space or tab: {base}\nBoth products write this path unquoted "
                       "into tool rules and hook commands. Pick a path without spaces (for example "
                       f"{home() / 'skeleton-base-home'}) and run again with --base.")
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
        opts = {"frugal": True, "watch": True, "timer": False}
        opts.update(st.get("options") or {})          # a re-run or update keeps the first install's choices
        if self.a.no_frugal:
            opts["frugal"] = False
        if self.a.watch is not None:
            opts["watch"] = self.a.watch
        if self.a.timer:
            opts["timer"] = True
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
        connect_flags = ["--watch"] if opts["watch"] else (["--timer"] if opts["timer"] else [])

        plan = self.plan(base, opts, own, connect_flags)
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
              "originals": st["originals"] if "originals" in st else self.save_originals(),
              "claude_access": dict(st.get("claude_access") or {}),
              "done": list((journal or {}).get("done") or [])}
        self.st, self.base = st, base
        self.say(("resuming an interrupted install" if resumed else "updating" if update else "installing")
                 + f" The Mothership {VERSION} -> base {base}")
        self.save_journal()
        try:
            self.steps(base, opts, own, use_frugal, connect_flags)
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

    def plan(self, base, opts, own, flags):
        p = [f"check {LOCK} against the vendored components", f"copy itself to {self.payload}"]
        p.append(("adopt and refresh" if own.get("base") == "adopted" else "install")
                 + f" Skeleton Base in {base} (brain.py init --frugal=no)")
        if opts["frugal"]:
            p.append(f"install Frugal-Bridge into the base (kit/setup.py install {base})")
        p.append("connect the base for this user: pointer blocks in your AI tools' user rules files, Claude Code "
                 "hooks" + (", systemd user units (watcher + daily timer)" if flags == ["--watch"] else
                            ", a daily systemd user timer" if flags else ""))
        if opts["frugal"]:
            p.append("install Frugal-Bridge for this user (kit/setup.py install --global), after the base block, "
                     "using the base as its user file")
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
                self.say(f"- {f}: differs from before the install (changed since?); left as it is")

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

    def steps(self, base, opts, own, use_frugal, flags):
        self.stage()
        self.track("stage")
        probs = verify_lock(self.payload)
        if probs:
            raise Fail("the staged copy does not match the lock:\n  " + "\n  ".join(probs))

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
                self.py(self.fbk / "kit" / "setup.py", "install", base)
        self.track("frugal-project")

        kit = self.frugal_kit_for_base(own)
        env = {"FRUGAL_BRIDGE_KIT": str(kit)} if (use_frugal and kit) else {}
        self.say("- Skeleton Base: connect for this user " + " ".join(flags))
        self.py(base / "tools" / "brain.py", "connect", "--base", base, *flags, env=env)
        self.track("connect")

        if opts["frugal"]:
            if own.get("frugal_global") == "adopted" and kit != self.fbk:
                self.say(f"- Frugal-Bridge for this user: already installed (its own kit {kit}); re-run by connect")
            else:
                self.say("- Frugal-Bridge: install for this user (--global)")
                self.py(self.fbk / "kit" / "setup.py", "install", "--global")
        self.track("frugal-global")

        self.set_kit_key(own)
        self.track("frugal-kit-key")

        self.claude_access(base)
        self.track("claude-access")

        self.py(base / "tools" / "brain.py", "connect", "--base", base, *flags, env=env)
        self.py(base / "tools" / "brain.py", "map", "--root", base)      # redraw with pages the import added
        self.track("reconnect")

        self.systemd(base, opts, flags)
        self.track("systemd")

    def claude_access(self, base):
        """Claude Code only reads files inside its working folder and its additionalDirectories. The base's
        pointer block tells it to read the base from any folder, so the base is added there (one list entry,
        recorded, removed again on uninstall). Only when the base is connected to Claude Code."""
        conn = (kits(base).get("base-folder") or {}).get("connect") or {}
        f = json_configs()[0]
        rel = (Path(os.environ.get("CLAUDE_CONFIG_DIR") or home() / ".claude") / "CLAUDE.md")
        try:
            rel = rel.relative_to(Path(conn.get("home") or home())).as_posix()
        except ValueError:
            rel = str(rel)
        if rel not in (conn.get("blocks") or {}):
            return
        t = read(f)
        try:
            data = json.loads(t) if t and t.strip() else {}
        except json.JSONDecodeError:
            self.say(f"- {f} is not valid JSON: Claude Code access to the base not added (fix the file, re-run)")
            return
        ca = self.st.setdefault("claude_access", {})
        if ca.get("file") and ca["file"] != str(f):
            return
        perms = data.get("permissions")
        if perms is None:
            perms = data["permissions"] = {}
            ca.setdefault("created_permissions", True)
        lst = perms.get("additionalDirectories")
        if lst is None:
            lst = perms["additionalDirectories"] = []
            ca.setdefault("created_list", True)
        ca["file"], ca["dir"] = str(f), str(base)
        if str(base) not in lst:
            lst.append(str(base))
            ca["added"] = True
            write_if_changed(f, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            self.say(f"- Claude Code: the base is readable from any folder (permissions.additionalDirectories)")
        ca.setdefault("added", False)

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
        self.say("checks: " + ("all OK" if not report else f"{len(report)} problem(s)"))
        for r in report:
            self.say("  FAIL " + r)
        self.say(f"\nYour knowledge base: {base}\n  open {base / 'hot.md'} (what matters now)\n"
                 f"  open {base / 'maps' / 'brain.html'} in a browser (mind map, offline)\n"
                 "  then ask any AI tool: \"interview me and fill wiki/me/, one question at a time\"\n"
                 f"  check: python3 {self.payload / 'install.py'} check   uninstall: python3 "
                 f"{self.payload / 'install.py'} uninstall")

    # ---- rollback / uninstall
    def rollback(self):
        st = dict(self.st)
        st["own"] = {k: v for k, v in st["own"].items() if v == "installed"}
        self.undo(st, keep_backups=False, rollback=True)

    def uninstall(self):
        base = self.resolve_base(False)
        st = load_json(mothership_home() / "journal.json")
        if not st or Path(st.get("base", "")) != base:
            st = load_json(base / STATE)
        if not st:
            raise Fail(f"no install record in {base / STATE}; nothing to remove")
        self.base = base
        if self.a.purge:
            if st["own"].get("base") != "installed":
                raise Fail(f"{base} existed before The Mothership; --purge refuses to delete it. Remove it yourself.")
            ok = self.a.confirm_purge and Path(os.path.abspath(os.path.expanduser(self.a.confirm_purge))) == base
            if not ok and sys.stdin.isatty():
                ok = input(f"--purge deletes {base} with ALL your pages. Type its full path to confirm: ").strip() \
                    == str(base)
            if not ok:
                raise Fail(f"--purge needs confirmation: --confirm-purge {base} (or type the path when asked)")
        errors = self.undo(st, keep_backups=self.a.keep_backups, rollback=False)
        if self.a.purge and base.exists():
            shutil.rmtree(base)
            self.say(f"- purged {base}")
        self.say("uninstalled" + (f" with {len(errors)} note(s)" if errors else ""))
        return 1 if errors else 0

    def undo(self, st, keep_backups, rollback):
        base = Path(st["base"])
        own = st.get("own") or {}
        errors = []
        payload = Path(st.get("data") or mothership_home()) / "payload"
        sbk = payload / "components" / SB if (payload / "components" / SB).is_dir() else ROOT / "components" / SB
        fbk = payload / "components" / FB if (payload / "components" / FB).is_dir() else ROOT / "components" / FB
        bsnap = backup_snapshot(base)

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
            step("Frugal-Bridge: uninstall from the base",
                 lambda: self.py(fbk / "kit" / "setup.py", "uninstall", base))
        if own.get("base") == "installed" and "base-folder" in kits(base):
            step("Skeleton Base: uninstall", lambda: self.py(sbk / "tools" / "brain.py", "uninstall", base))

        for f in (base / STATE,):
            if f.exists():
                f.unlink()
        self.restore_originals(st.get("originals"))
        mh0 = Path(st.get("data") or mothership_home())
        if (mh0 / "originals").is_dir():
            shutil.rmtree(mh0 / "originals")
        if not keep_backups:
            made = set(st.get("backups") or []) | (backup_snapshot(base) - bsnap)
            roots = [str(r) for r in backup_roots(base)]
            for b in sorted(made):
                if any(b.startswith(r + os.sep) for r in roots) and os.path.exists(b):
                    shutil.rmtree(b) if os.path.isdir(b) else os.remove(b)
            if made:
                self.say(f"- removed {len(made)} backup folder(s) the products made during these runs "
                         "(--keep-backups keeps them)")
        mh = Path(st.get("data") or mothership_home())
        if payload.is_dir():
            shutil.rmtree(payload)       # also when running from it: Python already read this file
        for f in ("journal.json", "installed.json"):
            if (mh / f).exists() and (f != "installed.json" or Path((load_json(mh / f) or {}).get("base", ""))
                                      == base):
                (mh / f).unlink()
        if own.get("base") == "installed" and base.is_dir():
            for r, _, _ in sorted(os.walk(base), key=lambda t: -len(Path(t[0]).parts)):
                if Path(r) != base:
                    try:
                        os.rmdir(r)      # only empty folders inside the base this install made
                    except OSError:
                        pass
        self.prune(st.get("created_dirs") or [])
        if base.is_dir() and own.get("base") == "installed":
            left = [p for p in base.rglob("*") if p.is_file()]
            if left:
                self.say(f"- kept {base}: {len(left)} file(s) you wrote or changed (--purge deletes them)")
        return errors

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
        if rc:
            probs.append("brain.py lint: " + out.splitlines()[-1] if out else "brain.py lint failed")
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
        ca = st.get("claude_access") or {}
        if ca.get("added"):
            lst = ((load_json(ca["file"], {}) or {}).get("permissions") or {}).get("additionalDirectories") or []
            if ca["dir"] not in lst:
                probs.append(f"{ca['file']}: the base is not in permissions.additionalDirectories (Claude Code "
                             "cannot read it from other folders): run install again")
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

    def check(self):
        base = self.resolve_base(False)
        if not (base / STATE).exists():
            self.say(f"FAIL no install record in {base / STATE}")
            return 1
        probs = self.checks(base)
        self.say(f"check: {'OK' if not probs else str(len(probs)) + ' problem(s)'} ({base})")
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
        self.say(f"user file: {base / 'wiki' / 'me'}/ (one for every tool)")
        return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="install.py", description="The Mothership: Skeleton Base + Frugal-Bridge, "
                                "one install.")
    p.add_argument("command", nargs="?", default="install",
                   choices=("install", "check", "status", "update", "uninstall"))
    p.add_argument("--base", help=f"the knowledge base folder (default {DEFAULT_BASE}, or the one already connected)")
    p.add_argument("--yes", "-y", action="store_true", help="no questions; run systemctl --user when available")
    p.add_argument("--no-frugal", action="store_true", help="only Skeleton Base")
    p.add_argument("--watch", dest="watch", action="store_true", default=None, help="watcher service (default on Linux)")
    p.add_argument("--no-watch", dest="watch", action="store_false")
    p.add_argument("--timer", action="store_true", help="daily collect timer (also comes with --watch)")
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    p.add_argument("--keep-backups", action="store_true", help="uninstall: keep the products' backup folders")
    p.add_argument("--purge", action="store_true", help="uninstall: also delete the base with your pages")
    p.add_argument("--confirm-purge", metavar="DIR", help="non-interactive confirmation for --purge")
    p.add_argument("--verbose", "-v", action="store_true", help="show the products' own output")
    p.add_argument("--version", action="version", version=f"The Mothership {VERSION}")
    a = p.parse_args(argv)
    m = Mothership(a)
    try:
        if a.command in ("install", "update"):
            return m.install(update=a.command == "update")
        if a.command == "uninstall":
            return m.uninstall()
        if a.command == "check":
            return m.check()
        return m.status()
    except Fail as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted; run the same command again to continue", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
