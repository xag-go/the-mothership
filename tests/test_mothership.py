"""The Mothership tests. Run: python3 -m unittest -v   (standard library only)

Every test runs in a temporary HOME with FRUGAL_HOME / XDG / tool-home overrides removed and PATH reduced to a
folder holding only python3 (plus a fake systemctl where a test needs one), so nothing touches the real home or
the real systemd user manager.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SB_VENDOR = REPO / "components" / "skeleton-base"
FB_VENDOR = REPO / "components" / "frugal-bridge"
frugal_quoted = "def parse_base_path" in (FB_VENDOR / "kit" / "setup.py").read_text()   # reads quoted Path: lines
SCRUB = ("HERMES_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "FRUGAL_HOME", "FRUGAL_BRIDGE_KIT", "FRUGAL_BRIDGE_SRC",
         "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "MOTHERSHIP_HOME",
         "MOTHERSHIP_PLATFORM", "MOTHERSHIP_TEST_FAIL", "MOTHERSHIP_TEST_KILL", "BRAIN_ROOT", "HERMES_AGENT")
USER_CLAUDE = "# my global rules\nUse tabs.\n"
USER_SETTINGS = ('{\n  "hooks": {\n    "Stop": [\n      {"hooks": [{"type": "command", "command": "echo my-own-hook"}]}\n'
                 '    ]\n  },\n  "theme": "dark"\n}\n')
FAKE_USER = ("# USER.md\n\n- Name of the main agent (any name the user likes): Atlas\n- Language and script: English\n"
             "- Name: Robin Example\n")
FAKE_SYSTEMCTL = """#!/bin/sh
echo "$@" >> "$FAKE_SD_LOG"
case "$2" in
  show-environment) echo HOME=x; exit 0;;
  is-enabled) echo disabled; exit 1;;
  is-active) read -r s < "$FAKE_SD_STATE"; echo "$s"; [ "$s" = active ];;
  *) exit 0;;
esac
"""


def tree(d, skip=()):
    """rel path -> sha256 (files), 'dir' (folders), 'link:target' (symlinks)."""
    out, d = {}, Path(d)
    if not d.exists():
        return out
    for root, dirs, files in os.walk(d):
        for name in dirs + files:
            p = Path(root) / name
            rel = p.relative_to(d).as_posix()
            if any(rel == s or rel.startswith(s + "/") for s in skip):
                continue
            if p.is_symlink():
                out[rel] = "link:" + os.readlink(p)
            elif p.is_dir():
                out[rel] = "dir"
            else:
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def page_text(title, body):
    """A wiki page that passes brain.py lint (frontmatter with sources and scope)."""
    return f"---\ntitle: {title}\nsources: [conversation 2026-11-11]\nupdated: 2026-11-11\nscope: private\n---\n\n# {title}\n\n{body}\n"


def strip_blocks(text, kit):
    return re.sub(rf"\n*<!-- {kit}:start[^>]*-->.*?<!-- {kit}:end -->\n?", "\n", text, flags=re.S)


class Base(unittest.TestCase):
    repo = REPO

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="mothership-")
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        for d in (".claude", ".codex", ".gemini"):
            (self.home / d).mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        self.sd_log = self.tmp / "systemctl.log"
        self.sd_state = self.tmp / "systemctl.state"
        self.extra_env = {}

    def tearDown(self):
        self._td.cleanup()

    @property
    def base(self):
        return self.home / "skeleton-base-home"

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if k not in SCRUB and not k.startswith("MOTHERSHIP_")}
        e.update(HOME=str(self.home), PATH=str(self.bin), BRAIN_TODAY="2026-11-11", PYTHONDONTWRITEBYTECODE="1",
                 FAKE_SD_LOG=str(self.sd_log), FAKE_SD_STATE=str(self.sd_state), LANG="C.UTF-8")
        e.update(self.extra_env)
        e.update(extra)
        return e

    def ms(self, *args, rc=0, repo=None, **extra):
        r = subprocess.run([sys.executable, str((repo or self.repo) / "install.py"), *map(str, args)],
                           capture_output=True, text=True, env=self.env(**extra), cwd=str(self.tmp), stdin=subprocess.DEVNULL)
        out = r.stdout + r.stderr
        if rc is not None:
            self.assertEqual(r.returncode, rc, out)
        self.assertNotIn("Traceback", out)
        return out

    def py(self, *args, rc=0, **extra):
        r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, env=self.env(**extra),
                           cwd=str(self.tmp), stdin=subprocess.DEVNULL)
        if rc is not None:
            self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def user_files(self):
        (self.home / ".claude" / "CLAUDE.md").write_text(USER_CLAUDE)
        (self.home / ".claude" / "settings.json").write_text(USER_SETTINGS)

    def fake_systemctl(self, state="active"):
        f = self.bin / "systemctl"
        f.write_text(FAKE_SYSTEMCTL)
        f.chmod(0o755)
        self.sd_state.write_text(state)

    def frugal_kit_copy(self, src=FB_VENDOR):
        dst = self.tmp / "frugal-kit"
        if not dst.exists():
            shutil.copytree(src, dst)
        return dst / "kit" / "setup.py"

    def rules(self):
        return [self.home / ".claude/CLAUDE.md", self.home / ".codex/AGENTS.md", self.home / ".gemini/GEMINI.md"]

    def assert_order(self, f):
        t = f.read_text()
        self.assertEqual(t.count("<!-- base-folder:start"), 1, f)
        self.assertEqual(len(re.findall(r"<!-- frugal-bridge:start", t)), 1, f)
        self.assertLess(t.index("<!-- base-folder:start"), t.index("<!-- frugal-bridge:start"), f)

    def state(self, base=None):
        return json.loads(((base or self.base) / ".mothership.json").read_text())

    def copy_repo(self, dst):
        shutil.copytree(self.repo, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        return dst


class InstallTests(Base):
    def test_fresh_install_both_products_working_together(self):
        out = self.ms("--yes")
        self.assertIn("checks: all OK", out)
        self.assertIn("systemctl --user daemon-reload && systemctl --user enable --now skeleton-base-watch.service "
                      "skeleton-base-collect.timer", out)
        self.assertIn("hot.md", out)
        self.assertIn("maps/brain.html", out)
        for f in self.rules():
            self.assert_order(f)
            self.assertIn(f"Path: {self.base}", f.read_text())
        reg = json.loads((self.home / ".frugal-bridge/global.json").read_text())
        self.assertEqual(reg["base"], str(self.base))                         # one user slot: the base
        self.assertEqual(reg["kit"], str(self.home / ".local/share/the-mothership/payload/components/frugal-bridge"))
        self.assertFalse((self.home / ".frugal-bridge/USER.md").exists())
        cs = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(cs["permissions"]["additionalDirectories"], [str(self.base)])   # Claude reads it anywhere
        kits = json.loads((self.base / ".kits.json").read_text())
        self.assertEqual(set(kits["kits"]), {"base-folder", "frugal-bridge"})
        self.assertEqual(kits["slots"]["now"], "hot.md")
        a = (self.base / "AGENTS.md").read_text()
        self.assertLess(a.index("<!-- base-folder:start"), a.index("<!-- frugal-bridge:start"))
        for u in ("skeleton-base-watch.service", "skeleton-base-collect.timer"):
            self.assertTrue((self.home / ".config/systemd/user" / u).is_file())
        st = self.state()
        self.assertEqual(st["own"], {"base": "installed", "connect": "installed", "frugal_global": "installed",
                                     "frugal_project": "installed"})
        self.assertEqual(st["components"]["skeleton-base"]["commit"],
                         json.loads((REPO / "components.lock").read_text())["components"]["skeleton-base"]["commit"])
        self.assertTrue((self.base / "maps/brain.html").is_file() and (self.base / "hot.md").is_file())
        self.assertFalse((self.home / ".local/share/the-mothership/journal.json").exists())
        self.assertIn("check: OK", self.ms("check"))

    def test_rerun_is_byte_identical(self):
        self.user_files()
        self.ms("--yes")
        t1 = tree(self.home)
        self.ms("--yes")
        self.assertEqual(tree(self.home), t1)
        self.ms()                       # without --yes (no tty): same result
        self.assertEqual(tree(self.home), t1)

    def test_dry_run_writes_nothing(self):
        self.user_files()
        t0 = tree(self.home)
        out = self.ms("--dry-run")
        self.assertIn("dry run: nothing is written", out)
        self.assertIn("kit/setup.py install --global", out)
        self.assertEqual(tree(self.home), t0)

    def test_user_text_and_other_hooks_kept_and_uninstall_restores_home_byte_identical(self):
        self.user_files()
        (self.home / ".gemini/GEMINI.md").write_text("Gemini: answer briefly.\n")
        (self.home / ".codex/AGENTS.md").write_text("# codex notes\n- run tests first\n")
        t0 = tree(self.home)
        self.ms("--yes")
        c = (self.home / ".claude/CLAUDE.md").read_text()
        self.assertTrue(c.startswith(USER_CLAUDE))
        self.assertEqual(strip_blocks(strip_blocks(c, "frugal-bridge"), "base-folder").strip(), USER_CLAUDE.strip())
        s = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(s["theme"], "dark")
        self.assertIn("echo my-own-hook", json.dumps(s["hooks"]["Stop"]))
        self.assertIn("SessionEnd", s["hooks"])          # base collect hook
        self.assertIn("SessionStart", s["hooks"])        # Frugal-Bridge hook
        out = self.ms("uninstall")
        self.assertIn("uninstalled", out)
        self.assertEqual(tree(self.home), t0)

    def test_uninstall_fresh_home_byte_identical_including_folders(self):
        t0 = tree(self.home)
        self.ms("--yes")
        self.ms("uninstall")
        self.assertEqual(tree(self.home), t0)
        self.assertFalse(self.base.exists())

    def test_keep_backups_documented_leftovers_only(self):
        self.user_files()
        t0 = tree(self.home)
        self.ms("--yes")
        self.ms("uninstall", "--keep-backups")
        extra = set(tree(self.home)) - set(t0)
        self.assertTrue(extra)
        for p in extra:
            self.assertTrue(p.startswith((".frugal-bridge", "skeleton-base-home")), p)
            self.assertTrue(re.search(r"(^\.frugal-bridge$|^\.frugal-bridge/backup|/\.brain(/backups|$)|"
                                      r"/\.frugal-bridge(/backup|$)|^skeleton-base-home$)", p), p)
        for rel, h in t0.items():
            self.assertEqual(tree(self.home).get(rel), h, rel)

    def test_inside_an_agent_session_env_and_existing_hermes_identity(self):
        """Run from inside an agent tool (HERMES_AGENT set): nothing may be left in that tool's home."""
        t0 = tree(self.home)
        self.ms("--yes", HERMES_AGENT="true")
        self.ms("uninstall", HERMES_AGENT="true")
        self.assertEqual(tree(self.home), t0)
        soul = self.home / ".hermes/SOUL.md"
        soul.parent.mkdir()
        soul.write_text("You are my assistant.\n")
        t0 = tree(self.home)
        self.ms("--yes", HERMES_AGENT="true")
        self.assert_order(soul)
        self.assertTrue(soul.read_text().startswith("You are my assistant.\n"))
        self.ms("uninstall", HERMES_AGENT="true")
        self.assertEqual(tree(self.home), t0)

    def test_no_frugal(self):
        t0 = tree(self.home)
        out = self.ms("--yes", "--no-frugal")
        self.assertIn("checks: all OK", out)
        self.assertFalse((self.home / ".frugal-bridge").exists())
        self.assertFalse((self.base / ".frugal-bridge").exists())
        self.assertNotIn("frugal-bridge", json.loads((self.base / ".kits.json").read_text())["kits"])
        for f in self.rules():
            self.assertNotIn("frugal-bridge:start", f.read_text())
            self.assertIn("base-folder:start", f.read_text())
        self.assertNotIn("frugal", json.dumps(self.state()["own"]))
        self.ms("uninstall")
        self.assertEqual(tree(self.home), t0)

    def test_non_default_base_inside_and_outside_home(self):
        for base in (self.home / "notes" / "brain", self.tmp / "elsewhere" / "kb"):
            with self.subTest(base=base):
                t0, o0 = tree(self.home), tree(self.tmp / "elsewhere")
                out = self.ms("--yes", "--base", base)
                self.assertIn(f"Your knowledge base: {base}", out)
                self.assertEqual(json.loads((self.home / ".frugal-bridge/global.json").read_text())["base"], str(base))
                self.assertIn(str(base), self.ms("status"))     # found without --base
                self.assertIn("check: OK", self.ms("check"))
                self.ms("uninstall")
                self.assertEqual(tree(self.home), t0)
                self.assertFalse(base.exists())

    def test_install_from_a_path_with_spaces(self):
        repo = self.copy_repo(self.tmp / "My Downloads" / "the mothership")
        t0 = tree(self.home)
        out = self.ms("--yes", repo=repo)
        self.assertIn("checks: all OK", out)
        payload = self.home / ".local/share/the-mothership/payload"
        self.assertEqual(tree(payload / "components"), tree(repo / "components"))
        shutil.rmtree(repo)                         # the clone may go away: the payload copy is enough
        self.py(payload / "install.py", "check")
        self.py(payload / "install.py", "uninstall")
        self.assertEqual(tree(self.home), t0)

    def test_base_path_with_spaces(self):
        """Skeleton Base quotes a path with spaces everywhere; without Frugal-Bridge that always works."""
        base = self.home / "my base"
        t0 = tree(self.home)
        out = self.ms("--yes", "--no-frugal", "--base", base)
        self.assertIn("checks: all OK", out)
        for f in self.rules():
            self.assertIn(f'Path: "{base}"\n', f.read_text())
        self.assertIn(str(base), self.ms("status"))
        unit = (self.home / ".config/systemd/user/skeleton-base-watch.service").read_text()
        self.assertIn(f'watch --base "{base}"', unit)
        self.ms("uninstall")
        self.assertEqual(tree(self.home), t0)
        # an already connected base with spaces is found again by its quoted Path: line
        self.py(SB_VENDOR / "tools/brain.py", "init", base, "--frugal=no")
        self.py(base / "tools/brain.py", "connect", "--base", base)
        out = self.ms("--yes", "--no-frugal")
        self.assertIn(f"found an existing knowledge base: {base}", out)

    @unittest.skipUnless(frugal_quoted, "the vendored Frugal-Bridge has no parse_base_path (quoted Path: lines)")
    def test_base_path_with_spaces_and_frugal_install_uninstall_byte_identical(self):
        """The vendored Frugal-Bridge reads a quoted Path: line, so a base path with spaces works with it too:
        one user file (the base), both blocks in order, and uninstall gives the home back byte for byte."""
        self.user_files()
        base = self.home / "my notes" / "second brain"
        t0 = tree(self.home)
        out = self.ms("--yes", "--base", base)
        self.assertIn("checks: all OK", out)
        self.assertIn(f"Your knowledge base: {base}", out)
        for f in self.rules():
            self.assert_order(f)
            self.assertIn(f'Path: "{base}"\n', f.read_text())
        self.assertEqual(json.loads((self.home / ".frugal-bridge/global.json").read_text())["base"], str(base))
        self.assertFalse((self.home / ".frugal-bridge/USER.md").exists())      # no second user file
        self.assertIn(str(base), self.ms("status"))                             # found without --base
        self.assertIn("check: OK", self.ms("check"))
        t1 = tree(self.home)
        self.ms("--yes", "--base", base)                                         # re-run: byte-identical
        self.assertEqual(tree(self.home), t1)
        self.ms("uninstall")
        self.assertEqual(tree(self.home), t0)
        self.assertFalse(base.exists())

    def test_base_path_with_spaces_refused_with_an_older_frugal(self):
        """A vendored Frugal-Bridge without parse_base_path reads the path only up to the first space: refused
        before anything is written, with --no-frugal as the way out."""
        repo = self.copy_repo(self.tmp / "older-frugal")
        setup = repo / "components" / FB_VENDOR.name / "kit" / "setup.py"
        setup.write_text(setup.read_text().replace("parse_base_path", "old_base_path"))
        self.py(repo / "tools/update-components.py", "--relock", "--only", "frugal-bridge")
        base = self.home / "my base"
        t0 = tree(self.home)
        out = self.ms("--yes", "--base", base, rc=2, repo=repo)
        self.assertIn("contains a space", out)
        self.assertIn("--no-frugal", out)
        self.assertEqual(tree(self.home), t0)
        self.assertIn("checks: all OK", self.ms("--yes", "--no-frugal", "--base", base, repo=repo))

    def test_hermes_without_soul_md_stays_without_it(self):
        """A Hermes home with no SOUL.md keeps its default identity: Frugal-Bridge never creates SOUL.md, and
        install + uninstall leave the home byte-identical."""
        hermes = self.home / ".hermes"
        hermes.mkdir()
        (hermes / "config.yaml").write_text("model: default\n")
        t0 = tree(self.home)
        for env in ({}, {"HERMES_AGENT": "true"}):
            with self.subTest(env=env):
                out = self.ms("--yes", **env)
                self.assertIn("checks: all OK", out)
                self.assertFalse((hermes / "SOUL.md").exists(), out)
                self.ms("check", **env)
                self.ms("uninstall", **env)
                self.assertFalse((hermes / "SOUL.md").exists())
                self.assertEqual(tree(self.home), t0)

    def test_existing_base_adopted_not_duplicated(self):
        mine = self.home / "my-brain"
        self.py(SB_VENDOR / "tools/brain.py", "init", mine, "--frugal=no")
        self.py(mine / "tools/brain.py", "connect", "--base", mine)
        (mine / "wiki/projects/garden.md").write_text(page_text("Garden", "Tomatoes."))
        self.py(mine / "tools/brain.py", "index", "--root", mine)
        out = self.ms("--yes")                               # no --base: finds the connected base
        self.assertIn(f"found an existing knowledge base: {mine}", out)
        self.assertFalse(self.base.exists())                 # no second base
        st = self.state(mine)
        self.assertEqual(st["own"]["base"], "adopted")
        self.assertEqual(st["own"]["connect"], "adopted")
        for f in self.rules():
            self.assert_order(f)
        self.assertEqual(json.loads((self.home / ".frugal-bridge/global.json").read_text())["base"], str(mine))
        self.ms("uninstall")
        self.assertIn("base-folder", json.loads((mine / ".kits.json").read_text())["kits"])   # adopted: kept
        self.assertEqual((mine / "wiki/projects/garden.md").read_text().splitlines()[-1], "Tomatoes.")
        self.assertFalse((self.home / ".frugal-bridge/global.json").exists())
        for f in self.rules():
            self.assertIn("base-folder:start", f.read_text())
            self.assertNotIn("frugal-bridge:start", f.read_text())

    def test_existing_frugal_global_adopted_with_user_import(self):
        self.user_files()
        setup = self.frugal_kit_copy()
        self.py(setup, "install", "--global")
        (self.home / ".frugal-bridge/USER.md").write_text(FAKE_USER)
        before = {f: f.read_bytes() for f in self.rules() + [self.home / ".claude/settings.json"]}
        out = self.ms("--yes")
        self.assertIn("checks: all OK", out)
        st = self.state()
        self.assertEqual(st["own"]["frugal_global"], "adopted")
        self.assertEqual(st["own"]["base"], "installed")
        who = (self.base / "wiki/me/who-i-am.md").read_text()
        talk = (self.base / "wiki/me/how-to-talk-to-me.md").read_text()
        self.assertIn("Robin Example", who)
        self.assertIn("Atlas", talk)
        for f in self.rules():
            self.assert_order(f)
        reg = json.loads((self.home / ".frugal-bridge/global.json").read_text())
        self.assertEqual(reg["base"], str(self.base))
        t1 = tree(self.home)
        self.ms("--yes")
        self.assertEqual(tree(self.home), t1)
        self.assertEqual(who.count("Robin Example"), 1)
        self.ms("uninstall")
        reg = json.loads((self.home / ".frugal-bridge/global.json").read_text())   # Frugal stays (adopted)
        self.assertNotIn("base", reg)
        self.assertNotIn("kit", reg)
        for f, b in before.items():
            self.assertEqual(f.read_bytes(), b, f)              # its files back exactly as before the base came
        self.assertIn("Robin Example", (self.home / ".frugal-bridge/USER.md").read_text())

    def test_lock_tamper_refused_nothing_written(self):
        repo = self.copy_repo(self.tmp / "ms")
        f = repo / "components/skeleton-base/tools/brain.py"
        f.write_text(f.read_text() + "\n# tampered\n")
        (repo / "components/frugal-bridge/kit/extra.py").write_text("print('x')\n")
        t0 = tree(self.home)
        out = self.ms("--yes", repo=repo, rc=2)
        self.assertIn("changed tools/brain.py", out)
        self.assertIn("extra kit/extra.py", out)
        self.assertIn("nothing was installed", out)
        self.assertEqual(tree(self.home), t0)
        self.assertIn("changed tools/brain.py", self.py(repo / "tools/update-components.py", "--check", rc=1))

    def test_missing_or_corrupt_component_refused(self):
        for case in ("missing", "manifest", "lock"):
            with self.subTest(case=case):
                repo = self.copy_repo(self.tmp / f"ms-{case}")
                if case == "missing":
                    shutil.rmtree(repo / "components/frugal-bridge")
                    want = "frugal-bridge: vendored copy missing"
                elif case == "manifest":
                    (repo / "components/skeleton-base.manifest").write_text("0" * 64 + "  x\n")
                    want = "skeleton-base: manifest does not match"
                else:
                    (repo / "components.lock").write_text("{ not json")
                    want = "components.lock is missing or not valid JSON"
                t0 = tree(self.home)
                out = self.ms("--yes", repo=repo, rc=2)
                self.assertIn(want, out)
                self.assertEqual(tree(self.home), t0)

    def test_failure_mid_install_rolls_back(self):
        self.user_files()
        t0 = tree(self.home)
        for step in ("base-init", "connect", "frugal-global", "reconnect"):
            with self.subTest(step=step):
                out = self.ms("--yes", rc=3, MOTHERSHIP_TEST_FAIL=step)
                self.assertIn("rolled back", out)
                self.assertEqual(tree(self.home), t0)

    def test_interrupted_install_then_rerun_recovers(self):
        self.user_files()
        t0 = tree(self.home)
        for step in ("base-init", "connect", "frugal-global"):
            with self.subTest(step=step):
                self.ms("--yes", rc=9, MOTHERSHIP_TEST_KILL=step)
                self.assertTrue((self.home / ".local/share/the-mothership/journal.json").exists())
                out = self.ms("--yes")
                self.assertIn("resuming an interrupted install", out)
                self.assertIn("checks: all OK", out)
                self.assertEqual(set(self.state()["own"].values()), {"installed"})   # still its own, not "found"
                self.ms("uninstall")
                self.assertEqual(tree(self.home), t0)

    def test_interrupted_install_can_be_uninstalled_directly(self):
        t0 = tree(self.home)
        self.ms("--yes", rc=9, MOTHERSHIP_TEST_KILL="frugal-global")
        self.ms("uninstall")
        self.assertEqual(tree(self.home), t0)


class SystemdTests(Base):
    def test_yes_enables_units_when_systemctl_works_and_uninstall_disables(self):
        self.fake_systemctl()
        out = self.ms("--yes")
        self.assertIn("systemd: enabled skeleton-base-watch.service skeleton-base-collect.timer", out)
        log = self.sd_log.read_text()
        self.assertIn("--user enable --now skeleton-base-watch.service skeleton-base-collect.timer", log)
        self.assertEqual(self.state()["systemd"]["enabled_by_us"],
                         ["skeleton-base-watch.service", "skeleton-base-collect.timer"])
        self.ms("uninstall")
        self.assertIn("--user disable --now skeleton-base-watch.service skeleton-base-collect.timer",
                      self.sd_log.read_text())

    def test_without_yes_only_prints(self):
        self.fake_systemctl()
        out = self.ms()
        self.assertIn("systemd: not started. To start it:", out)
        self.assertNotIn("enable", self.sd_log.read_text())

    def test_check_reports_stopped_watcher(self):
        self.fake_systemctl()
        self.ms("--yes")
        self.assertIn("check: OK", self.ms("check"))
        self.sd_state.write_text("inactive")
        out = self.ms("check", rc=1)
        self.assertIn("FAIL skeleton-base-watch.service is not running (inactive)", out)

    def test_macos_like_without_systemctl(self):
        t0 = tree(self.home)
        out = self.ms("--yes", MOTHERSHIP_PLATFORM="darwin")
        self.assertIn("watcher: skipped (no systemd on this system)", out)
        self.assertIn("checks: all OK", out)
        self.assertFalse((self.home / ".config/systemd").exists())
        self.assertEqual(self.state()["options"]["watch"], False)
        self.ms("check", MOTHERSHIP_PLATFORM="darwin")
        self.ms("uninstall", MOTHERSHIP_PLATFORM="darwin")
        self.assertEqual(tree(self.home), t0)

    def test_timer_only(self):
        out = self.ms("--yes", "--no-watch", "--timer")
        self.assertIn("enable --now skeleton-base-collect.timer", out)
        self.assertFalse((self.home / ".config/systemd/user/skeleton-base-watch.service").exists())
        self.assertTrue((self.home / ".config/systemd/user/skeleton-base-collect.timer").exists())


class CheckStatusTests(Base):
    def test_check_reports_problems_precisely(self):
        self.ms("--yes")
        codex = self.home / ".codex/AGENTS.md"
        codex.write_text(strip_blocks(codex.read_text(), "base-folder"))
        out = self.ms("check", rc=1)
        self.assertIn(f"FAIL {codex}: 0 base pointer blocks (want 1)", out)
        self.ms("--yes")                                           # re-run repairs it
        self.assertIn("check: OK", self.ms("check"))
        cs = self.home / ".claude/settings.json"
        d = json.loads(cs.read_text())
        d["permissions"]["additionalDirectories"] = []
        cs.write_text(json.dumps(d, indent=2) + "\n")
        self.assertIn("the base is not in permissions.additionalDirectories", self.ms("check", rc=1))
        self.ms("--yes")
        self.assertIn("check: OK", self.ms("check"))
        (self.home / ".gemini/GEMINI.md").unlink()
        self.assertIn("GEMINI.md: missing (pointer block gone)", self.ms("check", rc=1))
        self.ms("--yes")
        f = self.home / ".local/share/the-mothership/payload/components/frugal-bridge/kit/AGENTS.md"
        f.write_text(f.read_text() + "x")
        out = self.ms("check", rc=1)
        self.assertIn("frugal-bridge: vendored files do not match the lock: changed kit/AGENTS.md", out)

    def test_check_reports_frugal_block_order(self):
        self.ms("--yes")
        c = self.home / ".claude/CLAUDE.md"
        t = c.read_text()
        fb = re.search(r"<!-- frugal-bridge:start.*?<!-- frugal-bridge:end -->\n", t, re.S).group(0)
        c.write_text(fb + t.replace(fb, ""))
        self.assertIn("Frugal-Bridge block comes before the base block", self.ms("check", rc=1))

    def test_check_and_status_when_not_installed(self):
        self.assertIn("not installed for this user", self.ms("check", rc=2))
        self.assertIn("not installed for this user", self.ms("status", rc=2))
        self.assertIn("nothing to update", self.ms("update", "--base", self.base, rc=2))

    def test_status_output_stable(self):
        self.ms("--yes")
        s1 = self.ms("status")
        self.ms("--yes")
        s2 = self.ms("status")
        self.assertEqual(s1, s2)
        lock = json.loads((REPO / "components.lock").read_text())["components"]
        self.assertEqual(s1.splitlines()[:4], [
            "The Mothership 1.0.2", f"base: {self.base}",
            f"component frugal-bridge: {lock['frugal-bridge']['version']} @ {lock['frugal-bridge']['commit']}",
            f"component skeleton-base: {lock['skeleton-base']['version']} @ {lock['skeleton-base']['commit']}"])
        self.assertIn("connected: ~/.claude/CLAUDE.md", s1)


class UpdateUninstallTests(Base):
    def old_repo(self):
        """A copy of The Mothership whose vendored components are an 'older version' (locally patched, relocked)."""
        old = self.copy_repo(self.tmp / "ms-old")
        t = old / "components/skeleton-base/templates/person.md"
        t.write_text(t.read_text() + "\nOLD TEMPLATE LINE\n")
        a = old / "components/frugal-bridge/kit/AGENTS.md"
        a.write_text(a.read_text().replace("Frugal-Bridge CORE rules", "Frugal-Bridge CORE rules (old)", 1))
        self.py(old / "tools/update-components.py", "--relock")
        self.assertIn("components.lock: OK", self.py(old / "tools/update-components.py", "--check"))
        return old

    def test_update_from_older_version_keeps_user_pages_and_import(self):
        old = self.old_repo()
        self.py(self.frugal_kit_copy(old / "components/frugal-bridge"), "install", "--global")
        (self.home / ".frugal-bridge/USER.md").write_text(FAKE_USER)
        self.ms("--yes", repo=old)
        self.assertIn("CORE rules (old)", (self.home / ".claude/CLAUDE.md").read_text())
        who = self.base / "wiki/me/who-i-am.md"
        self.assertIn("Robin Example", who.read_text())
        who.write_text(who.read_text() + "\n- Hobby: sailing\n")                  # user edits
        page = self.base / "wiki/projects/my-project.md"
        page.write_text(page_text("My project", "Ship it."))
        self.py(self.base / "tools/brain.py", "index", "--root", self.base)
        mine = {p: p.read_bytes() for p in (who, page)}
        out = self.ms("update", "--yes")
        self.assertIn("checks: all OK", out)
        self.assertIn("(was ", out)                                              # version change reported
        for p, b in mine.items():
            self.assertEqual(p.read_bytes(), b, p)
        self.assertEqual(who.read_text().count("Robin Example"), 1)               # no second import
        self.assertEqual((self.base / "templates/person.md").read_bytes(),
                         (SB_VENDOR / "templates/person.md").read_bytes())          # untouched kit file upgraded
        for f in self.rules():
            self.assertNotIn("CORE rules (old)", f.read_text())
            self.assert_order(f)
        st = self.state()
        lock = json.loads((REPO / "components.lock").read_text())["components"]
        self.assertEqual(st["components"]["frugal-bridge"]["commit"], lock["frugal-bridge"]["commit"])
        self.assertEqual(st["own"]["frugal_global"], "adopted")
        self.assertIn("check: OK", self.ms("check"))

    def test_update_keeps_options(self):
        self.ms("--yes", "--no-frugal")
        self.ms("update", "--yes")
        self.assertFalse((self.home / ".frugal-bridge").exists())

    def test_uninstall_after_user_deleted_files(self):
        self.user_files()
        self.ms("--yes")
        (self.home / ".codex/AGENTS.md").unlink()
        (self.base / "tools/brain.py").unlink()
        (self.base / "AGENTS.md").unlink()
        shutil.rmtree(self.base / "wiki/people")
        out = self.ms("uninstall", rc=None)
        self.assertIn("uninstalled", out)
        self.assertEqual((self.home / ".claude/CLAUDE.md").read_text(), USER_CLAUDE)
        self.assertEqual((self.home / ".claude/settings.json").read_text(), USER_SETTINGS)
        self.assertFalse((self.home / ".frugal-bridge/global.json").exists())
        self.assertFalse((self.home / ".local/share/the-mothership").exists())

    def test_uninstall_keeps_user_pages_and_purge_needs_confirmation(self):
        self.ms("--yes")
        page = self.base / "wiki/people/kim.md"
        page.write_text(page_text("Kim", "Friend."))
        self.py(self.base / "tools/brain.py", "index", "--root", self.base)
        t_before = tree(self.home)
        out = self.ms("uninstall", "--purge", rc=2)
        self.assertIn("--purge needs confirmation", out)
        self.assertEqual(tree(self.home), t_before)
        self.ms("uninstall")
        self.assertEqual(page.read_text().splitlines()[-1], "Friend.")
        self.assertEqual(sorted(p.relative_to(self.base).as_posix() for p in self.base.rglob("*") if p.is_file()),
                         ["wiki/index.md", "wiki/people/kim.md"])       # both edited by the user
        self.ms("--yes")
        self.ms("uninstall", "--purge", "--confirm-purge", self.base)
        self.assertFalse(self.base.exists())

    def test_zero_touch_new_tool_and_frugal_rerun_without_env(self):
        self.ms("--yes")
        oc = self.home / ".qwen"
        oc.mkdir()
        self.py(self.base / "tools/brain.py", "watch", "--once", "--base", self.base, "--no-commit")
        self.assertIn("base-folder:start", (oc / "QWEN.md").read_text())       # a tool installed later is connected
        # Skeleton Base re-runs Frugal-Bridge's setup by itself; it finds the kit through global.json "kit"
        out = self.py(self.base / "tools/brain.py", "disconnect", "--base", self.base)
        self.assertNotIn("kit was not found", out)
        self.assertTrue((self.home / ".frugal-bridge/USER.md").is_file())       # Frugal works on its own file again
        out = self.py(self.base / "tools/brain.py", "connect", "--watch", "--base", self.base)
        self.assertNotIn("kit was not found", out)
        self.assertEqual(json.loads((self.home / ".frugal-bridge/global.json").read_text())["base"], str(self.base))
        for f in self.rules():
            self.assert_order(f)


class AdoptVersionTests(Base):
    """Adopting an existing base never downgrades it."""

    def newer_skeleton(self, release="9.0.0"):
        sb = self.tmp / "sb-newer"
        shutil.copytree(SB_VENDOR, sb, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        b = sb / "tools/brain.py"
        t = b.read_text()
        self.assertRegex(t, r'(?m)^RELEASE = "')
        b.write_text(re.sub(r'(?m)^RELEASE = "[^"]+"', f'RELEASE = "{release}"', t, count=1))
        p = sb / "templates/person.md"
        p.write_text(p.read_text() + "\nNEWER TEMPLATE LINE\n")
        return sb

    def test_newer_base_is_kept_unless_force(self):
        sb = self.newer_skeleton()
        self.py(sb / "tools/brain.py", "init", self.base, "--frugal=no")
        newer = {r: (self.base / r).read_bytes() for r in ("tools/brain.py", "templates/person.md")}
        self.assertEqual(json.loads((self.base / ".kits.json").read_text())["kits"]["base-folder"]["release"], "9.0.0")
        plan = self.ms("--dry-run", "--base", self.base)
        self.assertIn("keep Skeleton Base 9.0.0", plan)
        out = self.ms("--yes", "--base", self.base)
        self.assertIn("Skeleton Base in the base: 9.0.0 is newer than the vendored", out)
        self.assertIn("note: the base keeps its newer Skeleton Base 9.0.0", out)
        self.assertIn("checks: all OK", out)
        for r, b in newer.items():
            self.assertEqual((self.base / r).read_bytes(), b, r)        # not downgraded
        self.assertEqual(self.state()["base_kept"]["release"], "9.0.0")
        for f in self.rules():
            self.assert_order(f)
        t1 = tree(self.home)
        self.ms("--yes")                                                # re-run: still kept, byte-identical
        self.assertEqual(tree(self.home), t1)
        out = self.ms("update", "--yes")
        self.assertIn("is newer than the vendored", out)
        self.assertEqual((self.base / "tools/brain.py").read_bytes(), newer["tools/brain.py"])
        out = self.ms("--yes", "--force")
        self.assertIn("--force: Skeleton Base 9.0.0 in the base is replaced", out)
        for r in newer:
            self.assertEqual((self.base / r).read_bytes(), (SB_VENDOR / r).read_bytes(), r)
        self.assertIsNone(self.state()["base_kept"])
        self.assertIn("check: OK", self.ms("check"))

    def test_same_or_older_base_is_refreshed(self):
        for rel, want in (("1.0.0", "refreshed"), (None, "refreshed")):
            with self.subTest(release=rel):
                base = self.tmp / f"b-{rel}"
                self.py(SB_VENDOR / "tools/brain.py", "init", base, "--frugal=no")
                k = json.loads((base / ".kits.json").read_text())
                if rel:
                    k["kits"]["base-folder"]["release"] = rel
                else:
                    k["kits"]["base-folder"].pop("release")           # a base from before 1.3.2
                (base / ".kits.json").write_text(json.dumps(k, indent=2) + "\n")
                out = self.ms("--yes", "--no-frugal", "--base", base)
                self.assertNotIn("is newer than the vendored", out)
                self.assertIn("- Skeleton Base: init", out)
                self.assertEqual(json.loads((base / ".kits.json").read_text())["kits"]["base-folder"]["release"],
                                 json.loads((REPO / "components.lock").read_text())["components"]["skeleton-base"]
                                 ["version"])
                self.ms("uninstall")


class LintWarningTests(Base):
    """Lint issues in your own pages are warnings, never an install failure."""

    def bad_pages(self, base):
        (base / "wiki/projects/no-front.md").write_text("# No frontmatter\n\nSee [[nowhere]].\n")
        (base / "wiki/people/Bad_Name.md").write_text(page_text("Bad", "x"))

    def test_install_exits_0_with_warnings_and_check_fails_only_for_install_problems(self):
        self.ms("--yes")
        self.bad_pages(self.base)
        out = self.ms("--yes")                                  # re-run with broken pages: still 0
        self.assertIn("checks: all OK", out)
        self.assertIn("lint issue(s) in your own pages", out)
        self.assertIn("WARN lint: wiki/projects/no-front.md: missing frontmatter", out)
        self.assertIn("WARN lint: wiki/projects/no-front.md: broken link [[nowhere]]", out)
        self.assertIn("WARN lint: wiki/people/Bad_Name.md: file name must be lowercase", out)
        out = self.ms("check")
        self.assertIn("WARN lint: wiki/projects/no-front.md: missing frontmatter", out)
        self.assertRegex(out, r"check: OK, \d+ warning\(s\)")
        self.assertNotIn("FAIL", out)
        codex = self.home / ".codex/AGENTS.md"                  # an install problem still fails check
        codex.write_text(strip_blocks(codex.read_text(), "base-folder"))
        out = self.ms("check", rc=1)
        self.assertIn(f"FAIL {codex}: 0 base pointer blocks", out)
        self.assertIn("WARN lint:", out)
        self.ms("--yes")
        for p in ("wiki/projects/no-front.md", "wiki/people/Bad_Name.md"):
            (self.base / p).unlink()
        self.py(self.base / "tools/brain.py", "index", "--root", self.base)
        out = self.ms("check")
        self.assertIn("check: OK (", out)
        self.assertNotIn("WARN", out)

    def test_adopting_a_base_with_lint_issues_installs(self):
        mine = self.home / "my-brain"
        self.py(SB_VENDOR / "tools/brain.py", "init", mine, "--frugal=no")
        self.bad_pages(mine)
        out = self.ms("--yes", "--base", mine)
        self.assertIn("checks: all OK", out)
        self.assertIn("WARN lint: wiki/projects/no-front.md: missing frontmatter", out)
        for f in self.rules():
            self.assert_order(f)


class ComponentSuiteTests(Base):
    """Both vendored products' own test suites, run from a copy of the vendored files."""

    def test_skeleton_base_suite_passes_from_vendored_copy(self):
        sb, fb = self.tmp / "sb", self.tmp / "fb"
        shutil.copytree(SB_VENDOR, sb)
        shutil.copytree(FB_VENDOR, fb)
        bin_ = str(self.bin) + os.pathsep + "/usr/bin" + os.pathsep + "/bin"     # its suite uses git
        r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=sb, capture_output=True, text=True,
                           env=self.env(PATH=bin_, FRUGAL_BRIDGE_SRC=str(fb)))
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out[-3000:])
        m = re.search(r"Ran (\d+) tests", out)
        self.assertTrue(m and int(m.group(1)) >= 80, out[-500:])
        self.assertNotIn("skipped", out.splitlines()[-1])
        print(f"\n  skeleton-base vendored suite: {m.group(0)}, {out.strip().splitlines()[-1]}", file=sys.stderr)

    def test_frugal_bridge_suite_passes_from_vendored_copy(self):
        fb = self.tmp / "fb"
        shutil.copytree(FB_VENDOR, fb)
        r = subprocess.run([sys.executable, str(REPO / "tests/pytest_adapter.py"), str(fb / "kit/test_setup.py")],
                           capture_output=True, text=True, env=self.env(), cwd=fb)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out[-3000:])
        self.assertRegex(out, r"\b2\d passed, 0 failed")
        print(f"\n  frugal-bridge vendored suite: {out.strip().splitlines()[-1]}", file=sys.stderr)


class PublicTests(unittest.TestCase):
    def test_lock_matches_vendored_files(self):
        sys.path.insert(0, str(REPO))
        import importlib.util
        spec = importlib.util.spec_from_file_location("ms_install", REPO / "install.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.verify_lock(REPO), [])

    def test_check_public_files_and_history(self):
        """Skeleton Base's own check-public on this tree (and its git history when there is one). Your own list of
        words that must never appear: MOTHERSHIP_BLOCKED_WORDS=/path/to/words.txt (kept outside the repo)."""
        words = os.environ.get("MOTHERSHIP_BLOCKED_WORDS")
        with tempfile.TemporaryDirectory() as td:
            if not words:
                words = str(Path(td) / "words.txt")
                Path(words).write_text("zq" + uuid.uuid4().hex + "\n")     # a word that cannot be anywhere
            r = subprocess.run([sys.executable, str(SB_VENDOR / "tools/brain.py"), "check-public", "--words", words,
                                str(REPO)], capture_output=True, text=True,
                               env={k: v for k, v in os.environ.items() if k not in SCRUB})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS", r.stdout + r.stderr)


@unittest.skipUnless(os.environ.get("MOTHERSHIP_REAL_CLAUDE") == "1",
                     "real Claude Code test: set MOTHERSHIP_REAL_CLAUDE=1 (needs the claude CLI, network, and "
                     "~/.claude/.credentials.json, which is copied into the temporary HOME)")
class RealToolTests(Base):
    def test_claude_cold_start_answers_from_the_base(self):
        claude = shutil.which("claude", path=os.environ.get("PATH")) or str(Path.home() / ".local/bin/claude")
        cred = Path.home() / ".claude" / ".credentials.json"
        self.assertTrue(Path(claude).exists() and cred.is_file(), "claude CLI or credentials missing")
        (self.bin / "claude").symlink_to(Path(claude).resolve())
        shutil.copy2(cred, self.home / ".claude" / ".credentials.json")
        self.ms("--yes")
        who = self.base / "wiki/me/who-i-am.md"
        t = who.read_text()
        t = t.replace("- Name:", "- Name: Robin Example", 1) if "- Name:" in t else t + "\n- Name: Robin Example\n"
        who.write_text(t)
        hot = self.base / "hot.md"
        hot.write_text(hot.read_text().rstrip() + "\n- Current focus: the Lighthouse garden project\n")
        work = self.tmp / "unrelated-project"
        work.mkdir()
        bin_ = str(self.bin) + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
        q = ("Who am I (my name) and what am I focused on right now? Also give the full path of the knowledge base "
             "you used. Answer in 3 short lines.")
        r = subprocess.run([str(self.bin / "claude"), "-p", q, "--model", "sonnet"], capture_output=True, text=True,
                           cwd=work, env=self.env(PATH=bin_), timeout=600)
        out = r.stdout + r.stderr
        print(f"\n  claude -p answer:\n{out}", file=sys.stderr)
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("Robin", out)
        self.assertIn("Lighthouse", out)
        self.assertIn(str(self.base), out)


if __name__ == "__main__":
    unittest.main()
