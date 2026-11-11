"""Tests for the frugal-tiers delegation provider (no Hermes needed, except the real-load test which uses the
installed Hermes Agent when it is found and is skipped otherwise). Run: pytest -q adapter/plugin/test_tiers.py"""
import importlib.util, json, os, re, shutil, subprocess, sys, textwrap

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(HERE, "frugal-tiers")
ROUTING = os.path.join(HERE, "..", "..", "kit", "ROUTING.md")
# found at collection time, before the isolated-HOME fixture runs
HERMES_BIN = shutil.which("hermes")
REAL_HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def load():
    spec = importlib.util.spec_from_file_location("frugal_tiers_t", os.path.join(PLUGIN, "__init__.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


M = load()
DELEG = {"backend": "frugal-tiers", "model": "", "provider": "", "base_url": "", "api_key": "", "max_iterations": 50}


def r(task, parent, settings=None, config=None):
    return M.route(task, config or DELEG, settings or {}, parent=parent)


# ---------------------------------------------------------------- table
def test_table_in_sync_with_routing_md():
    want = M.parse_routing(open(ROUTING, encoding="utf-8").read())
    have = json.load(open(os.path.join(PLUGIN, "tiers.json"), encoding="utf-8"))["tiers"]
    assert have == want, "tiers.json is stale: run python3 adapter/plugin/frugal-tiers/__init__.py --regen kit/ROUTING.md"
    assert set(want) == {"cheap", "mid", "top"}


def test_routing_parse_rules():
    t = M.parse_routing(textwrap.dedent("""\
        | Tier | Anthropic | OpenAI | Google | Effort |
        |---|---|---|---|---|
        | cheap | Claude Haiku 5.5 | GPT-6 Luna or GPT-6.1 Terra (untested) | Gemini 3.8 Flash (partly tested) | medium |
        | mid | Claude Sonnet 5.5 | GPT-6.1 Sol (untested) | — | medium; high for public English writing |
        | top | Claude Opus 5.5 | GPT-6.1 Sol high or GPT-6 Astra (untested) | Gemini 4 Argon/Carbon (untested) | medium |
        """))
    assert t["cheap"]["anthropic"]["id"] == "claude-haiku-5.5"
    assert t["cheap"]["openai"] == {"id": "gpt-6-luna", "name": "GPT-6 Luna", "untested": True}
    assert t["cheap"]["google"]["id"] == "gemini-3.8-flash" and "untested" not in t["cheap"]["google"]
    assert "google" not in t["mid"] and t["mid"]["effort"] == "medium"
    assert t["top"]["openai"]["effort"] == "high" and t["top"]["openai"]["id"] == "gpt-6.1-sol"
    assert t["top"]["google"]["id"] == "gemini-4-argon"


# ---------------------------------------------------------------- routes per parent family
@pytest.mark.parametrize("parent,want", [
    (("anthropic", "claude-opus-5-5"), {"cheap": "claude-haiku-5-5", "mid": "claude-sonnet-5-5", "top": "claude-opus-5-5"}),
    (("openai-codex", "gpt-6-sol"), {"cheap": "gpt-6-luna", "mid": "gpt-6.1-sol", "top": "gpt-6.1-sol"}),
    (("openai", "gpt-6.1-sol"), {"cheap": "gpt-6-luna", "mid": "gpt-6.1-sol", "top": "gpt-6.1-sol"}),
    (("gemini", "gemini-4-argon"), {"cheap": "gemini-3.8-flash", "top": "gemini-4-argon"}),
    (("openrouter", "anthropic/claude-opus-5.5"),
     {"cheap": "anthropic/claude-haiku-5.5", "mid": "anthropic/claude-sonnet-5.5", "top": "anthropic/claude-opus-5.5"}),
    (("nous", "openai/gpt-6-astra"), {"cheap": "openai/gpt-6-luna", "mid": "openai/gpt-6.1-sol"}),
    (("openrouter", "google/gemini-4-argon"), {"cheap": "google/gemini-3.8-flash", "top": "google/gemini-4-argon"}),
    (("", "claude-opus-5-5"), {"cheap": "claude-haiku-5-5"}),          # provider auto: guessed from the model
])
def test_tier_maps_to_parent_family(parent, want):
    for tier, model in want.items():
        out = r({"tier": tier}, parent)
        assert out["model"] == model, (parent, tier, out)
        assert out["label"].startswith(tier + ": " + model)
        assert out["reasoning_effort"] in ("medium", "high")
        assert not out.get("provider")                   # same provider/credentials as the parent
        assert "backends" not in out and "backend" not in out


def test_openai_top_effort_from_table_and_effort_param_wins():
    assert r({"tier": "top"}, ("openai", "gpt-6-sol"))["reasoning_effort"] == "high"
    assert r({"tier": "top", "effort": "medium"}, ("openai", "gpt-6-sol"))["reasoning_effort"] == "medium"
    assert r({"tier": "cheap", "effort": "high"}, ("anthropic", "claude-opus-5-5"))["reasoning_effort"] == "high"


def test_untested_entries_say_so_in_label():
    assert "(untested)" in r({"tier": "cheap"}, ("openai-codex", "gpt-6-sol"))["label"]
    assert "untested" not in r({"tier": "cheap"}, ("anthropic", "claude-opus-5-5"))["label"]


# ---------------------------------------------------------------- inherit cases
def test_no_tier_is_the_default_route():
    out = r({"goal": "x"}, ("anthropic", "claude-opus-5-5"))
    assert out == {k: v for k, v in DELEG.items() if k != "backend"}
    assert "label" not in out and not out["model"]


def test_no_tier_with_effort_only_sets_effort():
    out = r({"effort": "high"}, ("anthropic", "claude-opus-5-5"))
    assert out["reasoning_effort"] == "high" and not out["model"]


@pytest.mark.parametrize("parent", [("bedrock", "us.anthropic.claude-opus-5-5"), ("custom", "my-local-model"),
                                    ("openrouter", "x-ai/grok-4.7"), ("zai", "glm-5.3")])
def test_unknown_family_inherits_with_note(parent):
    out = r({"tier": "cheap"}, parent)
    assert not out["model"] and "parent model kept" in out["label"]


def test_missing_table_entry_inherits_with_note():
    out = r({"tier": "mid"}, ("gemini", "gemini-4-argon"))            # ROUTING.md has no Google mid model
    assert not out["model"] and "no mid model for google" in out["label"]


def test_delegation_pin_is_kept_and_used_as_parent():
    cfg = {**DELEG, "provider": "openrouter", "model": "anthropic/claude-opus-5.5"}
    out = M.route({"tier": "cheap"}, cfg, {})                         # parent read from the delegation pin
    assert out["provider"] == "openrouter" and out["model"] == "anthropic/claude-haiku-5.5"


# ---------------------------------------------------------------- overrides
def test_override_model_same_provider():
    out = r({"tier": "cheap"}, ("anthropic", "claude-opus-5-5"), {"cheap": {"model": "claude-haiku-4-5-20251001"}})
    assert out["model"] == "claude-haiku-4-5-20251001" and not out["provider"] and "override" in out["label"]


def test_override_other_provider_drops_inherited_endpoint():
    cfg = {**DELEG, "base_url": "http://old", "api_key": "old"}
    out = r({"tier": "mid", "effort": "high"}, ("anthropic", "claude-opus-5-5"),
            {"mid": {"provider": "openrouter", "model": "anthropic/claude-sonnet-5.5"}}, cfg)
    assert out["provider"] == "openrouter" and out["model"] == "anthropic/claude-sonnet-5.5"
    assert "base_url" not in out and "api_key" not in out and out["reasoning_effort"] == "high"


def test_override_shorthand_and_effort():
    out = r({"tier": "top"}, ("custom", "x"), {"top": "big-model"})
    assert out["model"] == "big-model"
    out = r({"tier": "top"}, ("anthropic", "x"), {"top": {"model": "m", "effort": "high"}})
    assert out["reasoning_effort"] == "high"


# ---------------------------------------------------------------- errors, schema, provider object
def test_unknown_tier_and_effort_refused():
    with pytest.raises(M.DelegationRouteError, match="Unknown tier"):
        r({"tier": "huge"}, ("anthropic", "x"))
    with pytest.raises(M.DelegationRouteError, match="Unknown effort"):
        r({"tier": "cheap", "effort": "xhigh"}, ("anthropic", "x"))


def test_schema_params_and_description():
    p = M.FrugalTiers()
    params = p.task_parameters(DELEG)
    assert params["tier"]["enum"] == ["cheap", "mid", "top"] and params["effort"]["enum"] == ["low", "medium", "high"]
    assert p.task_parameters(DELEG) == params                         # deterministic (prompt cache)
    d = p.description(DELEG)
    assert 3 <= len(d.splitlines()) <= 4 and "never low" in d and "one tier up" in d
    assert p.name == "frugal-tiers" and p.is_available() is True


def test_settings_from_backends_block():
    p = M.FrugalTiers()
    cfg = {**DELEG, "backends": {"frugal-tiers": {"cheap": {"model": "m1"}}}}
    assert p.route_task({"tier": "cheap"}, cfg)["model"] == "m1"


def test_is_available_without_table(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "TABLE_FILE", str(tmp_path / "missing.json"))
    assert M.FrugalTiers().is_available() is False


def test_no_network_imports():
    src = open(os.path.join(PLUGIN, "__init__.py"), encoding="utf-8").read()
    assert not re.search(r"^\s*(import|from)\s+(urllib|http|socket|requests|httpx)", src, re.M)


# ---------------------------------------------------------------- real load through Hermes's own plugin loader
def _hermes_runtime():
    """(python, agent_dir) of the installed Hermes Agent, read from its launcher script; None when absent."""
    if not HERMES_BIN:
        return None
    try:
        txt = open(HERMES_BIN, encoding="utf-8").read()
        m = re.search(r"exec\s+(\S+)", txt)
        if m and not m.group(1).endswith("python3"):
            txt = open(m.group(1), encoding="utf-8").read()   # a shim that execs the real launcher
        py = re.search(r"exec\s+(\S+python3)\s+-I", txt).group(1)
        agent = re.search(r"sys\.path\.insert\(0,\s*'\"'\"'([^']+)'\"'\"'\)", txt).group(1)
    except (OSError, AttributeError):
        return None
    if os.path.isfile(py) and os.path.isfile(os.path.join(agent, "agent", "delegation_registry.py")):
        return py, agent
    return None


PROBE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from pm.environments import activate_dependencies  # select Hermes's own installed dependencies (no install)
activate_dependencies(Path(sys.argv[1]))           # under the real data root (read: which env is committed)
import os
os.environ["HERMES_HOME"] = sys.argv[2]             # from here on: the isolated test home only
from hermes_cli.plugins import PluginManager
from hermes_cli.config import load_config_readonly
from agent.delegation_registry import get_active_provider
from tools.delegate_tool_routes import schema_extension
PluginManager().discover_and_load()
cfg = load_config_readonly()["delegation"]
p = get_active_provider(cfg)
props, desc = schema_extension(cfg)
out = {"name": p.name, "type": type(p).__mro__[1].__module__, "props": sorted(props),
       "tier_enum": props["tier"]["enum"], "desc": desc,
       "cheap": p.route_task({"goal": "g", "index": 0, "tier": "cheap"}, cfg),
       "mid": p.route_task({"goal": "g", "index": 1, "tier": "mid"}, cfg),
       "none": p.route_task({"goal": "g", "index": 2}, cfg)}
try:
    p.route_task({"tier": "huge"}, cfg); out["huge"] = "accepted"
except Exception as e:
    out["huge"] = type(e).__name__
print("RESULT " + json.dumps(out))
'''


@pytest.mark.skipif(_hermes_runtime() is None, reason="Hermes Agent not installed here")
def test_real_load_through_hermes_plugin_loader(tmp_path):
    py, agent = _hermes_runtime()
    hh = tmp_path / ".hermes"
    shutil.copytree(PLUGIN, hh / "plugins" / "frugal-tiers", ignore=shutil.ignore_patterns("__pycache__"))
    (hh / "config.yaml").write_text(textwrap.dedent("""\
        model:
          provider: anthropic
          default: claude-opus-5-5
        plugins:
          enabled: [frugal-tiers]
        delegation:
          backend: frugal-tiers
          backends:
            frugal-tiers:
              top: {model: claude-opus-5-5, effort: high}
        """))
    (tmp_path / "probe.py").write_text(PROBE)
    (tmp_path / "os-home").mkdir()
    env = {"HOME": str(tmp_path / "os-home"), "HERMES_HOME": str(hh), "PATH": "/usr/bin:/bin",
           "HERMES_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"}
    env["HERMES_HOME"] = REAL_HERMES_HOME   # only to select Hermes's installed dependencies; the probe switches
    res = subprocess.run([py, "-I", str(tmp_path / "probe.py"), agent, str(hh)], env=env, cwd=str(tmp_path),
                         capture_output=True, text=True, timeout=240)
    line = [ln for ln in res.stdout.splitlines() if ln.startswith("RESULT ")]
    assert line, res.stdout[-2000:] + res.stderr[-3000:]
    out = json.loads(line[-1][7:])
    assert out["name"] == "frugal-tiers" and out["type"] == "agent.delegation_provider"
    assert out["props"] == ["effort", "tier"] and out["tier_enum"] == ["cheap", "mid", "top"]
    assert "Frugal tiers" in out["desc"]
    assert out["cheap"]["model"] == "claude-haiku-5-5" and out["mid"]["model"] == "claude-sonnet-5-5"
    assert "label" not in out["none"] and not out["none"].get("model")
    assert out["huge"] == "DelegationRouteError"
