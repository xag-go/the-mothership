"""Tests for kit/setup.py (coexistence contract). Run: pytest -q kit/test_setup.py"""
import hashlib, importlib.util, json, os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("setup_kit", os.path.join(HERE, "setup.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)


def tree(d, skip=(".frugal-bridge/backup",)):
    out = {}
    for root, dirs, files in os.walk(d):
        rel = os.path.relpath(root, d)
        if any(rel == s or rel.startswith(s + os.sep) for s in skip):
            continue
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, d)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        for x in dirs:
            out.setdefault(os.path.relpath(os.path.join(root, x), d) + "/", "dir")
    return out


def strip_dirs(t):
    return {k: v for k, v in t.items() if v != "dir" and not k.startswith(".frugal-bridge/backup")}


def inst(d, **kw):
    return S.Setup(str(d)).install(**kw)


def test_fresh_install(tmp_path):
    rep, _ = inst(tmp_path)
    assert rep.startswith("OK"), rep
    a = (tmp_path / "AGENTS.md").read_text()
    assert a.count("<!-- frugal-bridge:start") == 1 and a.count("<!-- frugal-bridge:end -->") == 1
    assert (tmp_path / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert (tmp_path / "GEMINI.md").read_text() == "@AGENTS.md\n"
    k = json.loads((tmp_path / ".kits.json").read_text())
    assert k["slots"]["now"] == "PROGRESS.md" and (tmp_path / "PROGRESS.md").exists() and (tmp_path / "USER.md").exists()
    st = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert any(S.HOOK_MARK in h["command"] for g in st["hooks"]["SessionStart"] for h in g["hooks"])
    assert (tmp_path / ".claude/skills/frugal-handoff/SKILL.md").exists()


def test_rerun_is_byte_identical(tmp_path):
    inst(tmp_path); t1 = tree(tmp_path)
    inst(tmp_path); t2 = tree(tmp_path)
    assert strip_dirs(t1) == strip_dirs(t2)


def test_install_uninstall_restores_empty(tmp_path):
    before = strip_dirs(tree(tmp_path))
    inst(tmp_path); S.Setup(str(tmp_path)).uninstall()
    assert strip_dirs(tree(tmp_path)) == before


def test_user_text_kept_byte_identical(tmp_path):
    for content in ("# My rules\nbe nice\n", "no newline at end", "two newlines\n\n"):
        d = tmp_path / str(abs(hash(content))); d.mkdir()
        (d / "AGENTS.md").write_text(content); (d / "CLAUDE.md").write_text("my claude notes\n")
        inst(d)
        a = (d / "AGENTS.md").read_text()
        assert a.startswith(content.rstrip("\n")) and a.count("frugal-bridge:start") == 1
        c = (d / "CLAUDE.md").read_text()
        assert c.startswith("my claude notes\n") and "@AGENTS.md" in c
        S.Setup(str(d)).uninstall()
        assert (d / "AGENTS.md").read_text() == content
        assert (d / "CLAUDE.md").read_text() == "my claude notes\n"


def test_existing_pointer_left_alone(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\nextra\n")
    inst(tmp_path)
    assert (tmp_path / "CLAUDE.md").read_text() == "@AGENTS.md\nextra\n"


def test_json_merge_keeps_other_hooks_and_keys(tmp_path):
    other = {"model": "x", "permissions": {"allow": ["Bash(ls)"]},
             "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "my-own.sh"}]}],
                       "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt.sh"}]}]}}
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude/settings.json").write_text(json.dumps(other))
    inst(tmp_path); inst(tmp_path)   # twice: no duplicate entries
    st = json.loads((tmp_path / ".claude/settings.json").read_text())
    ss = st["hooks"]["SessionStart"]
    assert sum(1 for g in ss for h in g["hooks"] if S.HOOK_MARK in h["command"]) == 1
    assert any(h["command"] == "my-own.sh" for g in ss for h in g["hooks"])
    assert st["model"] == "x" and st["hooks"]["PostToolUse"] == other["hooks"]["PostToolUse"]
    S.Setup(str(tmp_path)).uninstall()
    assert json.loads((tmp_path / ".claude/settings.json").read_text()) == other


def test_invalid_json_settings_refused(tmp_path):
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude/settings.json").write_text("{ not json")
    try:
        inst(tmp_path)
        assert False, "should refuse"
    except SystemExit as e:
        assert "not valid JSON" in str(e)
    assert (tmp_path / ".claude/settings.json").read_text() == "{ not json"


def base_folder(d):
    (d / "wiki/me").mkdir(parents=True); (d / "wiki/me/README.md").write_text("me\n"); (d / "hot.md").write_text("now\n")
    (d / "AGENTS.md").write_text("intro\n\n<!-- base-folder:start v1 -->\nbase rules\n<!-- base-folder:end -->\n\nmy tail\n")
    k = {"kits": {"base-folder": {"version": "1"}},
         "slots": {"user": "wiki/me/README.md", "now": "hot.md", "decisions": "wiki/decisions/", "map": "wiki/index.md", "sources": "raw/"}}
    (d / ".kits.json").write_text(json.dumps(k, indent=2) + "\n")


def test_base_first_then_frugal(tmp_path):
    base_folder(tmp_path)
    before = (tmp_path / "AGENTS.md").read_text()
    rep, _ = inst(tmp_path)
    assert rep.startswith("OK"), rep
    for f in ("USER.md", "PROGRESS.md", "DECISIONS.md", "sources"):
        assert not (tmp_path / f).exists(), f
    a = (tmp_path / "AGENTS.md").read_text()
    assert a.index("base-folder:end") < a.index("frugal-bridge:start") < a.index("my tail")
    k = json.loads((tmp_path / ".kits.json").read_text())
    assert k["slots"]["now"] == "hot.md" and "base-folder" in k["kits"]
    S.Setup(str(tmp_path)).uninstall()
    assert (tmp_path / "AGENTS.md").read_text() == before
    k = json.loads((tmp_path / ".kits.json").read_text())
    assert "frugal-bridge" not in k["kits"] and k["slots"]["now"] == "hot.md"
    assert (tmp_path / "hot.md").read_text() == "now\n"


def test_uninstall_keeps_edited_slot_files(tmp_path):
    inst(tmp_path)
    (tmp_path / "USER.md").write_text("my real preferences\n")
    log = S.Setup(str(tmp_path)).uninstall()
    assert (tmp_path / "USER.md").read_text() == "my real preferences\n"
    assert any("kept" in l and "USER.md" in l for l in log)
    assert not (tmp_path / "PROGRESS.md").exists()


def test_old_version_without_registry(tmp_path):
    (tmp_path / "AGENTS.md").write_text("<!-- frugal-bridge:start v5 -->\nold rules\n<!-- frugal-bridge:end -->\n")
    rep, _ = inst(tmp_path)
    a = (tmp_path / "AGENTS.md").read_text()
    assert a.count("frugal-bridge:start") == 1 and "v6" in a and "old rules" not in a
    assert "frugal-bridge" in json.loads((tmp_path / ".kits.json").read_text())["kits"]


def test_size_check_flags_codex_limit(tmp_path):
    base_folder(tmp_path)
    a = (tmp_path / "AGENTS.md").read_text().replace("base rules", "x" * 30000)
    (tmp_path / "AGENTS.md").write_text(a)
    rep, _ = inst(tmp_path)
    assert rep.startswith("PROBLEMS") and "32768" in rep


def test_hermes_copy(tmp_path):
    home = tmp_path / "hh"; proj = tmp_path / "p"
    inst(proj, hosts=("hermes",), hermes_home=str(home))
    assert (home / "plugins/frugal-bridge/__init__.py").exists()
    assert json.loads((home / "frugal-bridge/config.json").read_text())["base_dir"] == str(proj)
    assert not (proj / "CLAUDE.md").exists()
    S.Setup(str(proj)).uninstall()
    assert not (home / "plugins/frugal-bridge").exists()


def test_auto_detect(tmp_path, monkeypatch):
    monkeypatch.setattr(S.shutil, "which", lambda b: "/usr/bin/" + b if b in ("claude", "codex") else None)
    for e in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "GEMINI_CLI", "HERMES_HOME", "HERMES_AGENT"):
        monkeypatch.delenv(e, raising=False)
    found, proxy = S.detect(str(tmp_path))
    assert found == ["claude-code"] and proxy == ["codex"]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hh"))
    found, _ = S.detect(str(tmp_path))
    assert "hermes" in found


def test_cli_hosts_none_is_rules_only(tmp_path, capsys):
    rc = S.main(["setup.py", "install", str(tmp_path / "p"), "--hosts", "none"])
    assert rc == 0
    p = tmp_path / "p"
    assert (p / "AGENTS.md").exists() and not (p / "CLAUDE.md").exists() and not (p / ".claude").exists()
    assert "Enforcement on this machine" in capsys.readouterr().out


def _fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for e in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "HERMES_HOME", "FRUGAL_HOME"):
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setattr(S.shutil, "which", lambda b: None)
    return home


def test_global_install_every_tool_and_clean_uninstall(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("# my own rules\nkeep me\n")
    (home / ".claude" / "settings.json").write_text('{"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}}')
    (home / ".codex").mkdir()
    (home / ".hermes").mkdir()
    (home / ".hermes" / "SOUL.md").write_text("You are Kai.\n")
    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    assert S.main(["setup.py", "install", "--global"]) == 0
    cl = (home / ".claude" / "CLAUDE.md").read_text()
    assert cl.startswith("# my own rules\nkeep me\n") and cl.count("frugal-bridge:start") == 1
    assert ".frugal-bridge/USER.md" in cl
    assert (home / ".codex" / "AGENTS.md").read_text().count("frugal-bridge:start") == 1
    assert (home / ".hermes" / "SOUL.md").read_text().startswith("You are Kai.")
    assert not (home / ".gemini").exists()          # tool not present -> not touched
    st = json.loads((home / ".claude" / "settings.json").read_text())
    assert st["model"] == "x" and st["hooks"]["Stop"][0]["hooks"][0]["command"] == "mine"
    assert any(".frugal-bridge/frugal_hook.py" in g["hooks"][0]["command"] for g in st["hooks"]["SessionStart"])
    assert (home / ".claude" / "skills" / "frugal-handoff" / "SKILL.md").exists()
    assert (home / ".hermes" / "plugins" / "frugal-bridge" / "__init__.py").exists()
    assert (home / ".frugal-bridge" / "USER.md").exists()
    # re-run is idempotent
    snap = {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and "backup" not in str(p)}
    assert S.main(["setup.py", "install", "--global"]) == 0
    assert snap == {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and "backup" not in str(p)}
    # uninstall restores every file the user had
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    for p, b in before.items():
        if p.name == "settings.json":
            assert json.loads(p.read_text()) == json.loads(b)
        else:
            assert p.read_bytes() == b, p
    assert not (home / ".codex" / "AGENTS.md").exists()
    assert not (home / ".claude" / "skills" / "frugal-handoff").exists()
    assert not (home / ".hermes" / "plugins" / "frugal-bridge").exists()


def test_global_user_file_found_by_adapter(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".claude").mkdir()
    assert S.main(["setup.py", "install", "--global"]) == 0
    import sys; sys.path.insert(0, os.path.join(S.ROOT, "adapter", "hooks"))
    import frugal_hook
    proj = tmp_path / "anyproject"; proj.mkdir()
    (proj / "PROGRESS.md").write_text("x")
    got = frugal_hook.slots(str(proj))
    assert got["now"].endswith("PROGRESS.md") and got["user"] == str(home / ".frugal-bridge" / "USER.md")


def _base(tmp_path):
    b = tmp_path / "mybase"
    (b / "wiki" / "me").mkdir(parents=True)
    (b / "hot.md").write_text("now")
    (b / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {"version": "1"}},
                                              "slots": {"user": "wiki/me/", "now": "hot.md"}}))
    block = f"<!-- base-folder:start v2 -->\n## Knowledge base\nPath: {b}\n- read hot.md\n<!-- base-folder:end -->\n"
    return b, block


def test_global_base_first_no_second_copy(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    b, block = _base(tmp_path)
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("mine\n" + block)
    assert S.main(["setup.py", "install", "--global"]) == 0
    t = (home / ".claude" / "CLAUDE.md").read_text()
    assert t.index("base-folder:end") < t.index("frugal-bridge:start")      # after the base block
    assert f"{b}/wiki/me/" in t and "never create a second copy" in t
    assert not (home / ".frugal-bridge" / "USER.md").exists()
    import sys; sys.path.insert(0, os.path.join(S.ROOT, "adapter", "hooks"))
    import importlib, frugal_hook; importlib.reload(frugal_hook)
    p = tmp_path / "proj"; p.mkdir()
    got = frugal_hook.slots(str(p))
    assert got == {"now": str(b / "hot.md"), "user": str(b / "wiki" / "me") + "/"} or got == {"now": str(b / "hot.md"), "user": str(b / "wiki/me/")}
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert (home / ".claude" / "CLAUDE.md").read_text() == "mine\n" + block


def test_global_frugal_first_then_base(tmp_path, monkeypatch, capsys):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("mine\n")
    assert S.main(["setup.py", "install", "--global"]) == 0
    assert (home / ".frugal-bridge" / "USER.md").exists()
    b, block = _base(tmp_path)
    t = (home / ".claude" / "CLAUDE.md").read_text()
    (home / ".claude" / "CLAUDE.md").write_text(t + block)                   # the base connects later
    capsys.readouterr()
    assert S.main(["setup.py", "install", "--global"]) == 0                  # re-run switches to the base
    out = capsys.readouterr().out
    assert "move what it says into" in out and "owned by the knowledge base" in out
    t = (home / ".claude" / "CLAUDE.md").read_text()
    assert t.count("frugal-bridge:start") == 1 and f"{b}/hot.md" in t


def _hooks_by_event(settings):
    return {ev: [h["command"] for g in lst for h in g["hooks"]] for ev, lst in json.loads(settings.read_text()).get("hooks", {}).items()}


def test_global_custom_frugal_home_no_duplicate_hooks(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.setenv("FRUGAL_HOME", str(tmp_path / "my-fb-folder"))      # not named .frugal-bridge
    (home / ".claude").mkdir()
    st = home / ".claude" / "settings.json"
    st.write_text('{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}')
    assert S.main(["setup.py", "install", "--global"]) == 0
    first = st.read_bytes()
    assert S.main(["setup.py", "install", "--global"]) == 0
    assert st.read_bytes() == first                                          # byte-identical re-run
    h = _hooks_by_event(st)
    assert h["SessionStart"] == ["echo mine", f'python3 "{tmp_path}/my-fb-folder/frugal_hook.py" {S.HOOK_TAG}']
    assert len(h["UserPromptSubmit"]) == 1
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert json.loads(st.read_text()) == {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}


def test_global_upgrade_from_old_style_hooks(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.setenv("FRUGAL_HOME", str(tmp_path / "fbnew"))
    (home / ".claude").mkdir()
    st = home / ".claude" / "settings.json"
    old = [{"hooks": [{"type": "command", "command": f'python3 "{home}/.frugal-bridge/frugal_hook.py"'}]},
           {"hooks": [{"type": "command", "command": f'python3 "{tmp_path}/elsewhere/frugal_hook.py"'}]}]
    other = {"hooks": [{"type": "command", "command": "python3 my_hook.py"}]}
    st.write_text(json.dumps({"x": 1, "hooks": {"SessionStart": old + [other], "UserPromptSubmit": old[:1]}}))
    assert S.main(["setup.py", "install", "--global"]) == 0
    h = _hooks_by_event(st)
    assert h["SessionStart"].count("python3 my_hook.py") == 1
    assert sum("frugal_hook.py" in c for c in h["SessionStart"]) == 1           # old ones replaced, not added to
    assert sum("frugal_hook.py" in c for c in h["UserPromptSubmit"]) == 1
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert json.loads(st.read_text()) == {"x": 1, "hooks": {"SessionStart": [other]}}


def test_project_hooks_tagged_and_not_duplicated(tmp_path):
    p = tmp_path / "p"
    S.Setup(str(p)).install(("claude-code",))
    S.Setup(str(p)).install(("claude-code",))
    h = _hooks_by_event(p / ".claude" / "settings.json")
    assert len(h["SessionStart"]) == 1 and S.HOOK_TAG in h["SessionStart"][0]


def test_is_ours_does_not_match_other_hooks():
    for c in ("python3 my_frugal_hook.py.bak", "echo frugal", "python3 /x/other_hook.py"):
        assert not S.Setup._is_ours({"hooks": [{"command": c}]}), c
    for c in ('python3 "/a b/.frugal-bridge/frugal_hook.py"', 'python3 /x/frugal_hook.py', f'python3 "/x/y.py" {S.HOOK_TAG}'):
        assert S.Setup._is_ours({"hooks": [{"command": c}]}), c
