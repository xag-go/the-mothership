"""REAL harness x provider matrix for The Mothership (opt-in, never in CI).

    MOTHERSHIP_REAL=1 python3 -m unittest tests.real.test_real_matrix -v
    MOTHERSHIP_REAL=1 MOTHERSHIP_REAL_ROWS=claude-anthropic,gemini-google python3 -m unittest tests.real.test_real_matrix

Each row runs in a fresh temporary HOME (never the real one): the harness gets its own minimal config, then
`install.py --yes`, then real one-shot prompts from an unrelated folder, then `install.py uninstall`. Checked from
files and outputs:
  a  finds the base       the answer names a fact that is only in the fixture base (Robin Example / Lighthouse garden)
  b  writes the base      after "remember ...", the fact is in the base (wiki page or raw/inbox, write-both rule)
  c  memory collected     the tool's own memory store item lands in raw/inbox/collected/ via `brain.py collect`
                          (N/A for tools without a local store)
  d  Frugal rules         the rules block is in the file the tool loads, the agent picks the cheap tier for a small
                          bug fix with tests, and the helper-tier config (model + effort) written for the tool
                          matches tiers.json for its provider
  e  uninstall            the HOME is byte-identical to before the install, except the tool's own session/cache
                          files (listed), the base folder (your data stays) and the backup archives
Plus a delegation check where the harness has cheap subagents (Claude Code agents, Hermes frugal-tiers backend).

What a row needs (else it is skipped with the reason, reported as NOT RUN):
  - the harness program: found on PATH (put its folder on PATH for the run)
  - Claude Code / Hermes + Anthropic: ~/.claude/.credentials.json (copied into the temp HOME, deleted with it)
  - Google rows: GEMINI_API_KEY in the environment (passed to the harness process only; never written to a file
    outside the temp HOME)
Results (with the answers as evidence) are written as JSON to MOTHERSHIP_REAL_OUT (default: a file in the temp
dir) and printed. Prompts are tiny on purpose (cost). Standard library only.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SB_KIT = REPO / "components" / "skeleton-base"
FB_KIT = REPO / "components" / "frugal-bridge"
TIERS = json.loads((FB_KIT / "adapter/plugin/frugal-tiers/tiers.json").read_text())["tiers"]
REAL = os.environ.get("MOTHERSHIP_REAL") == "1"
ROWS = [r for r in os.environ.get("MOTHERSHIP_REAL_ROWS", "").split(",") if r]
OUT = Path(os.environ.get("MOTHERSHIP_REAL_OUT") or Path(tempfile.gettempdir()) / "mothership-real-matrix.json")
SCRUB = ("HERMES_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "FRUGAL_HOME", "FRUGAL_BRIDGE_KIT", "FRUGAL_BRIDGE_SRC",
         "FRUGAL_BASE", "BRAIN_ROOT", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
         "HERMES_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "GEMINI_CLI", "QWEN_HOME", "OPENCODE",
         "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "GOOGLE_API_KEY", "GEMINI_API_KEY",
         "GOOGLE_GENERATIVE_AI_API_KEY", "OPENAI_MODEL")
HIDE = {"systemctl", "loginctl", "claude", "codex", "gemini", "qwen", "opencode", "hermes"}   # never the real ones
NAME, FOCUS, TEA = "Robin Example", "Lighthouse garden", "Moonleaf"
ASK_A = ("Answer in exactly 3 short lines, no extra text: 1) my name 2) what I am focused on right now "
         "3) which helper model tier (cheap, mid or top) you would give a small bug fix that has tests.")
ASK_B = f"Remember this for later: my favourite tea is {TEA} oolong. Save it now, then reply with one word: saved."
GOOGLE_CHEAP = TIERS["cheap"]["google"]["id"]
# the main model of the Google rows (default: the cheap tier's model). Free-tier keys have a small daily request
# limit per model: MOTHERSHIP_REAL_GOOGLE_MODEL=another-flash-model spreads the rows over several limits.
GOOGLE_MAIN = os.environ.get("MOTHERSHIP_REAL_GOOGLE_MODEL") or GOOGLE_CHEAP


def results_add(row, data):
    """Every run of a row is kept (newest last): {row: [run, ...]}."""
    old = json.loads(OUT.read_text()) if OUT.is_file() else {}
    runs = old.get(row) if isinstance(old.get(row), list) else ([old[row]] if row in old else [])
    data["when"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    data["main_model"] = GOOGLE_MAIN if "google" in row else None
    old[row] = runs + [data]
    OUT.write_text(json.dumps(old, indent=2) + "\n")


def tree(d, skip=()):
    out = {}
    d = Path(d)
    for r, dirs, files in os.walk(d):
        rel_r = os.path.relpath(r, d)
        dirs[:] = [x for x in dirs if os.path.normpath(os.path.join(rel_r, x)) not in skip]
        for f in files:
            p = Path(r) / f
            rel = os.path.normpath(os.path.join(rel_r, f))
            if p.is_symlink():
                out[rel] = "link:" + os.readlink(p)
            elif p.is_file():
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        for x in dirs:
            out.setdefault(os.path.normpath(os.path.join(rel_r, x)) + "/", "dir")
    return out


def groups(paths):
    """{first two path parts: count} so a long list of a tool's own files stays readable."""
    out = {}
    for k in paths:
        g = "/".join(k.rstrip("/").split("/")[:2])
        out[g] = out.get(g, 0) + 1
    return dict(sorted(out.items()))


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text or "", re.S)
    out = {}
    for ln in (m.group(1).splitlines() if m else []):
        if ": " in ln:
            k, v = ln.split(": ", 1)
            try:
                out[k] = json.loads(v)
            except ValueError:
                out[k] = v
    return out


def expected_tiers(family):
    """{agent: (model id, effort)} from tiers.json, the way ROUTING.md defines them (mid-writing = mid at high)."""
    out = {}
    for agent, tier, eff in (("frugal-cheap", "cheap", None), ("frugal-mid", "mid", None),
                             ("frugal-mid-writing", "mid", "high"), ("frugal-top", "top", None)):
        row = TIERS.get(tier) or {}
        e = row.get(family)
        if isinstance(e, dict) and e.get("id"):
            out[agent] = (e["id"], eff or e.get("effort") or row.get("effort") or "medium")
    return out


@unittest.skipUnless(REAL, "real harness runs: set MOTHERSHIP_REAL=1 (needs the tools, logins and keys)")
class RealMatrix(unittest.TestCase):
    maxDiff = None

    # ------------------------------------------------------------ plumbing
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="ms-real-")
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.work = self.home / "work" / "unrelated-project"
        self.work.mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.sysbin = self.tmp / "sysbin"            # /usr/bin without systemctl and without other harnesses
        self.sysbin.mkdir()
        for d in ("/usr/bin", "/bin"):
            for n in os.listdir(d):
                if n not in HIDE and not (self.sysbin / n).exists():
                    (self.sysbin / n).symlink_to(Path(d) / n)
        (self.bin / "python3").symlink_to(sys.executable)
        self.base = self.home / "skeleton-base-home"
        self.extra_path = []
        self.secret_env = {}
        self.res = {"checks": {}, "evidence": {}}

    def tearDown(self):
        pid_file = self.home / ".hermes" / "gateway.pid"   # Hermes starts an idle-exit gateway for its home: stop it
        try:                                               # first, or it writes into the folder after it is removed
            pid = int(json.loads(pid_file.read_text()).get("pid"))
            env_of = Path(f"/proc/{pid}/environ").read_bytes()        # only that home's gateway (pids get reused)
            if f"HOME={self.home}".encode() not in env_of and f"={self.home}/.hermes".encode() not in env_of:
                raise ValueError("not this test's gateway")
            os.kill(pid, 15)
            for _ in range(50):
                os.kill(pid, 0)
                time.sleep(0.1)
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        self._td.cleanup()                           # also the copied credentials
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **kw):
        e = {k: v for k, v in os.environ.items() if k not in SCRUB and not k.startswith("MOTHERSHIP_")}
        e.update(HOME=str(self.home), PATH=os.pathsep.join([str(self.bin), *self.extra_path, str(self.sysbin)]),
                 LANG="C.UTF-8", NO_COLOR="1", TERM="dumb")
        e.update(self.secret_env)
        e.update(kw)
        return e

    def run_cmd(self, cmd, cwd=None, timeout=600, **kw):
        t0 = time.time()
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, cwd=str(cwd or self.work),
                           env=self.env(**kw), stdin=subprocess.DEVNULL, timeout=timeout)
        out = r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")
        for v in self.secret_env.values():           # never show a key, even if a tool echoes it
            out = out.replace(v, "<key>")
        return r.returncode, out, round(time.time() - t0, 1)

    def link_tool(self, name):
        p = shutil.which(name)
        if not p:
            self.skipTest(f"NOT RUN: {name} not found on PATH")
        (self.bin / name).symlink_to(Path(p).resolve() if name == "opencode" else p)
        if name in ("gemini", "qwen"):                # node scripts: node on PATH
            node = shutil.which("node")
            if not node:
                self.skipTest("NOT RUN: node not found on PATH")
            self.extra_path.append(str(Path(node).parent))
        return self.bin / name

    def claude_creds(self):
        cred = Path.home() / ".claude" / ".credentials.json"
        if not cred.is_file():
            self.skipTest("NOT RUN: no ~/.claude/.credentials.json")
        (self.home / ".claude").mkdir(exist_ok=True)
        shutil.copy2(cred, self.home / ".claude" / ".credentials.json")

    def gemini_key(self):
        k = os.environ.get("GEMINI_API_KEY")
        if not k:
            self.skipTest("NOT RUN: GEMINI_API_KEY not set")
        return k

    def write(self, rel, text):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def ms(self, *args):
        return self.run_cmd([sys.executable, REPO / "install.py", *args], cwd=self.tmp)

    def brain(self, *args):
        return self.run_cmd([sys.executable, self.base / "tools" / "brain.py", *args], cwd=self.base)

    def seed_base(self):
        who = self.base / "wiki/me/who-i-am.md"
        t = who.read_text()
        who.write_text(t.replace("- Name:", f"- Name: {NAME}", 1) if "- Name:" in t else t + f"\n- Name: {NAME}\n")
        hot = self.base / "hot.md"
        hot.write_text(hot.read_text().rstrip() + f"\n- Current focus: the {FOCUS} project\n")

    def base_has(self, word):
        hits = []
        for p in list((self.base / "wiki").rglob("*.md")) + list((self.base / "raw").rglob("*")) + \
                [self.base / "hot.md"]:
            if p.is_file() and "inbox/collected" not in str(p) and word in p.read_text(errors="replace"):
                hits.append(str(p.relative_to(self.base)))
        return hits

    def collected(self, word=None):
        d = self.base / "raw/inbox/collected"
        files = [p for p in d.rglob("*") if p.is_file()] if d.is_dir() else []
        if word:
            files = [p for p in files if word in p.read_text(errors="replace")]
        return sorted(str(p.relative_to(self.base)) for p in files)

    def mark(self, key, ok, evidence):
        self.res["checks"][key] = "PASS" if ok is True else ("FAIL" if ok is False else ok)
        self.res["evidence"][key] = evidence

    # ------------------------------------------------------------ one row
    def row(self, name, prompt, own_files, rules_file, tier_check, memory=True, delegation=None, before_snap=None):
        """prompt(text) -> (rc, out, secs); own_files = regexes of the tool's own session/cache paths."""
        if ROWS and name not in ROWS:
            self.skipTest(f"not selected (MOTHERSHIP_REAL_ROWS={','.join(ROWS)})")
        if before_snap:
            before_snap()
        h0 = tree(self.home)
        rc, out, secs = self.ms("--yes")
        self.res["install"] = {"rc": rc, "secs": secs, "tail": out.strip().splitlines()[-25:]}
        self.assertIn(rc, (0, 1), out)
        self.assertIn("checks: all OK", out, out)
        self.seed_base()
        self.brain("collect", "--base", self.base, "--quiet")          # what is there before the prompts
        before_collected = set(self.collected())

        # a + d(answer)
        rc, out, secs = prompt(ASK_A)
        self.res["evidence"]["prompt_a"] = {"rc": rc, "secs": secs, "answer": out.strip()[-1200:]}
        self.mark("a_finds_base", rc == 0 and NAME.split()[0] in out and "Lighthouse" in out,
                  "answer names Robin + Lighthouse" if rc == 0 else f"rc {rc}")
        lines = out.lower()
        cheap = bool(re.search(r"\bcheap\b", lines)) and not re.search(r"3\)\s*(mid|top)\b", lines)
        # d: rules block loaded where the tool reads it + the answer + tier config
        rf = self.home / rules_file
        rt = rf.read_text() if rf.is_file() else ""
        block = "<!-- base-folder:start" in rt and "<!-- frugal-bridge:start" in rt and \
            rt.index("<!-- base-folder:start") < rt.index("<!-- frugal-bridge:start")
        tc_ok, tc_ev = tier_check()
        self.mark("d_frugal", block and cheap and tc_ok,
                  {"rules_file": rules_file, "base_then_frugal_block": block, "answer_says_cheap": cheap,
                   "tier_config": tc_ev})

        # b
        rc, out, secs = prompt(ASK_B)
        self.res["evidence"]["prompt_b"] = {"rc": rc, "secs": secs, "answer": out.strip()[-600:]}
        hits = self.base_has(TEA)
        self.mark("b_writes_base", bool(hits), hits or "fact not found in the base (wiki/, raw/, hot.md)")

        # c
        if memory:
            rc, out, _ = self.brain("collect", "--base", self.base)
            new = sorted(set(self.collected()) - before_collected)
            with_tea = self.collected(TEA)
            self.mark("c_memory_collected", bool(with_tea), {"new_collected": new[:10], "with_fact": with_tea,
                                                              "collect_out": out.strip()[-400:]})
        else:
            self.mark("c_memory_collected", "N/A", "this tool keeps no local memory store")

        if delegation:
            ok, ev = delegation()
            self.mark("delegation", ok, ev)

        # e
        rc, out, secs = self.ms("uninstall")
        self.res["uninstall"] = {"rc": rc, "tail": out.strip().splitlines()[-8:]}
        h1 = tree(self.home)
        skip = ("skeleton-base-home", "skeleton-base-backups")
        changed = sorted(k for k in set(h0) | set(h1) if h0.get(k) != h1.get(k) and not k.startswith(skip))
        own = {k for k in changed if any(re.search(p, k) for p in own_files)}
        for k in sorted((k for k in changed if k.endswith("/")), key=len, reverse=True):
            under = [x for x in changed if x != k and x.startswith(k)]
            if under and all(x in own for x in under):
                own.add(k)                           # a folder the tool made for its own files only
        own = sorted(own)
        # kept on purpose: Frugal-Bridge's usage log is your data (its uninstall never deletes it)
        kept = [k for k in changed if k in (".frugal-bridge/", ".frugal-bridge/usage.jsonl")]
        other = [k for k in changed if k not in own and k not in kept]
        self.mark("e_uninstall_identical", rc == 0 and not other,
                  {"tool_own_groups": groups(own), "tool_own_count": len(own), "other_changes": other[:60],
                   "tool_config_changed": [k for k in own if re.search(r"(config\.yaml|settings\.json|opencode\.json|"
                                                                        r"SOUL\.md|\.claude\.json)$", k)],
                   "kept_by_design": kept,
                   "base_kept": self.base.is_dir(),
                   "backups": sorted(os.listdir(self.home / "skeleton-base-backups"))
                   if (self.home / "skeleton-base-backups").is_dir() else []})
        results_add(name, self.res)
        print(f"\n[{name}] " + json.dumps(self.res["checks"]), file=sys.stderr)
        fails = {k: v for k, v in self.res["checks"].items() if v == "FAIL"}
        self.assertFalse(fails, json.dumps(self.res, indent=2)[-6000:])

    # ------------------------------------------------------------ tier config checks (independent of Frugal's code)
    def agent_files_check(self, folder, family, model_of=lambda mid: mid, effort_key="effort", effort_fmt=None):
        exp = expected_tiers(family)
        got, bad = {}, []
        for agent, (mid, eff) in exp.items():
            fm = frontmatter((self.home / folder / f"{agent}.md").read_text()
                             if (self.home / folder / f"{agent}.md").is_file() else "")
            got[agent] = {k: fm.get(k) for k in ("model", effort_key) if k in fm}
            want_model = model_of(mid) if not effort_fmt else effort_fmt(model_of(mid), eff)
            if fm.get("model") != want_model:
                bad.append(f"{agent}: model {fm.get('model')!r} != {want_model!r}")
            if effort_key and not effort_fmt and fm.get(effort_key) != eff:
                bad.append(f"{agent}: {effort_key} {fm.get(effort_key)!r} != {eff!r}")
        return (not bad and bool(exp)), {"expected_from_tiers.json": exp, "written": got, "mismatch": bad}

    # ------------------------------------------------------------ rows
    def test_claude_anthropic(self):
        claude = self.link_tool("claude")
        self.claude_creds()

        def prompt(q, extra=()):
            if extra:
                return self.run_cmd([claude, "-p", q, "--model", "sonnet", "--permission-mode", "acceptEdits", *extra])
            rc, out, secs = self.run_cmd([claude, "-p", q, "--model", "sonnet", "--permission-mode", "acceptEdits",
                                          "--output-format", "json"])
            try:
                d = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                return rc, out, secs
            den = d.get("permission_denials") or []
            if den:                                  # what the tool refused, as evidence
                self.res["evidence"].setdefault("permission_denials", []).extend(
                    {"tool": x.get("tool_name"), "input": json.dumps(x.get("tool_input"))[:400]} for x in den)
            return rc, str(d.get("result", "")), secs

        def tiers():                                 # Anthropic id form of the table's model (dots -> dashes)
            return self.agent_files_check(".claude/agents", "anthropic", model_of=lambda mid: mid.replace(".", "-"))

        def delegation():
            q = ("Use the frugal-cheap subagent (Agent tool) to compute 2+2. Reply with its answer and the name of the "
                 "subagent you used.")
            known = set(self.home.glob(".claude/projects/*/*/subagents/*.jsonl"))
            rc, out, secs = prompt(q, ("--output-format", "stream-json", "--verbose"))
            sub, final, main_models = [], "", set()
            for ln in out.splitlines():
                try:
                    ev = json.loads(ln)
                except ValueError:
                    continue
                if ev.get("type") == "result":
                    final = str(ev.get("result", ""))
                msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
                if ev.get("type") == "assistant" and msg.get("model") and not ev.get("parent_tool_use_id"):
                    main_models.add(msg["model"])
                for c in msg.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and (c.get("input") or {}).get("subagent_type"):
                        sub.append(c["input"]["subagent_type"])
            # which model the helper really ran on: its own transcript (Claude Code writes one per subagent)
            child = {}
            for f in sorted(set(self.home.glob(".claude/projects/*/*/subagents/*.jsonl")) - known):
                ms = set()
                for ln in f.read_text(errors="replace").splitlines():
                    try:
                        m = (json.loads(ln).get("message") or {}).get("model")
                    except (ValueError, AttributeError):
                        m = None
                    if m:
                        ms.add(m)
                meta = f.with_name(f.name.replace(".jsonl", ".meta.json"))
                child[f.name] = {"models": sorted(ms), "meta": json.loads(meta.read_text()) if meta.is_file() else None}
            want = TIERS["cheap"]["anthropic"]["id"].replace(".", "-")
            ok = rc == 0 and "frugal-cheap" in sub and "4" in final and bool(child) and \
                all(any(m.startswith(want) for m in c["models"]) for c in child.values())
            return ok, {"subagent_type": sub, "main_model": sorted(main_models), "child_transcripts": child,
                        "result": final[-300:], "secs": secs}

        self.row("claude-anthropic", prompt,
                 own_files=[r"^\.claude/projects/", r"^\.claude/(sessions|shell-snapshots|statsig|todos|debug|"
                            r"session-env|file-history|plugins|ide|backups|cache|telemetry|paste-cache)(/|$)",
                            r"^\.claude\.json(\.backup.*)?$", r"^\.claude/history\.jsonl$", r"^\.cache/",
                            r"^\.local/state/claude", r"^\.claude/\.credentials\.json$", r"^\.local/share/claude",
                            r"^\.claude/\.last-cleanup$", r"^\.claude/skills/synced/"],
                 rules_file=".claude/CLAUDE.md", tier_check=tiers, delegation=delegation)

    def hermes_row(self, name, provider, model, own_creds, delegation_test):
        hermes = self.link_tool("hermes")
        if own_creds == "claude":
            self.claude_creds()
        else:
            self.secret_env["GEMINI_API_KEY"] = self.gemini_key()
        hh = self.home / ".hermes"
        hh.mkdir(exist_ok=True)
        (hh / "config.yaml").write_text(f'model:\n  default: "{model}"\n  provider: "{provider}"\n')

        def boot():                                  # first run: Hermes makes its home (SOUL.md, deps) itself
            rc, out, _ = self.run_cmd([hermes, "config", "path"], timeout=600)
            self.assertEqual(rc, 0, out)
            self.assertTrue((hh / "SOUL.md").is_file(), "Hermes did not create SOUL.md")

        def prompt(q):
            return self.run_cmd([hermes, "chat", "-q", q], timeout=900)

        def tiers():
            p = hh / "plugins" / "frugal-tiers" / "tiers.json"
            same = p.is_file() and p.read_bytes() == (FB_KIT / "adapter/plugin/frugal-tiers/tiers.json").read_bytes()
            soul = (hh / "SOUL.md").read_text()
            para = "Helper tiers here" in soul and "tier" in soul
            fam = "anthropic" if provider == "anthropic" else "google"
            return same and para, {"plugin_tiers.json_equals_kit": same, "rules_paragraph": para,
                                   "expected_for_provider": expected_tiers(fam),
                                   "note": "Hermes maps tiers at call time in the frugal-tiers delegation backend "
                                           "(per provider, model + effort); off until the user enables it"}

        def delegation():
            cmds = [[hermes, "plugins", "enable", "frugal-tiers"],
                    [hermes, "config", "set", "delegation.backend", "frugal-tiers"]]
            for c in cmds:
                rc, out, _ = self.run_cmd(c, timeout=300)
                if rc:
                    return False, f"{' '.join(map(str, c[1:]))}: rc {rc} {out[-300:]}"
            rc, out, secs = prompt("Use delegate_task with tier cheap to compute 2+2. Reply with the result only.")
            db = hh / "state.db"
            rows = []
            if db.is_file():
                con = sqlite3.connect(db)
                cols = [r[1] for r in con.execute("PRAGMA table_info(sessions)")]
                if "parent_session_id" in cols:
                    sel = ", ".join(c for c in ("id", "model", "parent_session_id") if c in cols)
                    rows = [dict(zip(sel.split(", "), r)) for r in
                            con.execute(f"SELECT {sel} FROM sessions WHERE parent_session_id IS NOT NULL")]
                con.close()
            fam = "anthropic" if provider == "anthropic" else "google"
            want = TIERS["cheap"][fam]["id"].replace(".", "-")
            ok = rc == 0 and any(want in str(r.get("model", "")).replace(".", "-") for r in rows) and "4" in out
            # the user's undo (Frugal prints it): backend back, plugin off
            for c in ([hermes, "config", "set", "delegation.backend", "default"],
                      [hermes, "plugins", "disable", "frugal-tiers"]):
                self.run_cmd(c, timeout=300)
            return ok, {"child_sessions": rows, "want_model": want, "answer": out.strip()[-300:], "secs": secs}

        self.row(name, prompt,
                 own_files=[r"^\.hermes/(sessions|logs|cache|audio_cache|image_cache|state|memories|pairing|"
                            r"pending_messages|platforms|plugin-update-checks|runtime|installs|cron|kanban|hooks|"
                            r"backups|bootstrap-cache|lsp|gateway)(/|$)", r"^\.hermes/skills/(?!frugal)",
                            r"^\.hermes/[^/]*\.(db|db-shm|db-wal|lock|pid|sock|json|etag|log)$",
                            r"^\.hermes/(state\.db.*|projects\.db.*|kanban\.db.*)$", r"^\.hermes/config\.yaml$",
                            r"^\.cache/", r"^\.claude/\.credentials\.json$", r"^\.local/state/",
                            r"^\.hermes/(install_id|\.install_id\.lock)$", r"^\.hermes/source-checks/"],
                 rules_file=".hermes/SOUL.md", tier_check=tiers, delegation=delegation if delegation_test else None,
                 before_snap=boot)

    def test_hermes_anthropic(self):
        self.hermes_row("hermes-anthropic", "anthropic", "claude-sonnet-5-5", "claude", delegation_test=True)

    def test_hermes_google(self):
        self.hermes_row("hermes-google", "gemini", GOOGLE_MAIN, "gemini", delegation_test=True)

    def test_gemini_google(self):
        gemini = self.link_tool("gemini")
        self.secret_env["GEMINI_API_KEY"] = self.gemini_key()
        # current key names: Gemini CLI rewrites deprecated ones (disableAutoUpdate) in place on its first start
        self.write(".gemini/settings.json", json.dumps({
            "security": {"auth": {"selectedType": "gemini-api-key"}}, "model": {"name": GOOGLE_MAIN},
            "general": {"enableAutoUpdate": False}, "privacy": {"usageStatisticsEnabled": False}}, indent=2) + "\n")

        def prompt(q):                # the project folder is trusted, as the user does once per project
            return self.run_cmd([gemini, "-p", q, "-m", GOOGLE_MAIN, "--approval-mode", "yolo"], timeout=600,
                                GEMINI_CLI_TRUST_WORKSPACE="true")

        def tiers():
            ok, ev = self.agent_files_check(".gemini/agents", "google", effort_key=None)
            st = json.loads((self.home / ".gemini/settings.json").read_text())
            ov = {o.get("match", {}).get("overrideScope"): o.get("modelConfig", {}).get("generateContentConfig", {})
                  .get("thinkingConfig", {}).get("thinkingLevel") for o in (st.get("modelConfigs") or {})
                  .get("overrides", [])}
            want = {a: e.upper() for a, (_, e) in expected_tiers("google").items()}
            ev["thinkingLevel_overrides"] = ov
            ok = ok and all(ov.get(a) == lv for a, lv in want.items())
            return ok, ev

        self.row("gemini-google", prompt,
                 own_files=[r"^\.gemini/(tmp|history|antigravity|cache|commands)(/|$)", r"^\.gemini/(?!settings\.json$)[^/]*\.json$",
                            r"^\.cache/", r"^\.local/state/", r"^\.config/configstore/", r"^\.npm/"],
                 rules_file=".gemini/GEMINI.md", tier_check=tiers)

    def test_qwen_google_openai_compatible(self):
        qwen = self.link_tool("qwen")
        k = self.gemini_key()
        self.secret_env.update(OPENAI_API_KEY=k, OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/",
                               OPENAI_MODEL=GOOGLE_MAIN)
        self.write(".qwen/settings.json", json.dumps({
            "security": {"auth": {"selectedType": "openai"}}, "model": {"name": GOOGLE_MAIN},
            "general": {"disableAutoUpdate": True}, "privacy": {"usageStatisticsEnabled": False}}, indent=2) + "\n")

        def prompt(q):
            return self.run_cmd([qwen, q, "-m", GOOGLE_MAIN, "--approval-mode", "yolo"], timeout=600)

        def boot():           # first start: Qwen migrates its settings ("$version") and makes its home; no API call
            self.run_cmd([qwen, "hi"], timeout=120, OPENAI_BASE_URL="http://127.0.0.1:9/")

        def tiers():
            st = json.loads((self.home / ".qwen/settings.json").read_text())
            grades = (st.get("agents") or {}).get("modelGrades") or {}
            exp = {a: m for a, (m, _) in expected_tiers("google").items() if a != "frugal-mid-writing"}
            bad = [f"{a}: {grades.get(a)!r} != {m!r}" for a, m in exp.items() if grades.get(a) != m]
            return not bad, {"expected_from_tiers.json": exp, "agents.modelGrades": grades, "mismatch": bad,
                             "effort": "Qwen has no per-subagent effort (said in the rules)"}

        self.row("qwen-google", prompt,
                 own_files=[r"^\.qwen/(tmp|history|projects|todos|cache|debug|commands|logs|memories)(/|$)",
                            r"^\.qwen/usage_record\.jsonl$",
                            r"^\.qwen/(?!settings\.json$)[^/]*\.json$", r"^\.cache/", r"^\.local/state/", r"^\.config/configstore/"],
                 rules_file=".qwen/QWEN.md", tier_check=tiers, before_snap=boot)

    def test_opencode_google(self):
        oc = self.link_tool("opencode")
        self.secret_env["GOOGLE_GENERATIVE_AI_API_KEY"] = self.gemini_key()
        self.write(".config/opencode/opencode.json", json.dumps({
            "$schema": "https://opencode.ai/config.json", "model": f"google/{GOOGLE_MAIN}",
            "small_model": f"google/{GOOGLE_MAIN}", "autoupdate": False}, indent=2) + "\n")   # one model: one quota

        def prompt(q):
            return self.run_cmd([oc, "run", q, "-m", f"google/{GOOGLE_MAIN}"], timeout=600)

        def tiers():
            return self.agent_files_check(".config/opencode/agents", "google", model_of=lambda m: f"google/{m}",
                                          effort_key=None,
                                          effort_fmt=lambda m, e: m + (f"#{e}" if e != "medium" else ""))

        self.row("opencode-google", prompt,
                 own_files=[r"^\.local/share/opencode(/|$)", r"^\.local/state/", r"^\.cache/",
                            r"^\.config/opencode/(node_modules|package\.json|package-lock\.json|bun\.lock|\.gitignore)",
                            r"^\.bun/", r"^\.npm/"],
                 rules_file=".config/opencode/AGENTS.md", tier_check=tiers, memory=False)

    def test_codex_openai(self):
        self.skipTest("NOT RUN: Codex + OpenAI: the account's usage limit is reached until 2026-11-13")


if __name__ == "__main__":
    unittest.main()
