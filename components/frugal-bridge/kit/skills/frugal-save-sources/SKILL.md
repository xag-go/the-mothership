---
name: frugal-save-sources
description: "Use when the user pastes long material. Saves it to a file before work."
---

# Save sources

When the user pastes or attaches long material (transcript, document, data, email thread, > ~40 lines):
1. Write it verbatim to the sources slot (`sources/` by default, see `.kits.json`): `sources/<YYYY-MM-DD>-<short-topic>.<md|txt|csv>`.
2. Note the path in `PROGRESS.md` (Sources line).
3. Work from the file: grep/read the parts you need, or hand the file path to a cheap helper for extraction and
   keep only its result in the chat.
A handoff keeps only what was asked; anything not in a file is lost at the next session.
