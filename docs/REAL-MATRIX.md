# Real harness x provider matrix

Real runs of the whole install with real AI tools and real providers, each in a fresh temporary HOME (the
machine's own tool settings are never touched). Script: `tests/real/test_real_matrix.py` (opt-in, not in CI):

```sh
MOTHERSHIP_REAL=1 python3 -m unittest tests.real.test_real_matrix -v
MOTHERSHIP_REAL=1 MOTHERSHIP_REAL_ROWS=claude-anthropic python3 -m unittest tests.real.test_real_matrix
```

Per row: the tool's own minimal config + login/key in the temp HOME, `install.py --yes`, two tiny prompts from an
unrelated folder, `brain.py collect`, `install.py uninstall`, then a file-by-file compare of the HOME.

- **a** finds the base: the answer names facts only the fixture base has (`Robin Example`, `Lighthouse garden`)
- **b** writes the base: after "Remember this: my favourite tea is Moonleaf oolong", the fact is in the base
- **c** its own memory is collected: the tool's memory item lands in `raw/inbox/collected/TOOL/`
- **d** Frugal-Bridge: its block is after the base block in the file the tool loads, the agent picks **cheap** for
  "a small bug fix that has tests", and the helper-tier config written for the tool matches `tiers.json` for its
  provider (model **and** effort where the tool has a per-helper effort)
- **e** uninstall: the HOME is byte-identical to before, except the tool's own session/cache files (listed below),
  the base folder (your data stays) and the backup archives
- **deleg.**: a real helper call on the cheap tier, with the model proven from the tool's own records

## Results (2026-11-11, The Mothership 1.1.1: Skeleton Base 1.4.1, Frugal-Bridge a1e1ef9)

| tool | provider (main model) | a | b | c | d | e | deleg. |
|---|---|---|---|---|---|---|---|
| Claude Code | Anthropic (sonnet) | PASS | PASS | PASS | PASS | PASS | PASS: `frugal-cheap` ran `claude-haiku-5-5` (its subagent transcript) |
| Hermes Agent | Anthropic (claude-sonnet-5-5) | PASS | PASS | PASS | PASS | PASS | PASS: child session model `claude-haiku-5-5` (`state.db`) |
| Hermes Agent | Google, provider `gemini` (gemini-3.8-flash) | PASS | PASS | PASS | PASS | PASS | PASS: child session model `gemini-3.8-flash` |
| Gemini CLI 0.68 | Google (gemini-3.8-flash) | PASS | NOT RUN | NOT RUN | PASS | PASS | not tested |
| Qwen Code 0.27 | Google through its OpenAI-compatible endpoint (gemini-3.5-flash) | PASS | PASS | PASS | PASS | PASS | not tested |
| opencode 1.19 | Google (gemini-3.7-flash) | NOT RUN | NOT RUN | n/a (no store) | config PASS, answer NOT RUN | PASS | not tested |
| Codex | OpenAI | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

### Relocated config dir (2026-11-12, The Mothership 1.2.0: Skeleton Base 1.6.0 `9d5991e`, Frugal-Bridge `3fee219`)

Row `claude-relocated-config`: Claude Code 2.1.287 with `CLAUDE_CONFIG_DIR=BASE/engines/claude` (the credentials
file copied there, `~/.claude` absent), main model `claude-haiku-5-5` (cost). f = `~/.claude` and `~/.claude.json`
never made; g = git ignores `engines/claude/.credentials.json`, `.claude.json`, `projects/*.jsonl` and keeps
`engines/claude/CLAUDE.md`.

| tool | provider (main model) | a | b | c | d | e | f | g |
|---|---|---|---|---|---|---|---|---|
| Claude Code, config dir in the base | Anthropic (claude-haiku-5-5) | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

Evidence: answer "Robin Example / Current focus: the Lighthouse garden project / Cheap tier (frugal-cheap, medium
effort)"; the tea fact saved in the base and collected from `engines/claude/projects/*/memory/`; the rules file
`engines/claude/CLAUDE.md` has the base block, then Frugal-Bridge's; after uninstall the only HOME changes are
Claude's own `~/.cache/claude-cli-nodejs` files. `codex-relocated-home` NOT RUN (Codex usage limit until
2026-11-13).

Why NOT RUN:
- Gemini CLI b/c and opencode a/b/d-answer: the Google key is on the free tier (20 requests per model per day).
  `gemini-3.8-flash` (the cheap tier's model, also what Gemini CLI 0.68 calls internally before every prompt
  whatever `-m` says, and what opencode's `frugal-cheap` helper uses) hit its daily limit during the run (HTTP 429,
  "retry in 22h"). Re-run these rows after the reset or with a paid key.
- Codex: the account's usage limit is reached until 2026-11-13.

### Re-run of the blocked rows (2026-11-13, The Mothership 1.2.2: Skeleton Base 1.6.3 `518485d`, Frugal-Bridge `693f28b`)

New checks: **f** role: the base has `agents/twin.md` (`engines: [hermes]`, `name: TwinName`) and
`agents/engineer.md` (`engines: [claude-code, codex]`); "who are you? one line: your role and your name if any" from
an unrelated folder. Codex must answer engineer, never TwinName; tools with no matching role use no personal name.
**g** tidy: a scratch copy of the base with 3 lines under `## Collected`, `brain.py tidy --force --harness H`: merged
with no put-back, no line left, the facts in the prose, `lint` 0 problems.

| tool | provider (main model) | a | b | c | d | e | f | g |
|---|---|---|---|---|---|---|---|---|
| Codex 0.159.3 | OpenAI (gpt-6.1-sol, effort medium) | PASS | PASS | n/a (Codex memories are off by default and built later in the background) | PASS | PASS | PASS | PASS |
| Gemini CLI 0.68 | Google (gemini-3.8-flash) | NOT RUN | NOT RUN | NOT RUN | config PASS, answer NOT RUN | PASS | NOT RUN | NOT RUN |
| opencode 1.19.5 | Google (gemini-3.7-flash) | NOT RUN | NOT RUN | n/a | config PASS, answer NOT RUN | PASS | NOT RUN | not tested (opencode tidy row unverified) |

Codex evidence: answer "1) Robin Example / 2) The Lighthouse garden project / 3) cheap"; "saved" with the tea fact in
`wiki/me/who-i-am.md`; the four `~/.codex/agents/frugal-*.toml` match tiers.json for openai (cheap `gpt-6-luna`
medium, mid `gpt-6.1-sol` medium, mid-writing and top `gpt-6.1-sol` high); role answer "Engineer role; no personal
name assigned."; tidy "ok, 3 line(s) ... 1 page(s) merged, 0 put back", lint 0 problems; after uninstall the only
non-own change is Codex's own `[projects."DIR"] trust_level` entry in `config.toml` (written by Codex for the folder
it ran in; nothing of ours is left).

Why NOT RUN: the free-tier Google key was already at its daily limit for `gemini-3.8-flash` when the run started
(HTTP 429 "limit: 20, model: gemini-3.8-flash ... retry in 18h59m"). Gemini CLI calls that model before every prompt,
and opencode also hit it with `-m google/gemini-3.7-flash`, so neither got one answer. Their install, rules block,
tier files and uninstall checks still passed. Re-run after the reset (about 08:00 UTC) or with a paid key.

Bugs found and fixed (each with a regression test):
- Role (f), Codex: the first run answered "I'm Codex, your coding agent." The rule "your own identity (your system
  prompt ...) first" let the tool's built-in line win. Fixed in Skeleton Base 1.6.3 (`role_rule`: a tool's product
  name and built-in "You are <tool>" line are not a role or a name; for "who are you?" read `agents/*.md`), test
  `test_tool_product_identity_is_not_a_role`; and in Frugal-Bridge `kit/AGENTS.md` (private `2108836`, public
  `693f28b`), test `test_core_says_the_tools_own_product_identity_is_not_a_role`. Re-run: PASS.
- Tidy (g), Codex: "0 lines merged ... no command-free local file reader is available". Codex has no file-read tool,
  and the prompt said "Do not run commands". Fixed in Skeleton Base 1.6.3 (Codex rows may read with read-only shell
  commands; its sandbox still limits writes to the base), test `test_codex_is_told_to_read_with_read_only_commands`.
  Re-run: PASS.

Live check (real home, read-only, no config change), `cd /tmp && codex exec 'chkoun nta? ...'` (Darija), before the fix
reached the real home: "I am Codex, your helper for code and technical tasks" (answered in Darija; FAIL: "Codex",
not Engineer; it did not take the twin's name). The real home's rules block gets the new role text on the next `brain.py connect` or update.

## What each tool leaves behind after uninstall (its own files)

- Claude Code: `~/.claude/projects/` (sessions, its auto memory), `~/.claude.json` + `~/.claude/backups/`,
  `~/.claude/cache/`, `~/.claude/skills/synced/` (skills synced from the account), `~/.claude/.last-cleanup`,
  `~/.cache/claude-cli-nodejs/`.
- Hermes: its home's sessions, logs, `state.db`, `memories/`, caches, `installs/`, `skills/` (its bundled skills),
  `source-checks/`, `install_id`, and `config.yaml` rewritten by `hermes plugins enable/disable` +
  `hermes config set delegation.backend` (the user's own steps to turn the tiers backend on and off).
- Gemini CLI: `~/.gemini/history/`, `~/.gemini/tmp/`, `~/.gemini/projects.json`.
- Qwen Code: `~/.qwen/projects/`, `~/.qwen/tmp/`, `~/.qwen/memories/` (its memory store), `user-memory-meta.json`,
  `usage_record.jsonl` (and on its first start `settings.json` gets `"$version"`; the runs start it once before the
  snapshot).
- opencode: `~/.local/share/opencode/`, `~/.local/state/`, `~/.cache/opencode/`, its plugin dependencies in
  `~/.config/opencode/` (`node_modules/`, `package.json`, `package-lock.json`, `bun.lock`), `~/.npm/`, `~/.bun/`.
- Codex: `~/.codex/sessions/`, `cache/`, `plugins/`, `skills/.system/`, `shell_snapshots/`, `thread-writer-locks/`,
  its `*.sqlite` files (state, logs, goals, queue, thread history, memories), `models_cache.json`,
  `installation_id`, `.sandbox_migration`, and a `[projects."DIR"] trust_level` table it adds to `config.toml`.
- Kept on purpose: Frugal-Bridge's usage log `~/.frugal-bridge/usage.jsonl` (your data; its uninstall never
  deletes it).

## Bugs these runs found (fixed, each with a regression test)

| found in | what | fixed in |
|---|---|---|
| Skeleton Base suite against Frugal-Bridge (connect, Frugal install, disconnect, Frugal re-run, Frugal uninstall) | Frugal's uninstall put back the text a settings file had before the base was disconnected: the base's hooks and folder entry came back in `~/.claude/settings.json` | Frugal-Bridge 25de157 |
| Claude Code delegation | the `frugal-cheap` agent had `model: haiku`; Claude Code's alias ran `claude-haiku-4-5`, not the table's Haiku 5.5 | Frugal-Bridge a1e1ef9 (exact ids) |
| Claude Code "remember" | the agent chained `brain.py index` and the log line in one shell command; the allow rule the base writes does not match that, so it was refused | Skeleton Base 1.4.1 (one command on its own, log with file tools) |
| Qwen Code "remember" | saved only to its own memory | Skeleton Base 1.4.1 ("Remember ..." goes to the base first, user facts to `wiki/me/`); re-run PASS |
| Qwen Code collect | an empty `MEMORY.md` was collected as an empty item | Skeleton Base 1.4.1 |
| Mothership tests | Hermes and Codex homes without the tool's program or config no longer count as installed | Mothership 1.1.0 tests |

Component versions per run: Claude Code and Hermes + Anthropic were re-run on the 1.1.1 components; Qwen Code's
passing run had Skeleton Base's two pointer fixes and Frugal-Bridge a1e1ef9 (not yet the empty-file collect fix);
Hermes + Google and Gemini CLI ran on the 1.1.0 components (their checks do not touch the changed parts). One run
per row after the fixes: small samples, a model can still decide differently on another run.
