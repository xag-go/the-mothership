# The Mothership: design

One install that brings two separate products together and makes them work with each other:

- **Skeleton Base**: a knowledge base ("second brain") as a folder of Markdown files, plus `tools/brain.py`.
- **Frugal-Bridge**: token-saving rules and adapters for AI tools, plus `kit/setup.py`.

The Mothership adds no third set of rules. It ships both products, runs each product's own setup in the order
their coexistence contract asks for, checks the result, and can undo everything again.

## 1. How the components are shipped: vendored at pinned commits

```
components/skeleton-base/          the public repository at one commit (git archive: tracked files only)
components/frugal-bridge/          the same for Frugal-Bridge
components/skeleton-base.manifest  "sha256  path" for every file, sorted
components/frugal-bridge.manifest
components.lock                    per component: repo URL, commit, version, sha256 of its manifest, file count
tools/update-components.py         re-vendor from the public GitHub repos (or a local path) and rewrite the lock
```

`tools/update-components.py --exclude-words FILE` leaves out upstream files that contain a word the maintainer
never wants in this public repository (names, organisations); the lock lists them under `excluded`. Only
documentation was left out this way (Frugal-Bridge `README.md`, `LICENSE`, `docs/DESIGN.md`); nothing the setups
or tests use. The lock names repositories as `https://github.com/<owner>/NAME`, `<owner>` being the owner of this
repository's `origin` remote.

`install.py` first recomputes every manifest and compares it with the lock. Any changed, missing or extra file
stops the install before anything is written. The install then works fully offline: no network, no `git`, no
package manager.

Alternatives considered:

| option | why not |
|---|---|
| git submodules | a plain "Download ZIP" or `git clone` without `--recursive` gives empty folders; needs `git` at install time; no content hash the installer can check by itself |
| download at install time | needs network and trust in whatever the network returns at that moment; breaks offline installs; versions drift |

Vendoring costs some repository size (both products are small text files) and needs an explicit update step,
which is what `tools/update-components.py` is for. Each product stays its own product: The Mothership never
edits vendored files, and the products never depend on The Mothership.

## 2. Where things go

| what | where | why |
|---|---|---|
| the base | `--base DIR`, default `~/skeleton-base-home` | a plain folder the user owns |
| a stable copy of The Mothership (install.py, lock, components) | `$XDG_DATA_HOME/the-mothership/payload` (default `~/.local/share/the-mothership/payload`; `MOTHERSHIP_HOME` moves it) | the clone may be deleted; the watcher still finds Frugal-Bridge's setup for zero-touch re-runs, and `uninstall` works from there |
| install record | `DIR/.mothership.json` | what was installed or adopted, options, created folders and backups |
| pointer to the base | `$MOTHERSHIP_HOME/installed.json` | so `check`, `status`, `update`, `uninstall` need no arguments |
| progress journal | `$MOTHERSHIP_HOME/journal.json` | only while an install runs; an interrupted install resumes from it |

Frugal-Bridge is never placed inside the base (the two products stay separate).

## 3. Install order (coexistence contract: base first, Frugal second)

1. verify `components.lock`; stage the payload copy
2. `brain.py init DIR --frugal=no` (Skeleton Base; its own Frugal question is answered by The Mothership). Skipped
   when the base already has a newer Skeleton Base (its `.kits.json` `release` or `RELEASE` in its `brain.py` is
   higher than the vendored one and its `brain.py` differs): never downgraded, said in the summary, `--force` overrides
3. `kit/setup.py install DIR` (Frugal-Bridge in the base: it sees the base and makes no second USER/PROGRESS files)
4. `DIR/tools/brain.py connect --base DIR --watch` (user-level pointer blocks, hooks, systemd user units on Linux)
5. `kit/setup.py install --global` (Frugal-Bridge at user level: finds the base through the block's `Path:` line,
   uses the base slots, puts its block after the base block)
6. write `"kit"` into Frugal-Bridge's `global.json` (pointing at the payload copy) so Skeleton Base's watcher can
   re-run Frugal's setup later without anybody setting `FRUGAL_BRIDGE_KIT`
7. Claude Code: add the base to `permissions.additionalDirectories` in `~/.claude/settings.json` (recorded,
   removed on uninstall). Without it a real `claude -p` started in another folder was refused reading the base
   ("outside this session's allowed directory"); with it, it answered from the base.
8. `connect` again, then `map` (a fixpoint: the base records the final state of `~/.claude/settings.json`; without this a
   second install run would not be byte-identical; `map` redraws pages an import added)
9. systemd: `--yes` runs `systemctl --user daemon-reload && systemctl --user enable --now ...` when
   `systemctl --user` works; otherwise the command is printed. macOS: the watcher is skipped and said so
   (hooks still collect at session end; `brain.py watch` runs it by hand)
10. checks: `brain.py check`, Frugal `check DIR` and `check --global`, the lock, the watcher, plus the contract
   checks of The Mothership (one base block and one Frugal block per file, base block first, Frugal uses the
   base as its only user slot). These are install problems: `install` / `check` exit 1. `brain.py lint` is about
   the user's own pages: its findings are printed as warnings and never change the exit code

A Frugal-Bridge that was installed at user level before is **adopted**: step 4 imports its `USER.md` into
`wiki/me/` (Skeleton Base's own import, never overwriting). An existing base is adopted the same way. Adopted
parts are never removed by `uninstall`.

## 4. Idempotent, recoverable, reversible

- Re-run: every product setup is idempotent; `.mothership.json` holds no timestamps. Second run = byte-identical.
- Failure on a fresh install: the steps done so far are undone with each product's own uninstall (rollback).
- Interrupted (killed) install: the journal says what this install owns; the next run continues and the parts it
  made are still treated as its own, not as "found".
- Uninstall, reverse order: systemd units it enabled; Frugal `uninstall --global`; `brain.py disconnect`;
  Frugal `uninstall DIR`; `brain.py uninstall DIR`. JSON settings files that existed before are copied first
  (`$MOTHERSHIP_HOME/originals/`, mode 600, never into the base); when the undo leaves the same JSON in another
  layout, the original bytes are put back. Then the backups the products made during these runs
  (`--keep-backups` keeps them), empty folders it created, the payload copy. Pages you wrote stay
  (`--purge` deletes the whole base after you type its path).

## 5. Limits

- Base path with spaces: Skeleton Base 1.3.2 quotes it everywhere (`Path: "..."`, shell commands, systemd
  units). The vendored Frugal-Bridge 6 reads the `Path:` line only up to the first space, so with Frugal-Bridge the
  installer refuses such a path (nothing written); `--no-frugal` installs it. The check looks at the Frugal-Bridge
  kit itself (a version that reads quoted paths has `parse_base_path`), so a re-vendored Frugal lifts it.
- `systemctl` parts run only where `systemctl --user` works. No launchd agent.
- A tool installed later: the watcher writes the base pointer and runs Frugal-Bridge's `install --global --hosts
  TOOL` for that tool alone (Skeleton Base 1.3.2), so it gets both blocks without another `install.py` run.
- Gemini CLI and other tools that limit file access to the working folder may still ask before reading the base;
  only Claude Code's access is configured (tested with a real `claude -p`).
- Adopting an existing base applies the vendored Skeleton Base version to it (same as re-running its `init`).
