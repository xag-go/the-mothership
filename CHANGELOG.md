# Changelog

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
