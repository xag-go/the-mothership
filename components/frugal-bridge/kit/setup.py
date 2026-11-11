#!/usr/bin/env python3
"""Frugal-Bridge setup: install / uninstall / check the kit in a project folder, following the coexistence contract
(docs/COEXISTENCE.md): marked blocks only, `.kits.json` registry, slots owned by a base folder when
present, key-level JSON merge for host settings, idempotent, reversible, backups of every touched file.

  python3 setup.py install   --global [--hosts auto|<tool>,<tool>...] [--base DIR]   (tools: kit/hosts.py)   (every project)
  python3 setup.py uninstall --global
  python3 setup.py check     --global
  python3 setup.py report    [days]      (token usage of every tool Frugal logs: hooks, plugins, proxy)
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
sys.path.insert(0, KIT)
import hosts as HOSTS  # noqa: E402  (kit/hosts.py: the table of agent tools)
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
PLUGINS = ("frugal-bridge", "frugal-tiers")   # Hermes-style plugins copied for a plugin tool (enabling = user step)
TIERS_BACKEND = "frugal-tiers"                 # the delegation backend the frugal-tiers plugin registers


def _yaml_key(text, section, key):
    """Raw value of a top-level `section:` -> `key:` in a simple YAML file (stdlib only; None when absent).
    A block list under the key is returned as a list."""
    lines = (text or "").splitlines()
    try:
        i = next(n for n, ln in enumerate(lines) if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", ln))
    except StopIteration:
        return None
    ind = None
    for n in range(i + 1, len(lines)):
        ln = lines[n]
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        cur = len(ln) - len(ln.lstrip())
        if cur == 0:
            return None
        ind = cur if ind is None else ind
        if cur != ind:
            continue
        m = re.match(rf"^\s*{re.escape(key)}:\s*(.*?)\s*(#.*)?$", ln)
        if not m:
            continue
        v = m.group(1)
        if v:
            return v.strip("'\"")
        items = []
        for ln2 in lines[n + 1:]:
            if not ln2.strip() or ln2.lstrip().startswith("#"):
                continue
            if (len(ln2) - len(ln2.lstrip())) <= ind and not ln2.lstrip().startswith("- "):
                break
            if ln2.lstrip().startswith("- "):
                items.append(ln2.lstrip()[2:].split("#")[0].strip().strip("'\""))
        return items
    return None


def hermes_backend(home):
    """delegation.backend in a Hermes-style home's config.yaml ('default' when unset)."""
    v = _yaml_key(read(os.path.join(home, "config.yaml")), "delegation", "backend")
    return v if isinstance(v, str) and v else "default"


def hermes_plugin_enabled(home, name):
    v = _yaml_key(read(os.path.join(home, "config.yaml")), "plugins", "enabled")
    if isinstance(v, str):
        v = [x.strip().strip("'\"") for x in v.strip("[]").split(",")]
    return name in (v or [])


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

    def copy_plugins(self, home, remember=False):
        """Copy every Frugal plugin into <home>/plugins/. Returns the frugal-bridge plugin path (registry key)."""
        for name in PLUGINS:
            dst = os.path.join(home, "plugins", name)
            if remember:
                self.remember_dirs(os.path.join(dst, "x"))
            self.copy_tree(os.path.join(ROOT, "adapter", "plugin", name), dst)
        return os.path.join(home, "plugins", PLUGINS[0])

    def remove_plugins(self, first_plugin, written):
        """Remove our plugin copies (first_plugin = the recorded frugal-bridge path; the others sit beside it)."""
        kept, pdir = [], os.path.dirname(first_plugin)
        for name in PLUGINS:
            kept += self.remove_copy(os.path.join(pdir, name), os.path.join(ROOT, "adapter", "plugin", name), written)
        return kept

    def restore_backend(self, home, prev):
        """After the plugin is gone, a delegation.backend still naming it would fail every delegate_task closed:
        put back the value from before (via the tool's own config command), else print the command."""
        if hermes_backend(home) != TIERS_BACKEND:
            return
        prev = prev if prev and prev != TIERS_BACKEND else "default"
        cmd = ["hermes", "config", "set", "delegation.backend", prev]
        ok, exe = False, shutil.which("hermes")
        if exe:
            import subprocess
            try:
                ok = subprocess.run([exe] + cmd[1:], env={**os.environ, "HERMES_HOME": home}, capture_output=True,
                                    timeout=120).returncode == 0 and hermes_backend(home) == prev
            except (OSError, subprocess.SubprocessError):
                ok = False
        self.log.append(f"delegation.backend restored to {prev} ({home})" if ok else
                        f"delegation.backend still names {TIERS_BACKEND}: run  HERMES_HOME={home} {' '.join(cmd)}")
        self.log.append(f"if you enabled it, also run: hermes plugins disable {TIERS_BACKEND}")

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
            bp = prev.get("hermes_backend_prev") or hermes_backend(kits_hermes)
            entry["hermes_backend_prev"] = bp if bp != TIERS_BACKEND else "default"
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
        dst = self.copy_plugins(home)
        cfgp = os.path.join(home, "frugal-bridge", "config.json")
        cfg = json.loads(read(cfgp) or "{}")
        cfg["base_dir"] = self.d
        write(cfgp, json.dumps(cfg, indent=2) + "\n")
        self.log.append(f"hermes plugin copied to {dst}; enable with: hermes plugins enable frugal-bridge (then restart the gateway)")
        self.log.append(f"tiers plugin copied beside it; per-subagent tiers: hermes plugins enable {TIERS_BACKEND} && "
                        f"hermes config set delegation.backend {TIERS_BACKEND}")

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
            kept += self.remove_plugins(os.path.join(h, "plugins", "frugal-bridge"), written)
            self.log.append("plugin files removed; if you enabled it, also run its disable command")
            self.restore_backend(h, me.get("hermes_backend_prev"))

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
    """User-level install: one marked block per tool's own rules file (any folder, any session), plus each tool's
    strongest enforcement (hooks / plugin / proxy hint) and its helper tiers (model + effort). Table: kit/hosts.py."""

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
        try:
            return json.loads(read(self.reg_path()) or "{}")
        except json.JSONDecodeError:
            raise SystemExit(f"{self.reg_path()} is not valid JSON; fix it by hand first (nothing changed).")

    def detect(self):
        return [t for t in HOSTS.H if HOSTS.installed(t)]

    # ------------------------------------------------------------ rules targets
    def rules_target(self, t):
        """The rules file for tool t: the base's file when it holds a base block, else the tool's own file
        (Codex: AGENTS.override.md when present, since it hides AGENTS.md). None = no rules file (hook/rules copy)."""
        h = HOSTS.H[t]
        if h.get("rules") in (None, "aider-read"):
            return None
        for bf in h.get("base_files") or []:
            f = HOSTS.expand(t, bf)
            if "<!-- base-folder:start" in (read(f) or ""):
                return f
        ov = h.get("override")
        if ov and (read(HOSTS.expand(t, ov)) or "").strip():
            return HOSTS.expand(t, ov)
        return HOSTS.expand(t, h["rules"])

    def plan_rules(self, sel):
        """{tool: file} and {tool: (other tool, file)} for tools that already load another selected tool's file."""
        files = {t: self.rules_target(t) for t in sel}
        via = {}
        for t in sel:
            reads = [HOSTS.expand(t, x) for x in HOSTS.H[t].get("reads") or []]
            for u in sel:
                if u != t and u not in via and files.get(u) and files[u] in reads and not HOSTS.H[u].get("policy"):
                    via[t] = (u, files[u])
                    break
        return files, via

    # ------------------------------------------------------------ owned files and config edits (ledger)
    def own_file(self, t, path, text, mode=None):
        """Write a file Frugal owns entirely. A file there that is not ours is left alone (returns False)."""
        ed = self.r.setdefault("edits", {})
        cur = read(path)
        rec = ed.get(path)
        if cur is not None and cur != text and not (rec and rec.get("fmt") == "file" and sha(cur) == rec.get("sha")):
            self.log.append(f"{t}: {path} exists and is not Frugal's: left alone")
            return False
        self.remember_dirs(path)
        if cur != text:
            self.backup(path) if cur is not None else None
            write(path, text)
        if mode:
            os.chmod(path, mode)
        ed[path] = {"fmt": "file", "tool": t, "sha": sha(text), "created": rec["created"] if rec else cur is None}
        self.note_written(path)
        return True

    def cfg_edit(self, t, fmt, path, hooks=None, changes=(), lines=()):
        """Merge Frugal's part into a config file of another format, recording the text from before (first install)
        and a hash of the text after, so uninstall gives the exact bytes back when nothing else changed."""
        ed = self.r.setdefault("edits", {})
        rec = ed.get(path) or {}
        cur = read(path)
        if fmt == "lines" and cur is None and HOSTS.H[t].get("hooks") == "crush" and \
                os.path.exists(HOSTS.expand(t, "@root/crush.json")):
            self.log.append(f"{t}: only the old crush.json is there; not creating crushrc (add the hook by hand)")
            return False
        # the text from before = as it is now, on the first run of this ledger (an older install's snapshot would
        # drop what others added since, e.g. a base's permissions: never restore from it)
        orig = rec["orig"] if "orig" in rec else cur
        # the file changed since our last write (another kit or the user): the recorded text from before is out of
        # date (e.g. it still holds a base's hooks that its disconnect removed since). Uninstall must then remove
        # only our entries, never put that old text back.
        orig_stale = bool(rec.get("orig_stale")) or ("orig" in rec and rec.get("after") is not None
                                                     and (cur is None or sha(cur) != rec["after"]))
        notes, made = [], list(rec.get("made") or [])
        if fmt in ("json", "jsonc") and changes:   # record only keys Frugal adds (a value the user had stays theirs)
            try:
                data = json.loads(HOSTS.strip_jsonc(cur)) if cur and cur.strip() else {}
            except ValueError:
                data = {}
            before = [tuple([c[0], tuple(c[1]), c[2]]) for c in rec.get("changes") or []]
            def ours(c):
                if c in before:
                    return True
                v = HOSTS._get(data, c[1]) if isinstance(data, dict) else None
                return v is None if c[0] == "set" else not (isinstance(v, list) and c[2] in v)
            for c in changes:
                v = HOSTS._get(data, tuple(c[1])) if isinstance(data, dict) else None
                if not ours(tuple([c[0], tuple(c[1]), c[2]])) and c[0] == "set" and v != c[2]:
                    notes.append(f"{'.'.join(c[1])} already set by you: left as is")
            changes = [c for c in changes if ours(tuple([c[0], tuple(c[1]), c[2]]))]
        if fmt in ("json", "jsonc"):
            new, notes, m2 = HOSTS.json_apply(cur, hooks or {}, list(changes))
            if new is None:
                self.log.append(f"{t}: {path}: " + "; ".join(notes)); return False
            made += [m for m in m2 if m not in made]
        elif fmt == "lines":
            new = HOSTS.lines_apply(cur, list(lines))
        elif fmt == "toml":
            new, notes = HOSTS.toml_apply(cur, [(a, b, v) for _, (a, b), v in changes])
        elif fmt == "yaml-list":
            new, notes = cur, []
            for key, item in lines:
                n2, nn = HOSTS.yaml_list_apply(new, key, item)
                notes += nn
                new = n2 if n2 is not None else new
        else:
            raise ValueError(fmt)
        for n in notes:
            self.log.append(f"{t}: {path}: {n}")
        if new is None or (new == (cur or "") and cur is None):
            return False
        self.remember_dirs(path)
        if new != cur:
            self.backup(path) if cur is not None else None
            write(path, new)
        ed[path] = {"fmt": fmt, "tool": t, "orig": orig, "after": sha(new), "hooks": hooks or {},
                    "changes": [list(c) for c in changes], "made": made}
        if orig_stale:
            ed[path]["orig_stale"] = True
        return True

    def undo_edit(self, path, rec):
        cur = read(path)
        if cur is None:
            return
        orig = rec.get("orig")
        if rec["fmt"] == "file":
            if sha(cur) == rec.get("sha"):
                os.remove(path); self.log.append(f"removed {path}")
            else:
                self.log.append(f"kept {path} (you changed it)")
            return
        stale = rec["fmt"] in ("json", "jsonc") and orig and rec.get("hooks") and \
            (HOOK_TAG in orig or HOOK_FILE in orig)    # the text from before had an older Frugal's hooks
        stale = stale or bool(rec.get("orig_stale"))    # changed by someone else between two of our runs
        if sha(cur) == rec.get("after") and not stale:
            new = orig                                 # nothing else touched it: the exact bytes from before
        elif rec["fmt"] in ("json", "jsonc"):
            ch = [tuple([c[0], tuple(c[1]), c[2]]) for c in rec.get("changes") or []]
            data = HOSTS.json_remove(cur, rec.get("hooks"), ch, rec.get("made") or [])
            if data is None:
                self.log.append(f"{path} is not valid JSON now: Frugal's entries left for you to remove"); return
            try:
                od = json.loads(HOSTS.strip_jsonc(orig)) if orig and orig.strip() else ({} if orig is not None else None)
            except ValueError:
                od = None
            if rec.get("orig_stale") and od:
                od = None                              # out-of-date text: never compared, never put back
            if od is not None and data == od:
                new = orig
            elif data == {}:   # empty now: the user's own empty file back, else (another kit's content gone) remove
                new = orig if orig is not None and orig.strip() in ("", "{}") else None
            elif HOSTS.has_comments(cur):
                self.log.append(f"{path} has comments and was changed since: remove Frugal's entries by hand"); return
            else:
                new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        else:
            new = HOSTS.lines_remove(cur)
            if orig is not None and new.strip() == orig.strip():
                new = orig
            elif orig is None and not new.strip():
                new = None
        self.backup(path)
        if new is None:
            os.remove(path); self.log.append(f"removed {path} (only Frugal's part was in it)")
        elif new != cur:
            write(path, new)

    # ------------------------------------------------------------ install
    def install(self, hosts=None, hermes_home=None):
        os.makedirs(self.d, exist_ok=True)
        r = self.r = self.reg()
        tools = r.setdefault("tools", {})
        table = HOSTS.load_tiers(KIT)
        if hosts:
            for h in hosts:
                if h not in HOSTS.H:
                    self.log.append(f"unknown tool {h!r} (known: {', '.join(HOSTS.H)})")
            asked = [h for h in hosts if h in HOSTS.H]
        else:
            asked = self.detect()
        sel = [t for t in asked if HOSTS.installed(t)]
        for t in asked:
            if t not in sel:
                self.log.append(f"skipped {t}: not installed (no {' / '.join(HOSTS.H[t]['bins'])} on PATH and none of "
                                f"{', '.join(HOSTS.expand(t, x) for x in HOSTS.H[t].get('proof') or []) or 'its own config files'})")
        kept_only = set()      # installed earlier, tool not found now: keep its rules block current, add nothing
        for t in list(tools) + list((r.get("copied") or {})):
            if t in HOSTS.H and t not in sel:
                sel.append(t); kept_only.add(t)
                self.log.append(f"kept current: {t} (installed earlier; tool not found now, so only its rules block "
                                f"is refreshed — nothing new added)")
        user = os.path.join(self.d, "USER.md")
        base = find_base(HOSTS.rules_candidates(), os.path.expanduser("~"),
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
        files, via = self.plan_rules(sel)
        old_tiers = dict(r.get("tiers") or {})
        tiers_out = r["tiers"] = {}
        hook = os.path.join(self.d, HOOK_FILE)
        need_hook = any(HOSTS.H[t].get("hooks") not in (None, "hermes-plugin") for t in sel)
        if need_hook or "claude-code" in sel:
            new = open(os.path.join(ROOT, "adapter", "hooks", "frugal_hook.py")).read()
            if read(hook) != new:
                write(hook, new); os.chmod(hook, 0o755)
        # 1. helper tiers first (the rules paragraph names the values written)
        tier_txt, pending = {}, {}
        for t in sel:
            if t in kept_only:
                prev_rows = (old_tiers.get(t) or {}).get("rows") or []
                if old_tiers.get(t):
                    tiers_out[t] = old_tiers[t]
                tier_txt[t] = HOSTS.tier_rules(t, table, prev_rows)
                continue
            fs, changes, rows, note = HOSTS.tier_files(t, table)
            for f, text in fs.items():
                self.own_file(t, f, text)
            for c in changes:
                if c[0] == "toml":
                    pending.setdefault((t, "toml", HOSTS.expand(t, "@root/config.toml")), [None, []])[1].append(c)
                else:
                    cfgp = {"gemini": "@root/settings.json", "copilot": "@root/settings.json",
                            "qwen": "@root/settings.json"}[t]
                    fmt = "json" if t == "copilot" else "jsonc"
                    pending.setdefault((t, fmt, HOSTS.expand(t, cfgp)), [None, []])[1].append(c)
            tiers_out[t] = {"rows": rows, "note": note}
            if note:
                self.log.append(f"{t} tiers: {note}")
            tier_txt[t] = HOSTS.tier_rules(t, table, rows)
        # 2. hooks / plugins
        native = [t for t in (r.get("native_hooks") or []) if t in kept_only]
        for t in sel:
            if t in kept_only:
                continue
            spec = HOSTS.hook_spec(t, hook, "claude-code" in sel)
            if spec is None:
                pj = HOSTS.plugin_js(t, ROOT, hook, self.d)
                if pj:
                    self.own_file(t, pj[0], pj[1]) and native.append(t)
                continue
            if spec[0] == "via":
                self.log.append(f"{t}: hooks come from {spec[1]} (it runs ~/.claude/settings.json hooks)")
                continue
            if spec[0] == "file":
                if t == "cline" and any(os.path.splitext(x)[0].lower() == "taskstart" and os.path.join(
                        os.path.dirname(spec[1]), x) != spec[1] for x in (os.listdir(os.path.dirname(spec[1]))
                                                                         if os.path.isdir(os.path.dirname(spec[1])) else [])):
                    self.log.append(f"{t}: a TaskStart hook of yours exists (one file per event): not added")
                    continue
                if self.own_file(t, spec[1], spec[2], 0o755 if t == "cline" else None):
                    native.append(t)
                continue
            fmt, path, hk, sets = spec
            key = (t, fmt, path)
            pending.setdefault(key, [None, []])
            pending[key][0] = hk if fmt != "lines" else None
            pending[key][1] += [("set",) + tuple(x) for x in sets] if fmt != "lines" else []
            if fmt == "lines":
                pending[key].append(hk)
            native.append(t)
        for (t, fmt, path), v in pending.items():
            if fmt == "lines":
                self.cfg_edit(t, "lines", path, lines=v[2])
            elif fmt == "toml":
                self.cfg_edit(t, "toml", path, changes=v[1])
            else:
                self.cfg_edit(t, fmt, path, hooks=v[0], changes=v[1])
        r["native_hooks"] = sorted(set(native))
        # 3. rules blocks
        done_files = {}
        for t in sel:
            h = HOSTS.H[t]
            prev = tools.get(t, {})
            full = body + "\n" + tier_txt.get(t, "") + "\n"
            if t in via:
                tools[t] = {"via": via[t][0], "file": via[t][1]}
                continue
            if h.get("rules") is None or h.get("rules") == "aider-read":
                rp = os.path.join(self.d, "RULES.md")
                write(rp, self.core(full) + "\n")
                if h.get("rules") == "aider-read":
                    self.cfg_edit(t, "yaml-list", os.path.expanduser("~/.aider.conf.yml"), lines=[("read", rp)])
                tools[t] = {"rules_copy": rp}
                continue
            f = files[t]
            if f in done_files:
                tools[t] = {"same_as": done_files[f], "file": f}
                continue
            if h.get("policy") == "existing" and not os.path.exists(f):
                tools.pop(t, None)
                # Creating it would replace the tool's default identity / seed: only add to an existing one.
                r.setdefault("needs_user", {})[t] = f
                self.pending_block = self.core(full)
                if t == "hermes":
                    self.copy_skills_for(t, r)
                    dst = self.copy_plugins(HOSTS.root(t), remember=True)
                    r.setdefault("copied", {})[t] = {"home": HOSTS.root(t), "plugin": dst}
                    self.note_backend(r, HOSTS.root(t))
                continue
            self._modes = {f: prev.get("mode")} if prev.get("mode") and prev.get("file") == f else {}
            cur = read(f) or ""
            m_ = START_RE.search(cur)
            if m_ and "<!-- base-folder:start" in cur[m_.end():]:      # a base came later, below us: move after it
                stripped, _ = self.strip_block(cur, self._modes.get(f))
                self.change(f, stripped)
                self._modes = {}
                prev = {**prev, "mode": None}
            existed = os.path.exists(f)
            self.remember(f)
            mode = self.put_block(f, full, after_base=True)
            bsh = list(prev.get("block_sha") or [])
            hh = self.block_sha_of(f)
            if hh and hh not in bsh:
                bsh.append(hh)
            tools[t] = {"file": f, "mode": mode, "created": prev.get("created", not existed) if prev.get("file") == f
                        else not existed, "block_sha": bsh}
            if prev.get("file") and prev["file"] != f:
                self.log.append(f"{t}: the rules moved to {f}; the old block in {prev['file']} is left (uninstall it first to move cleanly)")
            done_files[f] = t
            if t == "hermes":
                tools[t]["plugin"] = self.copy_plugins(HOSTS.root(t), remember=True)
                self.note_backend(r, HOSTS.root(t))
        for t in sel:
            if (t in tools or t in (r.get("copied") or {})) and t not in kept_only:
                self.copy_skills_for(t, r)
        r["version"] = VERSION
        r["written"] = {**(r.get("written") or {}), **(getattr(self, "written", None) or {})}
        write(self.reg_path(), json.dumps(r, indent=2) + "\n")
        return self.check(), self.log

    def copy_skills_for(self, t, r):
        """Skills once per folder: the shared ~/.agents/skills for every tool that reads it, else the tool's own."""
        s = HOSTS.H[t].get("skills")
        if not s:
            return
        if t == "hermes":
            ext = HOSTS._read(os.path.join(HOSTS.root(t), "config.yaml")) or ""
            dirs = _yaml_key(ext, "skills", "external_dirs") or []
            if any(os.path.expanduser(x).rstrip("/") == os.path.expanduser(HOSTS.SHARED_SKILLS) for x in dirs):
                s = "shared"
        d = os.path.expanduser(HOSTS.SHARED_SKILLS) if s == "shared" else HOSTS.expand(t, s)
        sd = r.setdefault("skills_dirs", [])
        if d not in sd:
            sd.append(d)
        self.copy_skills(d)
        if t == "codex":       # older versions copied them to ~/.codex/skills: Codex reads ~/.agents/skills
            old = os.path.join(HOSTS.root(t), "skills")
            for sk in os.listdir(os.path.join(KIT, "skills")):
                self.remove_copy(os.path.join(old, sk), os.path.join(KIT, "skills", sk), r.get("written") or {})

    @staticmethod
    def note_backend(r, home):
        """Record delegation.backend from before Frugal (once), so uninstall can put it back."""
        prev = r.setdefault("hermes_backend_prev", {})
        if home not in prev:
            b = hermes_backend(home)
            prev[home] = b if b != TIERS_BACKEND else "default"

    def copy_skills(self, dst_root):
        for sk in sorted(os.listdir(os.path.join(KIT, "skills"))):
            body = open(os.path.join(KIT, "skills", sk, "SKILL.md")).read()
            f = os.path.join(dst_root, sk, "SKILL.md")
            if hasattr(self, "r"):
                self.remember_dirs(f)
            if read(f) != body:
                write(f, body)
            self.note_written(f)

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

    # ------------------------------------------------------------ uninstall
    def uninstall(self):
        r = self.r = self.reg()
        written, kept = r.get("written") or {}, []
        edits = r.get("edits") or {}
        for path in reversed(list(edits)):
            self.undo_edit(path, edits[path])
        legacy_claude = os.path.join(HOSTS.root("claude-code"), "settings.json")
        if "claude-code" in (r.get("tools") or {}) and legacy_claude not in edits:   # installs before the ledger
            st = read(legacy_claude)
            if st:
                data = json.loads(st)
                self.drop_hooks(data)
                self.drop_or_restore(legacy_claude, json.dumps(data, indent=2, ensure_ascii=False) + "\n", data == {})
        for t, info in (r.get("tools") or {}).items():
            f = info.get("file")
            if f and not info.get("via") and not info.get("same_as"):
                txt = read(f)
                if txt is not None:
                    saved = self.keep_edited_block(f, txt, info.get("block_sha"), os.path.join(self.d, "kept"))
                    if saved:
                        self.log.append(f"you had edited the Frugal-Bridge block in {f}: saved to {saved}")
                    new, had = self.strip_block(txt, info.get("mode"))
                    if had:
                        self.drop_or_restore(f, new, not new.strip())
            if t == "hermes":
                home = HOSTS.root(t) if not info.get("plugin") else os.path.dirname(os.path.dirname(info["plugin"]))
                kept += self.remove_plugins(info.get("plugin") or os.path.join(home, "plugins", "frugal-bridge"), written)
                self.log.append("plugin files removed; if you enabled it, also run its disable command")
                self.restore_backend(home, (r.get("hermes_backend_prev") or {}).get(home))
        dirs = list(r.get("skills_dirs") or [])
        for t in list(r.get("tools") or {}) + list(r.get("copied") or {}):   # where older versions put them
            if t == "hermes":
                h = (r.get("copied") or {}).get(t, {}).get("home") or HOSTS.root(t)
                dirs.append(os.path.join(h, "skills", "frugal-bridge"))
            elif t in ("claude-code", "codex"):
                dirs.append(os.path.join(HOSTS.root(t), "skills"))
        for d in dict.fromkeys(dirs):
            for sk in os.listdir(os.path.join(KIT, "skills")):
                kept += self.remove_copy(os.path.join(d, sk), os.path.join(KIT, "skills", sk), written)
            if d.endswith(os.path.join("skills", "frugal-bridge")) and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        for t, info in (r.get("copied") or {}).items():
            kept += self.remove_plugins(info["plugin"], written)
            self.restore_backend(info["home"], (r.get("hermes_backend_prev") or {}).get(info["home"]))
        for f in ("frugal_hook.py", "RULES.md", "hook-state.json", "global.json"):
            if os.path.exists(os.path.join(self.d, f)):
                os.remove(os.path.join(self.d, f))
        if os.path.isdir(os.path.join(self.d, "once")):
            shutil.rmtree(os.path.join(self.d, "once"), ignore_errors=True)
        for d in sorted(r.get("made_dirs", []), key=len, reverse=True):   # folders we made, only if now empty
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        if kept:
            self.log.append("kept (you changed or added them): " + ", ".join(kept))
        self.log.append(f"your data is kept: {os.path.join(self.d, 'USER.md')}, your own text in every file, files "
                        f"you changed or added, usage logs, backups in {os.path.join(self.d, 'backup')}")
        return self.log

    @staticmethod
    def tiers_status(home):
        copied = os.path.isfile(os.path.join(home, "plugins", TIERS_BACKEND, "__init__.py"))
        on = hermes_plugin_enabled(home, TIERS_BACKEND)
        b = hermes_backend(home)
        state = "on" if copied and on and b == TIERS_BACKEND else "off"
        return (f"hermes tiers: {state} (plugin {'copied' if copied else 'missing'}, "
                f"{'enabled' if on else 'not enabled'}, delegation.backend={b})")

    def check(self):
        out, ok = [], True
        r = self.reg()
        tools = r.get("tools") or {}
        for t, f in (r.get("needs_user") or {}).items():
            out.append(f"{t}: needs user — {f} does not exist; not created (it would replace the default identity)")
        if not tools and r.get("needs_user"):
            for t, info in (r.get("copied") or {}).items():
                if t == "hermes" and info.get("plugin"):
                    out.append(self.tiers_status(info["home"]))
            out.insert(0, "OK")
            return "\n".join(out)
        if not tools:
            return "PROBLEMS\nnot installed for any tool (no agent tool found? use --hosts)"
        for t, info in tools.items():
            if info.get("via"):
                txt = read(info["file"]) or ""
                n = len(START_RE.findall(txt))
                out.append(f"{t}: loads the block from {info['file']} ({info['via']}) block={n}"); ok &= n == 1
                continue
            if info.get("rules_copy"):
                ex = os.path.isfile(info["rules_copy"])
                out.append(f"{t}: rules from {info['rules_copy']} ({'hook / read: list' if ex else 'MISSING'})"); ok &= ex
                continue
            txt = read(info["file"]) or ""
            n = len(START_RE.findall(txt)); b = len(txt.encode())
            if info.get("same_as"):
                out.append(f"{t}: same file as {info['same_as']} ({info['file']}) block={n}"); ok &= n == 1
                continue
            out.append(f"{t}: {info['file']} block={n} size={b}"); ok &= n == 1
            cap = (HOSTS.H.get(t) or {}).get("cap")
            if cap:
                size = b if cap[0] == "bytes" else len(txt)
                if size > cap[1]:
                    out.append(f"  over {cap[1]} {cap[0]} ({cap[2]}): {t} drops the rest; shorten it"); ok = False
                elif t == "codex" and size > SOFT_LIMIT:
                    out.append(f"  close to the 32 KiB limit (counts with the project AGENTS.md)")
            if "<!-- base-folder:start" in txt and START_RE.search(txt) and \
                    txt.find("<!-- base-folder:start") > START_RE.search(txt).start():
                out.append(f"  order: frugal block before the base block (should be after)"); ok = False
        for t, info in list(tools.items()) + list((r.get("copied") or {}).items()):
            if t == "hermes" and info.get("plugin"):
                out.append(self.tiers_status(os.path.dirname(os.path.dirname(info["plugin"]))))
        hooks = r.get("native_hooks") or []
        if hooks:
            out.append("hooks/plugins: " + ", ".join(hooks))
        for t, ti in (r.get("tiers") or {}).items():
            if ti.get("rows"):
                out.append(f"{t} tiers: " + ", ".join(f"{n}={m}" + (f"/{e}" if e else "") for n, m, e, _ in ti["rows"]))
        for path, rec in (r.get("edits") or {}).items():
            if rec.get("fmt") == "file" and not os.path.exists(path):
                out.append(f"  missing: {path} (re-run install --global)"); ok = False
        base = r.get("base")
        if base:
            if not os.path.isdir(base):
                out.append(f"knowledge base {base} is gone: re-run install --global"); ok = False
            else:
                out.append(f"user files: owned by the knowledge base {base}")
        elif not os.path.exists(os.path.join(self.d, "USER.md")):
            out.append("USER.md missing"); ok = False
        out.insert(0, "OK" if ok else "PROBLEMS")
        return "\n".join(out)


def usage_files():
    """Every usage.jsonl Frugal writes: hooks/plugins ($FRUGAL_HOME), the Hermes plugin (each profile), the proxy."""
    fs = [(os.path.join(frugal_home(), "usage.jsonl"), None)]
    hh = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    fs.append((os.path.join(hh, "frugal-bridge", "usage.jsonl"), "hermes"))
    prof = os.path.join(hh, "profiles")
    for p in sorted(os.listdir(prof)) if os.path.isdir(prof) else []:
        fs.append((os.path.join(prof, p, "frugal-bridge", "usage.jsonl"), f"hermes:{p}"))
    fs.append((os.path.expanduser("~/.local/share/frugal-bridge/proxy/usage.jsonl"), "proxy"))
    return fs


PRICE = {"opus": (5, 25, 0.5, 6.25), "sonnet": (3, 15, 0.3, 3.75), "haiku": (1, 5, 0.1, 1.25)}


def report(days=7, now=None):
    """One table over every tool: calls, tokens, ~cost at API list prices, biggest context, alerts."""
    import time
    now = now or time.time()
    rows, sess = {}, {}
    for path, tool in usage_files():
        if not os.path.isfile(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                x = json.loads(line)
            except ValueError:
                continue
            if not isinstance(x, dict) or now - x.get("ts", 0) > days * 86400:
                continue
            t = x.get("tool") or tool or "?"
            m = x.get("model") or "?"
            a = rows.setdefault((t, m), dict(calls=0, input=0, output=0, cache_read=0, cache_write=0, cost=0.0))
            a["calls"] += 1
            for k in ("input", "output", "cache_read", "cache_write"):
                a[k] += int(x.get(k) or 0)
            p = next((v for k, v in PRICE.items() if k in m.lower()), None)
            if p:
                a["cost"] += (int(x.get("input") or 0) * p[0] + int(x.get("output") or 0) * p[1] +
                              int(x.get("cache_read") or 0) * p[2] + int(x.get("cache_write") or 0) * p[3]) / 1e6
            s = sess.setdefault((t, x.get("session") or x.get("conv") or "?"), dict(calls=0, maxctx=0, model=m))
            s["calls"] += 1; s["maxctx"] = max(s["maxctx"], int(x.get("context") or 0))
    if not rows:
        return f"Frugal-Bridge: no usage logged in the last {days} days (files: " + \
               ", ".join(p for p, _ in usage_files()) + ")"
    out = [f"Frugal-Bridge usage, last {days} days (cost at API list prices; plans weigh output more)",
           "| tool | model | calls | input | output | cache read | cache write | ~$ |", "|---|---|---|---|---|---|---|---|"]
    for (t, m), a in sorted(rows.items(), key=lambda kv: (-kv[1]["cost"], kv[0])):
        out.append(f"| {t} | {m} | {a['calls']} | {a['input']:,} | {a['output']:,} | {a['cache_read']:,} | "
                   f"{a['cache_write']:,} | {a['cost']:.2f} |")
    alerts = []
    for (t, sid), s in sess.items():
        lim = 100000 if any(k in s["model"].lower() for k in ("haiku", "flash", "mini", "luna", "nano")) else 150000
        if s["maxctx"] > lim:
            alerts.append(f"- {t} session {str(sid)[:18]}: context reached {s['maxctx'] // 1000}k ({s['model']}) → hand off earlier")
        if s["calls"] > 300:
            alerts.append(f"- {t} session {str(sid)[:18]}: {s['calls']} calls → split the work into sessions")
    if alerts:
        out.append("\nAlerts:\n" + "\n".join(alerts[:15]))
    return "\n".join(out)


def matrix_lines(g):
    """What each installed tool got, one line each (printed after install)."""
    r = g.reg()
    out = []
    for t, info in (r.get("tools") or {}).items():
        h = HOSTS.H.get(t, {})
        rules = (f"via {info['via']}" if info.get("via") else "hook (RULES.md)" if info.get("rules_copy") and t == "cursor"
                 else "read: list" if info.get("rules_copy") else info.get("file", "?"))
        hk = "yes" if t in (r.get("native_hooks") or []) else ("plugin" if t == "hermes" else
                                                               "via claude-code" if h.get("hooks") in ("devin", "continue") and "claude-code" in r.get("tools", {}) else "no")
        ti = (r.get("tiers") or {}).get(t) or {}
        tiers = ", ".join(f"{n}={m}" + (f"/{e}" if e else "") for n, m, e, _ in ti.get("rows") or []) or \
            ("frugal-tiers backend" if t == "hermes" else "rules" if (h.get("tiers") or "").startswith("rules-") else "none")
        out.append(f"  {t}: rules {rules}; hooks {hk}; filter {'yes' if h.get('filter') and hk != 'no' else 'no'}; "
                   f"tiers {tiers}; proxy {h.get('proxy') or 'no'}")
    return out


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
        r = g.reg()
        tools = r.get("tools", {})
        print("Enforcement on this machine (every folder, every new session):")
        print("\n".join(matrix_lines(g)))
        if "codex" in (r.get("native_hooks") or []):
            print("  codex: open /hooks once in Codex and trust the Frugal-Bridge hooks (Codex runs hooks only after review)")
        for t, f in (r.get("needs_user") or {}).items():
            print(f"  {t}: NEEDS USER — {f} does not exist and was not created (creating it would replace the")
            print(f"    tool's default identity). To turn the rules on there, create that file with your own identity text")
            print(f"    and re-run install --global, or paste this block into it:")
            print(getattr(g, "pending_block", ""))
            c = (r.get("copied") or {}).get(t)
            if c:
                print(f"  {t} plugin: copied to {c['plugin']} — enable it to turn it on (restarts that tool's gateway)")
        hh = HOSTS.root("hermes")
        on = "hermes" in tools and hermes_plugin_enabled(hh, "frugal-bridge")
        if "hermes" in tools and on:
            print(f"  hermes plugin: {tools['hermes'].get('plugin')} — enabled")
        elif "hermes" in tools:
            print(f"  plugin: copied to {tools['hermes'].get('plugin')} — enable it to turn it on (restarts that tool's gateway)")
        if ("hermes" in tools or "hermes" in (r.get("copied") or {})) and g.tiers_status(hh).startswith("hermes tiers: on"):
            print(f"  {g.tiers_status(hh)}")
        elif "hermes" in tools or "hermes" in (r.get("copied") or {}):
            print(f"  tiers (per-subagent cheap/mid/top models): turn on with")
            print(f"    hermes plugins enable {TIERS_BACKEND}")
            print(f"    hermes config set delegation.backend {TIERS_BACKEND}")
            prev = next(iter((r.get("hermes_backend_prev") or {}).values()), "default")
            print(f"    undo: hermes config set delegation.backend {prev} && hermes plugins disable {TIERS_BACKEND}")
        if r.get("base"):
            print(f"  user files: the knowledge base {r['base']} owns them (no second copy made)")
        else:
            print(f"  user file: {os.path.join(g.d, 'USER.md')} — fill it (language, answer style; agent names go in role files, not here)")
        print("  usage report: python3 kit/setup.py report [days]")
        return 0 if rep.startswith("OK") else 1
    if argv[1] == "uninstall":
        print("\n".join(g.uninstall())); return 0
    rep = g.check(); print(rep)
    return 0 if rep.startswith("OK") else 1


def main(argv):
    if len(argv) >= 2 and argv[1] == "report":
        print(report(int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else 7)); return 0
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
