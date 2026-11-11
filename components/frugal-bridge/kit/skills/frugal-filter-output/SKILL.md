---
name: frugal-filter-output
description: "Use before running commands with big output (tests, logs, builds, browser)."
---

# Filter big outputs

Before a command that can print a lot:
- tests: `pytest -q 2>&1 | tail -25` (or `--tb=line`), failures first;
- logs: `grep -E "ERROR|Traceback|FAIL" file | tail -20`, then read around the match;
- builds/installs: quiet flags (`-q`, `--silent`), `tail` the end;
- big files: `wc -l`, `head`, `grep -n`, then read the needed range only;
- web/browser: extract the needed fields, not the full page.
Wait inside one command (`timeout N cmd`, a loop that exits on done) instead of polling status again and again.
Same call twice → reuse the earlier result. Same error twice → rethink the cause.
