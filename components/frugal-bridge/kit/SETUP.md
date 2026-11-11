# Frugal-Bridge — setup on any AI host

**Easiest:** ask your AI agent to "set up Frugal-Bridge" — it follows `INSTALL.md`.
**By hand:** `python3 kit/setup.py install --global` (once, every folder and every new session) · `check --global` ·
`uninstall --global`. One folder only: `install /path/to/project`. Idempotent, reversible, backups
in `<project>/.frugal-bridge/backup/`. Works alone or next to a knowledge base (any install order — see below).

The kit = `AGENTS.md` (rules) + `ROUTING.md` (tiers → models) + `templates/` + `skills/`. Your files (USER, PROGRESS,
PROJECT, DECISIONS, sources/) live in the project folder — or in a knowledge base, if you have one. Name your main
agent in `USER.md`.

## What setup does
1. Adds the rules as a marked block in the project's `AGENTS.md` (your text untouched).
2. Adds one-line pointer files (`@AGENTS.md`) for tools that read another file name (e.g. `CLAUDE.md`, `GEMINI.md`):
   an `@` import loads the file; a prose line like "Read AGENTS.md" does not.
3. Creates USER / PROGRESS / DECISIONS / `sources/` from templates — unless a knowledge base already owns them.
4. Installs the adapter for every agent tool it finds (`--hosts auto`): hooks where the tool has hooks, a plugin where
   it has plugins (enabling it is your call: it restarts that tool), and tells you which tools could use the proxy.
   Force a choice with `--hosts <list>` (`none` = rules only).
5. Checks: one block, pointers import `AGENTS.md`, start files exist, whole `AGENTS.md` under 32 KiB (some tools read
   only the first 32 KiB).

## Where setup can't run
| Where | How |
|---|---|
| Chat apps (projects with instructions) | Paste `AGENTS.md` + `ROUTING.md` + your `USER.md` into the project instructions; upload PROJECT/DECISIONS as files. The rules are followed, not enforced — start a new chat yourself when the agent proposes it. |
| Your own app / API | System prompt = `AGENTS.md` + `ROUTING.md` + `USER.md` (unchanged during a session, for the cache). Either route calls through `adapter/proxy/`, or do its jobs in code: count tokens, offer a new session at 150k, filter tool outputs, skip empty heartbeats, route helpers by tier. |

Fill `ROUTING.md` with the models you have. Check an independent benchmark (e.g. artificialanalysis.ai) for
candidates, then test on your own tasks (AGENTS.md section 8).

## Coexistence with a knowledge base (or any other kit)
- Shared Markdown files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`): edited only inside `<!-- frugal-bridge:start vN -->`
  … `<!-- frugal-bridge:end -->`; text outside is never touched; uninstall restores it byte for byte.
- JSON settings (a tool's `settings.json`; no comments, so no blocks): merged key by key — setup adds only hook entries
  whose command is its own `.frugal-bridge/frugal_hook.py`, replaces them on re-run, removes only them on uninstall.
  Invalid JSON → setup stops and changes nothing there.
- `.kits.json`: each kit writes only its own entry. If a base folder is registered, Frugal creates **no** USER/PROGRESS/
  DECISIONS files and its adapters read the base's `slots` (e.g. now = `hot.md`, user = `wiki/me/README.md`).
- Size: `setup.py check` measures the whole `AGENTS.md` (all blocks): some tools read only the first 32 KiB.
- Pointer files: `@AGENTS.md` (some tools also accept a setting that names `AGENTS.md` as their context file).
