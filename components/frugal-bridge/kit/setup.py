#!/usr/bin/env python3
"""Frugal-Bridge setup: install / uninstall / check the kit in a project folder, following the coexistence contract
(docs/COEXISTENCE.md): marked blocks only, `.kits.json` registry, slots owned by a base folder when
present, key-level JSON merge for host settings, idempotent, reversible, backups of every touched file.

  python3 setup.py install   --global [--hosts auto|claude-code,codex,gemini,opencode,hermes] [--base DIR]   (every project)
  python3 setup.py uninstall --global
  python3 setup.py check     --global
  python3 setup.py install   <dir> [--hosts auto|claude-code,gemini,hermes,none] [--hermes-home PATH]   (one folder)
  python3 setup.py uninstall <dir>
  python3 setup.py check     <dir>

--global (recommended): the rules go into each agent tool's own user-level instruction file, so they apply in every
folder and every new session with nothing more to do; hooks/skills/plugin are installed at user level too. The user
file lives in ~/.frugal-bridge/USER.md (FRUGAL_HOME to move it). Per-project files (PROGRESS, PROJECT, DECISIONS) are
created in a project only when there is something to put in them.

The rules (AGENTS.md block, pointer files, skills, templates) work with any agent. The adapter is picked
automatically (`--hosts auto`, the default): for every agent tool found it uses the strongest way that tool allows —
session/prompt hooks, a plugin, or (tools with a configurable API base URL) the local proxy, which setup only
suggests. Plugin-based tools get the plugin copied; enabling it (it restarts that tool's gateway) is left to the user.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KIT)
VERSION = "6"
START, END = "<!-- frugal-bridge:start v{v} -->", "<!-- frugal-bridge:end -->"
START_RE = re.compile(r"<!-- frugal-bridge:start v[^>]*-->")
BASE_END = "<!-- base-folder:end -->"
POINTER = "@AGENTS.md"
CODEX_LIMIT = 32 * 1024     # Codex default project_doc_max_bytes
SOFT_LIMIT = 24 * 1024
HOOK_MARK = ".frugal-bridge/frugal_hook.py"   # old-style marker (path), still recognised for upgrades
HOOK_TAG = "# frugal-bridge-hook"                # stable marker: independent of folder names (FRUGAL_HOME, project)
HOOK_FILE = "frugal_hook.py"
DEFAULT_SLOTS = {"user": "USER.md", "now": "PROGRESS.md", "decisions": "DECISIONS.md", "map": "MAP.md", "sources": "sources/"}
SLOT_TEMPLATES = {"user": "USER.md", "now": "PROGRESS.md", "decisions": "DECISIONS.md"}


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


def read(p):
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None


def write(p, text):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


HOOK_TOOLS = {"claude-code": ("claude", ".claude", ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")),
              "gemini": ("gemini", ".gemini", ("GEMINI_CLI",))}
PLUGIN_TOOLS = {"hermes": ("hermes", None, ("HERMES_HOME", "HERMES_AGENT"))}
PROXY_TOOLS = ("codex", "cursor-agent", "opencode", "aider", "goose", "continue", "crush", "amp")


def detect(project):
    """Agent tools present on this machine / in this project. Returns (hosts for setup, tools that could use the proxy)."""
    found = []
    for name, (binary, folder, envs) in {**HOOK_TOOLS, **PLUGIN_TOOLS}.items():
        if (any(os.environ.get(e) for e in envs) or shutil.which(binary)
                or (folder and os.path.isdir(os.path.join(project, folder)))):
            found.append(name)
    proxy = [b for b in PROXY_TOOLS if shutil.which(b)]
    return found, proxy


class Setup:
    def __init__(self, d):
        self.d = os.path.abspath(d)
        self.backup_dir = None
        self.log = []
        self._modes = {}

    # ---------------------------------------------------------------- helpers
    def p(self, rel):
        return os.path.join(self.d, rel)

    def backup(self, rel):
        src = self.p(rel)
        if not os.path.exists(src):
            return
        if not self.backup_dir:
            self.backup_dir = self.p(f".frugal-bridge/backup/{dt.datetime.now():%Y%m%d-%H%M%S-%f}")
        dst = os.path.join(self.backup_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    def kits(self):
        t = read(self.p(".kits.json"))
        try:
            return json.loads(t) if t else {}
        except json.JSONDecodeError:
            raise SystemExit(".kits.json is not valid JSON; fix it by hand first (nothing changed).")

    def save_kits(self, k):
        new = json.dumps(k, indent=2, ensure_ascii=False) + "\n"
        if read(self.p(".kits.json")) != new:
            self.backup(".kits.json"); write(self.p(".kits.json"), new)

    def change(self, rel, new):
        """Write rel only if content differs (keeps re-runs byte-identical)."""
        if read(self.p(rel)) == new:
            return False
        self.backup(rel); write(self.p(rel), new); self.log.append(f"wrote {rel}")
        return True

    @staticmethod
    def find_block(text):
        if not text:
            return None
        m = START_RE.search(text)
        if not m:
            return None
        e = text.find(END, m.end())
        return (m.start(), e + len(END)) if e >= 0 else None

    def strip_block(self, text, mode=None):
        """Remove our block and exactly the separators put_block added (mode recorded at install)."""
        r = self.find_block(text)
        if not r:
            return text, False
        a, b = r
        mode = mode or "append"
        if mode == "new":
            if text[b:b + 1] == "\n":
                b += 1
        elif mode == "after-base":
            if text[a - 2:a] == "\n\n":
                a -= 2
        else:  # append / append-noeol
            if text[b:b + 1] == "\n":
                b += 1
            if text[a - 1:a] == "\n":
                a -= 1
            if mode == "append-noeol" and text[a - 1:a] == "\n":
                a -= 1
        return text[:a] + text[b:], True

    def core(self, body):
        return f"{START.format(v=VERSION)}\n{body.rstrip()}\n{END}"

    # ---------------------------------------------------------------- never lose the user's data
    def note_written(self, path):
        """Remember what we wrote (sha), so uninstall deletes only our unchanged files."""
        w = getattr(self, "written", None)
        if w is None:
            w = self.written = {}
        if os.path.isfile(path):
            w[os.path.abspath(path)] = sha(open(path, "rb").read())

    def copy_tree(self, src, dst):
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        for root, _, files in os.walk(dst):
            for f in files:
                if os.path.exists(os.path.join(src, os.path.relpath(os.path.join(root, f), dst))):
                    self.note_written(os.path.join(root, f))

    def remove_copy(self, dst, src, written):
        """Delete our files under dst (unchanged since we wrote them, or identical to the kit's copy) and folders left
        empty; keep anything the user changed or added. Returns the kept paths."""
        kept = []
        if not os.path.isdir(dst):
            return kept
        for root, dirs, files in os.walk(dst, topdown=False):
            for f in files:
                p = os.path.join(root, f)
                s_ = os.path.join(src, os.path.relpath(p, dst))
                h = sha(open(p, "rb").read())
                ours = (h == written.get(os.path.abspath(p))
                        or (os.path.isfile(s_) and h == sha(open(s_, "rb").read()))
                        or "__pycache__" in p.split(os.sep) or f.endswith(".pyc"))
                if ours:
                    os.remove(p)
                else:
                    kept.append(p)
            if not os.listdir(root):
                os.rmdir(root)
        return kept

    def keep_edited_block(self, path, text, block_shas, keep_dir):
        """Our block was edited by the user: save its text before removing it. Returns the saved file or None."""
        r = self.find_block(text)
        if not r:
            return None
        blk = text[r[0]:r[1]]
        if not block_shas or sha(blk) in block_shas:
            return None
        os.makedirs(keep_dir, exist_ok=True)
        out = os.path.join(keep_dir, os.path.abspath(path).strip(os.sep).replace(os.sep, "_") + ".block.md")
        write(out, blk + "\n")
        return out

    def block_sha_of(self, path):
        t = read(path) or ""
        r = self.find_block(t)
        return sha(t[r[0]:r[1]]) if r else None

    def put_block(self, rel, body, after_base=True):
        """Insert or replace our block; returns the placement mode (stored in .kits.json for exact removal)."""
        old = read(self.p(rel))
        core = self.core(body)
        r = self.find_block(old)
        modes = self._modes
        if r:  # replace in place, keep the recorded mode
            new = old[:r[0]] + core + old[r[1]:]
            self.change(rel, new)
            return modes.get(rel, "append")
        if not old:
            mode, new = "new", core + "\n"
        elif after_base and BASE_END in old:
            i = old.index(BASE_END) + len(BASE_END)
            mode, new = "after-base", old[:i] + "\n\n" + core + old[i:]
        elif old.endswith("\n"):
            mode, new = "append", old + "\n" + core + "\n"
        else:
            mode, new = "append-noeol", old + "\n\n" + core + "\n"
        self.change(rel, new)
        return mode

    # ---------------------------------------------------------------- install
    def install(self, hosts=("claude-code", "gemini"), hermes_home=None):
        os.makedirs(self.d, exist_ok=True)
        k = self.kits()
        kits = k.setdefault("kits", {})
        prev = kits.get("frugal-bridge", {})
        created = set(prev.get("created", []))
        hashes = dict(prev.get("template_hashes", {}))
        base = "base-folder" in kits
        self._modes = dict(prev.get("placement", {}))

        # 1. AGENTS.md block (after the base block when present)
        existed = os.path.exists(self.p("AGENTS.md"))
        self._modes["AGENTS.md"] = self.put_block(
            "AGENTS.md", open(os.path.join(KIT, "AGENTS.md")).read() + "\n\n" + open(os.path.join(KIT, "ROUTING.md")).read())
        if not existed:
            created.add("AGENTS.md")

        # 2. pointer files: one line '@AGENTS.md' (Claude Code / Gemini CLI import it; plain prose does not load it)
        for rel, host in (("CLAUDE.md", "claude-code"), ("GEMINI.md", "gemini")):
            if host not in hosts:
                continue
            t = read(self.p(rel))
            if t is None:
                self.change(rel, POINTER + "\n"); created.add(rel)
            elif self.find_block(t) or not any(l.strip() == POINTER for l in t.splitlines()):
                self._modes[rel] = self.put_block(rel, POINTER, after_base=False)

        # 3. slots: base owns them when present; else Frugal's own files (created once, from templates)
        slots = k.setdefault("slots", {})
        if not base:
            for name, default in DEFAULT_SLOTS.items():
                slots.setdefault(name, default)
            for name, tpl in SLOT_TEMPLATES.items():
                rel = slots[name]
                if not os.path.exists(self.p(rel)):
                    body = open(os.path.join(KIT, "templates", tpl)).read()
                    write(self.p(rel), body); created.add(rel); hashes[rel] = sha(body); self.log.append(f"created {rel}")
            src = slots["sources"]
            if not os.path.exists(self.p(src)):
                os.makedirs(self.p(src)); created.add(src.rstrip("/") + "/")

        # 4. hosts
        adapters = set(prev.get("adapters", []))
        if "claude-code" in hosts:
            self.install_claude(created); adapters.add("claude-code")
        if "gemini" in hosts:
            adapters.add("gemini")
        if "hermes" in hosts and hermes_home:
            self.install_hermes(hermes_home); adapters.add("hermes")
            prev_h = prev.get("hermes_home")
            if prev_h and prev_h != hermes_home:
                self.log.append(f"note: hermes plugin also left in {prev_h}")
            kits_hermes = hermes_home
        else:
            kits_hermes = prev.get("hermes_home")

        bs = {k_: list(v) for k_, v in (prev.get("block_sha") or {}).items()}
        for rel in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            h = self.block_sha_of(self.p(rel))
            if h and h not in bs.setdefault(rel, []):
                bs[rel].append(h)
        entry = {"version": VERSION, "installed": prev.get("installed") or dt.date.today().isoformat(),
                 "adapters": sorted(adapters), "created": sorted(created), "template_hashes": hashes,
                 "placement": self._modes, "block_sha": {k_: v for k_, v in bs.items() if v},
                 "written": {**(prev.get("written") or {}), **(getattr(self, "written", None) or {})}}
        if kits_hermes:
            entry["hermes_home"] = kits_hermes
        kits["frugal-bridge"] = entry
        self.save_kits(k)
        return self.check(), self.log

    def install_claude(self, created):
        # hook script lives inside the project so its path is stable; settings merged key by key
        hook_src = os.path.join(ROOT, "adapter", "hooks", "frugal_hook.py")
        dst = self.p(HOOK_MARK)
        new = open(hook_src).read()
        if read(dst) != new:
            write(dst, new); os.chmod(dst, 0o755)
        for sk in sorted(os.listdir(os.path.join(KIT, "skills"))):
            s_src = os.path.join(KIT, "skills", sk, "SKILL.md"); rel = f".claude/skills/{sk}/SKILL.md"
            body = open(s_src).read()
            if read(self.p(rel)) != body:
                write(self.p(rel), body)
            self.note_written(self.p(rel))
        rel = ".claude/settings.json"
        t = read(self.p(rel))
        try:
            data = json.loads(t) if t and t.strip() else {}
        except json.JSONDecodeError:
            raise SystemExit(f"{rel} is not valid JSON; fix it by hand first (nothing changed there).")
        if t is None:
            created.add(rel)
        self.merge_hooks(data, ("SessionStart", "UserPromptSubmit"), dst)   # replaces our old entries
        self.change(rel, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    @staticmethod
    def _is_ours(group):
        """Our hook entries, in any tool's JSON hook list: the stable tag, or (older versions) our script name/path."""
        def mine(c):
            return HOOK_TAG in c or HOOK_MARK in c or re.search(r"(^|[/\s\"'])" + re.escape(HOOK_FILE) + r"[\"']?(\s|$)", c)
        return any(mine(h.get("command") or "") for h in (group.get("hooks") or []) if isinstance(h, dict))

    @classmethod
    def merge_hooks(cls, data, events, script):
        """Rule for every hook Frugal writes, in any tool's settings: replace our old entries, add one tagged entry."""
        cmd = f'python3 "{script}" {HOOK_TAG}'
        hooks = data.setdefault("hooks", {})
        for ev in events:
            lst = hooks.setdefault(ev, [])
            lst[:] = [g for g in lst if not (isinstance(g, dict) and cls._is_ours(g))]
            lst.append({"hooks": [{"type": "command", "command": cmd}]})

    @classmethod
    def drop_hooks(cls, data):
        hooks = data.get("hooks", {})
        for ev in list(hooks):
            hooks[ev] = [g for g in hooks[ev] if not (isinstance(g, dict) and cls._is_ours(g))]
            if not hooks[ev]:
                del hooks[ev]
        if not hooks:
            data.pop("hooks", None)

    def install_hermes(self, home):
        dst = os.path.join(home, "plugins", "frugal-bridge")
        self.copy_tree(os.path.join(ROOT, "adapter", "plugin", "frugal-bridge"), dst)
        cfgp = os.path.join(home, "frugal-bridge", "config.json")
        cfg = json.loads(read(cfgp) or "{}")
        cfg["base_dir"] = self.d
        write(cfgp, json.dumps(cfg, indent=2) + "\n")
        self.log.append(f"hermes plugin copied to {dst}; enable with: hermes plugins enable frugal-bridge (then restart the gateway)")

    # ---------------------------------------------------------------- uninstall
    def uninstall(self):
        k = self.kits()
        kits = k.get("kits", {})
        me = kits.get("frugal-bridge")
        if not me:
            return ["frugal-bridge not installed here (nothing changed)"]
        created = set(me.get("created", []))
        hashes = me.get("template_hashes", {})
        base = "base-folder" in kits
        kept = []
        modes = me.get("placement", {})

        written = me.get("written") or {}
        keep_dir = self.p(".frugal-bridge/kept")
        # blocks (a block the user edited is saved first)
        for rel in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            t = read(self.p(rel))
            if t is None:
                continue
            saved = self.keep_edited_block(self.p(rel), t, (me.get("block_sha") or {}).get(rel), keep_dir)
            if saved:
                self.log.append(f"you had edited the Frugal-Bridge block in {rel}: saved to {saved}")
            new, had = self.strip_block(t, modes.get(rel))
            if rel in created and rel != "AGENTS.md" and new.strip() == POINTER and not base:
                self.backup(rel); os.remove(self.p(rel)); self.log.append(f"removed {rel}"); continue
            if had:
                if rel in created and not new.strip():
                    self.backup(rel); os.remove(self.p(rel)); self.log.append(f"removed {rel}")
                else:
                    self.change(rel, new)

        # claude settings / hook / skills
        rel = ".claude/settings.json"
        t = read(self.p(rel))
        if t:
            data = json.loads(t)
            self.drop_hooks(data)
            if not data and rel in created:
                self.backup(rel); os.remove(self.p(rel))
            else:
                self.change(rel, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        for sk in os.listdir(os.path.join(KIT, "skills")):
            kept += [os.path.relpath(x, self.d) for x in
                     self.remove_copy(self.p(f".claude/skills/{sk}"), os.path.join(KIT, "skills", sk), written)]
        for d in (".claude/skills", ".claude"):
            if os.path.isdir(self.p(d)) and not os.listdir(self.p(d)):
                os.rmdir(self.p(d))
        if os.path.exists(self.p(HOOK_MARK)):
            os.remove(self.p(HOOK_MARK))

        # hermes plugin copy (not enabled/disabled here)
        h = me.get("hermes_home")
        if h:
            kept += self.remove_copy(os.path.join(h, "plugins", "frugal-bridge"), os.path.join(ROOT, "adapter", "plugin", "frugal-bridge"), written)
            self.log.append("plugin files removed; if you enabled it, also run its disable command")

        # slot files we created: remove only if untouched and no base owns slots
        for rel in sorted(created):
            if rel in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".claude/settings.json"):
                continue
            full = self.p(rel)
            if rel.endswith("/"):
                if os.path.isdir(full) and not os.listdir(full) and not base:
                    os.rmdir(full)
                elif os.path.isdir(full):
                    kept.append(rel)
                continue
            if not os.path.exists(full):
                continue
            if not base and sha(open(full, encoding="utf-8").read()) == hashes.get(rel):
                os.remove(full)
            else:
                kept.append(rel)
        if kept:
            self.log.append("kept (your content, or a base folder uses it): " + ", ".join(kept))
        self.log.append("your data is kept: your own text in every file, files you changed or added, usage logs, "
                        "backups in .frugal-bridge/backup/")

        # registry
        del kits["frugal-bridge"]
        if not base:
            mine = {v for v in DEFAULT_SLOTS.values()}
            for s, v in list(k.get("slots", {}).items()):
                if v in mine and v not in kept and not os.path.exists(self.p(v)):
                    del k["slots"][s]
            if not k.get("slots"):
                k.pop("slots", None)
        if not kits and not k.get("slots") and set(k) <= {"kits", "slots"}:
            self.backup(".kits.json"); os.remove(self.p(".kits.json"))
        else:
            self.save_kits(k)
        fb = self.p(".frugal-bridge")
        if os.path.isdir(fb) and not os.listdir(fb):
            os.rmdir(fb)  # backups (if any) are kept
        return self.log

    # ---------------------------------------------------------------- check
    def check(self):
        out, ok = [], True
        t = read(self.p("AGENTS.md")) or ""
        n = len(START_RE.findall(t))
        out.append(f"AGENTS.md frugal block: {n}"); ok &= n == 1
        b = len(t.encode())
        if b > CODEX_LIMIT:
            out.append(f"AGENTS.md size {b} bytes > {CODEX_LIMIT} (Codex reads only the first 32 KiB): shorten a block"); ok = False
        elif b > SOFT_LIMIT:
            out.append(f"AGENTS.md size {b} bytes: close to the 32 KiB Codex limit")
        else:
            out.append(f"AGENTS.md size {b} bytes (limit {CODEX_LIMIT})")
        if "<!-- base-folder:start" in t and t.find("<!-- base-folder:start") > (START_RE.search(t).start() if n else 1e9):
            out.append("order: frugal block is before the base block (should be after)"); ok = False
        for rel in ("CLAUDE.md", "GEMINI.md"):
            c = read(self.p(rel))
            if c is not None:
                has = any(l.strip() == POINTER for l in c.splitlines())
                out.append(f"{rel} imports AGENTS.md: {has}"); ok &= has
        k = self.kits()
        for s, v in (k.get("slots") or {}).items():
            if s in ("user", "now") and not os.path.exists(self.p(v)):
                out.append(f"slot {s} -> {v}: missing"); ok = False
        out.insert(0, "OK" if ok else "PROBLEMS")
        return "\n".join(out)


def frugal_home():
    return os.environ.get("FRUGAL_HOME") or os.path.expanduser("~/.frugal-bridge")


def global_targets():
    """tool -> (home dir, user-level instruction file, binary). Homes follow each tool's own env override."""
    e, h = os.environ.get, os.path.expanduser
    return {
        "claude-code": (e("CLAUDE_CONFIG_DIR") or h("~/.claude"), "CLAUDE.md", "claude"),
        "codex": (e("CODEX_HOME") or h("~/.codex"), "AGENTS.md", "codex"),
        "gemini": (h("~/.gemini"), "GEMINI.md", "gemini"),
        "opencode": (h("~/.config/opencode"), "AGENTS.md", "opencode"),
        "hermes": (e("HERMES_HOME") or h("~/.hermes"), "SOUL.md", "hermes"),
    }


GLOBAL_NOTE_BASE = """
## Where your files are (installed for every project)
These rules apply in every folder. A knowledge base owns the user's files: `{base}`. Its `.kits.json` slots say
where the user file and the "now" file are (user = `{user}`, now = `{now}`); use them instead of USER.md /
PROGRESS.md and never create a second copy. Project files (`PROGRESS.md`, `PROJECT.md`, `DECISIONS.md`) still live in
the current project folder, created only when needed. If the project has its own `.kits.json`, its slots win.
"""

KIT_BLOCK_RE = re.compile(r"<!-- (?!frugal-bridge)[a-z0-9-]+:start")
BASE_PATH_RE = re.compile(r"<!-- base-folder:start[^>]*-->.*?^Path:[ \t]*(.+?)[ \t]*$", re.S | re.M)


def parse_base_path(raw):
    """'Path:' value: `quoted`, "quoted" or 'quoted' (spaces allowed), else the rest of the line."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "`\"'" and raw[0] in raw[1:]:
        return raw[1:raw.index(raw[0], 1)]
    return raw


def is_base(d):
    k = read(os.path.join(d, ".kits.json")) if d else None
    try:
        return bool(k) and "base-folder" in json.loads(k).get("kits", {})
    except (json.JSONDecodeError, AttributeError):
        return False


def unit_base_paths(home):
    """--base <dir> from the base's own systemd user units (its registry when no tool rules file carries a block)."""
    import shlex
    d = os.path.join(home, ".config", "systemd", "user")
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not (f.startswith("skeleton-base") and f.endswith(".service")):
            continue
        for line in (read(os.path.join(d, f)) or "").splitlines():
            if line.startswith("ExecStart="):
                try:
                    w = shlex.split(line[len("ExecStart="):].replace("%%", "%").replace("$$", "$"))
                except ValueError:
                    continue
                if "--base" in w and w.index("--base") + 1 < len(w):
                    out.append(w[w.index("--base") + 1])
    return out


def find_base(files, home=None, extra=()):
    """The connected knowledge base, which owns the user's slots. Sources, in order: `extra` (--base, FRUGAL_BASE,
    a base recorded earlier), the 'Path:' line of its block in any tool rules file, its pointer file
    (~/.config/skeleton-base/base), its systemd user units (--base <dir>). Each candidate must have a .kits.json
    registering `base-folder`."""
    cands = [c for c in extra if c]
    for f in files:
        m = BASE_PATH_RE.search(read(f) or "")
        if m:
            cands.append(parse_base_path(m.group(1)))
    if home:
        ptr = (read(os.path.join(home, ".config", "skeleton-base", "base")) or "").strip().splitlines()
        cands += ptr[:1]
        cands += unit_base_paths(home)
    for c in cands:
        d = os.path.abspath(os.path.expanduser(c))
        if is_base(d):
            return d
    return None


GLOBAL_NOTE = """
## Where your files are (installed for every project)
These rules apply in every folder. The user file is `{user}`: read it at session start together with the
current project's `PROGRESS.md` (one call). Project files (`PROGRESS.md`, `PROJECT.md`, `DECISIONS.md`, `sources/`)
live in the current project folder; create one only when you have something to put in it. If the project has a
`.kits.json`, its slots win. A preference or the user's name goes to `{user}`, not to a project file.
"""


class GlobalSetup(Setup):
    """User-level install: one marked block per tool's own instruction file (any folder, any session)."""

    def __init__(self):
        super().__init__(frugal_home())

    def backup(self, rel):
        src = self.p(rel)
        if not os.path.exists(src):
            return
        if not self.backup_dir:
            self.backup_dir = os.path.join(self.d, "backup", f"{dt.datetime.now():%Y%m%d-%H%M%S-%f}")
        dst = os.path.join(self.backup_dir, os.path.abspath(src).lstrip(os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst) if os.path.isfile(src) else shutil.copytree(src, dst, dirs_exist_ok=True)

    def reg_path(self):
        return os.path.join(self.d, "global.json")

    # what was there before Frugal first touched a file / folder, so uninstall leaves no empty leftovers
    def remember(self, path):
        orig = self.r.setdefault("orig", {})
        if path not in orig:
            t = read(path)
            orig[path] = t if (t is None or len(t) < 256 * 1024) else "<big>"
        self.remember_dirs(path)

    def remember_dirs(self, path):
        made = self.r.setdefault("made_dirs", [])
        stop = os.path.expanduser("~")
        d = os.path.dirname(os.path.abspath(path))
        while d and d != stop and d != os.path.dirname(d) and not os.path.exists(d):
            if d not in made:
                made.append(d)
            d = os.path.dirname(d)

    @staticmethod
    def leftover(orig_known, orig, empty_now):
        """After our parts are removed and the file is empty: 'remove' it, 'restore' the user's own empty original,
        or None (keep). An original that had content now gone was another kit's (e.g. a disconnected base)."""
        if not empty_now:
            return None
        if not orig_known or orig is None or orig == "<big>":
            return "remove"
        return "restore" if (not orig.strip() or orig.strip() == "{}") else "remove"

    def reg(self):
        return json.loads(read(self.reg_path()) or "{}")

    def detect(self):
        return [t for t, (home, _, b) in global_targets().items() if shutil.which(b) or os.path.isdir(home)]

    def install(self, hosts=None, hermes_home=None):
        os.makedirs(self.d, exist_ok=True)
        r = self.r = self.reg()
        tools = r.setdefault("tools", {})
        targets = global_targets()
        hosts = [h for h in (hosts or self.detect()) if h in targets]
        user = os.path.join(self.d, "USER.md")
        base = find_base([os.path.join(targets[t][0], targets[t][1]) for t in targets], os.path.expanduser("~"),
                         (getattr(self, "base_arg", None), os.environ.get("FRUGAL_BASE"), r.get("base")))
        rules = open(os.path.join(KIT, "AGENTS.md")).read() + "\n\n" + open(os.path.join(KIT, "ROUTING.md")).read() + "\n"
        if base:  # coexistence contract: the base owns the slots, Frugal never makes a second copy
            sl = json.loads(read(os.path.join(base, ".kits.json"))).get("slots") or {}
            u, n = os.path.join(base, sl.get("user", "USER.md")), os.path.join(base, sl.get("now", "PROGRESS.md"))
            body = rules + GLOBAL_NOTE_BASE.format(base=base, user=u, now=n)
            r["base"] = base
            if os.path.exists(user):
                self.log.append(f"note: {user} exists from before the knowledge base — move what it says into {u}, then delete it")
        else:
            r.pop("base", None)
            if not os.path.exists(user):
                write(user, open(os.path.join(KIT, "templates", "USER.md")).read()); self.log.append(f"created {user}")
            body = rules + GLOBAL_NOTE.format(user=user)
        r.pop("needs_user", None)
        for t in hosts:
            home, fname, _ = targets[t]
            f = os.path.join(home, fname)
            prev = tools.get(t, {})
            if t == "hermes" and not os.path.exists(f):
                tools.pop(t, None)
                # Creating SOUL.md would replace the tool's default identity: only add to an existing one.
                r.setdefault("needs_user", {})[t] = f
                self.pending_block = self.core(body)
                self.remember_dirs(os.path.join(home, "plugins", "frugal-bridge", "x"))
                self.copy_skills(os.path.join(home, "skills", "frugal-bridge"))
                dst = os.path.join(home, "plugins", "frugal-bridge")
                self.copy_tree(os.path.join(ROOT, "adapter", "plugin", "frugal-bridge"), dst)
                r.setdefault("copied", {})[t] = {"home": home, "plugin": dst}
                continue
            self._modes = {f: prev.get("mode")} if prev.get("mode") else {}
            existed = os.path.exists(f)
            self.remember(f)
            mode = self.put_block(f, body, after_base=True)
            bsh = list(prev.get("block_sha") or [])
            h = self.block_sha_of(f)
            if h and h not in bsh:
                bsh.append(h)
            tools[t] = {"file": f, "mode": mode, "created": prev.get("created", not existed), "block_sha": bsh}
            if t == "claude-code":
                self.global_claude(home)
            if t in ("claude-code", "codex"):
                self.copy_skills(os.path.join(home, "skills"))
            if t == "hermes":
                self.remember_dirs(os.path.join(home, "plugins", "frugal-bridge", "x"))
                self.copy_skills(os.path.join(home, "skills", "frugal-bridge"))
                dst = os.path.join(home, "plugins", "frugal-bridge")
                self.copy_tree(os.path.join(ROOT, "adapter", "plugin", "frugal-bridge"), dst)
                tools[t]["plugin"] = dst
        r["version"] = VERSION
        r["written"] = {**(r.get("written") or {}), **(getattr(self, "written", None) or {})}
        write(self.reg_path(), json.dumps(r, indent=2) + "\n")
        return self.check(), self.log

    def copy_skills(self, dst_root):
        for sk in sorted(os.listdir(os.path.join(KIT, "skills"))):
            body = open(os.path.join(KIT, "skills", sk, "SKILL.md")).read()
            f = os.path.join(dst_root, sk, "SKILL.md")
            if hasattr(self, "r"):
                self.remember_dirs(f)
            if read(f) != body:
                write(f, body)
            self.note_written(f)

    def global_claude(self, home):
        dst = os.path.join(self.d, "frugal_hook.py")
        new = open(os.path.join(ROOT, "adapter", "hooks", "frugal_hook.py")).read()
        if read(dst) != new:
            write(dst, new); os.chmod(dst, 0o755)
        f = os.path.join(home, "settings.json")
        t = read(f)
        try:
            data = json.loads(t) if t and t.strip() else {}
        except json.JSONDecodeError:
            raise SystemExit(f"{f} is not valid JSON; fix it by hand first (nothing changed there).")
        self.remember(f)
        self.merge_hooks(data, ("SessionStart", "UserPromptSubmit"), dst)
        self.change(f, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def drop_or_restore(self, f, new, empty_now):
        orig = self.r.get("orig", {})
        o = orig.get(f)
        if (not empty_now and isinstance(o, str) and f.endswith(".md") and KIT_BLOCK_RE.search(o)
                and not KIT_BLOCK_RE.search(new)):
            # another kit's block (e.g. a base) was there when we came and is gone now: its separators were joined
            # to ours, so leave the user's text tidy — no extra blank lines at the start or end.
            new = new.strip("\n") + "\n"
        how = self.leftover(f in orig, orig.get(f), empty_now)
        if how == "remove":
            self.backup(f); os.remove(f); self.log.append(f"removed {f} (empty after removing Frugal-Bridge)")
        elif how == "restore":
            self.change(f, orig[f])
        else:
            self.change(f, new)

    def uninstall(self):
        r = self.r = self.reg()
        targets = global_targets()
        written, kept = r.get("written") or {}, []
        for t, info in (r.get("tools") or {}).items():
            f = info["file"]
            txt = read(f)
            if txt is not None:
                saved = self.keep_edited_block(f, txt, info.get("block_sha"), os.path.join(self.d, "kept"))
                if saved:
                    self.log.append(f"you had edited the Frugal-Bridge block in {f}: saved to {saved}")
                new, had = self.strip_block(txt, info.get("mode"))
                if had:
                    self.drop_or_restore(f, new, not new.strip())
            home = targets[t][0] if t in targets else os.path.dirname(f)
            skills = os.path.join(home, "skills", "frugal-bridge") if t == "hermes" else os.path.join(home, "skills")
            for sk in os.listdir(os.path.join(KIT, "skills")):
                kept += self.remove_copy(os.path.join(skills, sk), os.path.join(KIT, "skills", sk), written)
            if t == "hermes":
                d_ = os.path.join(home, "skills", "frugal-bridge")
                if os.path.isdir(d_) and not os.listdir(d_):
                    os.rmdir(d_)
                kept += self.remove_copy(info.get("plugin") or os.path.join(home, "plugins", "frugal-bridge"), os.path.join(ROOT, "adapter", "plugin", "frugal-bridge"), written)
                self.log.append("plugin files removed; if you enabled it, also run its disable command")
            if t == "claude-code":
                sf = os.path.join(home, "settings.json")
                st = read(sf)
                if st:
                    data = json.loads(st)
                    self.drop_hooks(data)
                    self.drop_or_restore(sf, json.dumps(data, indent=2, ensure_ascii=False) + "\n", data == {})
        for t, info in (r.get("copied") or {}).items():
            for sk in os.listdir(os.path.join(KIT, "skills")):
                kept += self.remove_copy(os.path.join(info["home"], "skills", "frugal-bridge", sk),
                                         os.path.join(KIT, "skills", sk), written)
            d_ = os.path.join(info["home"], "skills", "frugal-bridge")
            if os.path.isdir(d_) and not os.listdir(d_):
                os.rmdir(d_)
            kept += self.remove_copy(info["plugin"], os.path.join(ROOT, "adapter", "plugin", "frugal-bridge"), written)
        for f in ("frugal_hook.py", "global.json"):
            if os.path.exists(os.path.join(self.d, f)):
                os.remove(os.path.join(self.d, f))
        for d in sorted(r.get("made_dirs", []), key=len, reverse=True):   # folders we made, only if now empty
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        if kept:
            self.log.append("kept (you changed or added them): " + ", ".join(kept))
        self.log.append(f"your data is kept: {os.path.join(self.d, 'USER.md')}, your own text in every file, files "
                        f"you changed or added, usage logs, backups in {os.path.join(self.d, 'backup')}")
        return self.log

    def check(self):
        out, ok = [], True
        tools = (self.reg().get("tools") or {})
        for t, f in (self.reg().get("needs_user") or {}).items():
            out.append(f"{t}: needs user — {f} does not exist; not created (it would replace the default identity)")
        if not tools and self.reg().get("needs_user"):
            out.insert(0, "OK")
            return "\n".join(out)
        if not tools:
            return "PROBLEMS\nnot installed for any tool (no agent tool found? use --hosts)"
        for t, info in tools.items():
            txt = read(info["file"]) or ""
            n = len(START_RE.findall(txt)); b = len(txt.encode())
            out.append(f"{t}: {info['file']} block={n} size={b}"); ok &= n == 1
            if b > CODEX_LIMIT:
                out.append(f"  {info['file']} over 32 KiB: some tools read only the first 32 KiB"); ok = False
        base = self.reg().get("base")
        if base:
            if not os.path.isdir(base):
                out.append(f"knowledge base {base} is gone: re-run install --global"); ok = False
            else:
                out.append(f"user files: owned by the knowledge base {base}")
        elif not os.path.exists(os.path.join(self.d, "USER.md")):
            out.append("USER.md missing"); ok = False
        out.insert(0, "OK" if ok else "PROBLEMS")
        return "\n".join(out)


def main_global(argv):
    g = GlobalSetup()
    if "--base" in argv:
        g.base_arg = os.path.abspath(os.path.expanduser(argv[argv.index("--base") + 1]))
        if not is_base(g.base_arg):
            print(f"--base {g.base_arg}: no knowledge base there (.kits.json without base-folder); nothing changed")
            return 2
    hosts = None
    if "--hosts" in argv and argv[argv.index("--hosts") + 1] != "auto":
        hosts = argv[argv.index("--hosts") + 1].split(",")
    if argv[1] == "install":
        rep, log = g.install(hosts)
        print("\n".join(log)); print(rep)
        tools = g.reg().get("tools", {})
        print("Enforcement on this machine (every folder, every new session):")
        print("  rules: " + ", ".join(sorted(tools)) + " load them by themselves")
        if "claude-code" in tools:
            print("  hooks: context watch + start files (tools with session/prompt hooks)")
        for t, f in (g.reg().get("needs_user") or {}).items():
            print(f"  {t}: NEEDS USER — {f} does not exist and was not created (creating it would replace the")
            print(f"    tool's default identity). To turn the rules on there, create that file with your own identity text")
            print(f"    and re-run install --global, or paste this block into it:")
            print(getattr(g, "pending_block", ""))
            c = (g.reg().get("copied") or {}).get(t)
            if c:
                print(f"  {t} plugin: copied to {c['plugin']} — enable it to turn it on (restarts that tool's gateway)")
        if "hermes" in tools:
            print(f"  plugin: copied to {tools['hermes'].get('plugin')} — enable it to turn it on (restarts that tool's gateway)")
        proxy = [b for b in PROXY_TOOLS if shutil.which(b)]
        if proxy:
            print(f"  proxy available for: {', '.join(proxy)} — optional, adds enforcement (adapter/proxy/)")
        if g.reg().get("base"):
            print(f"  user files: the knowledge base {g.reg()['base']} owns them (no second copy made)")
        else:
            print(f"  user file: {os.path.join(g.d, 'USER.md')} — fill it (name of the main agent, language, style)")
        return 0 if rep.startswith("OK") else 1
    if argv[1] == "uninstall":
        print("\n".join(g.uninstall())); return 0
    rep = g.check(); print(rep)
    return 0 if rep.startswith("OK") else 1


def main(argv):
    if len(argv) >= 2 and "--global" in argv and argv[1] in ("install", "uninstall", "check"):
        return main_global(argv)
    if len(argv) < 3 or argv[1] not in ("install", "uninstall", "check"):
        print(__doc__); return 2
    s = Setup(argv[2])
    hosts_arg = argv[argv.index("--hosts") + 1] if "--hosts" in argv else "auto"
    proxy_tools = []
    if hosts_arg == "auto":
        found, proxy_tools = detect(s.d)
        hosts = tuple(found) + ("claude-code", "gemini")  # pointer files are harmless and help those tools later
        hosts = tuple(dict.fromkeys(hosts))
    else:
        hosts = tuple(h for h in hosts_arg.split(",") if h and h != "none")
    home = None
    if "--hermes-home" in argv:
        home = argv[argv.index("--hermes-home") + 1]
    elif "hermes" in hosts:
        home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    if argv[1] == "install":
        rep, log = s.install(hosts, home)
        print("\n".join(log)); print(rep)
        print("Enforcement on this machine:")
        print("  rules (AGENTS.md, skills): every agent that reads the project folder")
        for h in hosts:
            if h == "claude-code" and os.path.exists(s.p(".claude/settings.json")):
                print("  hooks: context watch + start files (agents with session/prompt hooks)")
            if h == "hermes" and home:
                print(f"  plugin: copied to {home}/plugins/frugal-bridge — enable it to turn it on (restarts that tool's gateway)")
        if proxy_tools:
            print(f"  proxy available for: {', '.join(proxy_tools)} — run adapter/proxy/frugal_proxy.py and point its base URL at it (optional)")
        return 0 if rep.startswith("OK") else 1
    if argv[1] == "uninstall":
        print("\n".join(s.uninstall())); return 0
    rep = s.check(); print(rep)
    return 0 if rep.startswith("OK") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
