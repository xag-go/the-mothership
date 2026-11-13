# Changelog

## v1.2.2 (2026-11-13)

- Skeleton Base 1.6.3 (`4e8a73a`) vendored (was 1.6.2 `0c26c3d`): role rule (a tool's built-in product name is not a role;
  "who are you?" is answered from `agents/*.md`), `engine revault` (puts vault links back after a tool rewrote its secret
  file; `watch` runs it each pass), `doctor` knows guard files/links left by `engine adopt` and points to revault,
  `engine vault` takes the tool id, tests no longer read the real tool-home variables.
- Frugal-Bridge unchanged (`3fee219`).

## v1.2.1 (2026-11-13)

- Skeleton Base 1.6.2 (`0c26c3d`) vendored (was 1.6.0 `9d5991e`; 1.6.1 included): `engine vault` / `vault add` (secrets of an
  engine in one vault outside the base, symlinks left, rotating backups as one folder link, `undo`), `engine share` and
  `engine sync-all` with a gitleaks content gate, `doctor` vault checks, `wiki/secrets.md`, folders outside on purpose with reasons.
- Frugal-Bridge unchanged (`3fee219`).

## v1.2.0 (2026-11-12)

- Skeleton Base 1.6.0 (`9d5991e`) vendored (was 1.5.4 `84f6e79`): every tool's folder follows its own setting
  (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `HERMES_HOME`, ...), several folders of one tool (`connect --tool-dir`, shared
  registry `~/.config/ai-tool-dirs.d/`), `engines/` and `projects/` in the base with per-tool share rules for git and
  Syncthing, `engine adopt|release|mirror`, `projects move|clone`, `doctor`, pre-commit guard.
- Frugal-Bridge `3fee219` vendored (was `ed757f2`): hook state under `CLAUDE_CONFIG_DIR`, `install --global
  --tool-dir` / `--claude-config-dir`, the shared registry, a moved `FRUGAL_HOME` rewrites its hook paths.
- `install.py --tool-dir TOOL=DIR` / `--claude-config-dir DIR` (repeatable, kept for re-runs and updates): passed to
  both products. The uninstall snapshot also covers `OPENCLAW_STATE_DIR`, `COPILOT_HOME` and the extra dirs.
- Tests: a Claude Code config dir inside the base (never `~/.claude`, secrets ignored by git, byte-identical
  uninstall), a second Claude dir by option kept for re-runs, a bad `--tool-dir`; real matrix row
  `claude-relocated-config` (a-g PASS on `claude-haiku-5-5`).

## v1.1.5 (2026-11-11)

- Skeleton Base 1.5.4 (`84f6e79`) vendored (was 1.5.3 `21f5b59`): `tidy` waits for the watcher's writes (a page run
  holds the collector lock) and ignores the watcher's own generated writes, so a good page is no longer put back;
  `tidy` exits 0 when a page was put back (the systemd unit no longer shows `failed`); `file` records index lines and
  duplicates as done, and `watch` commits that bookkeeping. 4 regression tests in Skeleton Base.

## v1.1.4 (2026-11-11)

- Skeleton Base 1.5.3 (`21f5b59`) vendored: `brain.py file` also flags a small number change in the same place
  (1.5.1 -> 1.5.2, a port or a count) as a conflict.

## v1.1.3 (2026-11-11)

- Skeleton Base 1.5.2 (`2abbf49`) vendored (was 1.5.1 `a31a61a`): `brain.py file` no longer flags a false
  "negation" conflict. A "not" in another clause of a long memory is no longer compared against an unrelated
  page sentence; real flips and changed numbers stay flagged. 3 regression tests in Skeleton Base.

## v1.1.2 (2026-11-11)

- Skeleton Base 1.5.1 (`a31a61a`) vendored from GitHub (was 1.4.1 `e282bde`), with 1.5.0: `brain.py file` (collected
  memories filed on one page each by code, 0 tokens) and `brain.py tidy` (rare model pass with whichever agent CLI
  is installed). 1.5.1: every tool's pointer block says how it finds its role and name (own identity first, else
  the ONE `agents/` file whose `engines:` lists it, else no name and ask once; never a name from `wiki/me/`);
  `engines:` lists in role files; watcher `MemoryMax` 160M (40M OOM-killed the 1.5.0 watcher).
- Frugal-Bridge `ed757f2` vendored (was `a1e1ef9`): the main agent's name no longer comes from the user file; the
  start notice adds the base role file only on one safe match.
- install enables the tidy timer that Skeleton Base `connect` writes (`skeleton-base-tidy.timer`, with the watcher
  or `--timer`), only when the unit file exists; uninstall disables it with the others and `disconnect` removes the
  files. An upgrade from 1.1.1 adds it to the units it enabled.

## v1.1.1 (2026-11-11)

- Real tool x provider matrix: `tests/real/test_real_matrix.py` (opt-in `MOTHERSHIP_REAL=1`, never in CI). Each row
  runs a real tool in a fresh temporary HOME (its own minimal config and login or key), `install.py --yes`, real
  prompts from an unrelated folder, `collect`, `uninstall`, and checks from files: finds the base, writes it, its
  memory collected, Frugal rules + tier config vs `tiers.json`, HOME byte-identical except the tool's own files, and
  a real cheap-tier helper call where the tool has one. Results: [docs/REAL-MATRIX.md](docs/REAL-MATRIX.md).
- Skeleton Base 1.4.1 (`e282bde`) and Frugal-Bridge `a1e1ef9` vendored from GitHub, with the fixes those runs
  found: Claude Code helper tiers use the table's exact model (the `haiku` alias ran an older Haiku); the base's save
  step is one allowed command; "remember" goes to the base first; empty memory files are not collected.

## v1.1.0 (2026-11-11)

- Skeleton Base 1.4.0 (`e15a9a9`) vendored from GitHub (was 1.3.5 `e66997f`): one tool table (26 rows) for
  `connect`: one pointer block per tool in the file it loads, the base on each tool's own allow list, skills once
  in `~/.agents/skills`, more memory stores collected, `brain.py mcp` (stdio MCP server) and `connect --mcp`.
- Frugal-Bridge `25de157` vendored from GitHub (was `45a0440`): hosts table (24 tools), rules once per tool after the
  base block, hooks / JS plugins per tool, helper tiers with model **and** effort in each tool's own setting, usage
  log + `setup.py report`; and a fix: an uninstall after a re-run no longer brings back entries another kit removed
  in between (a disconnected base's hooks in `~/.claude/settings.json`).
- `install.py`: Frugal-Bridge's user-level install runs with `--hosts auto` (its table, installed tools only);
  `--mcp` is passed to the base's `connect` and kept for re-runs and `update`; new `report [DAYS]` command (Frugal's
  usage report); the summary and `status` list which tools each product set up; the plan says "every tool found".
  An already connected base is found through every rules file of Skeleton Base's tool table.
- README: "Which tools, which provider" points to both products' tool matrices.
- Tests: the test home has its tools' programs on PATH (claude, codex, gemini; Skeleton Base 1.4.0 and Frugal only
  count a tool by its program or own config file, `~/.gemini` alone is not Gemini CLI) and Hermes homes have a
  `config.yaml`; new: every found tool (also Qwen Code, opencode) connected with `--mcp` and Frugal's hosts, re-run
  identical, uninstall byte-identical; dry-run plan; `report` (56 tests).

## v1.0.9 (2026-11-11)

- Frugal-Bridge `45a0440` vendored from GitHub (was `7e4cf9e`): new `frugal-tiers` plugin gives each helper a
  cheap / mid / top model from Frugal's routing table, mapped to the parent's provider (tools with a delegation
  backend, e.g. Hermes). It is copied with the other plugin; turning it on stays the user's step (setup prints the
  two commands and the undo). Uninstall removes only its files and puts `delegation.backend` back when it still
  names `frugal-tiers`. The rules now tell agents to pass the tier's model on a subagent call.

## v1.0.8 (2026-11-11)

- Frugal-Bridge `7e4cf9e` vendored from GitHub (was `16a2b9c`): its adapters (Hermes plugin, hooks, proxy) now name
  the start files in every install order. The knowledge base is found the same way Frugal's setup finds it, fresh
  each session (a base connected or removed later is used without re-installing), and a folder slot such as
  `wiki/me/` is listed as its `.md` files. Before, the Hermes plugin gave no start hint after a user-level install.
- Test: after one install the copied Hermes plugin names the base's `hot.md` and every `wiki/me/*.md`, also for a
  base path with spaces.

## v1.0.7 (2026-11-11)

- Frugal-Bridge `16a2b9c` vendored from GitHub (was `3c86a64`): its tests run with an isolated HOME/FRUGAL_HOME (conftest), so a real install on the machine can't change a result. No code change.

## v1.0.6 (2026-11-11)

- Skeleton Base 1.3.5 (`e66997f`) vendored from GitHub (was `64acace`): `connect` lets every tool read and write
  the base from any folder through its own allow list (Claude Code, Codex, Gemini CLI, Qwen Code, opencode),
  recorded and removed by the base.
- The Mothership no longer adds the base to Claude Code's `additionalDirectories` itself (it was Claude-only and
  could leave two owners for one entry). An entry an older Mothership added is handed over to the base on the
  next install run; uninstall of old records still removes it. `check` now checks every tool's allow list the base
  recorded.
- Test: one entry, owned by the base, old record handed over, `check` sees a lost entry, uninstall gives the home
  back byte-identical (52 tests).

## v1.0.5 (2026-11-11)

- Frugal-Bridge `3c86a64` vendored from GitHub (was `4920444`): its uninstall never loses user data (only unchanged own files removed, edited blocks saved to `kept/`) and leaves no empty leftovers.
- Test: the vendored Frugal-Bridge suite check accepts any test count with 0 failed.

## v1.0.4 (2026-11-11)

Uninstall keeps your data (owner rule: removing The Mothership or Skeleton Base never loses the user's data).

- Skeleton Base 1.3.4 (`64acace`) vendored from GitHub (was `81ca8ed`): its own uninstall backs up first and keeps
  edited maps, edits inside its blocks and your settings layout.
- `uninstall` stops the watcher, then writes a full backup of the base (`.git`, dotfiles) to
  `~/skeleton-base-backups/NAME-YYYYmmdd-HHMMSS.tar.gz` (mode 600, folder 700), checks it, prints its path and a
  restore command; a failed backup stops the uninstall with nothing changed. `--backup-dir DIR`, `--no-backup`.
- `--purge` needs the base's folder name typed (or `--yes-purge-NAME`; `--confirm-purge` takes the name or the
  path), refuses `--no-backup`, and backs up first. Before: it took the full path and deleted with no backup.
- Fixed data-loss paths found in the audit:
  - the empty-folder sweep after uninstall/rollback also removed empty folders inside `.git` (e.g. `refs/tags`)
    and folders that were in the base before the install: now never inside `.git`, never a folder that was there
    before (`base_dirs_before`);
  - backup copies made by the products (`.brain/backups/`, `.frugal-bridge/backup/`, `.base-folder/backup/`,
    `~/.frugal-bridge/backup/`) were deleted: now moved into `NAME-product-backups-TIME.tar.gz` (mode 600);
  - `update` (Frugal-Bridge's project install) overwrote Frugal-Bridge skill files you edited in
    `.claude/skills/`, and its uninstall removed them: both now keep your version;
  - a Skeleton Base map you edited made `update` fail (map exit code): the map step is a note now;
  - a failed install into an existing non-empty folder: that folder is backed up first; rollback leaves it
    byte-identical (product backups are moved out);
  - `originals/` (your settings from before the install) is kept when one of them could not be put back.
- Safety net: after the products' uninstall, any file that was in the base, is gone and is not a product file byte
  for byte is put back from the backup archive.
- After uninstall: what was kept and where (per folder, git history) and how to re-open or reinstall.
- Tests: 51 (50 by default + the opt-in real Claude Code test). 7 new: a rich base (pages, raw incl. collected
  and sqlite-sourced items, cards, edited template/agent/map/Frugal skill, `hot.md`, `progress/agents.log`, user
  text in `AGENTS.md`, 3 git commits, `.brain` state, unknown files, a symlink) through `update` and `uninstall`:
  every user file byte-identical, git intact, archive mode 600 restores the exact tree, home back, reinstall adopts
  without loss or duplication; purge without the name refuses, with it backs up first; `--no-backup`; backup
  failure stops; failed-install rollback keeps an existing folder byte-identical (5 steps); a faulty product
  uninstall is caught by the safety net; disconnect changes nothing in the base but `.kits.json`. Home trees in
  tests skip `~/skeleton-base-backups` (checked by these tests).

## v1.0.3 (2026-11-11)

- Skeleton Base 1.3.3 (`81ca8ed`) and Frugal-Bridge 6 (`4920444`) vendored from GitHub (were `d036212` and
  `a84e5ec`); nothing excluded.
- Frugal-Bridge finds the base without a tool rules file (`--base`, the base's pointer file
  `~/.config/skeleton-base/base`, its systemd units): a home whose only tool is Hermes without `SOUL.md` now has one
  user file, the base. Skeleton Base writes and removes the pointer file with `connect` / `disconnect`.
- Skeleton Base `disconnect` (when Frugal-Bridge still uses the base) removes everything Frugal-Bridge could find
  it from, then makes it forget the base and re-runs it, so it really goes back to its own user file.
- Tests: 44 (43 by default + the opt-in real Claude Code test); the Hermes-without-`SOUL.md` test now also checks
  the pointer file and that Frugal-Bridge uses the base (no `~/.frugal-bridge/USER.md`).

## v1.0.2 (2026-11-11)

- Frugal-Bridge 6 (`a84e5ec`) vendored from GitHub (was `c2841b1`); Skeleton Base 1.3.2 (`d036212`) unchanged.
- Frugal-Bridge ships complete: its `README.md`, `LICENSE` (MIT notice) and `docs/DESIGN.md` are no longer left
  out (`excluded` is empty for both components). `LICENSE` and `README.md` name both components' own MIT licenses.
- Base paths with spaces now work with Frugal-Bridge too: the vendored one reads the quoted `Path:` line. The
  installer still refuses such a path, before writing anything, when the Frugal-Bridge kit it would use has no
  `parse_base_path` (older kit).
- A Hermes folder without `SOUL.md` stays without it after install and uninstall (Frugal-Bridge no longer creates
  it; it says what to do instead).
- Tests: 44 (was 41; 43 run by default, the real Claude Code test is opt-in): install + uninstall with a base
  path containing spaces and Frugal-Bridge (byte-identical, re-run byte-identical), refusal with an older
  Frugal-Bridge, Hermes without `SOUL.md`.

## v1.0.1 (2026-11-11)

- Skeleton Base 1.3.2 (`d036212`) vendored from GitHub; Frugal-Bridge 6 (`c2841b1`) unchanged.
- A tool installed later gets both blocks (base first) from the watcher alone: Skeleton Base 1.3.2 runs
  Frugal-Bridge's `install --global --hosts TOOL` for it.
- Adopting an existing base never downgrades it: a base whose Skeleton Base release is newer than the vendored one
  is kept as it is (said in the plan and the summary, recorded as `base_kept` in `.mothership.json`); `--force`
  installs the vendored version over it. Also for `update`.
- Lint findings in your own pages are warnings: `install` exits 0 and lists them (`WARN lint: ...`); `check` lists
  them too and exits 1 only for install problems (missing blocks, block order, watcher stopped, lock mismatch,
  Frugal-Bridge checks).
- Base paths with spaces: allowed with `--no-frugal` (Skeleton Base quotes them everywhere); with Frugal-Bridge
  still refused before anything is written, because the vendored Frugal-Bridge reads the path only up to the first
  space. An already connected base is found from a quoted `Path:` line too.
- Tests: 41 (was 37), plus the opt-in real Claude Code test.

## v1.0.0 (2026-11-11)

First release.

- `install.py`: one install for Skeleton Base 1.3.1 (`d952670`) and Frugal-Bridge 6 (`c2841b1`), vendored at
  pinned commits and checked against `components.lock` (sha256 manifest per component) before anything is written.
- Order from the products' coexistence contract: base, Frugal-Bridge in the base, connect (user-level pointer
  blocks, hooks, systemd user units), Frugal-Bridge `install --global` using the base as its only user file.
- Claude Code can read the base from any folder (`permissions.additionalDirectories`, recorded and removed again).
- Frugal-Bridge's `global.json` gets a `kit` path to a stable copy, so the base's watcher can re-run its setup
  without any environment variable.
- `check`, `status`, `update`, `uninstall` (`--keep-backups`, `--purge` with confirmation).
- Existing Skeleton Base or Frugal-Bridge installs are adopted (Frugal-Bridge `USER.md` merged into `wiki/me/`).
- Idempotent (re-run is byte-identical), rollback on failure during a first install, resume after an interrupted
  install, uninstall restores your files byte for byte (JSON settings keep their original layout).
- `tools/update-components.py` re-vendors from GitHub or a local path and rewrites the lock.
- Tests: `python3 -m unittest` (isolated HOME), including both products' own suites from the vendored copies.
