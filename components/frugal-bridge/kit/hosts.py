"""Frugal-Bridge host table: every live agent tool, where its user-level rules load from, how Frugal enforces the
rules there (hooks / plugin / proxy), how helper tiers reach its subagents (model + effort), and what is impossible.

Sources: the harness audit (docs fetched 2026-11-11; adapter/README.md lists them per row). Paths are written as
"~/..." or "@root/..." (the tool's own home, which follows the tool's env override, e.g. CODEX_HOME).

Rules:
- Installed = the tool's binary on PATH, or a config file only that tool writes ("proof"). A shared folder alone
  (e.g. ~/.gemini, also made by an IDE) is never proof.
- One rules file per tool, the same one the knowledge base uses when it has a block there ("base_files" first), else
  "rules". A tool that already loads another selected tool's file ("reads") gets no file of its own (loads once).
- "existing" = only added to an existing file (Hermes SOUL.md is the tool's identity: never created).
Standard library only.
"""
import json
import os
import re
import shutil

TAG = "frugal-bridge"                 # tag on every line / key Frugal adds to a config file
LINE_TAG = "# frugal-bridge"
SHARED_SKILLS = "~/.agents/skills"

# tier agents: (name suffix, tier, effort override). mid-writing = public English writing (ROUTING.md: mid, high).
TIER_AGENTS = (("cheap", "cheap", None), ("mid", "mid", None), ("mid-writing", "mid", "high"), ("top", "top", None))
ALLOWED_EFFORT = ("medium", "high")   # never low for real work; no xhigh / max (AGENTS.md section 2)

H = {
    # ---- CLIs / agents
    "claude-code": dict(
        label="Claude Code", root=("CLAUDE_CONFIG_DIR", "~/.claude"), bins=["claude"],
        proof=["@root/settings.json", "~/.claude.json"], rules="@root/CLAUDE.md",
        skills="@root/skills", hooks="claude", filter=True, usage="Stop hook: transcript usage",
        tiers="claude-agents", family="anthropic", proxy="ANTHROPIC_BASE_URL",
        notes="Also read by Devin (Claude import on by default) and Kilo (fallback); Cursor, Grok, Devin and Continue cn "
              "run its hooks: the hook stands down / runs once."),
    "codex": dict(
        label="Codex CLI (and the ChatGPT desktop app's Codex side)", root=("CODEX_HOME", "~/.codex"), bins=["codex"],
        proof=["@root/config.toml", "@root/auth.json"], rules="@root/AGENTS.md", override="@root/AGENTS.override.md",
        cap=("bytes", 32 * 1024, "combined with the project AGENTS.md (project_doc_max_bytes)"),
        skills="shared", hooks="codex", filter=True, usage="PostModelRequest token_usage",
        tiers="codex-agents", family="codex-config", proxy="model_providers.<id>.base_url",
        notes="Hooks run only after the user trusts them in /hooks (by hash; re-trust after a change). Output filter = "
              "PostToolUse block+reason (the reason replaces the result; partial)."),
    "gemini": dict(
        label="Gemini CLI", root=("", "~/.gemini"), bins=["gemini"], proof=[], rules="@root/GEMINI.md",
        skills="shared", hooks="gemini", filter=True, usage="none in hooks (AfterModel fires per chunk); proxy",
        tiers="gemini-agents", family="google", proxy="GOOGLE_GEMINI_BASE_URL (env)",
        notes="~/.gemini is also made by Antigravity IDE: not proof. Subagents need experimental.enableAgents."),
    "antigravity": dict(
        label="Antigravity IDE", root=("", "~/.gemini"), bins=["antigravity"], proof=["~/.gemini/antigravity-ide"],
        rules="@root/GEMINI.md", skills=None, hooks=None, tiers=None, proxy="",
        notes="Reads ~/.gemini/GEMINI.md (shared with Gemini CLI: one block). No hooks or per-helper models."),
    "qwen": dict(
        label="Qwen Code", root=("QWEN_HOME", "~/.qwen"), bins=["qwen"], proof=["@root/settings.json"],
        rules="@root/QWEN.md", skills="shared", hooks="qwen", filter=False, usage="",
        tiers="qwen-grades", family="qwen-config", proxy="modelProviders[].baseUrl",
        notes="PostToolUse can only append context (no replace). No per-subagent effort (upstream: follow-up PRs)."),
    "opencode": dict(
        label="opencode", root=("", "~/.config/opencode"), bins=["opencode"],
        proof=["@root/opencode.json", "@root/opencode.jsonc"], rules="@root/AGENTS.md", skills="shared",
        hooks="opencode-plugin", filter=True, usage="plugin: message.updated tokens (V1 API)",
        tiers="opencode-agents", family="opencode-config", proxy="provider.<id>.options.baseURL",
        notes="One plugin file serves the V1 and V2 plugin APIs."),
    "hermes": dict(
        label="Hermes Agent", root=("HERMES_HOME", "~/.hermes"), bins=["hermes"], proof=["@root/config.yaml"],
        rules="@root/SOUL.md", policy="existing", cap=("chars", 20000, "CONTEXT_FILE_MAX_CHARS"),
        skills="@root/skills/frugal-bridge", hooks="hermes-plugin", filter=True, usage="plugin: every API request",
        tiers="hermes-backend", family="", proxy="model.base_url",
        notes="SOUL.md is the identity: never created. Plugins + delegation backend enabled by the user."),
    "openclaw": dict(
        label="OpenClaw", root=("OPENCLAW_STATE_DIR", "~/.openclaw"), bins=["openclaw"], proof=["@root/openclaw.json"],
        rules="@root/workspace/AGENTS.md", policy="existing", cap=("chars", 20000, "bootstrapMaxChars"),
        skills="shared", hooks=None, tiers="rules-openclaw", family="any", proxy="models.providers.<id>.baseUrl",
        notes="Workspace AGENTS.md is seeded by OpenClaw on first run. Plugin hooks exist (before_prompt_build, "
              "tool_result_persist, llm_output) but no Frugal plugin yet: rules + per-call model/thinking."),
    "grok": dict(
        label="Grok Build", root=("GROK_HOME", "~/.grok"), bins=["grok"], proof=["@root/config.toml"],
        rules="@root/rules/frugal-bridge.md", base_files=["@root/AGENTS.md", "@root/rules/skeleton-base.md"],
        skills="shared", hooks=None, tiers="grok-models", family="grok-config", proxy="[model.<id>] base_url",
        notes="Hooks: stdout of passive events is ignored (no context, no filter); Grok also runs Claude Code's "
              "hooks (harmless). xAI models are not in ROUTING.md: tiers only when the default is a mapped family."),
    "copilot": dict(
        label="GitHub Copilot CLI", root=("COPILOT_HOME", "~/.copilot"), bins=["copilot"],
        proof=["@root/settings.json", "@root/config.json"], rules="@root/copilot-instructions.md", skills="shared",
        hooks="copilot", filter=True, usage="none in hooks",
        tiers="copilot-agents", family="copilot-config", proxy="providers.json baseUrl (BYOK)",
        notes="Runs repo .claude/settings.json hooks too (once-guard). Under model 'auto' subagents always inherit."),
    "crush": dict(
        label="Crush", root=("", "~/.config/crush"), bins=["crush"], proof=["@root/crushrc", "@root/crush.json"],
        rules="@root/CRUSH.md", reads=["~/.config/AGENTS.md"], skills="shared", hooks="crush", filter=True,
        usage="", tiers=None, proxy="provider add --base-url",
        notes="SessionStart is observe-only (no context); the task subagent is hard-wired to the large model: no "
              "per-helper tier."),
    "goose": dict(
        label="Goose", root=("", "~/.config/goose"), bins=["goose"], proof=["@root/config.yaml"],
        rules="@root/.goosehints", skills="shared", hooks=None, tiers="goose-recipes", family="goose-config",
        proxy="OPENAI_HOST / ANTHROPIC_HOST",
        notes="Hooks live only in plugins (~/.agents/plugins, shared) and are observe-only: none built. Tiers = recipes "
              "with settings.goose_model (GOOSE_RECIPE_PATH may be needed); no per-helper effort."),
    "amp": dict(
        label="Amp", root=("", "~/.config/amp"), bins=["amp"], proof=["@root/settings.json"],
        rules="@root/AGENTS.md", reads=["~/.config/AGENTS.md"], skills="shared", hooks="amp-plugin", filter=True,
        usage="", tiers=None, proxy="Model Routing custom URL (UI)",
        notes="Subagents run the thread's model and effort: no per-helper tier."),
    "aider": dict(
        label="Aider", root=("", "~"), bins=["aider"], proof=["~/.aider.conf.yml"], rules="aider-read",
        skills=None, hooks=None, tiers=None, proxy="openai-api-base",
        notes="No auto rules file: Frugal's RULES.md is added to read: in ~/.aider.conf.yml (a repo config with its "
              "own read: replaces it). No hooks, no subagents (weak/editor model only)."),
    "kilo": dict(
        label="Kilo Code CLI", root=("", "~/.config/kilo"), bins=["kilo", "kilocode"],
        proof=["@root/kilo.jsonc", "@root/kilo.json"], rules="@root/AGENTS.md", reads=["@claude/CLAUDE.md"],
        skills="shared", hooks="kilo-plugin", filter=True, usage="plugin: message.updated tokens",
        tiers="kilo-agents", family="kilo-config", proxy="provider.<id>.options.baseURL",
        notes="Falls back to ~/.claude/CLAUDE.md: with Claude Code present it loads the block from there."),
    "droid": dict(
        label="Factory Droid", root=("", "~/.factory"), bins=["droid"], proof=["@root/settings.json"],
        rules="@root/AGENTS.md", reads=["~/.agents/AGENTS.md", "~/.agent/AGENTS.md"],
        cap=("chars", 80000, "initial AGENTS.md load"), skills="@root/skills", hooks="droid", filter=False,
        usage="", tiers="droid-agents", family="droid-config", proxy="customModels[].baseUrl",
        notes="Output replacement in PostToolUse is not documented: no filter."),
    "warp": dict(
        label="Warp Agent CLI", root=("", "~/.config/warp-terminal"), bins=["warp", "warp-terminal"],
        proof=["@root/cli/settings.toml"], rules="~/.agents/AGENTS.md", skills="shared", hooks=None, tiers=None,
        proxy="custom inference endpoint (UI)",
        notes="The app's global rules are in Warp Drive (cloud, not a file). No hooks; cloud orchestration only."),
    # ---- IDEs / apps with local files
    "cursor": dict(
        label="Cursor (editor + cursor-agent)", root=("CURSOR_CONFIG_DIR", "~/.cursor"), bins=["cursor-agent", "cursor"],
        proof=["@root/cli-config.json", "@root/hooks.json"], rules=None, skills="shared", hooks="cursor",
        filter=False, usage="preCompact context tokens", tiers="cursor-agents", family="cursor-config", proxy="",
        notes="User Rules are app settings, not a file: the rules come with the sessionStart hook. postToolUse can "
              "replace MCP output only. Runs Claude Code hooks by default (stands down)."),
    "devin": dict(
        label="Devin Desktop / Devin CLI (ex-Windsurf)", root=("", "~/.config/devin"), bins=["devin"],
        proof=["@root/config.json"], rules="@root/AGENTS.md", base_files=["~/.devin/global_rules.md"],
        reads=["@claude/CLAUDE.md"], skills="shared", hooks="devin", filter=False, usage="",
        tiers="devin-agents", family="anthropic", proxy="",
        notes="Reads ~/.claude/CLAUDE.md, settings.json hooks, skills by default (read_config_from.claude). No "
              "per-helper effort; only Cognition-hosted models."),
    "kiro": dict(
        label="Kiro (IDE + kiro-cli)", root=("", "~/.kiro"), bins=["kiro-cli", "kiro"],
        proof=["@root/settings/cli.json", "@root/settings/mcp.json"], rules="@root/steering/frugal-bridge.md",
        base_files=["@root/steering/skeleton-base.md"], skills="@root/skills", hooks="kiro", filter=False,
        usage="", tiers="kiro-agents", family="anthropic", proxy="",
        notes="Global hooks load in kiro-cli V3 only. PostToolUse cannot rewrite output. No per-agent effort."),
    "cline": dict(
        label="Cline (CLI / Desktop / extension)", root=("", "~/.cline"), bins=["cline"],
        proof=["@root/data/settings/global-settings.json", "@root/data/settings/providers.json"],
        rules="@root/rules/frugal-bridge.md", reads=["~/.agents/AGENTS.md"], skills="shared", hooks="cline",
        filter=False, usage="", tiers=None, proxy="OpenAI-compatible base URL",
        notes="spawn_agent takes only a prompt and task: no per-helper model. Hooks must be enabled in VS Code."),
    "continue": dict(
        label="Continue (cn CLI + IDE)", root=("CONTINUE_GLOBAL_DIR", "~/.continue"), bins=["cn"],
        proof=["@root/config.yaml"], rules="@root/rules/frugal-bridge.md", skills=None, hooks="continue",
        filter=False, usage="", tiers=None, proxy="models[].apiBase",
        notes="Subagents are config.yaml model entries (need the user's provider + key): not written. cn runs "
              "~/.claude/settings.json hooks."),
    "zed": dict(
        label="Zed agent", root=("", "~/.config/zed"), bins=["zed", "zeditor"], proof=["@root/settings.json"],
        rules="@root/AGENTS.md", skills="shared", hooks=None, tiers="rules-zed", family="any",
        proxy="api_url (custom provider)",
        notes="No agent hooks. spawn_agent can request a model; effort is one global agent.subagent_model.effort."),
    "junie": dict(
        label="JetBrains Junie CLI", root=("JUNIE_HOME", "~/.junie"), bins=["junie"],
        proof=["@root/config.json", "@root/settings.json"], rules="@root/AGENTS.md", skills="shared",
        hooks="junie", filter=True, usage="", tiers="junie-agents", family="anthropic",
        proxy="models/*.json baseUrl",
        notes="No pre-compact event; project hooks are ignored by default (user-level only)."),
}

# documented only: no local file Frugal can write, or the product is gone
NOT_INSTALLABLE = {
    "roo-code": "Roo Code: shut down 2026-05-15 (repo archived). Not integrated; ~/.roo/rules/ would still be read.",
    "claude-app": "Claude app / Claude Desktop: rules and memory are account settings (paste the block into "
                  "'Instructions for Claude'); only claude_desktop_config.json (MCP) is local.",
    "claude-duet": "Claude Duet: phone app + cloud computer, Opus 5.5 fixed, no local files.",
    "chatgpt-desktop": "ChatGPT desktop app: its Codex side reads ~/.codex (covered by the codex row); the ChatGPT "
                       "side keeps instructions server-side.",
    "warp-app": "Warp app global rules: Warp Drive (cloud), edit with /add-rule.",
}


# ---------------------------------------------------------------- paths
def root(t):
    env, default = H[t]["root"]
    r = os.environ.get(env) if env else None
    return os.path.abspath(os.path.expanduser(r or default))


def expand(t, p):
    if p is None:
        return None
    if p.startswith("@root/"):
        return os.path.join(root(t), p[6:])
    if p.startswith("@claude/"):
        return os.path.join(root("claude-code"), p[8:])
    return os.path.abspath(os.path.expanduser(p))


def installed(t):
    h = H[t]
    if any(shutil.which(b) for b in h["bins"]):
        return True
    return any(os.path.exists(expand(t, p)) for p in h.get("proof") or [])


def rules_candidates():
    """Every user-level rules file of every tool (where a base block may be found)."""
    out = []
    for t, h in H.items():
        for p in [h.get("rules")] + list(h.get("base_files") or []):
            if p and p != "aider-read":
                out.append(expand(t, p))
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- tiers
def load_tiers(kit):
    p = os.path.join(os.path.dirname(kit), "adapter", "plugin", "frugal-tiers", "tiers.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["tiers"]


ALIAS = (("haiku", "haiku"), ("sonnet", "sonnet"), ("opus", "opus"))


def tier_plan(table, family):
    """[(agent name, tier, model id, model name, effort)] for a family; tiers the table lacks are left out."""
    out = []
    for suffix, tier, eff in TIER_AGENTS:
        row = table.get(tier) or {}
        e = row.get(family)
        if not isinstance(e, dict) or not e.get("id"):
            continue
        effort = eff or e.get("effort") or row.get("effort") or "medium"
        assert effort in ALLOWED_EFFORT, effort
        out.append((f"frugal-{suffix}", tier, e["id"], e.get("name", e["id"]), effort))
    return out


def claude_alias(model_id):
    m = model_id.lower()
    return next((a for k, a in ALIAS if k in m), model_id)


GUESS = (("claude", "anthropic"), ("gpt-", "openai"), ("o3", "openai"), ("o4", "openai"), ("gemini", "google"))


def guess_family(model):
    m = (model or "").lower().split("/")[-1]
    v = (model or "").lower().split("/")[0] if "/" in (model or "") else ""
    if v in ("anthropic", "openai", "google"):
        return v
    return next((f for k, f in GUESS if m.startswith(k)), None)


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except (OSError, TypeError):
        return None


def has_comments(text):
    return strip_jsonc(text or "", commas=False) != (text or "")


def strip_jsonc(text, commas=True):
    """JSONC -> JSON text: drop // and /* */ comments outside strings, and trailing commas."""
    out, i, n, s = [], 0, len(text), None
    while i < n:
        c = text[i]
        if s:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == s:
                s = None
            i += 1; continue
        if c == '"':
            s = c; out.append(c); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i); i = n if j < 0 else j; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        out.append(c); i += 1
    out = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", out) if commas else out


def load_jsonish(p):
    t = _read(p)
    if not t or not t.strip():
        return {}
    try:
        v = json.loads(strip_jsonc(t))
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def toml_value(text, table, key):
    """A string value from a simple TOML file ('' table = top level)."""
    cur = ""
    for line in (text or "").splitlines():
        s = line.strip()
        m = re.match(r"^\[([^\]]+)\]", s)
        if m:
            cur = m.group(1).strip(); continue
        m = re.match(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', s)
        if m and cur == table:
            return m.group(1)
    return None


def yaml_top(text, key):
    for line in (text or "").splitlines():
        m = re.match(rf"^{re.escape(key)}:\s*['\"]?([^'\"#\n]+?)['\"]?\s*(#.*)?$", line)
        if m:
            return m.group(1).strip()
    return None


def tool_family(t):
    """(family, provider prefix or '', main model) for the tool's configured provider; family None = not mapped."""
    h = H[t]
    f = h.get("family") or ""
    if f in ("anthropic", "google", "openai"):
        return f, "", ""
    if f == "codex-config":
        txt = _read(expand(t, "@root/config.toml"))
        model, prov = toml_value(txt, "", "model") or "", toml_value(txt, "", "model_provider") or ""
        if not model and prov in ("", "openai"):
            return "openai", "", ""
        return guess_family(model), "", model
    if f in ("opencode-config", "kilo-config"):
        cfg = {}
        for n in ("opencode.jsonc", "opencode.json") if t == "opencode" else ("kilo.jsonc", "kilo.json"):
            cfg = cfg or load_jsonish(os.path.join(root(t), n))
        model = cfg.get("model") if isinstance(cfg.get("model"), str) else ""
        if "/" not in model:
            return None, "", model
        prov, mid = model.split("/", 1)
        return guess_family(mid), prov, model
    if f == "qwen-config":
        m = (load_jsonish(expand(t, "@root/settings.json")).get("model") or {})
        model = m.get("name", "") if isinstance(m, dict) else ""
        return guess_family(model), "", model
    if f in ("copilot-config", "cursor-config", "droid-config"):
        p = {"copilot-config": "@root/settings.json", "cursor-config": "@root/cli-config.json",
             "droid-config": "@root/settings.json"}[f]
        model = load_jsonish(expand(t, p)).get("model")
        model = model if isinstance(model, str) else (model or {}).get("modelId", "") if isinstance(model, dict) else ""
        return (guess_family(model) if model and model != "auto" else "anthropic"), "", model
    if f == "grok-config":
        model = toml_value(_read(expand(t, "@root/config.toml")), "models", "default") or ""
        return guess_family(model), "", model
    if f == "goose-config":
        txt = _read(expand(t, "@root/config.yaml"))
        prov = yaml_top(txt, "GOOSE_PROVIDER") or yaml_top(txt, "active_provider") or ""
        model = yaml_top(txt, "GOOSE_MODEL") or ""
        fam = {"anthropic": "anthropic", "openai": "openai", "google": "google", "gemini": "google"}.get(prov)
        if prov == "openrouter":
            fam = guess_family(model)
        return fam, prov, model
    if f == "any":
        return "any", "", ""
    return None, "", ""


def model_for(t, family, prov, entry_id):
    """The model value a tool's own setting takes for a table entry."""
    if t == "claude-code":
        # the exact model (Anthropic id form), not the family alias: Claude Code's `haiku` alias can run an older
        # Haiku than the table's cheap model (real run: alias -> claude-haiku-4-5, table -> claude-haiku-5.5)
        return entry_id.replace(".", "-")
    if t == "junie" and family == "anthropic":
        return claude_alias(entry_id)          # Junie's docs use the aliases (model: "sonnet")
    if t in ("opencode", "kilo"):
        if prov == "anthropic":
            return f"anthropic/{entry_id.replace('.', '-')}"
        if prov in ("openrouter", "kilo", "vercel", "requesty"):
            return f"{prov}/{family}/{entry_id}"
        return f"{prov}/{entry_id}"
    if t == "goose" and prov == "anthropic":
        return entry_id.replace(".", "-")
    if t == "goose" and prov == "openrouter":
        return f"{family}/{entry_id}"
    return entry_id


GEMINI_LEVEL = {"medium": "MEDIUM", "high": "HIGH"}


# ---------------------------------------------------------------- what each tool gets (pure: text in, text out)
HOOK_TAG = "# frugal-bridge-hook"
TIER_USE = {"cheap": "checkable work (code with tests, exact answers, extraction, formatting, lookups)",
            "mid": "data memos, partner thinking", "mid-writing": "public English writing",
            "top": "decisions, plans, architecture, hard languages"}
HELPER_BRIEF = ("You are a Frugal-Bridge helper on the {tier} tier. Do exactly what the brief asks, nothing more. "
                "Write the full result to the path the brief names and reply with a summary of at most 10 lines "
                "plus what you checked.")


def hook_cmd(script, tool, event=None):
    ev = f" --event {event}" if event else ""
    return f'python3 "{script}" --tool {tool}{ev} {HOOK_TAG}'


def is_ours_hook(group):
    s = json.dumps(group)
    return HOOK_TAG in s or ".frugal-bridge/frugal_hook.py" in s or bool(re.search(r'frugal_hook\.py\\?"?(\s|$|\\\\|")', s))


def hook_spec(t, script, has_claude_hooks):
    """(config path, format, {event: [entries]}, extra top-level sets) for tools whose hooks live in a shared
    config file; ('file', path, text) for tools with a hooks file of their own; None = no hooks / not here."""
    c = lambda ev=None: hook_cmd(script, t, ev)
    cmd = lambda ev=None: {"type": "command", "command": c(ev)}
    g = lambda ev=None, matcher=None, **kw: dict(({"matcher": matcher} if matcher else {}), hooks=[dict(cmd(ev), **kw)])
    k = H[t].get("hooks")
    if k == "claude":
        return ("json", expand(t, "@root/settings.json"), {
            "SessionStart": [g("start")], "UserPromptSubmit": [g("prompt")],
            "PostToolUse": [g("post_tool", "Bash")], "Stop": [g("usage")]}, [])
    if k == "codex":
        return ("json", expand(t, "@root/hooks.json"), {
            "SessionStart": [g("start", "startup|resume|clear|compact")], "UserPromptSubmit": [g("prompt")],
            "PostToolUse": [g("post_tool", "Bash")], "PostModelRequest": [g("usage")]}, [])
    if k == "gemini":
        n = {"name": "frugal-bridge"}
        return ("jsonc", expand(t, "@root/settings.json"), {
            "SessionStart": [g("start", **n)], "BeforeAgent": [g("prompt", **n)],
            "AfterTool": [g("post_tool", "run_shell_command", **n)]}, [])
    if k == "qwen":
        return ("jsonc", expand(t, "@root/settings.json"), {"SessionStart": [g("start")],
                                                          "UserPromptSubmit": [g("prompt")]}, [])
    if k == "junie":
        return ("json", expand(t, "@root/config.json"), {
            "SessionStart": [g("start")], "UserPromptSubmit": [g("prompt")], "PostToolUse": [g("post_tool", "Bash")]}, [])
    if k == "droid":
        return ("jsonc", expand(t, "@root/settings.json"), {
            "SessionStart": [g("start")], "UserPromptSubmit": [g("prompt")], "Stop": [g("usage")]}, [])
    if k in ("devin", "continue"):
        if has_claude_hooks:
            return ("via", "claude-code")      # it runs ~/.claude/settings.json hooks by default
        p = expand(t, "@root/config.json" if k == "devin" else "@root/settings.json")
        return ("jsonc" if k == "devin" else "json", p, {"SessionStart": [g("start")],
                                                         "UserPromptSubmit": [g("prompt")]}, [])
    if k == "cursor":
        return ("json", expand(t, "@root/hooks.json"), {
            "sessionStart": [{"command": c("start")}], "preCompact": [{"command": c("precompact")}]},
            [(("version",), 1)])
    if k == "copilot":
        e = lambda ev: {"type": "command", "bash": c(ev), "timeoutSec": 15}
        return ("file", expand(t, "@root/hooks/frugal-bridge.json"), json.dumps(
            {"version": 1, "hooks": {"sessionStart": [e("start")], "postToolUse": [e("post_tool")]}}, indent=2) + "\n")
    if k == "kiro":
        e = lambda name, trig, ev: {"name": name, "trigger": trig, "action": {"type": "command", "command": c(ev)},
                                    "timeout": 15}
        return ("file", expand(t, "@root/hooks/frugal-bridge.json"), json.dumps(
            {"version": "v1", "hooks": [e("frugal-bridge start files", "SessionStart", "start"),
                                        e("frugal-bridge context watch", "UserPromptSubmit", "prompt")]},
            indent=2) + "\n")
    if k == "cline":
        return ("file", expand(t, "@root/hooks/TaskStart"),
                f"#!/bin/sh\n{HOOK_TAG}\nexec {c('start').replace(' ' + HOOK_TAG, '')}\n")
    if k == "crush":
        return ("lines", expand(t, "@root/crushrc"), [
            f"hook add PostToolUse --matcher '^bash$' --command '{c('post_tool').replace(' ' + HOOK_TAG, '')}' "
            f"--name frugal-bridge-filter --timeout 15  {LINE_TAG}"], [])
    return None


PLUGIN_JS = {"opencode-plugin": ("frugal-bridge.js", "@root/plugins/frugal-bridge.js"),
             "kilo-plugin": ("frugal-bridge.js", "@root/plugin/frugal-bridge.js"),
             "amp-plugin": ("amp.js", "@root/plugins/frugal-bridge.js")}


def plugin_js(t, kit_root, script, fhome):
    k = H[t].get("hooks")
    if k not in PLUGIN_JS:
        return None
    src, dst = PLUGIN_JS[k]
    body = _read(os.path.join(kit_root, "adapter", "plugin-js", src))
    body = body.replace("__FRUGAL_HOOK__", script).replace("__FRUGAL_HOME__", fhome).replace("__FRUGAL_TOOL__", t)
    return expand(t, dst), body


def _fm(d):
    """YAML frontmatter (values quoted with JSON rules, valid YAML)."""
    return "---\n" + "".join(f"{k}: {json.dumps(v)}\n" for k, v in d.items() if v is not None) + "---\n"


def tier_files(t, table):
    """What setup writes for this tool's helper tiers: (files {path: text}, config changes, summary rows, note).
    rows = [(agent, model value, effort written or None, effort how)]."""
    kind = H[t].get("tiers")
    fam, prov, main = tool_family(t)
    if kind in (None, "hermes-backend") or kind.startswith("rules-"):
        return {}, [], [], None
    if not fam or fam == "any":
        return {}, [], [], f"no tier mapping: configured model '{main or 'unknown'}' is not in ROUTING.md families"
    if t in ("opencode", "kilo") and not prov:
        return {}, [], [], "no tier mapping: set a provider/model in the tool's config first"
    plan = tier_plan(table, fam)
    files, changes, rows = {}, [], []
    no_effort = kind in ("kiro-agents", "devin-agents", "qwen-grades", "goose-recipes", "grok-models")
    for name, tier, mid, mname, effort in plan:
        if no_effort and name == "frugal-mid-writing":
            continue                                       # same model as mid and no effort setting: no extra agent
        m = model_for(t, fam, prov, mid)
        desc = f"Frugal-Bridge {tier} tier ({mname}, effort {effort}): {TIER_USE[name[7:]]}."
        brief = HELPER_BRIEF.format(tier=name[7:])
        if kind == "claude-agents":
            files[expand(t, f"@root/agents/{name}.md")] = _fm(dict(name=name, description=desc, model=m, effort=effort)) + "\n" + brief + "\n"
            rows.append((name, m, effort, "effort"))
        elif kind == "codex-agents":
            files[expand(t, f"@root/agents/{name}.toml")] = (
                f"name = {json.dumps(name)}\ndescription = {json.dumps(desc)}\n"
                f"developer_instructions = {json.dumps(brief)}\nmodel = {json.dumps(m)}\n"
                f"model_reasoning_effort = {json.dumps(effort)}\n")
            rows.append((name, m, effort, "model_reasoning_effort"))
        elif kind == "cursor-agents":
            files[expand(t, f"@root/agents/{name}.md")] = _fm(dict(name=name, description=desc, model=f"{m}[effort={effort}]")) + "\n" + brief + "\n"
            rows.append((name, f"{m}[effort={effort}]", effort, "model:id[effort=..]"))
        elif kind == "droid-agents":
            files[expand(t, f"@root/droids/{name}.md")] = _fm(dict(name=name, description=desc, model=m, reasoningEffort=effort)) + "\n" + brief + "\n"
            rows.append((name, m, effort, "reasoningEffort"))
        elif kind == "opencode-agents":
            v = m + (f"#{effort}" if effort != "medium" else "")     # medium = the model's default variant
            files[expand(t, f"@root/agents/{name}.md")] = _fm(dict(description=desc, mode="subagent", model=v)) + "\n" + brief + "\n"
            rows.append((name, v, effort, "#variant (medium = default, no variant)"))
        elif kind == "kilo-agents":
            files[expand(t, f"@root/agents/{name}.md")] = _fm(dict(description=desc, mode="subagent", model=m, reasoningEffort=effort)) + "\n" + brief + "\n"
            rows.append((name, m, effort, "reasoningEffort"))
        elif kind == "junie-agents":
            files[expand(t, f"@root/agents/{name}.md")] = _fm(dict(name=name, description=desc, model=m, reasoningLevel=effort)) + "\n" + brief + "\n"
            rows.append((name, m, effort, "reasoningLevel"))
        elif kind == "gemini-agents":
            files[expand(t, f"@root/agents/{name}.md")] = _fm(dict(name=name, description=desc, kind="local", model=m)) + "\n" + brief + "\n"
            changes.append(("append", ("modelConfigs", "overrides"), {"match": {"overrideScope": name}, "modelConfig": {
                "generateContentConfig": {"thinkingConfig": {"thinkingLevel": GEMINI_LEVEL[effort]}}}}))
            rows.append((name, m, effort, "modelConfigs.overrides thinkingLevel " + GEMINI_LEVEL[effort]))
        elif kind == "copilot-agents":
            files[expand(t, f"@root/agents/{name}.agent.md")] = _fm(dict(name=name, description=desc, model=m)) + "\n" + brief + "\n"
            changes.append(("set", ("subagents", "agents", name), {"model": m, "effortLevel": effort}))
            rows.append((name, m, effort, "subagents.agents.<name>.effortLevel"))
        elif kind == "kiro-agents":
            files[expand(t, f"@root/agents/{name}.json")] = json.dumps(dict(
                name=name, description=desc, prompt=brief, model=m,
                resources=["file://~/.kiro/steering/**/*.md"]), indent=2) + "\n"
            rows.append((name, m, None, "no per-agent effort in Kiro"))
        elif kind == "devin-agents":
            files[expand(t, f"@root/agents/{name}.md")] = _fm(dict(name=name, description=desc, model=m)) + "\n" + brief + "\n"
            rows.append((name, m, None, "no per-subagent effort in Devin"))
        elif kind == "qwen-grades":
            changes.append(("set", ("agents", "modelGrades", name), m))
            rows.append((name, m, None, "no per-subagent effort in Qwen"))
        elif kind == "goose-recipes":
            files[expand(t, f"@root/recipes/{name}.yaml")] = (
                f"version: 1.0.0\ntitle: {name}\ndescription: {json.dumps(desc)}\ninstructions: {json.dumps(brief)}\n"
                f"settings:\n  goose_provider: {json.dumps(prov)}\n  goose_model: {json.dumps(m)}\n")
            rows.append((name, m, None, "no per-recipe effort in Goose"))
        elif kind == "grok-models":
            if name in ("frugal-cheap", "frugal-top"):
                sub = "explore" if name == "frugal-cheap" else "plan"
                changes.append(("toml", ("subagents.models", sub), m))
                rows.append((sub, m, None, "built-in subagent -> model; effort not settable per subagent"))
    return files, changes, rows, None


def tier_rules(t, table, rows):
    """The tool-specific 'Helper tiers' paragraph appended to the rules block."""
    kind = H[t].get("tiers")
    label = H[t]["label"]
    if kind == "hermes-backend":
        return ("## Helper tiers here\nOn `delegate_task` set `tier` (cheap / mid / top) and `effort` (medium; high for "
                "public English writing or a retry after a failed check) when the frugal-tiers backend is on.")
    if kind in ("rules-openclaw", "rules-zed"):
        lines = []
        for fam in ("anthropic", "openai", "google"):
            p = tier_plan(table, fam)
            if not p:
                continue
            if kind == "rules-openclaw":
                lines.append(f"- {fam}: " + "; ".join(f"{n[7:]} = model `{mid}`, thinking `{e}`" for n, _, mid, _, e in p))
            else:
                lines.append(f"- {fam}: " + "; ".join(f"{n[7:]} = `{mid}`" for n, _, mid, _, e in p))
        call = ("`sessions_spawn`: pass `model` and `thinking` for the tier (your provider's row):" if kind == "rules-openclaw"
                else "`spawn_agent`: request the tier's model (your provider's row); effort is not per helper here:")
        return "## Helper tiers here\n" + call + "\n" + "\n".join(lines)
    if not rows:
        return ("## Helper tiers here\nNo per-helper model or effort in this tool: helpers run on your model and effort; "
                "say so when it matters.")
    if kind == "grok-models":
        return ("## Helper tiers here\nBuilt-in subagents are mapped: " + ", ".join(f"`{n}` = {m}" for n, m, _, _ in rows)
                + " (explore = checkable look-ups, plan = decisions). Other helpers run on your model.")
    if kind == "qwen-grades":
        return ("## Helper tiers here\nOn the Agent tool pass `model:` = the tier's grade: " +
                ", ".join(f"`{n}` ({m})" for n, m, _, _ in rows) + ". Effort is not per helper here (public writing: "
                "ask for extra care in the brief).")
    use = "; ".join(f"`{n}` = {m}" + (f", effort {e}" if e else "") for n, m, e, _ in rows)
    extra = ""
    if kind == "claude-agents":
        extra = (" (prefer the subagent: the Agent tool's `model: haiku / sonnet / opus` alias can pick an older "
                 "model)")
    if kind == "goose-recipes":
        extra = " (use the recipe by name)"
    tail = "" if any(e for _, _, e, _ in rows) else " Effort is not per helper here."
    writing = " `frugal-mid-writing` = public English writing." if any(n == "frugal-mid-writing" for n, *_ in rows) else ""
    return (f"## Helper tiers here\nSend each helper to the subagent of its tier{extra}: {use}.{writing}{tail} "
            "A tier missing here: the helper runs on your model; say so.")


# ---------------------------------------------------------------- config writers (text in, text out)
def _get(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set(d, path, v):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = v


def _detect_indent(text):
    m = re.search(r"\n([ \t]+)\"", text or "")
    return len(m.group(1)) if m and m.group(1).strip() == "" and " " in m.group(1) else 2


def json_apply(text, hooks, changes):
    """Merge Frugal's hooks and keys into a JSON / JSONC settings text. Returns (new text, notes, made) where made =
    key paths that did not exist before (removed again on uninstall when empty). Comments: only keys absent at the
    top level can be added (inserted as text); anything else is reported, not written."""
    notes, made = [], []
    raw = text if text and text.strip() else "{}"
    plain = strip_jsonc(raw)
    try:
        data = json.loads(plain)
    except ValueError:
        return None, ["not valid JSON; fix it by hand first (nothing changed)"], []
    if not isinstance(data, dict):
        return None, ["not a JSON object (nothing changed)"], []
    new = json.loads(json.dumps(data))
    for path, v in [c[1:] for c in changes if c[0] == "set"]:
        cur = _get(new, path)
        if cur is not None and cur != v:
            notes.append(f"{'.'.join(path)} already set by you: left as is")
            continue
        for i in range(1, len(path) + 1):
            if _get(new, path[:i]) is None:
                made.append(list(path[:i])); break
        _set(new, path, v)
    for path, item in [c[1:] for c in changes if c[0] == "append"]:
        lst = _get(new, path)
        if lst is None:
            for i in range(1, len(path) + 1):
                if _get(new, path[:i]) is None:
                    made.append(list(path[:i])); break
            _set(new, path, []); lst = _get(new, path)
        if not isinstance(lst, list):
            notes.append(f"{'.'.join(path)} is not a list: left as is"); continue
        if item not in lst:
            lst.append(item)
    if hooks:
        if "hooks" not in new:
            made.append(["hooks"])
        hk = new.setdefault("hooks", {})
        for ev, entries in hooks.items():
            if ev not in hk:
                made.append(["hooks", ev])
            lst = hk.setdefault(ev, [])
            lst[:] = [x for x in lst if not (isinstance(x, dict) and is_ours_hook(x))] + entries
    if new == data:
        return raw if text and text.strip() else text, notes, made
    if has_comments(raw):   # comments: textual insert of new top-level keys only
        added = [k for k in new if k not in data]
        changed = [k for k in data if new.get(k) != data[k]]
        if changed:
            return text, notes + [f"has comments and {', '.join(changed)} exists: add Frugal's part by hand"], []
        i = raw.index("{") + 1
        ind = " " * _detect_indent(raw)
        body = ",\n".join(f"{ind}{json.dumps(k)}: " + json.dumps(new[k], indent=len(ind)).replace("\n", "\n" + ind)
                          for k in added)
        rest = raw[i:]
        sep = "," if data else ""
        return raw[:i] + "\n" + body + sep + ("" if rest.startswith("\n") else "\n") + rest, notes, made
    return json.dumps(new, indent=_detect_indent(raw), ensure_ascii=False) + "\n", notes, made


def json_remove(text, hooks, changes, made):
    """Take Frugal's hooks and keys out again (only values still equal to ours); drop containers we made that are
    empty now. Returns the new text, or None when the text is not JSON any more."""
    try:
        data = json.loads(strip_jsonc(text or "{}"))
    except ValueError:
        return None
    for path, v in [c[1:] for c in changes if c[0] == "set"]:
        if _get(data, path) == v:
            parent = _get(data, path[:-1]) if len(path) > 1 else data
            parent.pop(path[-1], None)
    for path, item in [c[1:] for c in changes if c[0] == "append"]:
        lst = _get(data, path)
        if isinstance(lst, list) and item in lst:
            lst.remove(item)
    if hooks and isinstance(data.get("hooks"), dict):
        for ev in list(data["hooks"]):
            lst = data["hooks"][ev]
            if isinstance(lst, list):
                keep = [x for x in lst if not (isinstance(x, dict) and is_ours_hook(x))]
                if keep or len(keep) == len(lst):
                    data["hooks"][ev] = keep
                else:
                    del data["hooks"][ev]          # only Frugal's entries were in it
        if not data["hooks"]:
            del data["hooks"]
    for path in sorted(made, key=len, reverse=True):
        v = _get(data, path)
        if v in ({}, []):
            parent = _get(data, path[:-1]) if len(path) > 1 else data
            parent.pop(path[-1], None)
    return data


def lines_apply(text, lines):
    t = text or ""
    have = set(t.splitlines())
    add = [l for l in lines if l not in have]
    old = [l for l in t.splitlines() if l.rstrip().endswith(LINE_TAG) and l not in lines]
    if old:
        t = "".join(l + "\n" for l in t.splitlines() if l not in old)
    if not add:
        return t
    if t and not t.endswith("\n"):
        t += "\n"
    return t + "".join(l + "\n" for l in add)


def lines_remove(text):
    return "".join(l + "\n" for l in (text or "").splitlines() if not l.rstrip().endswith(LINE_TAG))


def toml_apply(text, sets):
    """sets = [(table, key, value)]: add `key = "value"  # frugal-bridge` under [table] (header added, tagged, when
    missing). A key the user already set is left alone (note)."""
    lines, notes = (text or "").splitlines(), []
    for table, key, val in sets:
        line = f"{key} = {json.dumps(val)}  {LINE_TAG}"
        hdr = next((i for i, l in enumerate(lines) if re.match(rf"^\[{re.escape(table)}\]\s*(#.*)?$", l.strip())), None)
        if hdr is None:
            if lines and lines[-1].strip():
                lines.append(f"{LINE_TAG} (spacer)")
            lines += [f"[{table}]  {LINE_TAG}", line]
            continue
        end = next((j for j in range(hdr + 1, len(lines)) if lines[j].strip().startswith("[")), len(lines))
        cur = [j for j in range(hdr + 1, end) if re.match(rf"^\s*{re.escape(key)}\s*=", lines[j])]
        if cur and not lines[cur[0]].rstrip().endswith(LINE_TAG):
            notes.append(f"[{table}] {key} already set by you: left as is"); continue
        if cur:
            lines[cur[0]] = line
        else:
            lines.insert(hdr + 1, line)
    return "".join(l + "\n" for l in lines), notes


def yaml_list_apply(text, key, item):
    """Add `- item  # frugal-bridge` to the top-level block list `key:` (key added, tagged, when missing)."""
    lines = (text or "").splitlines()
    entry = f"  - {json.dumps(item)}  {LINE_TAG}"
    if entry in lines:
        return "".join(l + "\n" for l in lines), []
    i = next((n for n, l in enumerate(lines) if re.match(rf"^{re.escape(key)}:", l)), None)
    if i is None:
        return "".join(l + "\n" for l in lines + [f"{key}:  {LINE_TAG}", entry]), []
    rest = lines[i].split(":", 1)[1].split("#")[0].strip()
    if rest:
        return None, [f"{key}: is written inline ({rest}); add {item} to it by hand"]
    lines.insert(i + 1, entry)
    return "".join(l + "\n" for l in lines), []
