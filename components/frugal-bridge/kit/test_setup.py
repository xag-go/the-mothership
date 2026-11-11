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
    # a tool counts as installed by its binary: these tests make a tool "present" by creating its folder
    present = {"claude": ".claude", "codex": ".codex", "hermes": ".hermes", "gemini": ".gemini"}
    def which(b):
        if b == "hermes" and os.environ.get("HERMES_HOME") and os.path.isdir(os.environ["HERMES_HOME"]):
            return "/fake/bin/hermes"
        return f"/fake/bin/{b}" if b in present and (home / present[b]).is_dir() else None
    monkeypatch.setattr(S.shutil, "which", which)
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
    assert h["SessionStart"] == ["echo mine",
                                 f'python3 "{tmp_path}/my-fb-folder/frugal_hook.py" --tool claude-code --event start {S.HOOK_TAG}']
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


def test_global_never_creates_soul_md(tmp_path, monkeypatch, capsys):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".hermes").mkdir()                       # Hermes present, no SOUL.md (default identity in use)
    (home / ".claude").mkdir()
    assert S.main(["setup.py", "install", "--global"]) == 0
    out = capsys.readouterr().out
    assert not (home / ".hermes" / "SOUL.md").exists()
    assert "NEEDS USER" in out and "frugal-bridge:start" in out           # block printed for the user
    assert "needs user" in S.GlobalSetup().check()
    assert (home / ".claude" / "CLAUDE.md").read_text().count("frugal-bridge:start") == 1
    assert (home / ".hermes" / "plugins" / "frugal-bridge").exists()       # plugin copy is not identity
    assert S.main(["setup.py", "install", "--global"]) == 0               # re-run: still not created
    assert not (home / ".hermes" / "SOUL.md").exists()
    (home / ".hermes" / "SOUL.md").write_text("You are Kai.\n")            # user makes one -> block added after
    assert S.main(["setup.py", "install", "--global"]) == 0
    t = (home / ".hermes" / "SOUL.md").read_text()
    assert t.startswith("You are Kai.\n") and t.count("frugal-bridge:start") == 1
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert (home / ".hermes" / "SOUL.md").read_text() == "You are Kai.\n"
    assert not (home / ".hermes" / "plugins" / "frugal-bridge").exists()


def test_global_hermes_profile_soul_not_created(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    prof = tmp_path / "hh" / "profiles" / "work"; prof.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(prof))
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0
    assert not (prof / "SOUL.md").exists()


def test_base_path_with_spaces(tmp_path):
    b = tmp_path / "My Base Folder"; (b / "wiki" / "me").mkdir(parents=True)
    (b / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {}}, "slots": {"user": "wiki/me/", "now": "hot.md"}}))
    f = tmp_path / "CLAUDE.md"
    for line in (f"Path: `{b}`", f'Path: "{b}"', f"Path: '{b}'", f"Path: {b}", f"Path:   {b}   "):
        f.write_text(f"x\n<!-- base-folder:start v2 -->\n## KB\n{line}\n- more\n<!-- base-folder:end -->\n")
        assert S.find_base([str(f)]) == str(b), line
    nb = tmp_path / "plainbase"; nb.mkdir()
    (nb / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {}}}))
    f.write_text(f"<!-- base-folder:start v2 -->\nPath: {nb}\n<!-- base-folder:end -->\n")   # old format
    assert S.find_base([str(f)]) == str(nb)
    assert S.parse_base_path("`/a b/c` (the base)") == "/a b/c"


def test_public_license_and_docs_have_no_org_names():
    root = os.path.dirname(HERE)
    src = os.path.join(root, "public") if os.path.isdir(os.path.join(root, "public")) else root   # private tree / export
    lic = open(os.path.join(src, "LICENSE")).read()
    org = "x" + "ag-" + "go"      # spelled in parts so the public export carries no org name
    assert "Copyright (c) 2026 Frugal-Bridge contributors" in lic and org[:3] not in lic.lower()
    assert org not in open(os.path.join(src, "README.md")).read()


def _bare_base(path):
    (path / "wiki" / "me").mkdir(parents=True)
    (path / "hot.md").write_text("now")
    (path / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {}}, "slots": {"user": "wiki/me/", "now": "hot.md"}}))
    return path


def _check_uses_base(home, b, tmp_path):
    assert not (home / ".frugal-bridge" / "USER.md").exists()
    assert json.loads((home / ".frugal-bridge" / "global.json").read_text())["base"] == str(b)
    import sys, importlib; sys.path.insert(0, os.path.join(S.ROOT, "adapter", "hooks"))
    import frugal_hook; importlib.reload(frugal_hook)
    p = tmp_path / "proj"; p.mkdir(exist_ok=True)
    got = frugal_hook.slots(str(p))
    assert got["now"] == str(b / "hot.md") and got["user"].startswith(str(b / "wiki" / "me"))


def test_global_hermes_only_base_from_units(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".hermes").mkdir()                                  # the only tool, no SOUL.md
    b = _bare_base(tmp_path / "My Base")                         # space in the path
    u = home / ".config" / "systemd" / "user"; u.mkdir(parents=True)
    (u / "skeleton-base-watch.service").write_text(
        f'[Service]\nExecStart=/usr/bin/env python3 -S "{b}/tools/brain.py" watch --base "{b}"\n')
    assert S.main(["setup.py", "install", "--global"]) == 0
    _check_uses_base(home, b, tmp_path)
    assert not (home / ".hermes" / "SOUL.md").exists()
    assert S.main(["setup.py", "install", "--global"]) == 0     # re-run keeps the recorded base
    _check_uses_base(home, b, tmp_path)


def test_global_base_from_pointer_file_and_flag(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".hermes").mkdir()
    b = _bare_base(tmp_path / "kb")
    (home / ".config" / "skeleton-base").mkdir(parents=True)
    (home / ".config" / "skeleton-base" / "base").write_text(str(b) + "\n")
    assert S.main(["setup.py", "install", "--global"]) == 0
    _check_uses_base(home, b, tmp_path)


def test_global_base_flag(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".hermes").mkdir()
    b = _bare_base(tmp_path / "kb2")
    assert S.main(["setup.py", "install", "--global", "--base", str(tmp_path / "nothing")]) == 2
    assert not (home / ".frugal-bridge").exists()
    assert S.main(["setup.py", "install", "--global", "--base", str(b)]) == 0
    _check_uses_base(home, b, tmp_path)


def test_global_uninstall_after_base_disconnect_leaves_nothing(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    b = _bare_base(tmp_path / "kb")
    blk = f"<!-- base-folder:start v2 -->\n## KB\nPath: {b}\n<!-- base-folder:end -->"
    base_hook = {"hooks": [{"type": "command", "command": f"python3 {b}/tools/brain.py collect"}]}
    # before anything: the user's own files
    (home / ".claude").mkdir(); (home / ".codex").mkdir(); (home / ".hermes").mkdir()
    user_claude = "my rules\n"
    (home / ".claude" / "CLAUDE.md").write_text(user_claude)
    (home / ".hermes" / "SOUL.md").write_text("You are Kai.\n")
    pristine = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    # 1. base connects first (its blocks, a settings.json it creates, an AGENTS.md it creates)
    (home / ".claude" / "CLAUDE.md").write_text(user_claude + "\n" + blk + "\n")
    (home / ".codex" / "AGENTS.md").write_text(blk + "\n")
    (home / ".hermes" / "SOUL.md").write_text("You are Kai.\n" + "\n" + blk + "\n")
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionEnd": [base_hook]}}, indent=2))
    # 2. Frugal installs at user level
    assert S.main(["setup.py", "install", "--global"]) == 0
    # 3. base disconnects: removes exactly its own block / hook
    for f in (home / ".claude" / "CLAUDE.md", home / ".codex" / "AGENTS.md", home / ".hermes" / "SOUL.md"):
        f.write_text(f.read_text().replace("\n" + blk + "\n", "\n", 1) if not f.read_text().startswith(blk)
                     else f.read_text().replace(blk + "\n", "", 1))
    st = json.loads((home / ".claude" / "settings.json").read_text()); del st["hooks"]["SessionEnd"]
    (home / ".claude" / "settings.json").write_text(json.dumps(st, indent=2))
    # 4. Frugal uninstalls: no empty leftovers, the user's originals byte-identical
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert not (home / ".claude" / "settings.json").exists()          # was {} after removal -> removed
    assert not (home / ".codex" / "AGENTS.md").exists()                 # newline-only -> removed
    assert not (home / ".claude" / "skills").exists()                   # empty folders we made -> removed
    assert not (home / ".codex" / "skills").exists()
    assert not (home / ".hermes" / "plugins").exists() and not (home / ".hermes" / "skills").exists()
    now = {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and ".frugal-bridge" not in str(p)}
    assert now == pristine


def test_global_rerun_after_base_disconnect_never_brings_base_entries_back(tmp_path, monkeypatch):
    """A re-run after another kit changed a settings file (a base connected, Frugal installed, the base
    disconnected, Frugal re-run): uninstall must not put back the text from before the other kit's change (the
    base's hooks and folder entry would come back from the dead)."""
    home = _fake_home(tmp_path, monkeypatch)
    b = _bare_base(tmp_path / "kb")
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("my rules\n")
    sj = home / ".claude" / "settings.json"
    pristine = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    base_part = {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": f"python3 {b}/tools/brain.py collect"}]}]},
                 "permissions": {"additionalDirectories": [str(b)]}}
    sj.write_text(json.dumps(base_part, indent=2) + "\n")                  # 1. the base connects
    assert S.main(["setup.py", "install", "--global", "--hosts", "claude-code"]) == 0      # 2. Frugal
    st = json.loads(sj.read_text())                                         # 3. the base disconnects
    del st["hooks"]["SessionEnd"]; del st["permissions"]
    sj.write_text(json.dumps(st, indent=2) + "\n")
    assert S.main(["setup.py", "install", "--global", "--hosts", "claude-code"]) == 0      # 4. Frugal re-run
    assert S.main(["setup.py", "uninstall", "--global"]) == 0                              # 5. Frugal leaves
    assert "brain.py" not in (sj.read_text() if sj.exists() else ""), sj.read_text()
    assert str(b) not in (sj.read_text() if sj.exists() else "")
    now = {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and ".frugal-bridge" not in str(p)}
    assert now == pristine


def test_global_uninstall_restores_users_own_empty_files(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".claude").mkdir(); (home / ".claude" / "skills").mkdir()
    (home / ".claude" / "settings.json").write_text("{}")
    (home / ".claude" / "CLAUDE.md").write_text("\n")
    assert S.main(["setup.py", "install", "--global"]) == 0
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert (home / ".claude" / "settings.json").read_text() == "{}"      # user's own empty file kept as it was
    assert (home / ".claude" / "CLAUDE.md").read_text() == "\n"
    assert (home / ".claude" / "skills").is_dir()                        # existed before: kept


def test_global_uninstall_never_loses_user_data(tmp_path, monkeypatch, capsys):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".claude").mkdir(); (home / ".hermes").mkdir()
    (home / ".hermes" / "SOUL.md").write_text("You are Kai.\n")
    assert S.main(["setup.py", "install", "--global"]) == 0
    fh = home / ".frugal-bridge"
    (fh / "USER.md").write_text("- Name of the main agent: Sara\n")                          # preferences
    sk = home / ".claude" / "skills" / "frugal-handoff"
    (sk / "SKILL.md").write_text((sk / "SKILL.md").read_text() + "\nmy own tweak\n")      # edited skill
    (sk / "notes.md").write_text("mine")                                                   # file added in our folder
    plug = home / ".hermes" / "plugins" / "frugal-bridge"
    (plug / "my_patch.py").write_text("x = 1\n")
    (home / ".hermes" / "frugal-bridge").mkdir(exist_ok=True)
    (home / ".hermes" / "frugal-bridge" / "usage.jsonl").write_text('{"model": "m"}\n')    # usage log
    c = home / ".claude" / "CLAUDE.md"
    c.write_text(c.read_text().replace("<!-- frugal-bridge:end -->", "my line inside the block\n<!-- frugal-bridge:end -->"))
    other = home / ".claude" / "skills" / "frugal-delegate" / "SKILL.md"                   # unchanged -> removed
    capsys.readouterr()
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    out = capsys.readouterr().out
    assert (fh / "USER.md").read_text() == "- Name of the main agent: Sara\n"
    assert "my own tweak" in (sk / "SKILL.md").read_text() and (sk / "notes.md").read_text() == "mine"
    assert (plug / "my_patch.py").exists() and not (plug / "__init__.py").exists()
    assert (home / ".hermes" / "frugal-bridge" / "usage.jsonl").exists()
    assert not c.exists() and not other.exists()                    # Frugal had created CLAUDE.md
    saved = list((fh / "kept").glob("*CLAUDE.md.block.md"))
    assert saved and "my line inside the block" in saved[0].read_text()
    assert "your data is kept" in out and "saved to" in out
    assert any((fh / "backup").rglob("CLAUDE.md"))


def test_project_uninstall_never_loses_user_data(tmp_path):
    p = tmp_path / "p"
    S.Setup(str(p)).install(("claude-code",))
    (p / "PROGRESS.md").write_text("doing X\n")
    sk = p / ".claude" / "skills" / "frugal-handoff" / "SKILL.md"
    sk.write_text(sk.read_text() + "tweak\n")
    a = p / "AGENTS.md"
    a.write_text(a.read_text().replace("<!-- frugal-bridge:end -->", "my rule\n<!-- frugal-bridge:end -->"))
    log = S.Setup(str(p)).uninstall()
    assert (p / "PROGRESS.md").read_text() == "doing X\n"
    assert "tweak" in sk.read_text()
    assert "my rule" in list((p / ".frugal-bridge" / "kept").glob("*AGENTS.md.block.md"))[0].read_text()
    assert not (p / ".claude" / "skills" / "frugal-delegate").exists()
    assert any("your data is kept" in l for l in log)



# ---------------------------------------------------------------- frugal-tiers (delegation backend plugin)
FAKE_HERMES = """#!/usr/bin/env python3
import os, re, sys
home = os.environ["HERMES_HOME"]
open(os.path.join(home, "fake-hermes.log"), "a").write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["config", "set", "delegation.backend"]:
    p = os.path.join(home, "config.yaml"); t = open(p).read()
    open(p, "w").write(re.sub(r"(?m)^(  backend: ).*$", lambda m: m.group(1) + sys.argv[4], t, count=1))
"""


def _hermes_home_with_config(home, backend="profile_routes", enabled="[frugal-bridge]"):
    hh = home / ".hermes"; hh.mkdir(exist_ok=True)
    (hh / "SOUL.md").write_text("You are Kai.\n")
    cfg = f"model:\n  provider: anthropic\nplugins:\n  enabled: {enabled}\ndelegation:\n  max_iterations: 50\n  backend: {backend}\n"
    (hh / "config.yaml").write_text(cfg)
    return hh


def _fake_hermes_bin(tmp_path, monkeypatch):
    b = tmp_path / "bin"; b.mkdir(); exe = b / "hermes"
    exe.write_text(FAKE_HERMES); exe.chmod(0o755)
    monkeypatch.setattr(S.shutil, "which", lambda n: str(exe) if n == "hermes" else None)
    return exe


def test_yaml_key_reader():
    t = "plugins:\n  enabled:\n    - a\n    - frugal-tiers  # mine\n  disabled: []\ndelegation:\n  # c\n  backend: 'x-y'\n  backends:\n    x-y: {}\n"
    assert S._yaml_key(t, "plugins", "enabled") == ["a", "frugal-tiers"]
    assert S._yaml_key(t, "delegation", "backend") == "x-y"
    assert S._yaml_key("delegation:\n  model: m\n", "delegation", "backend") is None
    assert S._yaml_key("", "delegation", "backend") is None


def test_global_copies_tiers_plugin_prints_enable_and_uninstall_byte_identical(tmp_path, monkeypatch, capsys):
    home = _fake_home(tmp_path, monkeypatch)
    hh = _hermes_home_with_config(home)
    before = tree(str(home))
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0
    out = capsys.readouterr().out
    for f in ("__init__.py", "plugin.yaml", "tiers.json"):
        assert (hh / "plugins" / "frugal-tiers" / f).exists()
    assert "hermes plugins enable frugal-tiers" in out and "hermes config set delegation.backend frugal-tiers" in out
    assert "undo: hermes config set delegation.backend profile_routes" in out
    assert (hh / "config.yaml").read_text().count("backend: profile_routes") == 1     # config never edited by setup
    assert "hermes tiers: off (plugin copied, not enabled, delegation.backend=profile_routes)" in S.GlobalSetup().check()
    reg = json.loads((home / ".frugal-bridge" / "global.json").read_text())
    assert reg["hermes_backend_prev"] == {str(hh): "profile_routes"}
    snap = tree(str(home))
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0       # re-run: identical
    assert strip_dirs(tree(str(home))) == strip_dirs(snap)
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    after = strip_dirs(tree(str(home)))
    assert after.pop(".frugal-bridge/USER.md")                                     # the user's file is kept (data)
    assert after == strip_dirs(before)
    assert not (hh / "plugins").exists()


def test_global_uninstall_restores_previous_backend(tmp_path, monkeypatch, capsys):
    home = _fake_home(tmp_path, monkeypatch)
    hh = _hermes_home_with_config(home)
    original = (hh / "config.yaml").read_bytes()
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0
    # the user's turn-on step (what `hermes plugins enable` + `hermes config set` do)
    (hh / "config.yaml").write_text(original.decode().replace("[frugal-bridge]", "[frugal-bridge, frugal-tiers]")
                                    .replace("backend: profile_routes", "backend: frugal-tiers"))
    assert "hermes tiers: on (plugin copied, enabled, delegation.backend=frugal-tiers)" in S.GlobalSetup().check()
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0       # re-run keeps the first prev
    assert json.loads((home / ".frugal-bridge" / "global.json").read_text())["hermes_backend_prev"][str(hh)] == "profile_routes"
    exe = _fake_hermes_bin(tmp_path, monkeypatch)
    capsys.readouterr()
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    out = capsys.readouterr().out
    assert (hh / "fake-hermes.log").read_text() == "config set delegation.backend profile_routes\n"
    assert "delegation.backend restored to profile_routes" in out and "hermes plugins disable frugal-tiers" in out
    assert "backend: profile_routes" in (hh / "config.yaml").read_text()
    assert not (hh / "plugins" / "frugal-tiers").exists()


def test_global_uninstall_leaves_other_backend_alone(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    hh = _hermes_home_with_config(home, backend="default")
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0
    (hh / "config.yaml").write_text((hh / "config.yaml").read_text().replace("backend: default", "backend: my-own"))
    _fake_hermes_bin(tmp_path, monkeypatch)
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert not (hh / "fake-hermes.log").exists()                                # user switched away: not touched
    assert "backend: my-own" in (hh / "config.yaml").read_text()


def test_global_uninstall_without_hermes_binary_prints_command(tmp_path, monkeypatch, capsys):
    home = _fake_home(tmp_path, monkeypatch)
    hh = _hermes_home_with_config(home, backend="default")
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0
    (hh / "config.yaml").write_text((hh / "config.yaml").read_text().replace("backend: default", "backend: frugal-tiers"))
    capsys.readouterr()
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    out = capsys.readouterr().out
    assert f"HERMES_HOME={hh} hermes config set delegation.backend default" in out


def test_global_hermes_without_soul_still_copies_tiers(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    hh = home / ".hermes"; hh.mkdir()
    before = tree(str(home))
    assert S.main(["setup.py", "install", "--global", "--hosts", "hermes"]) == 0
    assert (hh / "plugins" / "frugal-tiers" / "tiers.json").exists() and not (hh / "SOUL.md").exists()
    assert "hermes tiers: off" in S.GlobalSetup().check()
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    after = strip_dirs(tree(str(home)))
    after.pop(".frugal-bridge/USER.md", None)
    assert after == strip_dirs(before)


def test_project_install_copies_and_removes_tiers_plugin(tmp_path):
    proj, hh = tmp_path / "p", tmp_path / "hh"; proj.mkdir(); hh.mkdir()
    inst(proj, hosts=("hermes",), hermes_home=str(hh))
    assert (hh / "plugins" / "frugal-tiers" / "__init__.py").exists()
    S.Setup(str(proj)).uninstall()
    assert not (hh / "plugins" / "frugal-tiers").exists()


def test_rules_tell_agents_to_pass_the_tier_model():
    a = open(os.path.join(HERE, "AGENTS.md")).read()
    sk = open(os.path.join(HERE, "skills", "frugal-delegate", "SKILL.md")).read()
    for t in (a, sk):
        assert "haiku" in t and "sonnet" in t and "opus" in t and "tier" in t
