# AGENTS.md — Frugal-Bridge CORE rules (token use + quality)

Every agent reads this first: the main agent, its helpers, and every new agent. Host-specific rule files only say
"read AGENTS.md". These rules come from A/B tests (3+ runs, blind judge, real checks). Quality comes first:
a saving that lowers quality is not allowed.

## 1. Roles
- **Main agent** = the agent the user talks to. The user gives it any name (set in `USER.md`); these rules call
  it "the main agent". It plans, decides, routes work and keeps the files. It is a manager:
  big or bulky work goes to helpers, so its own chat stays small.
- **Helpers** = subagents or other agents. They get a short brief, do one job, write long results to a file and
  return a short summary (max ~10 lines). **Check a helper's result before passing it on** (spot-check it against
  the source, or run the test) and say what you checked.
- The main agent asks the user only at big moments: a new session, a real decision, something risky. Small things it does.

## 2. Model and effort (set at session start, never changed inside a chat)
Tiers: **cheap / mid / top**, mapped to real models in `ROUTING.md` (the setup fills it per provider).
Effort: **medium** by default. Never **low** for real work. No **xhigh/max** (much higher cost, no gain in tests;
max can return nothing).

| Kind of work | Tier |
|---|---|
| The main agent itself; hard decisions; project plans; architecture | top, medium |
| Writing in a language cheaper models handle badly (e.g. Moroccan Darija) | top, medium |
| Public writing (English) | mid, high |
| Data analysis memos; partner thinking, brainstorming | mid, medium (memo that drives a decision → top) |
| Checkable work: bug fixes and small features with tests, extraction, fact-check, scheduling, formatting, small clear design | cheap, medium |

- To use another tier, send the work to a helper on that tier. Do not switch the chat's own model.
- The main agent runs on top, so **checkable work (code with tests, extraction, formatting) goes to a cheap helper**,
  not done by the main agent itself. Small replies (noting a preference, a short answer) it does itself, no helper.
- **Checkable work starts cheap and moves up only on a real failed check** (tests fail, exact answer wrong):
  cheap → mid (high) → top (medium). Move to a bigger model, not only more effort: a misread spec stays misread.
  The check must come from the task (acceptance tests, the expected answer), not only tests the agent wrote itself —
  those pass on a misread spec.
- **Judgment work goes straight to the right tier.** A rule check (word count, script, keywords) does not show
  quality, so a cheap answer would never be escalated.
- **One reviewer per piece of work**, model picked by the stakes. A second reviewer only on a real signal (failed
  test, disagreement, high-stakes release). "Low confidence" is not a signal.
- Helpers are not a way to save money. Use them for size, parallel work, isolation, or bulk material.

## 3. Sessions
- Propose a **new session** (one line, the user says yes/no) when: a task is done; the user switches to an unrelated
  task; the chat passes **150k tokens** (at **300k** propose at once); the chat went quiet past the cache life and a
  new task starts. Cheap-tier agents hand off **before 100k** (price step).
- **Every time the user switches to another topic**, add one short line **at the end** of the reply: new session +
  handoff (default) / compact (same task, big chat, at a task boundary) / carry on (small side question). The
  answer itself follows the user's format (e.g. opinion in the first line).
- Answer what was asked; no extra proposals or reopening settled facts and decisions unless the user asks.
- **Before any new session, save pasted raw material** (transcripts, docs, data) verbatim to `sources/`. A handoff
  keeps only what was asked; the rest is lost unless the source is in a file.
- Large inputs go to a file and to a cheap helper; only the result enters the main agent's chat.

## 4. Files (read a few small files, not the history)
| File | Holds | Read |
|---|---|---|
| `USER.md` | the user's preferences, language, answer style, the main agent's name | every session |
| `MAP.md` | where things live (projects, memory, docs, skills, agents) | when you need to find something |
| `PROJECT.md` | goal, audience, price, stack, constraints | session start on that project |
| `PROGRESS.md` | current task, next step, short handoff (max ~10 lines) | every session |
| `DECISIONS.md` | append-only: decision, why, what was rejected | search when a past decision matters; never read whole |
| `ROLE.md` | an agent's job title, duties, tools, tier, effort | that agent, every session |
| `sources/` | raw material saved verbatim | on demand |

These are default names. If `.kits.json` exists, read the paths from its `slots` (now = PROGRESS, user = USER,
decisions, map, sources): another kit, e.g. a knowledge base, may own those files. Never create a second copy.
- Update a file as soon as something is stated, not only at the end: a preference → `USER.md`, a project fact →
  `PROJECT.md`, a decision → one line in `DECISIONS.md` (decision, why, rejected) — **every** decision the user gives, with
  its reason, even several at once in the first message. Files hold short lines, not prose.
- A question about changing something ("someone said sell at 1500?") is not a decision: the stated value stays
  settled until the user decides otherwise; do not log it as open.
- `PROGRESS.md` = only the current task and the next step (max ~10 lines), rewritten each time, never appended.
  Before a new session add a handoff there with only what is not already in the other files (sources saved, open
  questions, reasons the user gave that are not decisions).
- At session start read `USER.md`, `PROGRESS.md` (and `PROJECT.md` for project work) in **one** call; grep
  `DECISIONS.md` only when a past decision matters. Create a missing file only when you have something to put in it.
  No other files (no MAP.md for one project, no copies of answers) unless the user asks for a document.

## 5. Calls and outputs
- **Filter big outputs before reading them** (grep for errors, tail, quiet flags). Never read a huge log or test
  output in full.
- Wait inside one command instead of polling a status again and again.
- Same call twice → use the earlier result. Same error twice → stop and rethink the cause. Three failed approaches →
  move up a tier or ask the user one clear question.
- No "make fewer calls" pressure: look at as much as the task needs.
- Plan in `PROGRESS.md` only for big, unclear tasks.

## 6. Tools and background work
- Each agent gets only the tools its job needs; load the rest on demand (deferred) where the host allows.
- Background runs (heartbeats, scheduled checks) check for changes first and skip the model when nothing changed.
- "Task completed" notices go to a log or board, not into the main agent's chat.

## 7. Cache
- Keep the start of the prompt (rules, tools, memory files) unchanged during a session. Edits apply next session.
- Cache length per provider, chosen by the setup (`ROUTING.md`).

## 8. Changing these rules
Nothing changes without a test: same tasks, 3+ runs, cost of the whole flow per finished task (not one part),
real checks first, blind judge second, a human rater for language/tone. One place first, with Undo. The rules change only in a new session.
