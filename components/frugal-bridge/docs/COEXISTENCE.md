# Coexistence contract: Frugal-Bridge + a knowledge base (any install order)


A knowledge base ("base folder": a second-brain folder any agent reads) and Frugal-Bridge are two separate
products. Either can be used alone. Either can be installed first, the other later, or both at once.
**No order may cause a conflict, a lost file, or a duplicate.**

## 1. Where conflicts could come from (all of them)

| # | Collision | Why it happens |
|---|---|---|
| C1 | `AGENTS.md` | Both kits put their rules in the root `AGENTS.md` |
| C2 | Pointer files | Both create `CLAUDE.md` / `GEMINI.md` one-liners |
| C3 | User files | Frugal has USER / PROGRESS / DECISIONS / MAP; Base has `wiki/me/`, `hot.md`, `wiki/decisions/`, `wiki/index.md` — same jobs, two copies |
| C4 | Read order | Frugal: "read USER + PROGRESS first"; Base: "read hot.md, then index" |
| C5 | Skills | Both ship skills; same name possible (e.g. `handoff`) |
| C6 | Hooks / plugins | Both want SessionStart / post-edit hooks in the same host config (`.claude/settings.json`, Hermes plugins) |
| C7 | `.gitignore` | Both add lines |
| C8 | Upgrade | Re-running one setup must not undo the other's changes |
| C9 | Uninstall | Removing one must leave the other fully working |
| C10 | User's own text | The user (or another tool, e.g. Graphify) already wrote in `AGENTS.md` / `CLAUDE.md` |

## 2. The contract both kits follow (5 rules)

1. **Blocks, never whole files.** Every shared file (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.gitignore`) is edited
   only inside the kit's own marked block:
   `<!-- base-folder:start v1 -->` … `<!-- base-folder:end -->` and
   `<!-- frugal-bridge:start v1 -->` … `<!-- frugal-bridge:end -->`.
   Text outside the blocks (user's own, other tools) is never touched. Fixes C1, C2, C7, C10.
   Fixed order in `AGENTS.md`: base block first, frugal block second (stable prompt start = cache stays valid).
   Pointer files hold one line `@AGENTS.md` (an import: Claude Code and Gemini CLI load the file; a prose line like
   "Read AGENTS.md" was shown in tests NOT to load it). Gemini may use `.gemini/settings.json` `context.fileName`
   instead. Whichever kit comes first writes the pointer; the second sees it and does nothing.
   **JSON files** (`.claude/settings.json`, `.gemini/settings.json`) have no comments, so no blocks: merge **by key** —
   each kit adds only entries it can recognise as its own (hook command path, its own list values), replaces them on
   re-run, removes only them on uninstall; invalid JSON = stop, change nothing. Fixes C6.
   **Size budget:** the whole `AGENTS.md` (all blocks) must stay under 32 KiB (Codex's default read limit); both
   setups and `brain.py lint` check the total, not just their own block.
2. **One registry: `.kits.json`** at the root. Each setup reads it first and writes only its own entry:
   ```json
   {"kits": {"base-folder": {"version": "1", "installed": "2026-11-10"},
             "frugal-bridge": {"version": "6", "installed": "2026-11-11", "adapters": ["hermes", "claude-code"]}},
    "slots": {"user": "wiki/me/README.md", "now": "hot.md", "decisions": "wiki/decisions/",
              "map": "wiki/index.md", "sources": "raw/"}}
   ```
3. **Slots, one owner each.** The 5 shared jobs (user, now, decisions, map, sources) are *slots*.
   - Base present → Base owns all slots (paths above).
   - Base absent → Frugal owns them with its own files (`USER.md`, `PROGRESS.md`, `DECISIONS.md`, `MAP.md`, `sources/`).
   - Rules, adapters and hooks never hard-code file names; they read the slot path from `.kits.json`.
   Fixes C3 and C4: one read order = `now` slot first, then `user`, then `map` only when needed.
4. **Namespaced skills and hooks.** (Frugal skills renamed `frugal-*` 2026-11-11.) Skills: `base-*` and `frugal-*` prefixes (no shared names). Hooks: each kit
   adds its own entry, identified by its command path; setup adds/updates only entries that point to its own
   scripts. Fixes C5, C6.
5. **Each setup is idempotent and reversible.** Re-run = same result (replaces only its block/entries). Every
   setup writes a backup of each file it touches and has an `uninstall`. Fixes C8, C9.

**Who decides when rules overlap:** Base decides *what is known and where it lives* (paths, permissions,
security, raw/ read-only). Frugal decides *how work is done cheaply* (sessions, routing, calls, outputs).
Security/permissions always win over token savings.

## 3. Every case

| # | Case | What setup does |
|---|---|---|
| 1 | Base only (fresh) | Creates skeleton, its `AGENTS.md` block, `.kits.json` with base entry + slots. |
| 2 | Frugal only (fresh) | Creates its block, own slot files (USER/PROGRESS/DECISIONS/MAP), `.kits.json` with slots pointing to them, installs adapter for the host. |
| 3 | **Base first, Frugal later** | Frugal setup sees `base-folder` in `.kits.json` → creates **no** slot files, uses base slot paths, adds only its block + skills + adapter. |
| 4 | **Frugal first, Base later** | Base setup sees `frugal-bridge` → **imports** Frugal's slot files: USER → `wiki/me/`, PROGRESS → `hot.md` (+ history in `progress/`), DECISIONS → `wiki/decisions/`, MAP → `wiki/index.md`, `sources/` → `raw/`. Originals copied to `raw/exports/frugal-<date>/`. Old files become one-line stubs ("moved to …") for one transition period. Rewrites `slots` in `.kits.json`. Frugal's block and adapter untouched; adapter picks the new paths on next session. |
| 5 | Both at once | Run Base first, then Frugal (= case 3). A combined installer just calls both in that order. |
| 6 | Frugal in several projects, one Base later | Each project has its own `.kits.json`. Base import runs per project: user-level USER merged once into `wiki/me/` (duplicates flagged for review, not overwritten); each project's PROGRESS/DECISIONS → `wiki/projects/<slug>/`. Project `.kits.json` slots then point into the base. |
| 7 | Remove Frugal (Base stays) | Remove its block, skills, adapter, `.kits.json` entry. Base untouched. |
| 8 | Remove Base (Frugal stays) | Base uninstall **exports slots back** to plain USER/PROGRESS/DECISIONS/MAP files, points `slots` to them, then removes its block. Frugal keeps working. |
| 9 | Upgrade either | Replace own block (version bump in marker), own skills, own hooks; never touches the other kit. |
| 10 | Existing user `AGENTS.md` / `CLAUDE.md` / other tool blocks | Kept as is; kit blocks are appended. If an existing `CLAUDE.md` does not point to `AGENTS.md`, setup adds the pointer line inside its own block. |
| 11 | Host without file access (chat apps) | Not a coexistence issue: user pastes `AGENTS.md` (both blocks) + current `now`/`user` files as project instructions. |
| 12 | Old version without `.kits.json` | Setup detects by markers / known files (`brain.py`, `kit/AGENTS.md` text) and writes `.kits.json` first, then continues as the right case. |

## 4. Proof before shipping (test matrix)

Each case 1–12 in a throwaway folder, checked by a script (no AI): no file lost (hash of every original present
in place or in `raw/exports/`), no duplicate slot, `AGENTS.md` has each block exactly once, user text outside
blocks byte-identical, re-run = no diff, install → uninstall = original tree (except backups). Then a cold
agent (Hermes + Claude Code) opens cases 3 and 4 and answers "who is the user, where are we now" correctly.

## 4b. Other doors and hosts
- **Chat apps (`brain.py brief --full`):** when `.kits.json` lists `frugal-bridge`, the bundle includes Frugal's CORE
  block — chat apps have no adapter, so this is the only way the token rules reach them.
- **Caged engines (sandbox with an egress proxy):** traffic leaves only via the egress proxy. With Frugal's proxy the
  path is agent → egress → Frugal proxy → provider (allow-list the Frugal proxy). A runtime should treat both kits as
  optional: use them when present, work without them.

## 5. Changes this forces in what exists

- ✅ Done 2026-11-11: Frugal Hermes adapter, Claude Code hook and proxy read slot paths from `.kits.json`; Frugal
  `kit/setup.py` implements blocks, pointer, JSON merge, slots, size check, uninstall (12 tests).
- Frugal `kit/SETUP.md` and Base build order (§15 of base-folder-design) → follow this contract.
- The planned proxy adapter (any host) reads `.kits.json` the same way.

Related: base-folder-design §23, base-folder-test-results.

## User-level (global) install
When either kit is installed for the user instead of one folder, the same contract holds in the tools' user-level
files (e.g. `~/.claude/CLAUDE.md`): one marked block each, the base block first. Frugal finds a connected base from
its block (`Path: <dir>`) and uses the base's slots — no second user file. If Frugal was installed first, re-running
its setup switches it to the base and asks the user to move the old `~/.frugal-bridge/USER.md` content into the base.
