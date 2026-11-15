"""One copy of the CORE rules per session and one Frugal hook entry per event (2.46).

A knowledge base that has its own install (`setup.py install <base>`) and is also the base of the user-level
install (`setup.py install --global`) used to load the rules twice: once from each tool's user-level rules file and
once from the base's AGENTS.md. Now the base's block is a short pointer while the user-level install serves it, and
its Claude Code hook entries stay out of the base's .claude/settings.json. Any other folder is unchanged."""
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("setup_kit_once", os.path.join(HERE, "setup.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)

RULE_MARK = "## 1. Roles"            # a heading only the full rules text holds
TOOLS = {"claude": ".claude", "codex": ".codex", "gemini": ".gemini", "opencode": ".config/opencode"}
MINE = {"hooks": [{"type": "command", "command": "mine"}]}


def _home(tmp_path, monkeypatch, tools=tuple(TOOLS)):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for e in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "HERMES_HOME", "FRUGAL_HOME", "GEMINI_CLI_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(e, raising=False)
    for t in tools:
        (home / TOOLS[t]).mkdir(parents=True)
    monkeypatch.setattr(S.shutil, "which", lambda b: f"/fake/bin/{b}" if b in tools else None)
    return home


def _base(tmp_path, home):
    """A knowledge base: its own rules block in AGENTS.md, pointer files, its user-level block in each tool's file."""
    b = tmp_path / "mybase"
    (b / "wiki" / "me").mkdir(parents=True)
    (b / "hot.md").write_text("now\n")
    (b / "AGENTS.md").write_text("<!-- base-folder:start v1 -->\n# Base rules\nread hot.md\n<!-- base-folder:end -->\n")
    (b / "CLAUDE.md").write_text("@AGENTS.md\n")
    (b / "GEMINI.md").write_text("@AGENTS.md\n")
    (b / ".claude").mkdir()
    (b / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [MINE]}}, indent=2) + "\n")
    (b / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {"version": "1"}},
                                              "slots": {"user": "wiki/me/", "now": "hot.md"}}, indent=2) + "\n")
    block = f"<!-- base-folder:start v2 -->\n## Knowledge base\nPath: {b}\n- read hot.md\n<!-- base-folder:end -->\n"
    for rel in (".claude/CLAUDE.md", ".codex/AGENTS.md", ".gemini/GEMINI.md", ".config/opencode/AGENTS.md"):
        if (home / rel).parent.is_dir():
            (home / rel).write_text(block)
    return b


def _glob():
    assert S.main(["setup.py", "install", "--global"]) == 0


def _proj(d):
    rep, _ = S.Setup(str(d)).install(hosts=("claude-code", "gemini"))
    assert rep.startswith("OK"), rep
    return rep


def _text(p):
    return p.read_text() if p.is_file() else ""


def loaded(home, d):
    """What each tool puts in its context at session start in folder d: its user-level rules file plus the project
    file it reads, with an '@AGENTS.md' import line replaced by that file."""
    def proj(name):
        t = _text(d / name)
        return "\n".join(_text(d / "AGENTS.md") if l.strip() == "@AGENTS.md" else l for l in t.splitlines())
    return {"claude-code": _text(home / ".claude/CLAUDE.md") + proj("CLAUDE.md"),
            "codex": _text(home / ".codex/AGENTS.md") + proj("AGENTS.md"),
            "gemini": _text(home / ".gemini/GEMINI.md") + proj("GEMINI.md"),
            "opencode": _text(home / ".config/opencode/AGENTS.md") + proj("AGENTS.md")}


def frugal_cmds(settings):
    data = json.loads(settings.read_text()) if settings.is_file() else {}
    return {ev: [h["command"] for g in lst for h in g["hooks"] if S.HOOK_TAG in h["command"]]
            for ev, lst in data.get("hooks", {}).items() if any(S.HOOK_TAG in h["command"] for g in lst for h in g["hooks"])}


def assert_once_everywhere(home, b, other):
    for where in (b, other):
        for tool, text in loaded(home, where).items():
            assert text.count(RULE_MARK) == 1, f"{tool} in {where.name}: {text.count(RULE_MARK)} copies of the rules"


# ---------------------------------------------------------------- the rules: one copy
def test_base_after_global_gets_a_pointer_and_every_tool_one_copy(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    other = tmp_path / "other-project"; other.mkdir()
    _glob()
    rep = _proj(b)
    a = (b / "AGENTS.md").read_text()
    assert a.count("<!-- frugal-bridge:start") == 1 and a.count("<!-- frugal-bridge:end -->") == 1
    assert RULE_MARK not in a and ".frugal-bridge/RULES.md" in a
    assert a.index("base-folder:end") < a.index("frugal-bridge:start")
    blk = a[a.index("<!-- frugal-bridge:start"):]
    assert len(blk.encode()) < 800, len(blk.encode())                 # short: a pointer, not the rules
    full = (b / ".frugal-bridge" / "RULES.md").read_text()            # the fallback holds the whole text
    assert RULE_MARK in full and "ROUTING.md" in full and "## 8. Changing these rules" in full
    assert "pointer" in rep
    assert_once_everywhere(home, b, other)


def test_base_first_then_global_is_turned_into_a_pointer(tmp_path, monkeypatch):
    """The Mothership's order: the base's own install runs first, the user-level install after it."""
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    other = tmp_path / "other-project"; other.mkdir()
    _proj(b)
    assert RULE_MARK in (b / "AGENTS.md").read_text()                 # no user-level install yet: the full text
    assert not (b / ".frugal-bridge" / "RULES.md").exists()
    _glob()
    a = (b / "AGENTS.md").read_text()
    assert RULE_MARK not in a and a.count("<!-- frugal-bridge:start") == 1
    assert RULE_MARK in (b / ".frugal-bridge" / "RULES.md").read_text()
    assert_once_everywhere(home, b, other)
    assert S.Setup(str(b)).check().startswith("OK")
    assert S.GlobalSetup().check().startswith("OK")


def test_both_orders_end_in_the_same_files_and_reruns_change_nothing(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _proj(b); _glob()
    one = {f: (b / f).read_bytes() for f in ("AGENTS.md", ".claude/settings.json", ".frugal-bridge/RULES.md")}
    snap = lambda: {str(p): p.read_bytes() for root in (b, home) for p in root.rglob("*")
                    if p.is_file() and "backup" not in str(p)}
    s1 = snap()
    _proj(b); _glob(); _glob(); _proj(b)
    assert snap() == s1
    S.Setup(str(b)).uninstall(); assert S.main(["setup.py", "uninstall", "--global"]) == 0
    _glob(); _proj(b)
    assert one == {f: (b / f).read_bytes() for f in one}


def test_global_uninstall_gives_the_base_its_full_rules_back(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _proj(b)
    full = {f: (b / f).read_bytes() for f in ("AGENTS.md", ".claude/settings.json")}
    _glob()
    assert (b / "AGENTS.md").read_bytes() != full["AGENTS.md"]
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert {f: (b / f).read_bytes() for f in full} == full            # the only copy left: whole again, hooks too
    assert not (b / ".frugal-bridge" / "RULES.md").exists()
    for tool, text in loaded(home, b).items():
        assert text.count(RULE_MARK) == 1, tool


def test_base_uninstall_in_pointer_mode_restores_every_byte(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    before = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    _glob(); _proj(b)
    S.Setup(str(b)).uninstall()
    after = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*")
             if p.is_file() and ".frugal-bridge/backup" not in p.as_posix()}
    assert after == before
    for tool, text in loaded(home, b).items():                        # the user-level copy still serves the base
        assert text.count(RULE_MARK) == 1, tool


def test_other_project_keeps_the_full_block(tmp_path, monkeypatch):
    """Only the base the user-level install serves gets a pointer: a project's files travel with the project
    (git, other people, other machines), so its own install stays whole."""
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _glob()
    p = tmp_path / "shared-repo"; p.mkdir()
    S.Setup(str(p)).install(hosts=("claude-code", "gemini"))
    assert RULE_MARK in (p / "AGENTS.md").read_text()
    assert not (p / ".frugal-bridge" / "RULES.md").exists()
    assert set(frugal_cmds(p / ".claude" / "settings.json")) == {"SessionStart", "UserPromptSubmit"}


def test_global_without_a_base_leaves_a_project_install_alone(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    _glob()
    p = tmp_path / "proj"; p.mkdir()
    S.Setup(str(p)).install(hosts=("claude-code", "gemini"))
    assert RULE_MARK in (p / "AGENTS.md").read_text()
    _glob()
    assert RULE_MARK in (p / "AGENTS.md").read_text()


def test_base_without_its_own_install_is_not_touched_by_global(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    before = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    _glob()
    assert {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()} == before
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()} == before


def test_pointer_names_the_fallback_for_a_tool_without_the_user_level_copy(tmp_path, monkeypatch):
    """A tool the user-level install did not wire (unknown tool, a second config dir) still reaches the rules: the
    pointer tells it to read the file in the base, which holds the same text as a full block would."""
    home = _home(tmp_path, monkeypatch, tools=("claude",))
    b = _base(tmp_path, home)
    _glob(); _proj(b)
    a = (b / "AGENTS.md").read_text()
    blk = a[a.index("<!-- frugal-bridge:start"):a.index("<!-- frugal-bridge:end -->")]
    assert "Frugal-Bridge CORE rules" in blk and "read `.frugal-bridge/RULES.md`" in blk
    body = open(os.path.join(S.KIT, "AGENTS.md")).read() + "\n\n" + open(os.path.join(S.KIT, "ROUTING.md")).read()
    assert (b / ".frugal-bridge" / "RULES.md").read_text().strip() == body.strip()


def test_fallback_file_is_listed_as_ours_only_while_it_exists(tmp_path, monkeypatch):
    """The Mothership's uninstall puts back any file of the base that a product removed unless its hash is in the
    kit or in this list: the fallback file must be in it, or it would come back after every uninstall."""
    import hashlib
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _proj(b); _glob()
    me = json.loads((b / ".kits.json").read_text())["kits"]["frugal-bridge"]
    h = hashlib.sha256((b / ".frugal-bridge" / "RULES.md").read_bytes()).hexdigest()
    assert me["template_hashes"][".frugal-bridge/RULES.md"] == h and me["rules"] == "pointer"
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    me = json.loads((b / ".kits.json").read_text())["kits"]["frugal-bridge"]
    assert ".frugal-bridge/RULES.md" not in me["template_hashes"] and "rules" not in me


def test_edited_fallback_file_is_kept_on_uninstall(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _glob(); _proj(b)
    f = b / ".frugal-bridge" / "RULES.md"
    f.write_text(f.read_text() + "\nmy own line\n")
    log = S.Setup(str(b)).uninstall()
    assert f.is_file() and "my own line" in f.read_text()
    assert any("RULES.md" in l for l in log)


def test_check_reports_a_missing_fallback(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _glob(); _proj(b)
    (b / ".frugal-bridge" / "RULES.md").unlink()
    rep = S.Setup(str(b)).check()
    assert rep.startswith("PROBLEMS") and "RULES.md" in rep
    _proj(b)                                                          # a re-run repairs it
    assert (b / ".frugal-bridge" / "RULES.md").is_file()


def test_base_served_by_another_frugal_home_is_not_a_pointer(tmp_path, monkeypatch):
    """The registry that counts is the one of this FRUGAL_HOME, and only when it names this very folder."""
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _glob()
    twin = tmp_path / "second-base"
    (twin / "wiki" / "me").mkdir(parents=True)
    (twin / "hot.md").write_text("now\n")
    (twin / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {"version": "1"}},
                                                 "slots": {"user": "wiki/me/", "now": "hot.md"}}) + "\n")
    S.Setup(str(twin)).install(hosts=("claude-code", "gemini"))
    assert RULE_MARK in (twin / "AGENTS.md").read_text()


# ---------------------------------------------------------------- the hook: one entry per event
def test_base_has_no_frugal_hook_entry_when_the_user_level_one_exists(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    _proj(b)
    st = b / ".claude" / "settings.json"
    assert set(frugal_cmds(st)) == {"SessionStart", "UserPromptSubmit"}        # alone: its own entries
    _glob()
    assert frugal_cmds(st) == {}                                               # served by the user-level entries
    assert json.loads(st.read_text())["hooks"]["SessionStart"] == [MINE]       # the user's own hook stays
    g = frugal_cmds(home / ".claude" / "settings.json")
    assert set(g) == {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"} and all(len(v) == 1 for v in g.values())
    _proj(b)
    assert frugal_cmds(st) == {}                                               # a re-run does not bring them back


def test_base_keeps_its_hook_entries_when_claude_is_not_wired_at_user_level(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch, tools=("codex",))
    b = _base(tmp_path, home)
    _proj(b); _glob()
    assert set(frugal_cmds(b / ".claude" / "settings.json")) == {"SessionStart", "UserPromptSubmit"}
    assert RULE_MARK not in (b / "AGENTS.md").read_text()                      # the rules are still one copy


def test_settings_file_made_only_for_our_hooks_goes_and_comes_back(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    b = _base(tmp_path, home)
    (b / ".claude" / "settings.json").unlink()
    _proj(b)
    assert (b / ".claude" / "settings.json").is_file()
    _glob()
    assert not (b / ".claude" / "settings.json").exists()                     # nothing of ours left in it: no empty file
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert set(frugal_cmds(b / ".claude" / "settings.json")) == {"SessionStart", "UserPromptSubmit"}
    S.Setup(str(b)).uninstall()
    assert not (b / ".claude" / "settings.json").exists()


def _fire(cmd, payload, env):
    r = subprocess.run(cmd, shell=True, input=json.dumps(payload).encode(), capture_output=True, env=env, timeout=60)
    return r.stdout.decode().strip()


def test_two_declared_entries_fire_twice_only_when_their_homes_differ(tmp_path, monkeypatch):
    """What the double declaration did before 2.46 (measured with the real hook script): both commands start; with
    one shared FRUGAL_HOME the once-guard silences the second, but a base copy started without FRUGAL_HOME while the
    user-level home is not ~/.frugal-bridge answers a second time. One declared entry removes both cases."""
    home = _home(tmp_path, monkeypatch)
    fh = tmp_path / "moved-frugal-home"
    monkeypatch.setenv("FRUGAL_HOME", str(fh))
    b = _base(tmp_path, home)
    (b / "agents").mkdir()
    (b / "agents" / "assistant.md").write_text("---\ntitle: Assistant\nengines: [claude-code]\n---\nduties\n")
    _glob()
    glob_cmd = frugal_cmds(home / ".claude" / "settings.json")["SessionStart"][0]
    old_proj_cmd = f'python3 "{b}/.frugal-bridge/frugal_hook.py" {S.HOOK_TAG}'       # the entry 2.45 wrote
    os.makedirs(b / ".frugal-bridge", exist_ok=True)
    (b / ".frugal-bridge" / "frugal_hook.py").write_text(open(os.path.join(S.ROOT, "adapter", "hooks", "frugal_hook.py")).read())
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    ev = lambda sid: {"hook_event_name": "SessionStart", "session_id": sid, "cwd": str(b), "source": "startup"}
    shared = dict(env, FRUGAL_HOME=str(fh))
    outs = [_fire(glob_cmd, ev("s1"), shared), _fire(old_proj_cmd, ev("s1"), shared)]
    assert outs[0] and not outs[1]                                    # same home: the second entry is silent
    outs = [_fire(glob_cmd, ev("s2"), env), _fire(old_proj_cmd, ev("s2"), env)]
    assert outs[0] and outs[1]                                        # homes differ: the hint came twice
    _proj(b)
    assert frugal_cmds(b / ".claude" / "settings.json") == {}         # 2.46: only the user-level entry is declared
