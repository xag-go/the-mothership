# Changelog

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
