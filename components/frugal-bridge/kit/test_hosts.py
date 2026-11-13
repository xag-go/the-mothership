"""Per-tool rows of the host table: fake HOME + fake binaries, every tool's own config format, install ->
check -> re-run (byte-identical) -> uninstall (byte-identical), the values written for helper tiers (model AND
effort), hooks per tool, and no double rules block when a base is present or tools share files."""
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fakehome as FH  # noqa: E402

spec = importlib.util.spec_from_file_location("fb_setup_hosts", os.path.join(HERE, "setup.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
HOSTS = S.HOSTS
ALL = [t for t in HOSTS.H]


@pytest.fixture
def home(_isolated_home):
    return _isolated_home


def install(*hosts):
    args = ["setup.py", "install", "--global"] + (["--hosts", ",".join(hosts)] if hosts else [])
    return S.main(args)


def read(home, rel):
    p = os.path.join(str(home), rel)
    return open(p).read() if os.path.exists(p) else None


def fm(text):
    """Frontmatter of an agent file -> dict (values are JSON-quoted by setup)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return {k: json.loads(v) for k, v in (ln.split(": ", 1) for ln in m.group(1).splitlines())}


# ------------------------------------------------------------------ every row: install -> check -> rerun -> uninstall
@pytest.mark.parametrize("tool", ALL)
def test_row_install_check_rerun_uninstall_byte_identical(tool, home, monkeypatch, capsys):
    FH.build(home, [tool], monkeypatch, S, HOSTS)
    before, before_dirs = FH.snapshot(home), FH.dirs(home)
    assert install(tool) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert f"skipped {tool}" not in out
    rep = S.GlobalSetup().check()
    assert rep.startswith("OK"), rep
    snap = FH.snapshot(home)
    assert install(tool) == 0
    assert FH.snapshot(home) == snap                                    # idempotent, byte for byte
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert FH.snapshot(home) == before                                  # every byte of the user's files back
    assert FH.dirs(home) == before_dirs                                 # and no folder left behind


@pytest.mark.parametrize("tool", ALL)
def test_row_rules_loaded_once(tool, home, monkeypatch):
    FH.build(home, [tool], monkeypatch, S, HOSTS)
    assert install(tool) == 0
    info = S.GlobalSetup().reg()["tools"].get(tool)
    if tool in ("hermes", "openclaw"):
        assert info and info["file"].endswith(("SOUL.md", "workspace/AGENTS.md"))
    if HOSTS.H[tool]["rules"] is None:                                  # Cursor: no rules file, the hook brings them
        assert info["rules_copy"].endswith("RULES.md")
        assert "frugal-bridge:start" in open(info["rules_copy"]).read()
        return
    if HOSTS.H[tool]["rules"] == "aider-read":
        y = read(home, ".aider.conf.yml")
        assert y.startswith("model: sonnet\nread:\n") and "RULES.md" in y and "CONVENTIONS.md" in y
        return
    txt = open(info["file"]).read()
    assert txt.count("frugal-bridge:start") == 1
    assert "## Helper tiers here" in txt


def test_detection_binary_or_own_config_not_shared_dirs(home, monkeypatch):
    monkeypatch.setattr(S.shutil, "which", lambda b: None)
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text("{}")             # Antigravity makes these too
    (home / ".config").mkdir(); (home / ".agents").mkdir()
    assert "gemini" not in S.GlobalSetup().detect()
    (home / ".gemini" / "antigravity-ide").mkdir()
    assert "antigravity" in S.GlobalSetup().detect() and "gemini" not in S.GlobalSetup().detect()
    monkeypatch.setattr(S.shutil, "which", lambda b: "/x/gemini" if b == "gemini" else None)
    assert "gemini" in S.GlobalSetup().detect()


def test_explicit_hosts_only_installed(home, monkeypatch, capsys):
    FH.build(home, ["claude-code"], monkeypatch, S, HOSTS)
    assert install("claude-code", "gemini", "zed") == 0
    out = capsys.readouterr().out
    assert "skipped gemini: not installed" in out and "skipped zed: not installed" in out
    assert not (home / ".gemini").exists() and not (home / ".config" / "zed").exists()


# ------------------------------------------------------------------ all tools at once
def test_all_tools_install_uninstall_byte_identical(home, monkeypatch, capsys):
    FH.build(home, ALL, monkeypatch, S, HOSTS)
    before, before_dirs = FH.snapshot(home), FH.dirs(home)
    assert install() == 0, capsys.readouterr().out
    rep = S.GlobalSetup().check()
    assert rep.startswith("OK"), rep
    snap = FH.snapshot(home)
    assert install() == 0
    assert FH.snapshot(home) == snap
    # every rules file holds exactly one Frugal block, and no tool loads two of them
    for rel, text in snap.items():
        assert text.count(b"frugal-bridge:start") <= 1, rel
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert FH.snapshot(home) == before
    assert FH.dirs(home) == before_dirs


def test_shared_files_load_once(home, monkeypatch):
    FH.build(home, ["claude-code", "kilo", "devin", "warp", "droid", "cline", "crush", "amp", "gemini", "antigravity"],
             monkeypatch, S, HOSTS)
    assert install() == 0
    tools = S.GlobalSetup().reg()["tools"]
    assert tools["kilo"]["via"] == "claude-code" and tools["devin"]["via"] == "claude-code"
    assert tools["droid"]["via"] == "warp" and tools["cline"]["via"] == "warp"
    assert tools["antigravity"]["same_as"] == "gemini"
    assert not (home / ".config" / "kilo" / "AGENTS.md").exists()
    assert not (home / ".factory" / "AGENTS.md").exists() and not (home / ".cline" / "rules").exists()
    assert not (home / ".config" / "AGENTS.md").exists()               # read by Crush AND Amp: never written
    assert read(home, ".agents/AGENTS.md").count("frugal-bridge:start") == 1
    # skills: once in the shared folder, Claude Code's own folder for Claude Code
    assert (home / ".agents" / "skills" / "frugal-delegate" / "SKILL.md").exists()
    assert (home / ".claude" / "skills" / "frugal-delegate" / "SKILL.md").exists()
    assert not (home / ".config" / "kilo" / "skills").exists()


def test_base_present_one_block_after_base(home, monkeypatch, tmp_path):
    b = tmp_path / "kb"; b.mkdir()
    (b / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {"version": "1"}},
                                              "slots": {"user": "wiki/me/", "now": "hot.md"}}))
    blk = f"<!-- base-folder:start v2 -->\nPath: {b}\n<!-- base-folder:end -->"
    tools = ["claude-code", "codex", "qwen", "kiro", "grok", "zed", "junie"]
    FH.build(home, tools, monkeypatch, S, HOSTS)
    base_files = {"claude-code": ".claude/CLAUDE.md", "codex": ".codex/AGENTS.md", "qwen": ".qwen/QWEN.md",
                  "kiro": ".kiro/steering/skeleton-base.md", "grok": ".grok/AGENTS.md", "zed": ".config/zed/AGENTS.md",
                  "junie": ".junie/AGENTS.md"}
    for t, rel in base_files.items():
        p = home / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if p.exists() else "") + blk + "\n")
    before = FH.snapshot(home)
    assert install(*tools) == 0
    reg = S.GlobalSetup().reg()
    for t, rel in base_files.items():
        txt = read(home, rel)
        assert reg["tools"][t]["file"] == str(home / rel), t              # the base's file, not a second one
        assert txt.count("frugal-bridge:start") == 1 and txt.index("base-folder:end") < txt.index("frugal-bridge:start")
    assert not (home / ".kiro" / "steering" / "frugal-bridge.md").exists()
    assert not (home / ".grok" / "rules").exists()
    assert S.GlobalSetup().check().startswith("OK")
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert FH.snapshot(home) == before


def test_caps(home, monkeypatch):
    FH.build(home, ["hermes"], monkeypatch, S, HOSTS)
    (home / ".hermes" / "SOUL.md").write_text("x" * 19000 + "\n")
    assert install("hermes") == 1
    rep = S.GlobalSetup().check()
    assert "over 20000 chars" in rep and rep.startswith("PROBLEMS")


def test_codex_override_file_wins(home, monkeypatch):
    FH.build(home, ["codex"], monkeypatch, S, HOSTS)
    (home / ".codex" / "AGENTS.override.md").write_text("override\n")
    assert install("codex") == 0
    assert read(home, ".codex/AGENTS.override.md").count("frugal-bridge:start") == 1
    assert not (home / ".codex" / "AGENTS.md").exists()


def test_never_creates_identity_files(home, monkeypatch):
    FH.build(home, ["hermes", "openclaw"], monkeypatch, S, HOSTS)
    os.remove(home / ".hermes" / "SOUL.md"); os.remove(home / ".openclaw" / "workspace" / "AGENTS.md")
    assert install("hermes", "openclaw") == 0
    assert not (home / ".hermes" / "SOUL.md").exists() and not (home / ".openclaw" / "workspace" / "AGENTS.md").exists()
    assert set(S.GlobalSetup().reg()["needs_user"]) == {"hermes", "openclaw"}


# ------------------------------------------------------------------ helper tiers: model AND effort per tool
TABLE = HOSTS.load_tiers(HERE)


def expect(tier, fam="anthropic"):
    e = TABLE[tier][fam]
    return e["id"], e.get("effort") or TABLE[tier]["effort"]


def test_tier_values_claude(home, monkeypatch):
    FH.build(home, ["claude-code"], monkeypatch, S, HOSTS)
    assert install("claude-code") == 0
    got = {n: fm(read(home, f".claude/agents/{n}.md")) for n in ("frugal-cheap", "frugal-mid", "frugal-mid-writing", "frugal-top")}
    assert {n: (v["model"], v["effort"]) for n, v in got.items()} == {
        "frugal-cheap": ("claude-haiku-5-5", "medium"), "frugal-mid": ("claude-sonnet-5-5", "medium"),
        "frugal-mid-writing": ("claude-sonnet-5-5", "high"), "frugal-top": ("claude-opus-5-5", "medium")}
    # the exact model of tiers.json (Anthropic id form), never the family alias: a real run showed Claude Code's
    # `haiku` alias running an older Haiku than the table's cheap model
    for n, v in got.items():
        assert v["model"] == expect(n.replace("frugal-", "").replace("mid-writing", "mid"))[0].replace(".", "-")
    txt = read(home, ".claude/CLAUDE.md")
    assert "`frugal-cheap` = claude-haiku-5-5, effort medium" in txt
    assert "`frugal-mid-writing` = claude-sonnet-5-5, effort high" in txt
    assert "older model" in txt                       # the alias fallback is named as second choice


def test_tier_values_codex(home, monkeypatch):
    FH.build(home, ["codex"], monkeypatch, S, HOSTS)
    assert install("codex") == 0
    for n, tier, eff in (("frugal-cheap", "cheap", None), ("frugal-mid", "mid", None),
                         ("frugal-mid-writing", "mid", "high"), ("frugal-top", "top", None)):
        t = read(home, f".codex/agents/{n}.toml")
        mid, e = expect(tier, "openai")
        assert f'model = "{mid}"' in t and f'model_reasoning_effort = "{eff or e}"' in t and f'name = "{n}"' in t
    assert 'model_reasoning_effort = "high"' in read(home, ".codex/agents/frugal-top.toml")   # tiers.json: openai top high


@pytest.mark.parametrize("tool,path,check", [
    ("cursor", ".cursor/agents/{n}.md", lambda f, m, e: f["model"] == f"{m}[effort={e}]"),
    ("droid", ".factory/droids/{n}.md", lambda f, m, e: f["model"] == m and f["reasoningEffort"] == e),
    ("junie", ".junie/agents/{n}.md", lambda f, m, e: f["model"] == HOSTS.claude_alias(m) and f["reasoningLevel"] == e),
    ("kilo", ".config/kilo/agents/{n}.md", lambda f, m, e: f["model"] == "anthropic/" + m.replace(".", "-")
     and f["reasoningEffort"] == e and f["mode"] == "subagent"),
    ("opencode", ".config/opencode/agents/{n}.md", lambda f, m, e: f["model"] == "anthropic/" + m.replace(".", "-")
     + ("" if e == "medium" else "#" + e) and f["mode"] == "subagent"),
    ("copilot", ".copilot/agents/{n}.agent.md", lambda f, m, e: f["model"] == m),
    ("devin", ".config/devin/agents/{n}.md", lambda f, m, e: f["model"] == m and "effort" not in f),
])
def test_tier_values_agent_files(tool, path, check, home, monkeypatch):
    FH.build(home, [tool], monkeypatch, S, HOSTS)
    assert install(tool) == 0
    for n, tier, eff in HOSTS.TIER_AGENTS:
        mid, e = expect(tier)
        if tool == "devin" and n == "mid-writing":                      # no effort field: no extra agent
            assert read(home, path.format(n="frugal-mid-writing")) is None
            continue
        f = fm(read(home, path.format(n=f"frugal-{n}")))
        assert check(f, mid, eff or e), (tool, n, f)


def test_tier_values_copilot_effort_setting(home, monkeypatch):
    FH.build(home, ["copilot"], monkeypatch, S, HOSTS)
    assert install("copilot") == 0
    st = json.loads(read(home, ".copilot/settings.json"))
    assert st["theme"] == "dim"
    assert st["subagents"]["agents"]["frugal-mid-writing"] == {"model": expect("mid")[0], "effortLevel": "high"}
    assert st["subagents"]["agents"]["frugal-cheap"]["effortLevel"] == "medium"


def test_tier_values_gemini_thinking_level(home, monkeypatch):
    FH.build(home, ["gemini"], monkeypatch, S, HOSTS)
    assert install("gemini") == 0
    st = read(home, ".gemini/settings.json")
    assert "// my comment" in st                                         # comments kept (text insert)
    d = json.loads(HOSTS.strip_jsonc(st))
    lv = {o["match"]["overrideScope"]: o["modelConfig"]["generateContentConfig"]["thinkingConfig"]["thinkingLevel"]
          for o in d["modelConfigs"]["overrides"]}
    assert lv == {"frugal-cheap": "MEDIUM", "frugal-top": "MEDIUM"}      # google has no mid row in ROUTING.md
    assert fm(read(home, ".gemini/agents/frugal-cheap.md"))["model"] == expect("cheap", "google")[0]
    assert not (home / ".gemini" / "agents" / "frugal-mid.md").exists()


def test_tier_values_qwen_grades_kiro_goose_grok(home, monkeypatch):
    FH.build(home, ["qwen", "kiro", "goose", "grok"], monkeypatch, S, HOSTS)
    assert install("qwen", "kiro", "goose", "grok") == 0
    g = json.loads(read(home, ".qwen/settings.json"))["agents"]["modelGrades"]
    assert g == {"frugal-cheap": expect("cheap")[0], "frugal-mid": expect("mid")[0], "frugal-top": expect("top")[0]}
    k = json.loads(read(home, ".kiro/agents/frugal-top.json"))
    assert k["model"] == expect("top")[0] and not any("effort" in key.lower() for key in k)
    r = read(home, ".config/goose/recipes/frugal-cheap.yaml")
    assert 'goose_model: "claude-haiku-5-5"' in r and 'goose_provider: "anthropic"' in r
    t = read(home, ".grok/config.toml")
    assert t.startswith('[models]\ndefault = "claude-sonnet-5.5"\n')
    assert f'explore = "{expect("cheap")[0]}"  # frugal-bridge' in t and f'plan = "{expect("top")[0]}"' in t


def test_tier_rules_openclaw_zed(home, monkeypatch):
    FH.build(home, ["openclaw", "zed"], monkeypatch, S, HOSTS)
    assert install("openclaw", "zed") == 0
    oc = read(home, ".openclaw/workspace/AGENTS.md")
    assert f"cheap = model `{expect('cheap')[0]}`, thinking `medium`" in oc
    assert f"top = model `{expect('top', 'openai')[0]}`, thinking `high`" in oc
    assert "mid-writing = model" in oc and "thinking `high`" in oc
    assert "effort is not per helper here" in read(home, ".config/zed/AGENTS.md")


def test_no_tier_for_unmapped_family(home, monkeypatch, capsys):
    FH.build(home, ["grok"], monkeypatch, S, HOSTS)
    (home / ".grok" / "config.toml").write_text('[models]\ndefault = "grok-5"\n')
    assert install("grok") == 0
    assert "not in ROUTING.md families" in capsys.readouterr().out
    assert read(home, ".grok/config.toml") == '[models]\ndefault = "grok-5"\n'
    assert "No per-helper model or effort" in read(home, ".grok/rules/frugal-bridge.md")


def test_effort_never_low_or_above_high(home, monkeypatch):
    FH.build(home, ALL, monkeypatch, S, HOSTS)
    assert install() == 0
    for rel, text in FH.snapshot(home).items():
        t = text.decode(errors="replace")
        if "frugal" in rel and ("agents" in rel or "droids" in rel or "recipes" in rel):
            assert not re.search(r"effort\W+\s*(low|xhigh|max)|reasoningLevel\W+(low)|thinkingLevel\W+LOW", t, re.I), rel
    for t, ti in S.GlobalSetup().reg()["tiers"].items():
        for _, _, e, _ in ti["rows"]:
            assert e in (None, "medium", "high"), (t, e)


# ------------------------------------------------------------------ hooks per tool
def hook_cmds(text):
    return re.findall(r'python3 \\?"[^"\\]*frugal_hook\.py\\?" --tool ([\w-]+) --event (\w+)', text)


@pytest.mark.parametrize("tool,rel,want", [
    ("claude-code", ".claude/settings.json", {("claude-code", "start"), ("claude-code", "prompt"),
                                              ("claude-code", "post_tool"), ("claude-code", "usage")}),
    ("codex", ".codex/hooks.json", {("codex", "start"), ("codex", "prompt"), ("codex", "post_tool"), ("codex", "usage")}),
    ("gemini", ".gemini/settings.json", {("gemini", "start"), ("gemini", "prompt"), ("gemini", "post_tool")}),
    ("qwen", ".qwen/settings.json", {("qwen", "start"), ("qwen", "prompt")}),
    ("junie", ".junie/config.json", {("junie", "start"), ("junie", "prompt"), ("junie", "post_tool")}),
    ("droid", ".factory/settings.json", {("droid", "start"), ("droid", "prompt"), ("droid", "usage")}),
    ("cursor", ".cursor/hooks.json", {("cursor", "start"), ("cursor", "precompact")}),
    ("copilot", ".copilot/hooks/frugal-bridge.json", {("copilot", "start"), ("copilot", "post_tool")}),
    ("kiro", ".kiro/hooks/frugal-bridge.json", {("kiro", "start"), ("kiro", "prompt")}),
    ("crush", ".config/crush/crushrc", {("crush", "post_tool")}),
    ("cline", ".cline/hooks/TaskStart", {("cline", "start")}),
    ("devin", ".config/devin/config.json", {("devin", "start"), ("devin", "prompt")}),
    ("continue", ".continue/settings.json", {("continue", "start"), ("continue", "prompt")}),
])
def test_hooks_written_per_tool(tool, rel, want, home, monkeypatch):
    FH.build(home, [tool], monkeypatch, S, HOSTS)
    assert install(tool) == 0
    assert set(hook_cmds(read(home, rel))) == want
    assert tool in S.GlobalSetup().reg()["native_hooks"]


def test_hooks_kept_user_entries_and_formats(home, monkeypatch):
    FH.build(home, ["claude-code", "crush", "cursor", "devin"], monkeypatch, S, HOSTS)
    assert install() == 0
    st = json.loads(read(home, ".claude/settings.json"))
    assert st["model"] == "opus" and st["hooks"]["Stop"][0]["hooks"][0]["command"] == "mine"
    assert any(g.get("matcher") == "Bash" for g in st["hooks"]["PostToolUse"])
    assert read(home, ".config/crush/crushrc").startswith("option theme dark\nhook add PostToolUse --matcher '^bash$'")
    cur = json.loads(read(home, ".cursor/hooks.json"))
    assert cur["version"] == 1 and "command" in cur["hooks"]["sessionStart"][0]
    # Devin runs Claude Code's hooks: no second copy in its own config
    assert "frugal_hook" not in read(home, ".config/devin/config.json")


def test_cline_hook_collision_left_alone(home, monkeypatch, capsys):
    FH.build(home, ["cline"], monkeypatch, S, HOSTS)
    (home / ".cline" / "hooks").mkdir(); (home / ".cline" / "hooks" / "TaskStart.sh").write_text("mine\n")
    assert install("cline") == 0
    assert "TaskStart hook of yours exists" in capsys.readouterr().out
    assert not (home / ".cline" / "hooks" / "TaskStart").exists()


def test_plugins_js_written_with_paths(home, monkeypatch):
    FH.build(home, ["opencode", "kilo", "amp"], monkeypatch, S, HOSTS)
    assert install("opencode", "kilo", "amp") == 0
    for rel in (".config/opencode/plugins/frugal-bridge.js", ".config/kilo/plugin/frugal-bridge.js",
                ".config/amp/plugins/frugal-bridge.js"):
        t = read(home, rel)
        assert "__FRUGAL_" not in t and str(home / ".frugal-bridge" / "frugal_hook.py") in t


def test_user_edits_to_our_files_are_kept(home, monkeypatch, capsys):
    FH.build(home, ["claude-code"], monkeypatch, S, HOSTS)
    assert install("claude-code") == 0
    p = home / ".claude" / "agents" / "frugal-top.md"
    p.write_text(p.read_text() + "my note\n")
    s = json.loads(read(home, ".claude/settings.json")); s["theme"] = "x"
    (home / ".claude" / "settings.json").write_text(json.dumps(s))
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    assert p.exists() and "my note" in p.read_text()
    s2 = json.loads(read(home, ".claude/settings.json"))
    assert s2["theme"] == "x" and s2["model"] == "opus" and "frugal_hook" not in json.dumps(s2)
    assert s2["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}


# ------------------------------------------------------------------ usage report
def test_report_merges_every_log(home, monkeypatch):
    import time
    fb = home / ".frugal-bridge"; fb.mkdir()
    (fb / "usage.jsonl").write_text(json.dumps(dict(ts=time.time(), session="s", model="claude-haiku-5-5", context=200000,
                                                    input=10, output=1000, cache_read=5000, cache_write=0, tool="codex")) + "\n")
    hh = home / ".hermes" / "frugal-bridge"; hh.mkdir(parents=True)
    (hh / "usage.jsonl").write_text(json.dumps(dict(ts=time.time(), session="h", model="claude-opus-5-5", context=10,
                                                    input=1000, output=1000, cache_read=0, cache_write=0)) + "\n")
    r = S.report(7)
    assert "| codex | claude-haiku-5-5 | 1 |" in r and "| hermes | claude-opus-5-5 | 1 |" in r
    assert "context reached 200k" in r
    p = subprocess.run([sys.executable, os.path.join(HERE, "setup.py"), "report", "7"], capture_output=True, text=True,
                       env=dict(os.environ, HOME=str(home), FRUGAL_HOME=str(fb)))
    assert p.returncode == 0 and "| codex |" in p.stdout


def test_tool_gone_keeps_block_current_adds_nothing(home, monkeypatch, capsys):
    FH.build(home, ["gemini"], monkeypatch, S, HOSTS)
    assert install("gemini") == 0
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    reg = home / ".frugal-bridge" / "global.json"
    # an older install registered gemini with only its rules block; the CLI is gone now (an IDE still reads the file)
    (home / ".gemini" / "GEMINI.md").write_text("<!-- frugal-bridge:start v5 -->\nOLDTEXT\n<!-- frugal-bridge:end -->\n")
    reg.write_text(json.dumps({"tools": {"gemini": {"file": str(home / ".gemini" / "GEMINI.md"), "mode": "new",
                                                    "created": True, "block_sha": []}}}))
    monkeypatch.setattr(S.shutil, "which", lambda b: None)
    settings = read(home, ".gemini/settings.json")
    assert install("gemini") == 0
    out = capsys.readouterr().out
    assert "skipped gemini: not installed" in out and "kept current: gemini" in out
    t = read(home, ".gemini/GEMINI.md")
    assert t.count("frugal-bridge:start v6") == 1 and "OLDTEXT" not in t
    assert read(home, ".gemini/settings.json") == settings and not (home / ".gemini" / "agents").exists()


def test_upgrade_from_older_install_keeps_keys_added_since(home, monkeypatch):
    """An older Frugal (no ledger) recorded settings.json before a base added its keys: uninstall after the upgrade
    must keep the base's keys (no restore from the old snapshot) and drop only Frugal's hooks."""
    FH.build(home, ["claude-code"], monkeypatch, S, HOSTS)
    st = home / ".claude" / "settings.json"
    old_snapshot = st.read_text()
    hook = f'python3 "{home}/.frugal-bridge/frugal_hook.py" {S.HOOK_TAG}'
    d = json.loads(old_snapshot)
    d["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "command": hook}]}]
    d["permissions"] = {"additionalDirectories": ["/kb"]}                   # added by a base after that install
    st.write_text(json.dumps(d, indent=2) + "\n")
    (home / ".frugal-bridge").mkdir(exist_ok=True)
    (home / ".frugal-bridge" / "global.json").write_text(json.dumps({"tools": {"claude-code": {
        "file": str(home / ".claude" / "CLAUDE.md"), "mode": "append", "created": False, "block_sha": []}},
        "orig": {str(st): old_snapshot}}))
    assert install("claude-code") == 0
    assert S.main(["setup.py", "uninstall", "--global"]) == 0
    after = json.loads(st.read_text())
    assert after["permissions"] == {"additionalDirectories": ["/kb"]} and after["model"] == "opus"
    assert "frugal_hook" not in st.read_text() and after["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}


def test_codex_stop_usage_hook_installed(home, monkeypatch):
    """Codex CLI 0.159.x has no PostModelRequest event: the usage hook must run on Stop (kept beside the others)."""
    FH.build(home, ["codex"], monkeypatch, S, HOSTS)
    assert install("codex") == 0
    hooks = json.loads(read(home, ".codex/hooks.json"))["hooks"]
    assert {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "PostModelRequest"} <= set(hooks)
    assert "--event usage" in json.dumps(hooks["Stop"])
