---
name: frugal-new-session
description: "Use when the topic changes or the chat is long. Offers new session/compact/carry on."
---

# New session check

Offer one short line **at the end** of your reply when any of these is true:
- the task is done, or the user switched to an unrelated topic;
- the chat is past ~150k tokens (at ~300k say it plainly); a cheap-tier agent past ~100k;
- the chat sat idle past the cache life and a new task starts.

Line format: `New topic → new session (handoff ready) / compact / carry on?`
- new session (default): run the `frugal-handoff` skill, then the user opens a fresh chat.
- compact: same task, big chat, at a task boundary — save sources to files first.
- carry on: a small side question.

Never switch the chat's model to save money; send the work to a helper instead.
