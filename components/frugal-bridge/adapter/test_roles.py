"""Who am I: the session-start notice adds the base's role file only when it is safe (one role lists the host, and
the host has no own identity). The CORE never takes the main agent's name from the user file."""
import importlib.util, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "hooks", "frugal_hook.py")
KIT = os.path.join(os.path.dirname(HERE), "kit")
SCRUB = ("FRUGAL_HOME", "FRUGAL_BASE", "HERMES_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "HERMES_AGENT")

TWIN = "---\ntitle: Twin\nrole: twin\nengines: [hermes]\nname: TwinName\n---\n"
ENGINEER = "---\ntitle: Engineer\nrole: engineer\nengines:\n  - claude-code\n  - codex\n---\n"
LEGACY = "---\ntitle: Old\nrole: old\nengine: gemini\n---\n"


def make_base(home, roles):
    b = home / "base"
    (b / "wiki" / "me").mkdir(parents=True)
    (b / "agents").mkdir()
    (b / "hot.md").write_text("now\n")
    (b / "wiki" / "me" / "owner.md").write_text("I call my twin TwinName.\n")
    (b / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {}}, "slots": {"now": "hot.md", "user": "wiki/me/"}}))
    for n, t in roles.items():
        (b / "agents" / n).write_text(t)
    (home / ".config" / "skeleton-base").mkdir(parents=True)
    (home / ".config" / "skeleton-base" / "base").write_text(str(b) + "\n")
    return b


_N = [0]


def hook(home, cwd, tool="claude-code"):
    _N[0] += 1
    env = {k: v for k, v in os.environ.items() if k not in SCRUB}
    env["HOME"] = str(home)
    r = subprocess.run([sys.executable, HOOK, "--tool", tool], input=json.dumps(
        {"hook_event_name": "SessionStart", "session_id": f"s{_N[0]}", "cwd": str(cwd)}), capture_output=True, text=True,
        env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""


def test_one_match_adds_the_role_file(tmp_path):
    b = make_base(tmp_path, {"twin.md": TWIN, "engineer.md": ENGINEER})
    w = tmp_path / "work"; w.mkdir()
    t = hook(tmp_path, w)
    assert str(b / "agents" / "engineer.md") in t and "your role and name" in t
    assert "twin.md" not in t
    assert str(b / "agents" / "engineer.md") in hook(tmp_path, w, "codex")


def test_zero_or_several_matches_or_own_identity_add_nothing(tmp_path):
    b = make_base(tmp_path, {"twin.md": TWIN, "engineer.md": ENGINEER, "old.md": LEGACY})
    w = tmp_path / "work"; w.mkdir()
    assert "agents" not in hook(tmp_path, w, "opencode")                  # no role lists it
    assert str(b / "agents" / "old.md") in hook(tmp_path, w, "gemini")    # legacy engine: still read
    (b / "agents" / "reviewer.md").write_text(ENGINEER.replace("engineer", "reviewer"))
    assert "agents" not in hook(tmp_path, w)                              # two roles: never guess
    (b / "agents" / "reviewer.md").unlink()
    (w / "ROLE.md").write_text("# ROLE.md - tester\n")
    assert "agents" not in hook(tmp_path, w)                              # the project's own ROLE.md wins


def test_hermes_plugin_with_own_soul_gets_no_role_file(tmp_path, monkeypatch):
    for k in SCRUB:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    b = make_base(tmp_path, {"twin.md": TWIN, "engineer.md": ENGINEER})
    hh = tmp_path / ".hermes"; hh.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hh))
    spec = importlib.util.spec_from_file_location("fbr", os.path.join(HERE, "plugin", "frugal-bridge", "__init__.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m._home = lambda: str(hh)
    (hh / "SOUL.md").write_text("<!-- base-folder:start v2 -->\nPath: x\n<!-- base-folder:end -->\n")
    ctx = m.on_pre_llm_call(session_id="p1", is_first_turn=True)["context"]
    assert str(b / "agents" / "twin.md") in ctx                           # only kit blocks: no own identity
    (hh / "SOUL.md").write_text("You are a profile with its own job.\n")
    ctx = m.on_pre_llm_call(session_id="p2", is_first_turn=True)["context"]
    assert "agents" not in ctx and "hot.md" in ctx


def test_proxy_never_adds_a_role_file(tmp_path, monkeypatch):
    for k in SCRUB:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    make_base(tmp_path, {"engineer.md": ENGINEER})
    spec = importlib.util.spec_from_file_location("fpx", os.path.join(HERE, "proxy", "frugal_proxy.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert "agents" not in m.start_hint(None)                             # the proxy does not know its host
    assert m.role_file(None) is None


def test_core_takes_no_name_from_the_user_file():
    core = open(os.path.join(KIT, "AGENTS.md"), encoding="utf-8").read()
    assert "any name (set in `USER.md`)" not in core
    assert "Never take a name from `USER.md`" in core and "engines:" in core and "no personal name" in core
    assert "name" not in open(os.path.join(KIT, "templates", "USER.md"), encoding="utf-8").read().lower()
    assert "Name (optional" in open(os.path.join(KIT, "templates", "ROLE.md"), encoding="utf-8").read()


def test_core_says_the_tools_own_product_identity_is_not_a_role():
    """Real run 2026-11-13: Codex answered "I'm Codex" although agents/engineer.md listed codex: "its own identity
    (system prompt ...)" let the tool's built-in line win. Only an identity the user set counts."""
    core = open(os.path.join(KIT, "AGENTS.md"), encoding="utf-8").read()
    assert "identity the user set" in core
    assert "built-in \"You are <tool>\" line are not a role or a name" in core
    assert "its own\n  identity (system prompt" not in core
