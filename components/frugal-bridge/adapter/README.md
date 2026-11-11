# The Frugal-Bridge adapter

**One adapter, for any agent, app or provider.** The rules (`kit/AGENTS.md`) already work everywhere; the adapter
makes the parts a prompt cannot guarantee happen automatically. `kit/setup.py` picks the way for you
(`--hosts auto`, the default): for each agent tool it finds, it uses the strongest mechanism that tool allows.

| What the tool allows | What the adapter uses | Enforced |
|---|---|---|
| Session / prompt hooks | `hooks/` (one small script) | context watch, start files |
| Plugins | `plugin/` | context watch, start files, big-output filter, usage report |
| A configurable API base URL (any provider) | `proxy/` (local, standard library only) | context watch, loop guard, output filter, start files, rules injection, usage report |
| None of these (chat apps) | — | the rules are pasted as project instructions: followed, not enforced |

The user never chooses: they ask their AI to "set up Frugal-Bridge" (`INSTALL.md`) or run `kit/setup.py install`.

## What it enforces
- **Context watch:** tracks each conversation's real size; past 150k tokens (100k on cheap models) it asks the agent,
  once, to offer the user a new session with a handoff / compact / carry on; at 300k it says it plainly. Notices go at
  the end of the turn, never the start, so the prompt cache stays valid.
- **Start files:** on a session's first turn, the agent reads the "now" and "user" files first, in one call. Paths
  come from `.kits.json` `slots` (project folder + up to 3 parents) — so it works the same next to a knowledge base —
  else `PROGRESS.md` / `USER.md`.
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
shell output rely on the `frugal-filter-output` skill for that rule. (Uses the hook format of Claude Code.)

**`plugin/frugal-bridge/`** — hooks on API requests, on each turn and on terminal output, plus a `/frugal` command.
Setup copies it into the tool's plugin folder; enabling it restarts that tool's gateway, so it is left to the user
(e.g. Hermes Agent: `hermes plugins enable frugal-bridge`). Optional `<tool home>/frugal-bridge/config.json`:
`{"base_dir": "...", "ctx_warn": 150000, "ctx_hard": 300000, "ctx_warn_cheap": 100000, "out_limit": 12000}`.

**`proxy/frugal_proxy.py`** — sits between any tool and any provider. Run it, then point the tool's base URL at
`http://127.0.0.1:8790/<route>` (routes: `anthropic`, `openai`, `chatgpt`, `openrouter`, `gemini`, `xai`; more in
config). Keys pass through untouched; it stores none. Wire formats: Anthropic Messages, OpenAI Chat Completions,
OpenAI Responses; anything else passes through unchanged; any internal error forwards the original request.
`core_file` set → the rules are added to the system prompt once (skipped if a `frugal-bridge:start` block is there).
Config: `~/.config/frugal-bridge/proxy.json` (or `--config`); `dump_dir` = debug only. Limit: it cannot start a new
session itself. Examples — Anthropic-format tools: `ANTHROPIC_BASE_URL=http://127.0.0.1:8790/anthropic`;
OpenAI-compatible tools: base URL `http://127.0.0.1:8790/openai/v1` (or `/openrouter/v1`, `/gemini/v1beta/openai`);
a ChatGPT-login CLI (Codex): `-c model_provider=fb -c 'model_providers.fb={name="fb",base_url="http://127.0.0.1:8790/chatgpt",wire_api="responses",requires_openai_auth=true}'`.

## Tests
`python3 -m pytest -q adapter kit` — hooks, plugin (also loaded through a real plugin manager), proxy (fake
upstream), setup. Real runs: an agent installed everything from one sentence and a new session loaded the rules; a
coding agent ran through the proxy with the context notice and loop guard working and the cache intact.
