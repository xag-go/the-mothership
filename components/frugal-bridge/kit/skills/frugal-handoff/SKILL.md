---
name: frugal-handoff
description: "Use when a task ends or a new session is due. Writes the short handoff."
---

# Handoff (before a new session)

File names below are Frugal's defaults. If `.kits.json` exists, use its `slots` paths instead (now, user,
decisions, map, sources) — a base folder may own them.

1. Save any pasted raw material (transcripts, docs, data) verbatim to `sources/<date>-<topic>.<ext>` if not saved yet.
2. Make sure every decision of this session is a line in `DECISIONS.md` (decision | why | rejected).
3. Put new preferences in `USER.md`, new project facts in `PROJECT.md`.
4. Rewrite `PROGRESS.md` (max ~10 lines):
   ```
   ## Current task
   <one line>
   ## Handoff
   - Done so far: <paths>
   - Not in other files: <reasons the user gave, open threads>
   - Sources: sources/...
   - Next step: <exactly one>
   - Open questions: <for the user>
   ```
5. Tell the user in one line: "Saved. Start a new session; it will read USER.md + PROGRESS.md."

Do not copy the chat. Do not repeat what is already in DECISIONS/USER/PROJECT.
