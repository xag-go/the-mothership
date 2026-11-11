# The Frugal-Bridge adapter

**One adapter, for any agent, app or provider.** The rules (`kit/AGENTS.md`) already work everywhere; the adapter
makes the parts a prompt cannot guarantee happen automatically. `kit/setup.py` picks the way for you
(`--hosts auto`, the default): for each agent tool it finds, it uses the strongest mechanism that tool allows.

| What the tool allows | What the adapter uses | Enforced |
|---|---|---|
| Session / prompt hooks | `hooks/` (one small script) | context watch, start files |
| Plugins | `plugin/` | context watch, start files, big-output filter, usage report; model tier per helper (delegation backend) |
| A configurable API base URL (any provider) | `proxy/` (local, standard library only) | context watch, loop guard, output filter, start files, rules injection, usage report |
| None of these (chat apps) | — | the rules are pasted as project instructions: followed, not enforced |

The user never chooses: they ask their AI to "set up Frugal-Bridge" (`INSTALL.md`) or run `kit/setup.py install`.

## What it enforces
- **Context watch:** tracks each conversation's real size; past 150k tokens (100k on cheap models) it asks the agent,
  once, to offer the user a new session with a handoff / compact / carry on; at 300k it says it plainly. Notices go at
  the end of the turn, never the start, so the prompt cache stays valid.
- **Start files:** on a session's first turn, the agent reads the "now" and "user" files first, in one call. Paths
  come from the project's `.kits.json` `slots` (project folder + up to 3 parents) or its `PROGRESS.md` / `USER.md`;
  what is missing comes from the connected knowledge base's slots (found like `kit/setup.py` finds it: `FRUGAL_BASE`,
  the base recorded in `global.json`, the base block's `Path:` line in a tool's rules file, the pointer file
  `~/.config/skeleton-base/base`, the base's systemd units), else the one `~/.frugal-bridge/USER.md`. Resolved fresh
  every session, so a base connected or removed later is used without re-installing. A folder slot (e.g.
  `wiki/me/`) is listed as its `.md` files (sorted, at most 8). The same code is in all three mechanisms.
- **Output filter:** shell output over ~12k characters is cut to head + error lines + tail; the full text is saved to
  a file whose path is given (file reads are never cut).
- **Loop guard (proxy):** the same tool call with the same result twice, or two calls failing with the same error →
  one "stop and rethink" notice (free-text fields such as `description` ignored).
- **Usage report:** per model — calls, output, cache reads, ~cost, alerts (long sessions, > 300 calls).

## The three mechanisms
**`hooks/frugal_hook.py`** — one script for two events: session start and prompt submit (context size read from the
transcript). Setup merges it into the tool's JSON settings key by key: only entries pointing to this script are added,
replaced on re-run and removed on uninstall; your own hooks and keys are untouched. Our entries carry the
tag `# frugal-bridge-hook` (older entries are recognised by the script name), so a moved or renamed folder never
leaves duplicates; every hook Frugal writes for any tool follows this rule. Tools with no hook that rewrites
shell output rely on the `frugal-filter-output` skill for that rule. The same script serves every tool with
command hooks (`--tool <name> --event start|prompt|post_tool|usage|precompact`), answering in that tool's own fields;
`plugin-js/` holds the JavaScript plugins for opencode, Kilo and Amp (filter, start files, usage).

**`plugin/frugal-bridge/`** — hooks on API requests, on each turn and on terminal output, plus a `/frugal` command.
Setup copies it into the tool's plugin folder; enabling it restarts that tool's gateway, so it is left to the user
(e.g. Hermes Agent: `hermes plugins enable frugal-bridge`). Optional `<tool home>/frugal-bridge/config.json`:
`{"base_dir": "...", "ctx_warn": 150000, "ctx_hard": 300000, "ctx_warn_cheap": 100000, "out_limit": 12000}`
(`base_dir` is written by a project install only; without it the start files come from the knowledge base or
`~/.frugal-bridge/USER.md`).

Role file (who am I): the start notice adds the knowledge base's `agents/` file for the tool only when the hook or
plugin knows its host, exactly ONE role file lists that host in `engines:` (or the old `engine:`), and the host has
no own identity (a project `ROLE.md`, or an identity file such as Hermes `SOUL.md` with text outside the kits'
blocks). Zero or several matches, an own identity, or the proxy (host unknown): no role file. The main agent's
name is never taken from the user file.

**`proxy/frugal_proxy.py`** — sits between any tool and any provider. Run it, then point the tool's base URL at
`http://127.0.0.1:8790/<route>` (routes: `anthropic`, `openai`, `chatgpt`, `openrouter`, `gemini`, `xai`; more in
config). Keys pass through untouched; it stores none. Wire formats: Anthropic Messages, OpenAI Chat Completions,
OpenAI Responses; anything else passes through unchanged; any internal error forwards the original request.
`core_file` set → the rules are added to the system prompt once (skipped if a `frugal-bridge:start` block is there).
Config: `~/.config/frugal-bridge/proxy.json` (or `--config`); `dump_dir` = debug only. Limit: it cannot start a new
session itself. Examples — Anthropic-format tools: `ANTHROPIC_BASE_URL=http://127.0.0.1:8790/anthropic`;
OpenAI-compatible tools: base URL `http://127.0.0.1:8790/openai/v1` (or `/openrouter/v1`, `/gemini/v1beta/openai`);
a ChatGPT-login CLI (Codex): `-c model_provider=fb -c 'model_providers.fb={name="fb",base_url="http://127.0.0.1:8790/chatgpt",wire_api="responses",requires_openai_auth=true}'`.

## Every tool: what `install --global` sets up (the matrix)
The table lives in `kit/hosts.py` (one row per tool); `kit/test_hosts.py` runs every row in a fake home with fake
binaries. Rules for all rows:
- **Installed** = the tool's binary on PATH, or a config file only that tool writes. A shared folder alone is not
  proof (`~/.gemini` is also made by Antigravity IDE). `--hosts a,b` installs only those of the list that are
  installed (the others are reported as skipped); a tool installed earlier and gone now only gets its block refreshed.
- **One rules file per tool, loaded once.** The knowledge base's file when it holds a base block (Frugal's block goes
  after it), else the tool's own file; a dedicated file in a rules folder where the tool loads one (Grok, Kiro,
  Cline, Continue). A tool that already loads another installed tool's file (Kilo and Devin → `~/.claude/CLAUDE.md`;
  Droid and Cline → `~/.agents/AGENTS.md` when Warp has it) gets no second copy. `~/.config/AGENTS.md` (read by Crush
  AND Amp) is never written. Caps are checked: Codex 32 KiB (with the project file), Hermes 20,000 chars, OpenClaw
  20,000, Droid 80,000. Identity / seeded files (Hermes `SOUL.md`, OpenClaw workspace `AGENTS.md`) are never created.
- **Skills once:** `~/.agents/skills/` for every tool that reads it; Claude Code, Hermes, Kiro, Droid get their own.
- **Config files in their own format** (JSON, JSONC with comments kept, TOML, YAML, crushrc lines): only Frugal's
  keys / tagged lines are added; the text from before is recorded and given back byte for byte on uninstall when
  nothing else changed it, else only Frugal's part is taken out (a value you set is never overwritten).
- **Hooks run once per event.** Cursor, Grok, Devin, Continue `cn` (and Copilot with a repo `.claude/settings.json`)
  also run Claude Code's hooks: the hook script sees the calling tool (payload marks) and the Claude entry stands
  down when that tool has its own Frugal entry; a short-lived marker per event payload drops any second call.
- **Helper tiers = ROUTING.md / `tiers.json` as they are** (no new routing): cheap / mid / top, effort medium,
  `frugal-mid-writing` = mid model at effort high for public English writing, never low, no xhigh/max. Each tool gets
  the model id of its configured provider family (a family the table lacks = no tier, rules say so); effort goes in
  the tool's own per-subagent field, or the matrix says there is none.
- **Usage:** hooks and plugins append to `$FRUGAL_HOME/usage.jsonl` (same record as the Hermes plugin, plus `tool`);
  `python3 kit/setup.py report [days]` merges it with the Hermes plugin's and the proxy's logs.

| Tool | Rules loaded from | Hooks / plugin | Output filter | Helper tier → model | Effort per helper | Usage log | Proxy (custom base URL) | Notes |
|---|---|---|---|---|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | SessionStart, UserPromptSubmit, PostToolUse(Bash), Stop — `settings.json` | yes (updatedToolOutput) | `~/.claude/agents/frugal-{cheap,mid,mid-writing,top}.md` `model:` the table's exact id (`claude-haiku-5-5` …; the `haiku` alias ran an older Haiku in a real run) | `effort:` medium; mid-writing high | yes: Stop → transcript usage | ANTHROPIC_BASE_URL | Also read by Devin (Claude import on by default) and Kilo (fallback); Cursor, Grok, Devin and Continue cn run its hooks: the hook stands down / runs once. |
| Codex CLI (and the ChatGPT desktop app's Codex side) | `~/.codex/AGENTS.md` cap 32768 bytes | SessionStart, UserPromptSubmit, PostToolUse(Bash), PostModelRequest — `hooks.json` (trust in /hooks) | partial (block + reason replaces the result) | `~/.codex/agents/frugal-*.toml` `model` (OpenAI row) | `model_reasoning_effort` medium; mid-writing high; top high (tiers.json) | yes: PostModelRequest token_usage | model_providers.<id>.base_url | Hooks run only after the user trusts them in /hooks (by hash; re-trust after a change). Output filter = PostToolUse block+reason (the reason replaces the result; partial). |
| Gemini CLI | `~/.gemini/GEMINI.md` | SessionStart, BeforeAgent, AfterTool(run_shell_command) — `settings.json` | yes (AfterTool deny + reason) | `~/.gemini/agents/frugal-cheap/top.md` `model` (Google row has no mid) | `modelConfigs.overrides` thinkingLevel MEDIUM | proxy | GOOGLE_GEMINI_BASE_URL (env) | ~/.gemini is also made by Antigravity IDE: not proof. Subagents need experimental.enableAgents. |
| Antigravity IDE | `~/.gemini/GEMINI.md` | — | no | impossible | — | no | no | Reads ~/.gemini/GEMINI.md (shared with Gemini CLI: one block). No hooks or per-helper models. |
| Qwen Code | `~/.qwen/QWEN.md` | SessionStart, UserPromptSubmit — `settings.json` | no (append only) | `agents.modelGrades` frugal-cheap/mid/top (Agent tool `model:` = grade) | no (upstream: not yet) | proxy | modelProviders[].baseUrl | PostToolUse can only append context (no replace). No per-subagent effort (upstream: follow-up PRs). |
| opencode | `~/.config/opencode/AGENTS.md` | plugin `plugins/frugal-bridge.js` (V1 + V2 API) | yes (execute.after result) | `~/.config/opencode/agents/frugal-*.md` `model: provider/id` | `#high` variant on mid-writing; medium = default (no variant) | yes: plugin message.updated tokens | provider.<id>.options.baseURL | One plugin file serves the V1 and V2 plugin APIs. |
| Hermes Agent | `~/.hermes/SOUL.md` (existing only) cap 20000 chars | plugins frugal-bridge + frugal-tiers (user enables) | yes (transform_terminal_output) | frugal-tiers backend: `tier` + `effort` per delegate_task | per task (`effort`) | yes: plugin (every API request) | model.base_url | SOUL.md is the identity: never created. Plugins + delegation backend enabled by the user. |
| OpenClaw | `~/.openclaw/workspace/AGENTS.md` (existing only) cap 20000 chars | — | no | rules: `sessions_spawn` `model` per tier (per provider row) | rules: `thinking` medium/high | proxy | models.providers.<id>.baseUrl | Workspace AGENTS.md is seeded by OpenClaw on first run. Plugin hooks exist (before_prompt_build, tool_result_persist, llm_output) but no Frugal plugin yet: rules + per-call model/thinking. |
| Grok Build | `~/.grok/rules/frugal-bridge.md` | — | no | `[subagents.models]` explore = cheap, plan = top (only when the default is a mapped family; xAI is not in ROUTING.md) | no | proxy | [model.<id>] base_url | Hooks: stdout of passive events is ignored (no context, no filter); Grok also runs Claude Code's hooks (harmless). xAI models are not in ROUTING.md: tiers only when the default is a mapped family. |
| GitHub Copilot CLI | `~/.copilot/copilot-instructions.md` | sessionStart, postToolUse — `hooks/frugal-bridge.json` | yes (modifiedResult) | `~/.copilot/agents/frugal-*.agent.md` + `subagents.agents.<name>.model` | `subagents.agents.<name>.effortLevel` medium; mid-writing high | proxy | providers.json baseUrl (BYOK) | Runs repo .claude/settings.json hooks too (once-guard). Under model 'auto' subagents always inherit. |
| Crush | `~/.config/crush/CRUSH.md`; also reads `~/.config/AGENTS.md` → loads that one when it has the block | `hook add PostToolUse` line in `crushrc` | yes (updated_output) | impossible | — | proxy | provider add --base-url | SessionStart is observe-only (no context); the task subagent is hard-wired to the large model: no per-helper tier. |
| Goose | `~/.config/goose/.goosehints` | — | no | recipes `~/.config/goose/recipes/frugal-*.yaml` `settings.goose_model` | no | proxy | OPENAI_HOST / ANTHROPIC_HOST | Hooks live only in plugins (~/.agents/plugins, shared) and are observe-only: none built. Tiers = recipes with settings.goose_model (GOOSE_RECIPE_PATH may be needed); no per-helper effort. |
| Amp | `~/.config/amp/AGENTS.md`; also reads `~/.config/AGENTS.md` → loads that one when it has the block | plugin `plugins/frugal-bridge.js` | yes (tool.result) | impossible | — | proxy | Model Routing custom URL (UI) | Subagents run the thread's model and effort: no per-helper tier. |
| Aider | `read:` list in `~/.aider.conf.yml` → `RULES.md` | — | no | impossible | — | proxy | openai-api-base | No auto rules file: Frugal's RULES.md is added to read: in ~/.aider.conf.yml (a repo config with its own read: replaces it). No hooks, no subagents (weak/editor model only). |
| Kilo Code CLI | `~/.config/kilo/AGENTS.md`; also reads `~/.claude/CLAUDE.md` → loads that one when it has the block | plugin `plugin/frugal-bridge.js` (V1 API) | yes (output.output) | `~/.config/kilo/agents/frugal-*.md` `model: provider/id` | `reasoningEffort` medium; mid-writing high | yes: plugin message.updated tokens | provider.<id>.options.baseURL | Falls back to ~/.claude/CLAUDE.md: with Claude Code present it loads the block from there. |
| Factory Droid | `~/.factory/AGENTS.md` cap 80000 chars; also reads `~/.agents/AGENTS.md`, `~/.agent/AGENTS.md` → loads that one when it has the block | SessionStart, UserPromptSubmit, Stop — `settings.json` | no (not documented) | `~/.factory/droids/frugal-*.md` `model` | `reasoningEffort` medium; mid-writing high | if its transcript is Claude-style (Stop) | customModels[].baseUrl | Output replacement in PostToolUse is not documented: no filter. |
| Warp Agent CLI | `~/.agents/AGENTS.md` | — | no | impossible | — | proxy | custom inference endpoint (UI) | The app's global rules are in Warp Drive (cloud, not a file). No hooks; cloud orchestration only. |
| Cursor (editor + cursor-agent) | sessionStart hook brings `RULES.md` (no rules file) | sessionStart (rules + start files), preCompact — `hooks.json` | no (MCP output only) | `~/.cursor/agents/frugal-*.md` `model: id[effort=..]` | `[effort=medium]`; mid-writing `[effort=high]` | context only: preCompact | no | User Rules are app settings, not a file: the rules come with the sessionStart hook. postToolUse can replace MCP output only. Runs Claude Code hooks by default (stands down). |
| Devin Desktop / Devin CLI (ex-Windsurf) | `~/.config/devin/AGENTS.md`; also reads `~/.claude/CLAUDE.md` → loads that one when it has the block | via Claude Code's hooks (default import); own `config.json` hooks when Claude Code is absent | no (not documented) | `~/.config/devin/agents/frugal-*.md` `model` | no | no | no | Reads ~/.claude/CLAUDE.md, settings.json hooks, skills by default (read_config_from.claude). No per-helper effort; only Cognition-hosted models. |
| Kiro (IDE + kiro-cli) | `~/.kiro/steering/frugal-bridge.md` | SessionStart, UserPromptSubmit — `hooks/frugal-bridge.json` (kiro-cli V3) | no (cannot rewrite) | `~/.kiro/agents/frugal-*.json` `model` | no | no | no | Global hooks load in kiro-cli V3 only. PostToolUse cannot rewrite output. No per-agent effort. |
| Cline (CLI / Desktop / extension) | `~/.cline/rules/frugal-bridge.md`; also reads `~/.agents/AGENTS.md` → loads that one when it has the block | `hooks/TaskStart` (one file per event; skipped if yours exists) | no (context only) | impossible | — | proxy | OpenAI-compatible base URL | spawn_agent takes only a prompt and task: no per-helper model. Hooks must be enabled in VS Code. |
| Continue (cn CLI + IDE) | `~/.continue/rules/frugal-bridge.md` | via Claude Code's hooks (cn imports them); own `settings.json` when absent | no (unverified) | impossible | — | proxy | models[].apiBase | Subagents are config.yaml model entries (need the user's provider + key): not written. cn runs ~/.claude/settings.json hooks. |
| Zed agent | `~/.config/zed/AGENTS.md` | — | no | rules: `spawn_agent` requests the tier's model | no (one global `agent.subagent_model.effort`) | proxy | api_url (custom provider) | No agent hooks. spawn_agent can request a model; effort is one global agent.subagent_model.effort. |
| JetBrains Junie CLI | `~/.junie/AGENTS.md` | SessionStart, UserPromptSubmit, PostToolUse(Bash) — `config.json` | yes (updatedToolOutput) | `~/.junie/agents/frugal-*.md` `model` | `reasoningLevel` medium; mid-writing high | proxy | models/*.json baseUrl | No pre-compact event; project hooks are ignored by default (user-level only). |

**Not installable (documented only):** Roo Code (shut down 2026-05-15; `~/.roo/rules/` still read by old copies);
Claude app / Desktop (rules and memory are account settings — paste the block into *Instructions for Claude*; only
the MCP config is local); Claude Duet (phone + cloud, fixed model); ChatGPT desktop (its Codex side = the Codex row;
the ChatGPT side is server-side); Warp app global rules (Warp Drive, cloud).

**Impossible per tool (helper tiers):** Amp (subagents run the thread's model and effort), Crush (task agent
hard-wired to the large model), Aider (no subagents; only weak/editor models), Cline (`spawn_agent` takes a prompt and
task only), Warp (cloud orchestration only), Continue (a subagent is a config model entry that needs your provider
key: not written), Antigravity, cloud apps. **No per-helper effort:** Qwen, Kiro, Devin, Goose, Grok, Zed (one global
value). **No output filter:** Cursor (MCP output only), Qwen (append only), Kiro, Cline, Droid, Devin, Continue,
OpenClaw, Zed, Warp, Aider, Goose, Grok (passive-event stdout ignored).

**Sources** (fetched 2026-11-11, official docs or source): Claude Code `code.claude.com/docs` (hooks
`updatedToolOutput`, sub-agents `effort`); Codex `learn.chatgpt.com/docs` (hooks, PostModelRequest `token_usage`,
custom agents, AGENTS.md 32 KiB); Gemini CLI `github.com/google-gemini/gemini-cli/docs` (hooks reference AfterTool,
subagents, `modelConfigs.overrides`); Qwen Code `QwenLM/qwen-code/docs` (hooks, `agents.modelGrades`); opencode
`opencode.ai/docs` (V2 plugins `execute.after` / `context`, agents `#variant`); Kilo `kilo.ai/docs/llms.txt`;
Crush `charmbracelet/crush` (hooks `updated_output`, crushrc); Goose `aaif-goose/goose` docs (recipes
`settings.goose_model`); Amp `ampcode.com/docs` (plugins `tool.result`); Aider `aider.chat/docs`; Factory Droid
`docs.factory.com` (droids `reasoningEffort`, hooks); Warp `docs.warp.dev`; Grok Build `docs.x.ai/build`
(`[subagents.models]`); Copilot CLI `docs.github.com` (hooks `modifiedResult`, `subagents.agents.<name>.effortLevel`);
OpenClaw `docs.openclaw.ai` (`sessions_spawn` model/thinking); Cursor `cursor.com/docs` (hooks, third-party hooks,
subagents `model: id[effort=..]`); Devin `docs.devin.ai` (rules, hooks, `read_config_from`, subagent profiles);
Kiro `kiro.dev/docs` (steering, hooks, custom agents); Cline `docs.cline.bot` + `cline/cline` source (hook files,
`spawn_agent`); Continue `docs.continue.dev` + source (cn hooks, subagent model entries); Zed `zed.dev/docs`
(instructions, `agent.subagent_model`); Junie `junie.jetbrains.com/docs` (hooks `updatedToolOutput`, subagents
`reasoningLevel`).

## Model tier per helper (cheap / mid / top)
The rule "checkable work goes to a cheap helper" only takes effect where the agent can pick a model per helper.
Setup gives each tool the strongest way it allows:

| What the tool allows | How the tier reaches the helper | Enforced |
|---|---|---|
| A delegation-backend plugin (e.g. Hermes Agent) | `plugin/frugal-tiers/`: adds `tier` (cheap/mid/top) and `effort` (low/medium/high) to the delegate tool; the tier maps to a model of the parent's provider family | yes: the backend sets the child's model |
| Subagents defined in config files with a model (+ effort) field (Claude Code, Codex, Cursor, Droid, opencode, Kilo, Gemini, Junie, Copilot, Kiro, Devin, Goose recipes, Qwen grades, Grok built-ins) | setup writes `frugal-cheap` / `frugal-mid` / `frugal-mid-writing` / `frugal-top` with the tier's model and effort (matrix above); the rules name them | the tool runs that model and effort; the agent picks the subagent |
| A per-call model field only (OpenClaw `sessions_spawn`, Zed `spawn_agent`, Claude Code's Agent tool) | the rules give the exact value to pass per tier (and `thinking` on OpenClaw) | the choice is the agent's |
| Neither (Amp, Crush, Aider, Cline, Warp, chat apps) | rules only: the helper runs on the agent's model, and the agent says so | no; for a fixed cheaper model, point the tool at `proxy/` |
| Chat apps | rules only | no |

**`plugin/frugal-tiers/`** (a Hermes-style delegation provider, `delegation.backend: frugal-tiers`). The table comes
from `kit/ROUTING.md` as `tiers.json` (regenerate: `python3 plugin/frugal-tiers/__init__.py --regen ../kit/ROUTING.md`;
a test fails when the two differ). Family = the parent's provider (`anthropic` → `claude-haiku-5-5` style ids;
`openai`/`openai-codex`; `gemini`) or the vendor of a `vendor/model` id on an aggregator (OpenRouter-style →
`anthropic/claude-haiku-5.5`). The parent is the `delegation` pin when set, else the configured main model
(`model.provider` / `model.default`; a mid-session model switch is not seen). No tier = the default route (as before).
A family or tier missing from the table = the default route with a label note; an unknown tier or effort refuses that
task. Effort: the tier's ROUTING.md default (medium) unless the task sets `effort`. Overrides per tier in
`delegation.backends.frugal-tiers`: `cheap: {model: ...}` (same provider) or `{provider: ..., model: ..., effort: ...}`.
Setup copies it with the other plugin; turning it on is the user's step:
`hermes plugins enable frugal-tiers` and `hermes config set delegation.backend frugal-tiers`. Undo:
`hermes config set delegation.backend <previous value>` and `hermes plugins disable frugal-tiers`. `uninstall --global`
removes only its files and, when `delegation.backend` still names it, puts the value recorded at install back (with
the tool's own `config set`; without the binary it prints the command), because a backend whose plugin is gone fails
every delegation closed. `check --global` shows `hermes tiers: on|off (...)`.

## Tests
`python3 -m pytest -q adapter kit` — every matrix row (`kit/test_hosts.py`: fake home + fake binaries, the tool's own
config format, install → check → re-run byte-identical → uninstall byte-identical, rules loaded once, hooks written,
tier model AND effort values per tool, all tools at once, shared files, base present), hook script per tool
(`adapter/hooks/test_hook_tools.py`: each tool's input shape and replace-output field, run-once, usage, JS plugins
under node), hooks, plugin (also loaded through a real plugin manager), tiers (every family,
overrides, inherit cases, table in sync, loaded through the installed Hermes plugin loader and delegation registry when
present), proxy (fake upstream), setup. Real runs: an agent installed everything from one sentence and a new session loaded the rules; a
coding agent ran through the proxy with the context notice and loop guard working and the cache intact.
