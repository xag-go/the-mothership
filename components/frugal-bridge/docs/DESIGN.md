# Frugal-Bridge — design

Status: design only. Nothing built yet.
Last update: 2026-11-10 (test results from `abtest/RESULTS.md` folded in).

How this doc is kept: every idea from the discussion lands here — in "Agreed" (2, 8),
"Proposed" (12), "Rejected" (11) or "Open" (13). Verification results go to "Findings" (Appendix E)
as they arrive.

Naming: the main agent is called "the Chief" in this doc for short; in use, each user names it as they like
(set in USER.md).

Scope rule: this system is **not tied to any product, host, provider or person**. Anyone can take it
and run it in any AI agent, harness or chat app, with any provider and model. Host and model names in
this doc are examples or sources, never requirements. Numbers measured on one real setup are kept as
evidence in Appendix E, without naming that setup.

## 1. Goal

A portable system you set up once in any AI. It cuts token use and keeps quality high.

- The user does not have to think about tokens. The main agent (the Chief) applies the rules and only
  asks yes/no at big moments: new session, big decisions.
- Every subagent and every new agent/bot inherits the same rules automatically.
- Quality comes first. A saving that lowers quality is rejected.
- Works with anything: any AI agent (personal assistants, coding agents, team/company agent platforms,
  chat apps, custom API agents), any harness, any provider (Anthropic, OpenAI, Google, xAI, OpenRouter,
  local models…), any model. On install it adapts to what the host can do (section 5).
  Examples of hosts: Claude Code, Codex, Gemini CLI, Cursor, OpenClaw, Paperclip, Grok, ChatGPT,
  Claude.ai, Gemini app, a custom agent on the raw API.
- The form (kit, skill, plugin, agent) and the name are decided last. The solution comes first.

## 2. Summary of what is agreed

| # | Topic | Agreed |
|---|---|---|
| 1 | DNA | CORE lives in AGENTS.md. The Chief, subagents and new agents all inherit it. Host-specific rule files (CLAUDE.md, GEMINI.md, system prompts…) are one-line pointers: `@AGENTS.md` (an import; tests showed a prose "read AGENTS.md" line does not load it). |
| 2 | Layers | CORE + skills + adapter + a quality gauge. Adapter = native plugin/hook where the host has one, else the proxy adapter (any host with a configurable API base URL); chat apps get CORE only (advise, not enforce). |
| 3 | New session | The Chief proposes it when a task is done, when the user switches task, or when the context passes a fixed size (~150k). It writes the handoff itself; the user says yes or no. **Before any reset, raw material pasted in chat (transcripts, docs, data) is saved to files**; if that is not possible, compact at the task boundary instead (XL2: reset without saved inputs lost 24/24 reasons; with inputs saved, reset kept 24/24 at −90%; compaction 24/24 at −51%). |
| 4 | Project files | USER, MAP, PROJECT, PROGRESS, DECISIONS (+ ROLE per agent) so a new session, agent or subagent reads a few small files, not the history (section 6). Tested over 5 sessions: same quality as one handoff file at −45% cost. |
| 5 | Calls | Filter huge outputs (tested: −63…−75%, context 6× smaller), no polling, loop detection. No "fewer calls" pressure (tests S/L: no saving, quality down). |
| 6 | Loops | Same call or same error twice → stop and rethink. No call limits. |
| 7 | Subagents | Short brief in, short summary out. Only for size, parallel work or isolation — **not to save money** (forced delegation cost 1.5–5.7× with equal quality). |
| 8 | Tools | Each agent gets only the tools its job needs; the rest deferred (40 loaded schemas cost +36% on a cheap model; deferred ≈ 0). |
| 9 | Routing | Model **and effort** are chosen per agent at session start and never change inside a chat. Other work is routed by sending it to a subagent or another agent that has the right model + effort. **By kind of work** (rule 7 table): checkable work starts cheap and escalates on a real failed check; judgment work (writing for the public, Darija/other languages, decisions, partner thinking) goes straight to the right model. Effort: medium default, never low, no xhigh/max. Tiers are abstract and mapped per provider (sections 8 and 9). |
| 10 | Map | Three levels: short index always loaded, area maps on demand, code graph (Graphify-style) for code projects (section 7). |
| 11 | Planning | Only for big, unclear tasks, written in PROGRESS.md (a plan rule on clear multi-file tasks: no gain, +7% cost). The Chief asks only on big decisions. |
| 12 | Task switch | One line with choices: new session + handoff (default), compact, carry on. |
| 13 | Cache | Keep the prompt start stable; cache length chosen per provider by the gap between turns (section 10). Anthropic: 5 min default; 1 h only across long pauses (1 h cost +11% in continuous work). |
| 14 | Visibility | Daily usage table + alerts (long chat, price step, runaway chat) — reference script `abtest/usage_report.py`. No budgets, no caps. |
| 15 | Proof | Nothing ships before a test (3+ runs, blind judge), one place first, with Undo. |
| 16 | Rejected | Compaction in the middle of a step, pruning tool results, splitting skills, "fewer calls" rules, hard call caps, mid-chat model/effort switch, low effort for real work, xhigh/max effort, subagents for saving, cheap-first cascade on judgment work (section 11). |

## 3. Why tokens get used

Rule of thumb: **cost ≈ number of calls × context per call**, priced per token type.
Every call re-reads the whole context. The model writes little, but what it writes (output, including
thinking) is the most expensive token type, so effort matters too.

Evidence from one real multi-agent setup: ~156k tokens of context per call on average,
93.7% of tokens were cache reads, output only 0.6% of tokens but ~26% of the priced cost on the main model,
and sessions over 300 calls took 44% of the cost.

### The 11 causes
1. Long chats: each message grows the context and every call re-reads all of it.
2. Many small calls: read, wait, read again. Each one is a full re-read.
3. Subagents and worker agents: each starts with its full fixed prompt and re-reads the same files.
   Duplicate checkers pay again.
4. Fixed prompt on every call: tool schemas, system prompt/persona, memory, skills index.
5. Big tool outputs (files, web pages, logs, browser dumps) stay in the context and get re-read on every later call.
6. Loaded skills stay in the context for the rest of the session.
7. Huge context windows (1M on current top models): hosts often compact late, so chats grow very large first.
8. The cache dies after a few minutes of silence (provider-dependent). Coming back after a pause
   re-writes the whole context at a higher price.
9. The top model for everything, easy and hard work alike.
10. Retries and loops: errors, the same file read twice, the same failed command again.
11. Effort set higher than the task needs: more thinking, and more and longer tool calls.

## 4. Architecture

```
CORE (AGENTS.md)          the DNA: token + quality rules, inherited by everyone
 ├─ Chief                 CORE + routing + context management + handoff
 │   └─ Subagents         short CORE + task brief, return a short summary
 ├─ New agents/bots       template: CORE + ROLE + tools + model tier + effort
 ├─ Project files         USER, MAP, PROJECT, PROGRESS, DECISIONS (section 6)
 ├─ Maps                  index → area maps → code graph (section 7)
 ├─ Skills                handoff, plan-first, stop-loop, delegate…
 ├─ Adapter (per host)    counts context, sets model/effort per agent, injects CORE, sets toolsets
 └─ Gauge                 test before/after with a blind judge
```

| Layer | What it is | Works in |
|---|---|---|
| CORE | Plain markdown rules | Every AI: rules files, system prompt, custom/project instructions, first message |
| Skills | Step-by-step procedures (SKILL.md or the host's equivalent) | Hosts with a skills system; elsewhere folded into CORE |
| Adapter | Thin code layer per host that enforces the rules | Hosts with hooks, plugins, middleware, or an API you control |
| Gauge | Same tasks run before/after, judged blind | Runs from outside, works for all |

- AGENTS.md is the single source. Other rule files are one-line pointers.
- Rules alone are a "should": agents forget them as chats grow. The adapter makes them a "must"
  (real context counts, CORE injected into every subagent without the agent remembering).
- Three adapter levels , so enforcement does not depend on the host having hooks:
  1. **Native adapter** (plugin/hook) for the big hosts: Hermes, Claude Code; Codex / Gemini CLI / Cursor /
     OpenClaw if their hooks allow (to verify).
  2. **Proxy adapter** (`adapter/proxy/`) for ANY host that lets you set the API base URL: sits between host
     and provider, sees every call, enforces context watch, loop guard, output filter, start files, optional CORE,
     usage log. Keys pass through, nothing stored. Limit: it cannot open a new session itself; it makes the agent
     tell the user, with the handoff ready.
  3. **Chat apps** (ChatGPT, Claude.ai, Gemini app): no base URL, no hooks → CORE as project instructions +
     "one session per task"; optional browser extension that counts chat length. No 100% enforcement there.
- The Chief is a manager, not a worker. If it does all the work itself, its own context grows and it
  becomes the biggest spender.
- One core, many adapters: the core never names a host; each adapter is a thin layer for one host.

## 5. Plug into any host and adapt

On install the system detects what the host can do and turns on only what that host supports.

| Capability the host may have | If yes | If no (fallback) |
|---|---|---|
| Reads a rules file / system prompt / custom instructions | Load CORE there | Paste CORE as the first message or project instructions |
| Skills (SKILL.md or similar) | Install the skills | Fold the key steps into CORE |
| Hooks / plugins / middleware / own API loop | Adapter enforces: context counter, new-session prompt, CORE injection into subagents | The Chief follows CORE by itself and asks the user |
| Subagents or multiple agents | Delegation + routing to other tiers | Single agent; pick model + effort at session start |
| Model and effort choice per agent | Tier routing | One model; rules for calls, context and sessions still apply |
| Prompt caching with TTL control | TTL by pace, per provider (section 10) | Keep the prompt start stable anyway |
| Usage / limit API or logs | Daily table + alerts | Count from the host's own logs, or skip |
| Several providers | Map each tier to the best model per provider | Map tiers within one provider |

- Model tiers are abstract: **cheap / mid / top**, each with an effort level. At setup they are mapped to
  real models of whatever provider is connected. New models = update the map, not the rules.
- Prices and limits differ per provider, so the mapping uses measured cost per finished task, not model names.

## 6. Files: who reads what, and when

Goal: a new session, a new agent or a subagent reads a few small files instead of the whole history.

| File | Holds | Written by | Read when | Size target |
|---|---|---|---|---|
| AGENTS.md (CORE) | Rules for tokens and quality, routing table, session rules | User + Chief (rare changes, never mid-session) | Always, every agent | Short (~1–2k tokens) |
| USER.md | Who the user is: language, style, how they want answers, what they decide themselves | Chief, when the user states a new preference | Always (Chief and agents that talk to the user); not subagents | Short |
| MAP.md | Level-1 index: where memory, projects, decisions, docs and skills live; who does what | Chief, when something moves | Always | 20–30 lines |
| PROJECT.md | What the project is: goal, users, stack, constraints, links | Chief at project start, rare updates | Session start on that project | Short |
| PROGRESS.md | Now: current task, plan with checkboxes, next step, blockers, and a "start here" handoff block | Chief at the end of every step and before a new session | Session start (only the "now" part) | Small; done items move to an archive |
| DECISIONS.md | Append-only log: date, decision, why, what was rejected | Chief after each real decision | On demand, searched by topic, never read whole | Grows; searched, not loaded |
| ROLE.md (per agent) | Renameable job title, responsibilities, allowed tools, model tier + effort | User/Chief when the agent is created | Always, for that agent | Short |
| Archive files | Finished PROGRESS items, old handoffs | Chief | Only when an old detail is needed | Unlimited |

Read order:
1. Always: AGENTS.md + MAP.md (+ USER.md for agents that talk to the user, + ROLE.md for agents).
2. Session start on a project: PROJECT.md + the "now" part of PROGRESS.md.
3. On demand only: DECISIONS.md (search), area maps, the code graph, archives.
4. Subagents: CORE-lite + the brief. They get exact file paths in the brief, not the file list.

Rules:
- Size targets are targets, not hard limits. The adapter warns when an always-loaded file grows past
  its target, so the Chief can trim or move details out.
- Keep the start of the prompt stable mid-session (CORE, tools, memory) so the cache keeps working.
  Edits to always-loaded files take effect in the next session.

### Handoff block (in PROGRESS.md)
Written by the Chief before a new session or a compact:
- What we were doing and why
- Done so far (with file paths)
- Decisions **with their reasons**, and reasons/context the user mentioned even if nobody asked for them yet
- Where the raw inputs are saved (sources/ files) — anything pasted in chat is saved before the reset

Bulk material (transcripts, long docs) reaches the Chief as a **file** (host attachment, or the adapter swaps a
long paste for a file path) and goes to a cheap helper; only the result enters the Chief's chat. Tested (E6):
Chief chat −57%, context 62k → 12k, quality within noise. Text already pasted into a chat stays in every later
call, so this needs the host/adapter; where impossible, save it and propose a new session after that task.
- Next step (exactly one)
- Open questions for the user
- Files to open first

### Subagent brief template
- Goal (one sentence) and done-criteria
- Inputs: exact file paths, line ranges, links
- Allowed tools only
- Model tier + effort
- Output: a short summary for the Chief + path to a full result file (the long result goes in the file,
  not in the Chief's context)

### New agent template
CORE + ROLE.md (renameable job title, responsibilities) + its tools + its model tier + effort.
Creating an agent = filling the template.

## 7. Maps (where to look, without searching)

Goal: the agent goes straight to the right place instead of search → read → search → read.

### Level 1 — MAP.md (always loaded)
20–30 lines. Tested on one 29k-line code repo: no effect on cost or quality (grep was enough there). Its value
is in setups with many places (projects, memory, wiki, agents), where the agent would otherwise search; cheap to keep.
Example:
- Memory: where short facts live, where long pages live (read their index first), where skills live
- Projects: where each repo/folder lives, its PROJECT.md path
- Decisions: which DECISIONS.md for which topic
- Team: which agent does what

### Level 2 — area maps (opened on demand)
One small file per area (a project, the docs, memory). Each line: item, 1-line summary, tags, links to
related items. Evidence: a knowledge map like this, together with a slimmer system prompt and the rule
"batch the work, never less research", gave −8% tokens with equal quality.

### Level 3 — code graph (code projects only), Graphify-style
Graphify (github.com/Graphify-Labs/graphify, Apache 2.0, ~144k stars, YC S26, active):
- Parses code locally with tree-sitter (no model, nothing leaves the machine, ~40 languages).
- Builds graph.json + graph.html + GRAPH_REPORT.md: key concepts, communities, calls/imports/inherits.
- The agent asks `query "<question>"`, `path A B`, `explain X` and gets a small subgraph instead of
  reading many files.
- Every edge is tagged EXTRACTED (read from the source) or INFERRED.
- Works as a skill in many coding agents.
- Docs, PDFs, images and video need a model pass: that costs tokens.

Tested (E6, real 29k-line repo): the graph builds locally in ~1 min; left optional, **the agent never used it** (grep was
enough). Forced to query it first (6 runs vs 9 without): same hidden tests (24/24), judge 55.3 vs 56.1, cost +21%.
**Not worth it at this size**; may pay only on repos too big to grep (untested).

How we would use it:
- Code projects: reuse Graphify (or any equivalent) rather than build our own, only where the rule above applies.
- Rebuild the graph incrementally when code changes (git hook or adapter). Store the commit hash in the
  graph; if it is behind, refresh before trusting it.
- Return only the small subgraph to the agent, never the whole graph.json.
- Doc/PDF semantic pass: only once, only when needed.
- Non-code work (content, scripts, research): no code graph. Use the level-2 knowledge map.

Honest expectation: Graphify's "−80%" is a marketing line for its paid cloud, not an independent test.
A similar map gave −8% in our evidence. It helps code exploration (cause 2); it does not fix long chats (cause 1).

## 8. Agreed rules

1. **Sessions.** The Chief proposes a new session when a task is done, when the user switches task, or
   when the context passes a fixed size (~150k, not a % of the window — 60% of 1M would be far too late).
   It writes the handoff itself; the user says yes or no.
2. **Task switch.** One line with choices:
   - New session with handoff (default; unrelated task, the old context is useless)
   - Compact (same task goes on but the chat is big; at a task boundary — tested: kept full quality at −51%, Appendix E6)
   - Carry on (small side question, then back)
   - Clear = new session without handoff (when nothing is worth keeping)
3. **Calls (revised after tests S and L).** Only rules that remove waste without limiting how much the agent
   looks: filter huge outputs before they enter the context (only failing tests, only the needed lines);
   wait inside one call instead of polling; loop detection (rule 4). **No "fewer calls / batch / don't re-read"
   pressure in CORE**: in tests S and L it saved nothing and lowered quality (Appendix E4, E5).
4. **Loops.** Same call or same error twice → stop and rethink. After N calls the Chief re-plans by
   itself. No hard call caps (they cut work in the middle and lower quality).
5. **Subagents.** Short brief in, short summary out. Delegate only when it pays (section 9): work bigger
   than one context window, independent parts that can run in parallel, or routine bulk work. Small or
   single-chain work stays with one agent. **One reviewer per piece of work** (tested, E6): the reviewer's model is
   picked by the stakes; a second reviewer only on a real signal (failed test, disagreement, high-stakes release).
   Self-reported "low confidence" is not a usable signal.
6. **Tools.** Each agent gets only the tools its job needs. Unused tool servers (MCP etc.) off; per-project
   tool config; deferred tool loading where the host supports it.
7. **Routing.**
   - Each agent gets model + effort at creation (from its ROLE) and keeps both for the whole session.
     **Neither model nor effort changes inside a chat** (every provider punishes a changed prompt start;
     one rule for every host, even where per-message effort exists).
   - Work that needs another tier goes to a subagent or another agent with that model + effort.
     "Hard" means a new agent/session at the higher tier.
   - Rule table in CORE, no extra model call to decide. **Route by kind of work** (tested, Appendix E6;
     tier → example model at medium effort unless noted):

     | Kind of work | Tier (Anthropic example) | Why (tests) | On failure |
     |---|---|---|---|
     | Checkable: bug fixes, small features with tests, extraction, fact-check, scheduling, formatting, small clear code design | **cheap** (Haiku 5.5 medium; high for strict instructions) | same quality as top tier on checkable kinds incl. hard variants; real-repo code judged 56/60 vs Opus 58, at 1/10–1/40 of the price; an ambiguous spec tripped the mid tier in ~45% of runs (cheap 0 of 20 clean runs, top 0%) — the real check + escalation is the safety net | real check fails → mid (Sonnet high) → top (Opus medium) |
     | Data analysis memo, English writing for the public | **mid** (Sonnet 5.5 high) | 9/10; Sonnet medium broke word limits | — |
     | Partner thinking, brainstorming | **mid** (Sonnet 5.5 medium) | 8.7/10 under two judges; top tier asked too many questions | — |
     | Writing in a language the cheap/mid models handle badly (here: Moroccan Darija) | **top** (Opus 5.5 medium) | native-speaker blind rating: Opus 10, Sonnet high 6.7, Haiku 4.7; AI judges under-rate the gap | — |
     | Hard decisions, project planning, architecture (the Chief's own planning) | **top** (Opus 5.5 medium) | only config never caught by the decision trap | — |
     | **The Chief itself** | **top** (Opus 5.5 medium; high adds cost, no gain) | Chief chat test: 69.7/80 vs mid 58, cheap 53; mid Chief still paid for top helpers | — |

   - **A check only protects the quality it measures.** The cheap-first cascade works only where a real check
     exists (tests, exact answers). On judgment work a cheap answer passes rule checks (word count, script,
     keywords) while its quality is low, so it never escalates — route that work directly by kind.
   - **Effort:** medium by default; high only where the table says; **never low** for real work (Haiku low and
     Sonnet low failed 1/3 and 2/3 runs); **no xhigh/max** (3–17× cost, no gain; Haiku max returned empty answers in
     5 of 6 long-reasoning runs; Opus max $10.34 for a run that medium did for $0.61).
   - Language/quality-sensitive kinds need a human reference rater at least once per new model (AI judges were
     not reliable on Darija).
   - Measure cost per finished task (with the quality judge and real tests), not cost per token. The judge alone
     misses correctness (a run failing 14/24 hidden tests got 55/60), so tests come first.
   - Refresh the tier map when new models ship: independent benchmarks to pick candidates, then the gauge.
   - Changing an agent's main model is the user's call; the Chief proposes.
8. **Planning.** Only for big tasks (many steps or many files). The plan goes into PROGRESS.md so it
   survives a new session. The Chief asks the user only on big decisions; small things it just does.
9. **Cache.**
   - Keep the prompt start (tools, system prompt, memory) byte-stable during a session.
   - The adapter picks the cache length per provider by the gap between turns (section 10).
   - Measured: 1 h cache cost +11% in continuous agent work (same quality) — 5 min stays the default.
   - Anthropic: 5 min for machine-paced agents — unless their tool steps take minutes (tests, builds),
     because the clock starts at the request — and 1 h for human chats with pauses (Anthropic's rule:
     once ~1 turn in 20 follows a 5–60 min pause and few gaps exceed 1 h; choose at conversation start).
     A 1 h write costs 2× instead of 1.25×.
   - OpenAI: default 30 min is usually enough; 12 h for stable shared material reused across long gaps.
   - Gemini: implicit only on current models; put big stable content first, send similar prefixes close together.
   - Scheduled jobs: a longer cache only if runs come closer together than its lifetime.
   - Each provider has its own cache. Switching model or provider loses it.
   - Example (150k context, Anthropic, 5 min cache): reply within 5 min ≈ 15k token-equivalents; after a
     10-min pause ≈ 187k.
10. **Visibility.** A small daily table: who used how much, plus an alert when a chat grows too long.
    A "what does my prompt cost" view (tools, system prompt, memory, files, messages). No budgets, no spend caps.
11. **Rollout and proof.** Nothing ships before a test: same tasks, 3+ runs, blind judge. Roll out to one
    place first, with Undo. Each number is marked measured or estimated.
    **Quality gate:** a change ships only if hidden-test results are equal to the baseline and the blind judge
    score is not lower than the baseline beyond run-to-run noise. A token saving never buys a quality drop.
    **Cost gate:** cost is measured on the whole flow per finished task (all sessions, helpers, reviews, file
    writes), never on one part. A rule that saves in one place but adds cost elsewhere does not ship.
    **How to test (lessons from the test campaign):** real checks first (hidden tests, exact answers), the judge second
    (a run failing 14/24 hidden tests still got 55/60 from the judge); two judges agree within 1 point on ~90% but
    both missed the Darija gap a native speaker saw → a human reference rater for language/tone work; 3+ runs per cell
    (single runs misled several times); keep test fixtures read-only and never show harness paths in prompts (an agent
    once edited the shared fixture and spoiled later runs); retry network errors for ~10 min (outages killed runs);
    measure cost per finished task, at the plan's own weighting when on a subscription (output ≈ 2.2× cached input).

## 9. Routing guide from the providers' own docs (checked 2026-11-09)

Sources saved in `sources/` (Anthropic: effort, choosing-a-model, optimizing-for-cost-and-intelligence,
models overview, prompt caching; OpenAI: latest-model, reasoning, models, prompt caching; Google: caching,
pricing). Numbers here are the providers' own measurements.

### Prices (USD per 1M tokens)

| Model | Input | Output | Cache read | Cache write | Note |
|---|---|---|---|---|---|
| Claude Fable 5.1 | 10 | 50 | 0.25 | 12.50 (5m) / 20 (1h) | cache read 0.025× |
| Claude Fable 5 (older) | 10 | 50 | 1.00 | 12.50 | 4× the cache-read price of 5.1 |
| Claude Opus 5.5 | 4 | 20 | 0.20 | 5 / 8 | |
| Claude Sonnet 5.5 | 2 | 10 | 0.10 | 2.50 / 4 | half of Opus 5.5 on every token type |
| Claude Sonnet 5 (older) | 2 | 10 | 0.20 | 2.50 | cache read = Opus 5.5 |
| Claude Haiku 5.5 | 0.10 | 0.50 | 0.01 | 0.125 / 0.20 | prompts over 100k: 0.50 / 2.50 / 0.05 (5×) |
| GPT-6 Astra | 10 | 50 | 1.00 | 12.50 | prompts over 272k: 2× input, 1.5× output |
| GPT-6.1 Sol | 2 | 10 | 0.10 | 1.25× | "near-Astra at a fifth of the price" |
| GPT-6.1 Terra | 1 | 5 | 0.05× input | 1.25× | |
| GPT-6 Luna | 0.10 | 0.50 | 0.1× input | 1.25× | |
| Gemini 4 Argon | 2 (4 from Dec 1, 2026) | 10 (20) | 0.10 (0.20) | — | implicit caching only |
| Gemini 3.8 Flash | 0.75 (1.50 from Jan 1, 2027) | 3.75 (7.50) | 0.075 (0.15) | storage fee for explicit cache | |

Lessons: older versions can cost more than newer ones (Fable 5 vs 5.1, Sonnet 5 vs 5.5) — keep the
tier map on current models. Cheap models have price steps at long prompts (Haiku 100k, Astra 272k) —
keep cheap-tier contexts short.

### Model cards: what each provider says a model is for

| Model | Provider says it is for | Default effort | Provider's effort advice |
|---|---|---|---|
| Claude Fable 5.1 | Highest capability: agent sessions that run for hours, multistep deep research, analysis carried to a finished document/spreadsheet/deck | high | xhigh/max for the most capability-sensitive work; medium/low for routine once tests show quality holds |
| Claude Opus 5.5 | "Most workloads start with Opus 5.5": complex agentic coding, multihour coding agents, large refactors, systems engineering, computer use | medium | Medium ≥ Opus 5 at high. Sweep effort on your own work |
| Claude Sonnet 5.5 | Everyday coding, agents, data analysis, content creation, agentic tool use | high | Agentic coding: medium for well-specified tasks, high for harder/longer ones. Chat: medium or low. xhigh/max only where tests show a gain |
| Claude Haiku 5.5 | Lowest latency and price: high-volume processing, classification, extraction, routing, subagent tasks | medium | Medium for most work; low for chat and short tool tasks (at low in long prompts it may skip a search or a check); high for knowledge work and strict instruction following |
| GPT-6 Astra | Most capable: computer use, browsing, software engineering, science, professional work; "stronger results using substantially fewer output tokens" | — | low…max |
| GPT-6.1 Sol | "Near-Astra performance at a lower cost" for complex coding, computer use, professional work | medium | low…max |
| GPT-6.1 Terra | Fast, efficient: visual reasoning, precise computer use, clear natural writing, drafting and revising | medium | Start medium, raise only if worth it |
| GPT-6 Luna | Most efficient, focused high-volume tasks | — | none…max |
| Gemini 4 Argon | Flagship reasoning: complex software engineering, deep math/science, autonomous multi-step agents | — | (to check) |
| Gemini 3.8 Flash | Most intelligent Flash: long-horizon software engineering, agents, enterprise workflows | — | (to check) |

OpenAI's effort table (all its reasoning models): none = classification/fast retrieval; low = tool use,
drafting, execution-oriented coding, chat assistant; medium = default, agentic coding, research,
delegating long work; high = hard reasoning, complex debugging, deep planning; xhigh = deep research,
long async runs, security/code review, "only when your evals show a clear benefit"; max = most complex
tasks, test against xhigh.

Anthropic on effort: effort applies to every output token (text, tool calls, thinking); "lower effort
also means fewer and terser tool calls"; max "adds significant cost for relatively small quality gains"
and "can lead to overthinking"; xhigh is for long agentic runs and costs "meaningfully" more than high;
"tuning effort is often a better lever than switching models".

### Independent benchmark: Artificial Analysis (artificialanalysis.ai, checked 2026-11-09)
Independent evals of many models at each effort level: Intelligence Index (9 evals), cost per task, time per
task, output tokens, plus a Coding Agent Index, a "Model Recommender" and router-model views.

| Model (effort) | Intelligence Index | Cost per index task | Time per task |
|---|---|---|---|
| Claude Fable 5.2 (max) — new, released 2026-11-09 | 65 | $26.54 | 44 min |
| Gemini 4 Carbon (high) | 60 | $7.76 | 27 min |
| Claude Opus 5.5 (max) | 59 | $10.04 | 25 min |
| GPT-6 Astra (max) | 57 | $6.24 | 23 min |
| GPT-6.1 Sol (max) | 55 | $1.27 | 20 min |
| Claude Sonnet 5.5 (max) | 55 | $10.02 | 32 min |
| Claude Haiku 5.5 (max) | 36 | $0.41 | 16 min |

Lessons for the design:
- At max effort Sonnet 5.5 costs as much per task as Opus 5.5 (very verbose: 335M output tokens on the index
  vs 218M for Opus). A cheap model at a high effort can lose its price advantage — supports "max rarely".
- GPT-6.1 Sol (max) scores like Sonnet 5.5 (max) at ~1/8 of the cost per task: worth a slot in the tier map
  where OpenAI is available.
- New models appear weekly (Fable 5.2 today). The tier map must be refreshable: use independent data like this
  to pick candidates (Pareto line of intelligence vs cost per task, per effort), then confirm with our own gauge.
- Benchmark ≠ your work: on our clear, checkable coding tasks Haiku 5.5 matched Sonnet 5.5 on hidden tests,
  although its index is 36 vs 55. The index ranks general capability; the gauge decides per task type.

### What the providers measured about strategies

| Strategy | Measurement (Anthropic unless noted) | Meaning for the design |
|---|---|---|
| Lower effort on the same model | Opus 5.5 on SWE-bench Pro: low 87.4% $0.11 · medium 92.8% $0.21 · high 95.3% $0.29 · xhigh 96.7% $0.74 per task. "Sweep effort before you add a second model." | Effort is the first lever. xhigh cost 2.5× high for +1.4 points |
| Cheaper model vs lower effort | Sonnet 5.5 high 87.6% $0.11 ≈ Opus 5.5 low 87.4% $0.12 per solved task | Compare cost per **finished task**, not per token |
| Re-run failures one level up | Opus 5.5 low + failures re-run at high: ~97% at ~$0.17 vs everything at high 95.3% at $0.29 | Best policy when a task can be checked. Needs a real failure signal; costs latency on failures |
| Orchestrator + cheaper subagents | Won only (1) for routine work with a long cost tail and (2) for work bigger than one context window (Opus 5.5 + Sonnet 5.5 subagents: about ⅓ cheaper, same score). Otherwise the orchestrator's model alone at lower effort won. Haiku subagents on coding ≈ lowering effort (−32% cost, −4 points) | Delegate for size, parallel or bulk work, not for "easy" as such |
| Top model as orchestrator | Fable 5.1 as orchestrator: +24% cost, no gain. Fable alone: 2.2–3.0× Opus 5.5 high, no higher score (defect search) | Top tier only where a test shows it wins |
| Advisor (executor consults a top model) | Helps only when the executor actually consults; one case +1.7 points (noise edge) for 2.1× cost, others no gain or worse | Not by default |
| Cache breaks | Editing the system prompt mid-chat: 25–50× the cost of the same text as a message; top-level effort change: 20–40× | Supports "never change model/effort/prompt start mid-chat" |
| Context lifecycle | On long runs compaction saved 32% and pruning 39%; on short runs nothing. On Claude 5.1+ rewriting old tool results breaks thinking blocks, so use compaction | **Conflict** with our evidence (early compaction at 100k hurt quality; 1 run, confounded). Re-test compaction at a task boundary |
| Delegation (OpenAI) | Astra is trained to split work into parallel subagents; delegate "if it could save time or improve quality" | Same rule: parallel work, not small work |
| Testing (OpenAI) | "Do not write tests for reversible, low-impact changes… broaden or repeat testing only when new changes, failures, or unresolved concerns justify it" | Fits rule 3 (no repeated checks) |

### An example tier plan (from a user's post), checked against the docs

| Plan | Docs say | Verdict |
|---|---|---|
| Haiku 5.5 xhigh — cheap worker | Haiku: medium for most, low for short tasks, high for strict instructions; xhigh only with proof | Use low/medium (high for strict work) |
| Sonnet 5.5 high — daily assistant + execution | Default high; agentic coding: medium for well-specified tasks | Good; medium for well-specified execution |
| Opus 5.5 high/medium — thinking partner + execution | Default medium; most workloads start here | Good |
| Opus 5.5 max — game changer | max: small gains, overthinking; Fable 5.1 is the top model | Prefer Opus 5.5 high/xhigh or Fable 5.1 high, by test |
| Sol 6.1 xhigh — daily assistant + cheap worker | xhigh only with clear benefit; low for chat/drafting/execution | Daily: medium; cheap worker: Luna/Terra or Sol low |
| Sol 6.1 max — thinking partner + execution | high = hard reasoning/deep planning; max = most complex | high by default, max for the hardest |
| Astra 6 max — game changer | Most capable, uses fewer output tokens; >272k prompt costs 2× | Good for rare hard work; keep context under 272k |

## 10. Cache per provider (official docs, checked 2026-11-09)

| | Anthropic (Claude) | OpenAI (GPT-5.6 and later) | Google (Gemini) |
|---|---|---|---|
| On by default | Automatic caching or explicit breakpoints | Yes (implicit), explicit optional | Implicit, all Gemini 2.5+ |
| Lifetime | 5 min (default) or 1 h | 30 min (default) or 12 h (Responses API) | Not stated for implicit; explicit cache (Gemini 2.5/3.x only, not Gemini 4) has a TTL you set + hourly storage fee |
| Timer | Refreshed free on every hit; counted from the **start** of the request (a 4-min reply leaves ~1 min) | Minimum lifetime; may live longer | — |
| Write price | 1.25× input (5 min), 2× (1 h) | 1.25× (30 min), 2.5× (12 h) | No write fee for implicit |
| Read price | 0.1× input; 0.05× Opus 5.5 / Sonnet 5.5; 0.025× Fable 5.1 | 0.1×; 0.05× Sol 6.1 / Terra 6.1 | ~0.05–0.1× |
| Minimum prefix | 512 tokens (current models) | 1,024 tokens | 4,096 (Gemini 3.x/4), 2,048 (2.5) |
| Gotchas | Byte-exact prefix (tools → system → messages); 20-block lookback per breakpoint; system-prompt edit mid-chat 25–50×, top-level effort change 20–40× | Compaction changes the prefix (less reuse right after); effort change: use `configuration_update`, not the request-level value; cached tokens still count for rate limits | Gemini 4 agent loops: the previous request is cached only if the new one adds ≥2,050 tokens; no guaranteed hit |

What this means:
- "5 min vs 1 h" is Anthropic-specific. The adapter picks the cache length per provider; CORE only says
  "keep the prompt start stable".
- On Anthropic, agents whose tool steps take minutes can lose the 5-min cache between calls; they need 1 h too.
- Every provider punishes changing the start of the prompt mid-chat; the "no mid-chat change" rule holds everywhere.

## 11. Rejected (tested: no saving, or quality dropped)

| Idea | Result |
|---|---|
| Compaction in the middle of a step (100k or lower) | Quality dropped, one run halted. **Compaction at a task boundary is accepted** (XL2: full quality, −51%) |
| Pruning old tool results | 0% saving, quality down; also breaks thinking blocks on newer Claude models |
| Splitting big skills into core + references | No saving, quality down |
| "Fewer calls" without guards | −26% but weak sources in fact-checks |
| "Batch / fewer calls / don't re-read" rules text in CORE | Tests S and L: 0% saving, judge −6.5% and −7%, two task-1 misreads (Appendix E4, E5) |
| Hard max calls per task | Cuts work mid-way; conflicts with the no-limits principle |
| Switching model or effort mid-chat | Breaks the cache, costs more |
| Low effort for real work | Haiku low failed 1/3 runs (judge 25/60 once), Sonnet low 2/3 (E6) |
| xhigh / max effort | 3–17× cost, no gain on hidden tests or judge; Haiku max empty answers 5/6 on long reasoning; Opus max $10.34/run (E6) |
| Subagents to save money | Forced delegation: equal quality at 1.5× (Haiku helpers) to 5.7× (Sonnet helpers) the cost (E6) |
| 1-hour cache in continuous work | +11% cost, same quality (E6) — keep it for long pauses only |
| Cheap-first cascade on judgment work | Rule checks pass weak answers; Darija/decision/partner quality 0.53–0.77 vs 0.83–1.0 routed directly (E6) |
| Several reviewers on the same work by default | Three mid-tier reviewers = cost of one top-tier, fewer errors caught, 3× false alarms (E6) |
| Reset without saving pasted inputs | Lost what the handoff did not carry: reasons 0/24 (E6) |
| ~~Lowering reasoning effort saves nothing~~ | Withdrawn: output is priced high (~26% of cost); effort is a lever, set per agent (rule 7) |

## 12. Proposed, not yet agreed (to discuss)

| Idea | Where it came from | View so far |
|---|---|---|
| Background runs (heartbeats, scheduled checks) skip the model when nothing changed; one forced run per day | First plan list | **Tested:** an empty heartbeat through a top-tier model with an 11k prompt costs $0.061 (~$3/day/agent at 30 min); gate = 0 → agreed |
| Notifications ("task completed") never land in the main chat | First plan list | Tested: +2% tokens, no quality change in a 60k chat — low priority, keep as hygiene |
| Trim the fixed prompt (system prompt / persona file) | Earlier test | Tested: part of the −8% package, quality equal |
| Tool weight: tool servers (MCP) are heavy (every tool's schema rides every call), skills are cheap (name + description only) | Claude's notes | **Tested:** 40 schemas +36% cost on a cheap model, deferred loading ≈ 0 → agreed |
| Replace a tool server by a skill + CLI/API when it only wraps a CLI | Claude's notes | Agree when quality is equal; test per case |
| Per-project tool config | Claude's notes | Agree; same as rule 6 |
| A "what does my prompt cost" view | Claude's notes | Agree; part of visibility |
| Tell the agent exactly where to look ("bug is in cart.js addItem") | Claude's notes | Agree; MAP + briefs do this automatically |
| Router levels (Junior → GOAT): cheapest first, verify, escalate on fail | Reel @donimas | Tested: works for checkable work only; content/judgment work routes by kind (rule 7) |
| Gatekeeper / planner↔builder / dashboard "mods" | Reel skillwars.ai | Gatekeeper = routing; planner↔builder adds handoff cost; dashboard = visibility |
| ~~One fact-checker instead of several on the same claims~~ | First plan list | Tested (E6): one top-tier reviewer 16/16, 0 false alarms, at the cost of three mid-tier reviewers (15.5/16, 1.67 false alarms) → agreed (rule 5) |
| ~~Re-test compaction at task boundaries~~ | Provider measurement (9) | Done (XL2): kept 24/24 at −51% → accepted (rule 2) |

### 12b. Proposed numbers (Open 4) — defaults, tuned later by the gauge

All are general defaults written in CORE; a user can change them; the adapter enforces them where the
host allows, otherwise the Chief follows them by itself.

**A. When the Chief proposes a new session** (any one is enough):
1. The task is done, or the user switches to an unrelated task.
2. Context passes **150k tokens** (soft: propose at the next natural break). At **300k** it proposes at once.
   Absolute numbers, never a % of the window (windows differ: 128k, 1M, 2M…).
3. The cache has gone cold (pause longer than the provider's cache life) **and** a new task starts.
   Reason: continuing re-writes the whole context at the write price; a fresh session with a handoff
   re-writes only a few k tokens. Example, Opus 5.5 at 150k: ~$0.75 to continue cold vs ~$0.10 fresh.
4. Cheap-tier agents stay under their provider's price step (Haiku 5.5: 100k; GPT-6 Astra: 272k):
   they hand off before crossing it. Tested (E6): Haiku past 100k cost ~4.7×; reset every task −90%.

**B. Re-plan checkpoint (no cap):**
- Every **25 tool calls without visible progress** (no checklist item done, no file changed, no new
  finding), the agent stops, writes a 3-line status in PROGRESS.md (done / blocked on / next), and picks
  the next step again. Progress resets the counter. Work never stops because of a count.

**C. Loop rule:**
1. Same tool with the same arguments twice → stop, use the result already in context.
2. Same error twice → no third try with a tiny change; change the approach.
3. Three failed approaches on the same goal → escalate: one tier up (a subagent with a stronger
   model/effort) or ask the user one clear question.
4. Checking the same status more than twice → wait inside one call instead of polling.

**D. Compaction (if the host offers it):** only at a task boundary when the same task continues, never in
the middle of a step. Tested (XL2): full quality at −51% vs never renewing. Use it when pasted inputs cannot be
saved to files; otherwise new session + handoff (cheaper: −82%) after saving the inputs.

## 13. Open (to check or decide)

1. ~~How subscription plans count usage~~ — tested on one Claude plan (E6): not like API prices. 1% of the week ≈ $33 of
   cache-read-heavy agent work but ≈ $15 of output-heavy work → output weighs ~2.2× more per API dollar (cache
   reads ~0.3×). On subscriptions, output/effort is the main lever. Other providers' plans: untested.
2. ~~Cache on Gemini and OpenAI~~ — done (section 10).
3. Effort details for Gemini models.
4. Exact numbers: context size that triggers "new session?", N calls before re-planning, loop rule details.
5. Which hosts accept SKILL.md (ChatGPT, Grok, Gemini app…).
6. ~~Graphify A/B on one real code repo~~ — done (E6): unused by the agent, no effect.
7. Write: CORE → Chief rules → file templates (USER, MAP, PROJECT, PROGRESS, DECISIONS, ROLE) → subagent
   brief → new-agent template → skills → adapters (one per host type) → test plan.
8. Name and form (kit/repo, plugin, adapters) — last.
9. Not tested yet: other providers' top models (OpenAI: no key; Gemini Argon/Carbon: free-tier key; Gemini 3.8 Flash
   in progress); where the cheap tier breaks on large multi-day work; a harder planning rubric; the re-plan
   checkpoint and the loop/poll rules under real failure (agents never looped in tests); the adapter itself (the
   test harness played its role) and real hosts (to test after the build).

## Appendix E. Evidence from one real setup (anonymized)

One user's multi-agent setup on a Claude subscription: a personal assistant harness, a 9-role
engineering team of worker agents on a task board, and a team workspace on a second machine (all on the
same account). These numbers are evidence for the design, not part of it.

### E3. How the subscription counted usage (one Claude plan, 2026-11-09)
- The plan's usage API showed one weekly limit for all models (22%) and a separate weekly limit scoped to
  one top model (Fable; allowance 50% of the weekly total; it had used 7 of the 22 points). No 5-hour
  window active. Whole-number percents only. All traffic was counted as "Claude Code" (OAuth agent traffic).
- Tokens since the reset across every agent on the account (prorated for sessions that started earlier):

  | Model | Output | Cache read | Cache write | Share of all tokens |
  |---|---|---|---|---|
  | Opus 5.5 | 3.83M | 540M | 21.8M | ~74% |
  | Sonnet 5 | 0.84M | 146M | 3.8M | ~20% |
  | Fable 5 | 0.53M | 44.5M | 2.9M | ~6% |

- Fable 5 = ~6% of the tokens but ~29–35% of the usage points. Raw tokens would give ~6%; tokens
  without cache reads ~10%. Priced at official API rates, Fable 5 ≈ 24% of cost. So the plan counts usage
  roughly like API prices (cache maybe weighted a bit higher). Anthropic docs also describe a credit
  conversion "rated in USD at standard per-model, per-feature rates (same as Claude API pricing)"
  (which plan surface it covers: to confirm).
- Fable 5 was expensive mainly because of its $1 cache reads; Fable 5.1 reads at $0.25. Sonnet 5 reads at
  the same price as Opus 5.5; Sonnet 5.5 at half. Lesson: keep tier maps on current model versions.
- Effort settings seen in that setup: the assistant at medium; team roles at high (architect, security,
  reviewer, manager) or medium (engineer, QA, release, UX).

### E4. A/B test S — small tasks (2026-11-09)
Setup: small synthetic Python repo (~200 lines), 4 chained tasks (discount codes, rounding bug, CSV export,
shipping refactor), 29 hidden tests the agent never sees, blind judge (Opus 5.5, high effort, /40, arms hidden).
Agent: Sonnet 5.5, effort medium, in both arms. 5 runs per arm. Harness: a minimal neutral agent loop
(bash, read, write, edit tools) on the raw API. Code: `abtest/runner.py`, results `abtest/runs/`.
- A = one session for all tasks, plain prompt. B = CORE rules + new session per task with a PROGRESS.md handoff + adapter notes.

| | A | B | Difference |
|---|---|---|---|
| Hidden tests | 29/29 in 5/5 runs | 29/29 in 5/5 runs | equal |
| Blind judge (/40) | 33.6 (31–35) | 31.4 (30–33) | B −2.2 (−6.5%), lower on every task (T1 −0.4, T2 −1.0, T3 −0.4, T4 −0.4) |
| Cost per run (API prices) | $0.095 | $0.098 | B +2.6% |
| Calls per run | 10.2 | 15.6 | B +53% |
| Max context | ~10k | ~5k | contexts tiny in both |
| Adapter notes fired | — | 0 | no loops, no re-plan, no 150k |

Reading: with tiny contexts a new session per task saves nothing (re-reading PROGRESS/README and writing the
handoff costs about what it saves) and the judge found weaker tests and small style slips in B
(filler assertions, imports inside functions, duplicated helpers). Correctness was equal. The 150k/300k
rules never fired. Which part causes the quality dip — the rules text or the session reset — is isolated by
test L (arm C = rules without reset).

### E5. A/B test L — real repo, chained tasks, human pauses (2026-11-09)
Setup: pallets/click (~29k lines incl. tests), 6 chained tasks (Duration type, unsorted groups, timedelta default
display, Context.find_param, Duration completion, Duration bounds), 24 hidden tests + the full click suite as
regression, blind judge (/60). 6-minute pause between tasks (cache goes cold). Sonnet 5.5 medium in every arm,
3 runs per arm. Code: `abtest/runner_l.py`, results `abtest/runs_l/`.
- A = one session, plain prompt. B = rules text + adapter + new session per task (PROGRESS.md handoff).
  C = rules text + adapter, one session (new session only past 150k — never reached; max context ~12k).

| | A | B | C |
|---|---|---|---|
| Hidden tests | 24/24 · 24/24 · 24/24 | 9 · 24 · 24 | 24 · 5 · 24 |
| Click suite regressions | 0 | 0 | 0 |
| Blind judge (/60) | **55.0** (53–57) | 51.7 (50–55) | 50.7 (49–52) |
| Cost per run | $0.272 | **$0.154 (−43%)** | $0.280 (+3%) |
| Calls per run | 23 | 25 | 25 |
| Cache read / write tokens | 151k / 67k | 51k / 23k | 185k / 63k |
| Adapter notes fired | — | 0 | 0 |

Reading:
- **New session per task after a pause saves ~43%** (the old chat is re-written cold at every task in A and C;
  B starts small). With the reset alone, quality was not hurt: B2/B3 were perfect on hidden tests.
- **The rules text saves nothing and costs quality.** C (rules, no reset) ≈ A in cost but lowest judge score;
  B and C both lost ~2 points on T6 (bounds). Both hidden-test failures (B1, C2) were the same misreading in
  task 1 (Duration built as an instance like click.UUID instead of a class), seen only in the two arms with the
  rules text (2 of 6 runs vs 0 of 3). Same direction as test S (rules arm −6.5% judge).
- Likely cause: "batch / fewer calls / don't re-read" pushes the agent to look at less code before deciding.
- Action: drop the "fewer calls" pressure from CORE; keep only rules that remove waste without limiting
  looking (filter huge outputs, no polling, loop detection, handoff). Re-test as arm B' = reset + handoff only.
- **Correction after B' (arm D):** D1 (no rules text) failed the same task-1 misreading (9/24), and Sonnet also
  failed it in routing arm E (2 of 3 runs). Haiku never did (0 of 9). So the failure is a Sonnet blind spot on an
  ambiguous spec, not caused by the rules text. A check + escalation safety net is what protects quality.

### E6. Later tests (2026-11-09/10): XL, XL2, loops, subagents, routing, effort, kinds of work, judges
Full detail and numbers: `abtest/RESULTS.md` (single source of truth). Summary:
- **Sessions (XL, 8 long transcripts):** new session per task −82% cost, equal quality, when inputs are in files.
- **Hard handoff (XL2, inputs pasted in chat):** never renew $6.86, reasons 24/24 · compact at 150k $3.36, 24/24 ·
  new session at 150k $2.13, 10/24 · new session every task $1.16, 0/24. The handoff kept what was asked
  (decisions) and lost what was not asked yet (reasons). **With the source rule (save pasted material verbatim to
  files, handoff lists reasons and points to the files): new session every task 24/24 at $0.71 (−90%).**
- **Real repo (L, 6 tasks, blind judge /60):** Opus one session 58 ($0.98) · Haiku high reset 56.3 ($0.041) ·
  Haiku medium reset 56.0 ($0.024) · Sonnet high 56.0 ($0.27) · Sonnet medium one session 55.7 ($0.27) ·
  Sonnet medium reset 51.7 ($0.17) · Haiku low 44.0. New session + handoff after a pause: −43% (Sonnet), −38% (Opus).
  MAP.md, 40 extra tools: no effect. 1-hour cache: +11%.
- **Loops:** no model looped on the traps (4–5 calls); loop rules showed no measurable effect (kept as a free guard).
- **Subagents:** never chosen freely; forced delegation 1.5–5.7× cost, equal quality.
- **Effort:** low unsafe; xhigh/max 3–17× cost with no gain; max can return nothing.
- **18 kinds of work × 8 model/effort configs × 3 runs:** cheap tier matched top on every checkable kind (incl.
  hard variants); Darija needs the top tier (native-speaker blind rating Opus 10 / Sonnet high 6.7 / Haiku 4.7); hard
  decisions need the top tier; partner thinking and public English writing → mid tier.
- **Cascade (simulated from real outputs):** top quality at cheap price on checkable kinds; fails on judgment kinds.
- **Reviewers (16 planted errors in a memo, code, a plan):** one top-tier reviewer 16/16, 0 false alarms, $0.058;
  three mid-tier reviewers 15.5/16, 1.67 false alarms, $0.057; one cheap reviewer 15.4/16 at $0.002; reviewers never
  reported low confidence, so confidence cannot gate a second review.
- **Step 2:** Chief model → top tier medium (69.7/80 vs mid 58, cheap 53); large inputs as files → −57% for the Chief;
  cheap tier past its 100k price step ~4.7× cost; code graph: unused when optional, +21% cost and no quality gain when forced (29k-line repo); re-plan checkpoint
  never triggered.
- **Step 3:** output filter rule −63…−75% (same result); polling and loop rules: no measurable effect (agents behaved);
  plan rule on clear tasks: no gain; 40 tool schemas +36%, deferred ≈ 0; helpers with CORE-lite −24% (weak, 2 runs);
  split project files −45% vs one growing handoff over 5 sessions, same quality; notifications +2% (no quality change);
  empty heartbeat via top model $0.061 vs gate $0.
- **Subscription counting (one Claude plan):** 1% of the week = $32.8 of cache-read-heavy Opus work vs $14.7 of
  output-heavy Sonnet work — output counts ~2.2× more per API dollar than cached input.
- **System-1 decision models (Jev by TypeSafe, hosted; Laya, open weights):** typed questions (yes/no, score,
  choice) over a state, answered with probabilities, no text. **Measured 2026-11-10 (RESULTS §2.20): not adopted as a
  router.** `typesafe/jev-router` on our 18 matrix kinds × 3: quality 0.85 (any model) / 0.82 (Claude-only) vs 0.91 for
  our fixed table; it over-buys on checkable code (Opus/GPT for bug fixes, 7–9× cost, same 100%) and under-buys on
  judgment (Darija −0.18…−0.28, decision −0.10, partner −0.07…−0.17). Jev 1.14 as a per-prompt tier classifier: 33%
  = chance (paired study arXiv 2610.02267 found the same). As a **cheap gate** (under-specified → ask; heartbeat needs
  action; checkable vs judgment) it was 100% on our easy 30-case sets — same as Haiku medium at ~half the price and
  ~1 s latency: usable, but the saving vs a Haiku gate is negligible. Keep routing by kind of work.
- **Cognee (github topoteretes/cognee, Apache-2.0; tested 2026-11-10, RESULTS §2.19):** graph + vector memory, run in
  local mode ($0 tokens). On 936 notes / 20 questions: Haiku 18.0 grep vs 17.7 Cognee vs 18.0 both (no gain); Opus 19.0
  grep vs 20.0 Cognee or both (+1, semantic recall helped a Darija-worded question), at +12% (both) to +33% (Cognee
  only) cost. Build: ~35 min, ~5.5 GB RAM, repeated OOM kills (it once restarted the host agent's service when not
  isolated). **Not in the default kit**; optional backend for very large memory on a machine with spare RAM, used
  next to grep, run in a memory-capped scope.
- **Second judge (Sonnet high):** within 1 point of the Opus judge on 91% of 240 answers; both under-rated the
  Darija gap a native speaker saw.


## Build status (2026-11-10)
| Part | Where | State |
|---|---|---|
| CORE rules | `kit/AGENTS.md` (v6) | built, tested (RESULTS §2.18) |
| Tiers → models | `kit/ROUTING.md` | built (Anthropic tested; OpenAI/Google untested) |
| Templates | `kit/templates/` | built |
| Skills | `kit/skills/` (6) | built |
| Setup per host | `kit/SETUP.md` | built |
| Hermes adapter | `adapter/plugin/frugal-bridge/` | built, tested in isolation; not installed live (user's yes needed) |
| Claude Code adapter | `adapter/hooks/frugal_hook.py` | built, tested (one real run) |
| Proxy adapter (any host with a base URL) | `adapter/proxy/frugal_proxy.py` | built, 18/18 tests + real Claude Code run through it (context notice + loop guard worked, cache intact); Codex real run pending (usage limit until 2026-11-13) — RESULTS §2.22 |
| Setup (install/check/uninstall) | `kit/setup.py` | built, 12/12 tests (fresh, re-run identical, uninstall restores, user text byte-identical, JSON merge, base-first, old version, size check, Hermes copy) |
| Coexistence with a base folder | `docs/COEXISTENCE.md` | contract implemented in setup + adapters (slots from `.kits.json`); Base side (import/export) is the base folder's setup |
| One adapter (auto-picked) | `adapter/` (hooks, plugin, proxy mechanisms) + `setup.py --hosts auto` | built 2026-11-11: setup detects agent tools and uses the strongest way each allows; docs present it as one adapter for any tool/provider |
| Install once, everywhere | `setup.py install --global` (default in INSTALL.md) | built 2026-11-11: rules in each tool's user-level file, user-level hooks/skills/plugin, one `~/.frugal-bridge/USER.md`; real test: new session in an empty folder loaded the rules (RESULTS §2.27) |
| Agent-driven install | `INSTALL.md` (public repo root) | built; real test: Claude Code set it up from one sentence, check OK, new session loads the rules (RESULTS §2.24) |
| Public repo | <this repository's URL> (public, MIT) | v0.1.0 pushed 2026-11-11: kit, adapters, docs (DESIGN, RESULTS, COEXISTENCE); harness not published. Sync: `./publish.sh` then commit in `~/frugal-bridge-public` |
| Start files in any install order | shared resolver in `adapter/hooks`, `adapter/plugin`, `adapter/proxy` | built 2026-11-11: base found like `setup.py find_base`, fresh every session, folder slots expanded; `adapter/test_install_orders.py` covers base-first, Frugal-first, disconnect/uninstall, Mothership, project install, no base, spaces (RESULTS §2.35) |
| Tier per helper (Hermes delegation backend) | `adapter/plugin/frugal-tiers/` + `tiers.json` from `kit/ROUTING.md` | built 2026-11-11: `tier`/`effort` per delegate task, mapped to the parent's provider family; installed and on in the user's Hermes (RESULTS §2.36). Claude Code: rules + skill say pass the model; Codex/others: rules only (+ proxy option) |
| Week test on real work | — | not started (after live install) |


## Relation to a knowledge base / "base folder" 
Frugal-Bridge is a standalone product, never bundled with a knowledge base; installed by its own setup, works with or without one, in any install order.
Contract (full plan: docs/COEXISTENCE.md): edit shared files only inside `<!-- frugal-bridge:start/end -->` blocks; register in `.kits.json`; never hard-code USER/PROGRESS/DECISIONS/MAP — read their paths from the `slots` in `.kits.json` (own files when no base, base files when a base exists); skills prefixed `frugal-*`; idempotent setup + uninstall.
Done 2026-11-11: all adapters read slots from `.kits.json`; skills renamed `frugal-*`; pointer files are `@AGENTS.md`
(an `@` import; tests showed a prose "Read AGENTS.md" line does not load it); JSON host settings merged key by key;
`setup.py check` measures the whole `AGENTS.md` (Codex 32 KiB limit). For chat apps a base folder's `brief --full`
should include Frugal's CORE block when Frugal is installed; inside an egress-proxied cage the path is agent → egress
→ Frugal proxy → provider.
