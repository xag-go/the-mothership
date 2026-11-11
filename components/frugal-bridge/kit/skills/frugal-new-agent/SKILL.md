---
name: frugal-new-agent
description: "Use when the user wants a new agent. Creates its ROLE.md."
---

# New agent

1. Ask only what is missing: job title (renameable), duties, which tools, who it talks to.
2. Pick tier/effort from the work it will do (ROUTING.md); default medium effort.
3. Write `agents/<slug>/ROLE.md` from templates/ROLE.md: title, duties, tools (only what the job needs), tier,
   effort, reports to the main agent, files it reads every session (AGENTS.md, ROLE.md, + USER.md if it talks to
   the user).
4. Add one line to the map slot (`MAP.md` by default, see `.kits.json`) (Team: <agent> = <title>, path).
5. Background agents: give them a check-first rule — look for changes, skip the model when nothing changed.
