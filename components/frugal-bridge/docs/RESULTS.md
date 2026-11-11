# Frugal-Bridge — test results log (single source of truth)

Purpose: every test, setup, number and conclusion, so nothing is lost when the chat is compacted or a new
session starts. Design doc: `DESIGN.md`
(this file keeps the full detail).

Last update: 2026-11-10 (step 2 done).

## 0. Goal of the tests (the brief, kept exact in meaning)
- **Quality must stay top ("wa3ra") — this comes first.** Then the lowest price that keeps that quality.
- "A cheap model is not automatically fine": find, per kind of work, which model + effort keeps top quality,
  when to route up, and why — with numbers.
- Do not add effort levels or tests that bring nothing; keep what matters.
- The system is portable (any harness, any provider); one real setup is evidence only, never named in the design.

## 1. Harness (how every test runs)
- Folder: `abtest/ (private harness, not published)/`. Python: path in `abtest/.env_local/py.txt`; repo venv `.venv` for pytest.
- `llm.py` — raw Anthropic API call, prompt caching (5 min default, 1 h optional), retries on connection/overload
  errors (added after 2 runs died with `APIConnectionError`).
- `runner.py` — neutral agent loop (bash/read/write/edit tools), `Session`, `run_task`, `cost()` at API list prices.
- Prices used (per 1M tokens): see `runner.PRICES` / DESIGN §9. Costs below are API-price USD, per run.
- Quality measures: hidden tests the agent never sees; exact checkers; blind judge = Opus 5.5 high, arms hidden.
- Runners: `runner.py` (S), `runner_l.py` (L + routing/effort/map arms), `runner_xl.py`, `runner_xl2.py`,
  `runner_loop.py`, `runner_loop2.py`, `runner_sub.py`, `runner_matrix.py`. Results in `runs_*/`.

## 2. Results so far

### 2.1 Test S — small repo, 4 chained tasks (done) — DESIGN E4
Sonnet 5.5 medium, 5 runs/arm. A = one session plain; B = rules + new session per task + PROGRESS.md handoff.
- Hidden tests 29/29 in all runs both arms. Judge /40: A 33.6, B 31.4 (−6.5%). Cost A $0.095, B $0.098.
- Reading: tiny contexts → reset saves nothing; rules text cost a little quality.

### 2.2 Test L — real repo (pallets/click ~29k lines), 6 chained tasks, 6-min pauses (done) — DESIGN E5
24 hidden tests + full click suite. Sonnet 5.5 medium unless noted. Mean cost per run:

| Arm | What | Hidden tests (per run) | Cost/run |
|---|---|---|---|
| A | one session, plain | 24·24·24 | $0.272 |
| B | rules + reset per task + handoff | 9·24·24 | $0.154 (−43%) |
| C | rules, one session | 24·5·24 | $0.280 |
| **D (B')** | reset + handoff only, no "fewer calls" text | 9·24·24 | **$0.166** |
| H | D + 1-hour cache | 24·24·24 | $0.184 (+11% vs D) |
| M | D + MAP.md | 24·24·24 | $0.177 |
| W | D + 40 extra tools | 24·24·24 | $0.181 |
| A7/A8 (Opus 5.5 medium, one session) | | 24·24 | $0.98 |
| D7/D8 (Opus 5.5 medium, reset+handoff) | | 24·24 | $0.61 (−38%) |

Readings:
- **Reset per task + handoff after a pause saves ~40%** on both Sonnet (−43%) and Opus (−38%).
- **1-hour cache does not pay** for continuous work (+11%); only for long pauses (>5 min) inside one session.
- MAP.md and 40 extra tools: no measurable effect on this repo (cost ±5%, all 24/24).
- **Correction (2026-11-09):** the hidden-test failures (B1 9/24, C2 5/24, D1 9/24) are all the same misreading
  of task 1 (Duration built as an instance instead of a class). It also happened in D1 (no rules text) and in
  routing arm E with Sonnet (2 of 3 runs, caught and fixed by escalation). Haiku never made it (0 of 9 runs).
  So it is a Sonnet misreading of an ambiguous spec, **not** caused by the rules text. Lesson: a check + escalation
  safety net is required; one model's blind spot is not another's.
- Blind judge for all arms: done 2026-11-09 — see §2.10.

### 2.10 Blind judge on all test-L runs (done, one batch, Opus 5.5 high, /60, arms hidden)

| Arm | Model.effort, setup | Judge /60 (runs) | Hidden tests | Cost/run |
|---|---|---|---|---|
| A-opus (A7/A8) | Opus medium, one session | **58.0** (58, 58) | 24·24 | $0.98 |
| L | Opus low, reset+handoff | 56.7 (55–59) | 24×3 | $0.287 |
| D-opus (D7/D8) | Opus medium, reset+handoff | 56.5 (55, 58) | 24·24 | $0.61 |
| **Y** | **Haiku high, reset+handoff** | **56.3** (53–58) | 24×3 | **$0.041** |
| **K** | **Haiku medium, reset+handoff** | **56.0** (55–57) | 24×3 | **$0.024** |
| Z | Sonnet high, reset+handoff | 56.0 (55–57) | 24×3 | $0.266 |
| A | Sonnet medium, one session | 55.7 (54–57) | 24×3 | $0.272 |
| E | tiers + escalation | 54.3 | 24×3 | $0.146 |
| H | Sonnet medium + 1 h cache | 54.3 | 24×3 | $0.184 |
| M | Sonnet medium + MAP.md | 54.3 | 24×3 | $0.177 |
| T | tiers Haiku/Sonnet | 53.7 | 24×3 | $0.072 |
| W | Sonnet medium + 40 tools | 53.7 | 24×3 | $0.181 |
| D | Sonnet medium, reset+handoff | 51.7 (49–54) | 9·24·24 | $0.166 |
| C | Sonnet medium, rules, one session | 51.7 | 24·5·24 | $0.280 |
| B | Sonnet medium, rules + reset | 51.3 | 9·24·24 | $0.154 |
| X | Haiku low | **44.0** (25, 52, 55) | 24·4·24 | $0.016 |
| 1-run evidence | haiku.xhigh 57, sonnet.xhigh 57, opus.high 55, opus.xhigh 55, sonnet.low 55 | | | $0.13–2.08 |

Readings:
- **Haiku 5.5 medium/high code was judged as good as Sonnet high and Sonnet one-session (~56/60) at 1/7–1/11 of the
  price.** Only Opus one-session was clearly higher (58) at 40× Haiku's price.
- **The weak cell is Sonnet medium with reset (D 51.7)**, not reset itself: Haiku and Opus with the same reset +
  handoff scored 56–56.5. Sonnet medium lost points on T1 (the ambiguous Duration spec) and T6 (bounds).
- **Low effort is unsafe** (Haiku low one run 25/60). xhigh: +1 point at 3–8× cost — not worth it.
- **The judge alone misses correctness:** sonnet.low scored 55/60 while failing 14 of 24 hidden tests. Quality
  gate = hidden/real tests first, judge second.

### 2.3 Test XL — 8 long meeting transcripts, decisions + changes (done)
Sonnet 5.5 medium, 3 runs/arm. All arms 48/48 decisions, 24/24 changes, 0 extras.

| Arm | Session renewal | Cost/run |
|---|---|---|
| N | never | $5.80 |
| R300 | new session at 300k | $2.82 |
| R150 | new session at 150k | $2.12 |
| RT | new session every task | **$1.05 (−82%)** |

### 2.4 Test XL2 — hard handoff + compaction (done, 3 runs/arm; scores re-computed with the fixed reasons checker)
Same 8 transcripts pasted in chat (not saved as files), reverts ("go back to meeting k"), a format rule given
mid-way (full numbers from M5), and a last task X10: reasons for each change (said in the transcripts).

| Arm | Decisions | Reverts | Changes | **Reasons** (3 runs) | Cost/run |
|---|---|---|---|---|---|
| N (never renew) | 48 ×3 | 11 ×3 | 24 ×3 | **24 · 24 · 24** | $6.86 |
| CMP (compact at 150k) | 48 ×3 | 11 ×3 | 24 ×3 | **24 · 24 · 24** | **$3.36 (−51%)** |
| R150 (new session at 150k) | 48 ×3 | 11 ×3 | 24 ×3 | 10 · 10 · 10 | $2.13 |
| RT (new session every task) | 48 ×3 | 11 ×3 | 24 ×3 | **0 · 0 · 0** | $1.16 |
| **RTS (new session every task + SAVE_RULE)** | 48 ×3 | 11 ×3 | 24 ×3 | **24 · 24 · 24** | **$0.71 (−90%)** ($0.37, $0.42, $1.35) |
| R150S (new session at 150k + SAVE_RULE) | 48 ×3 | 11 ×3 | 24 ×3 | **24 · 24 · 24** | $1.86 |

**Key finding — quality loss from reset:** reasons were only in the pasted transcripts. The handoff kept
decisions (what the task asked) but not reasons (asked only at the end), so after a reset they were gone:
RT 0/24, R150 10/24. Compaction (CMP) kept them (24/24) at about half the cost of N.
Design rules that follow:
1. **Raw inputs given in chat (transcripts, pasted docs) must be saved to files** before a reset, so a fresh
   session can re-read them. A handoff summary alone loses what nobody asked for yet.
2. Handoff = decisions + instructions + **reasons/context mentioned** + pointers to the raw files.
3. When raw inputs cannot be saved, compaction beats reset for quality.

**Fix confirmed (2026-11-10):** with SAVE_RULE in the system prompt the agent saved all 8 transcripts to sources/
in every run, and a new session every task got **24/24 reasons at $0.71 — full quality at −90% vs never renewing
and −79% vs compaction.** This is the recommended default for long work with pasted inputs.

### 2.5 Loops (done; no effect measurable)
- Loop 1 (simple traps) and Loop 2 (misleading EU number bug + two contradicting tests), Sonnet and Haiku,
  5 runs per arm, P = plain vs LP = loop rules. Every run solved it in 4–5 calls; no model looped; contradiction
  reported 10/10 (Sonnet), 9/10 (Haiku; one LP run missed it). Loop rules: **no evidence of saving**; keep only as
  a cheap safety rule (no cost seen), not as a measured win.

### 2.6 Subagents (done)
Bulk task over 8 transcripts (files on disk), Sonnet orchestrator.
- Free choice: orchestrator **never delegated** (grep was enough); all arms 100%; cost ~$0.08.
- Forced delegation (one helper per meeting): quality 100%; cost Sonnet helpers $0.46 (5.7×), Haiku helpers $0.12 (1.5×).
- Reading: **delegation does not save on bulk work the main agent can grep**; use it for isolation/parallel
  work or to keep a huge context out of the main chat, not for price.

### 2.7 Routing on test L (done; judge pending)

| Arm | Routing | Hidden tests | Cost/run | vs Sonnet D (~$0.166) |
|---|---|---|---|---|
| K | Haiku 5.5 medium everywhere | 24·24·24 | **$0.024** | −86% |
| T | tiers: Haiku easy, Sonnet medium tasks | 24·24·24 | $0.072 | −57% |
| E | tiers + re-run one level up when public tests fail | 24·24·24 | $0.146 | −12% (Sonnet failed task 1 in 2/3 runs → Opus fixed it) |
| L | Opus 5.5 low everywhere | 24·24·24 | $0.287 | +73% |

### 2.8 Effort on test L (done; max = 1 evidence run per model, sonnet.max not finished — killed by an outage, not re-run)

| Model.effort | Hidden tests | Cost/run |
|---|---|---|
| Haiku low (X) | 24·**4**·24 | $0.016 |
| Haiku medium (K) | 24·24·24 | $0.024 |
| Haiku high (Y) | 24·24·24 | $0.041 |
| Haiku xhigh | 24·24·24 | $0.119 (130–158 calls) |
| Sonnet low | **10 · 10** · 24 | $0.131 |
| Sonnet medium (D) | 9·24·24 | $0.166 |
| Sonnet high (Z) | 24·24·24 | $0.266 |
| Sonnet xhigh | 24·24·24 | $0.704 |
| Opus low (L) | 24·24·24 | $0.287 |
| Opus medium (D7/D8) | 24·24 | $0.61 |
| Opus high | 24·24·24 | $0.942 |
| Opus xhigh | 24 (run 1) | $2.08 |
| max (all 3 models) | haiku.max 24 (328 calls) $0.52 · **opus.max 24 (237 calls) $10.34** · sonnet.max running | — |

Readings: **low is risky** (Haiku low failed 1 of 3 runs, **Sonnet low failed 2 of 3**). **xhigh/max cost 3–8× with no gain**
on these tasks — by choice, keep them to one evidence run only. Docs agree: max = small gain, overthinking.

### 2.9 Matrix test — kinds of work × model × effort (done: 10 kinds + hard set of 8 kinds, Haiku xhigh/max, cascade, second judge)
`runner_matrix.py`, 3 runs per cell, judge Opus 5.5 high with strict rubrics. Score = judge /10, or exact checker.
Cost = mean per task (single-call tasks' costs vary with cache hits; treat as rough).

| Kind of work | Haiku med | Haiku high | Sonnet med | Sonnet high | Opus med | Opus high |
|---|---|---|---|---|---|---|
| Bug fix (hidden tests) | 100% $0.003 | 100% | 100% | 100% | 100% | 100% $0.05 |
| Fact-check vs policy (exact) | 10/10 $0.0002 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| Constraint scheduling (exact) | 100% $0.0006 | 100% | 100% | 100% | 100% | 100% |
| Extraction from transcript (exact) | 100% $0.005 | 100% | 100% | 100% | 100% | 100% $0.26 |
| Data analysis memo (judge) | 8.3 $0.001 | 8.7 | 9.0 | 9.0 | 9.3 | 9.3 $0.03 |
| Writing, English reel (judge) | 8.3 $0.0006 | 8.7 | 8.0 (2/3 over word limit) | **9.0** $0.010 | 9.0 $0.020 | 9.0 |
| **Writing, Darija (judge)** | 5.7 ✗ | 5.3 ✗ (Arabic script 2/3) | 5.0 ✗ | 7.3 | **8.0** $0.018 | **9.0** $0.034 |
| **Hard business decision (judge)** | 5.3 ✗ | 7.0 | 6.7 | 7.7 | **8.3** $0.083 | 8.0 |
| Partner thinking (judge) | 7.7 $0.001 | 7.7 | **8.7** $0.015 | 7.7 | 7.7 $0.040 | 8.0 |
| Small code design (hidden 5/5 all + judge) | **7.7** $0.003 | **8.0** $0.005 | 6.7 | 7.3 | 7.3 $0.062 | 7.7 $0.086 |

Notes:
- Design test v1 was flawed (hidden test needed a kwarg name the spec never gave); fixed spec + stricter
  rubric, re-run = table above.
- Partner: Opus asked 8–10 questions (too many) → lower score than Sonnet medium.
- Decision trap: 9% monthly churn eats growth; right answer = fix onboarding (C) first. Haiku medium and
  one Sonnet medium run picked ads without handling churn/cash (judge 4).
- Easy kinds (bug, fact-check, scheduling, extraction) did not separate models — every model 100%. Harder
  variants would be needed to find where Haiku breaks on them.

#### Hard set (done, 8 kinds × 8 configs × 3 runs = 192)
Score = exact checker, or judge /10 (Opus 5.5 high). Cost = mean per task.

| Kind | Haiku med | Haiku high | Haiku xhigh | Haiku max | Sonnet med | Sonnet high | Opus med | Opus high |
|---|---|---|---|---|---|---|---|---|
| Bug, 3 root causes in 3 files (hidden 7) | 100% $0.0016 | 100% | 100% | 100% | 100% | 100% | 100% | 100% $0.050 |
| Fact-check, 12 tricky claims | 12/12 $0.0003 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 |
| Scheduling, unique solution | 100% $0.0015 | 100% | 100% | 100% | 100% | 2/3 ✗ | 100% | 100% |
| Extraction ~36k tokens, reverts + reasons | 100% $0.0034 | 100% | 100% | 100% | 100% | 100% | 100% $0.27 | 100% |
| Darija: WhatsApp reply to angry client | 5.7 | 4.7 | 6.7 | 7.7 $0.006 | 3.7 ✗ (Arabic 2/3) | 8.0 $0.007 | **8.7** $0.015 | **9.0** $0.017 |
| Darija: explain "API" to a shop user | 5.7 | 6.3 | 6.3 | 7.3 | 5.7 | 6.7 | **8.3** $0.019 | 8.0 |
| Darija: Instagram caption | 6.3 | 6.0 | 7.0 | 7.0 | 4.3 ✗ (over limit 3/3) | 7.7 $0.009 | 7.7 $0.018 | **8.3** $0.020 |
| Project plan, 8-week launch with traps | **9.0** $0.002 | 9.0 | 9.0 | **0 ✗ empty 2/3** | 9.0 | 9.0 | 9.0 $0.076 | 9.0 |

Readings:
- The "hard" checkable kinds still did not break Haiku medium (bug in 3 files, 12 tricky claims, unique
  schedule, 36k-token extraction with reverts and reasons): 100% at 1/10–1/80 of Opus price.
- **Darija confirmed on 3 more prompts: Opus medium is the cheapest config that is reliably ≥ 8.** Sonnet high is
  close on two of three (8.0, 7.7) but weak on explaining (6.7). Sonnet medium is the worst on Darija (Arabic
  script, word limits). Haiku max helps (7–7.7) but stays below Opus.
- Project plan: every config 9/10 except Haiku max (empty answer 2/3 — max again ran out of output budget).
  The plan rubric may be too easy to separate models (all 9s).
- **Haiku max now failed with an empty answer in 5 of 6 long-reasoning runs** (decision 3/3, project plan 2/3).

#### Cascade simulation from the real outputs (`analyze_matrix.py`, `matrix_analysis.txt`)
Chain = try Haiku medium; accept if its cheap check passes (tests / exact checker / rule check); else Sonnet high; else Opus medium.

- On checkable kinds the cascade = top quality at Haiku price (bug, bug_hard, fact-check ×2, scheduling ×2,
  extraction ×2: quality 1.00 at $0.0002–0.005).
- **On judgment kinds the cascade does not work:** Haiku's answer passes the rule check (Latin letters, word
  count, keywords) even when its quality is low, so it never escalates — Darija 0.57–0.63, decision 0.53,
  partner 0.77, versus 0.83–0.90 for the right model. **A check only protects the quality it measures.**
- Design rule that follows: **route judgment kinds (Darija, decisions, partner, public writing) directly to the
  right model by kind**; use the cascade only where a real check exists (tests, exact answers).
  A judge-model gate would be the alternative, but it costs about as much as using the right model directly.

#### Haiku xhigh / max on the first 10 kinds (done, 3 runs each)

| Kind | Haiku medium | high | xhigh | max |
|---|---|---|---|---|
| Design (judge) | 7.7 $0.003 | 8.0 | 8.0 | 7.7 $0.035 |
| Bug / fact-check / scheduling / extraction | 100% | 100% | 100% | 100% (4–20× cost) |
| Writing English | 8.3 | 8.7 | 9.0 $0.0013 | 8.7 |
| Writing Darija | 5.7 | 5.3 (Arabic script 2/3) | 6.7 (Arabic 2/3) | **7.3** $0.019, no Arabic |
| Analysis | 8.3 | 8.7 | 9.0 | 9.3 $0.016 |
| Decision | 5.3 | 7.0 | 5.3 | **0 — empty answer 3/3** |
| Partner | 7.7 | 7.7 | 8.3 | **9.0** $0.013 |

Readings:
- **Max can fail hard:** on the business decision Haiku max spent the whole 64k output budget thinking and
  returned **no answer** in 3/3 runs ($0.032 each). Never use max without a big budget and a fallback.
- Haiku max lifted partner thinking to 9.0 (Sonnet medium 8.7 at $0.015, similar price) and Darija to 7.3
  (still below Opus medium 8.0 at about the same price $0.018) — so on these kinds max Haiku is not cheaper
  than the right bigger model and is less reliable.
- xhigh: small gains (+0.3–0.7) on writing/analysis/partner at 2–3× Haiku-medium price; still pennies.

#### Second judge (Sonnet 5.5 high) on all 240 judged matrix answers (done, `judge2.py`, `judge2.log`)
- Agreement: mean |difference| 0.57 points; **91% of answers within 1 point** of the Opus judge.
- Same best config on 6 of 10 kinds (Darija explain, Darija reply, decision, partner, project plan, English writing).
  Where they differ, the top configs are within 0.3 points (analysis, design, Darija ×2).
- **Possible self-preference on Darija:** the Opus judge gave Opus answers 1–2 points more than the Sonnet judge
  did (Darija reel: Opus high 9.0 vs 7.0; caption 8.3 vs 6.7). The order mostly holds (Opus ≥ Sonnet high >
  Haiku > Sonnet medium), but the size of Opus's lead on Darija is uncertain. Sonnet medium is last on Darija
  under both judges.
- Partner thinking: both judges rank Haiku max (9.0/8.7) and Sonnet medium (8.7/8.7) on top; Haiku max is
  unreliable elsewhere (empty answers), so Sonnet medium stays the pick.
- Next step for Darija: a **blind native-speaker rating** of a few Darija answers (the user is the real Darija judge).

#### Native-speaker blind rating of Darija (done 2026-11-09, `darija_blind_map.json`, widget `darija_rating.html`)
9 answers (run 1 of dar_reply, dar_explain, dar_caption × Haiku medium / Sonnet high / Opus medium), labels hidden.

| Config | User /10 (reply, explain, caption) | Opus judge | Sonnet judge |
|---|---|---|---|
| **Opus medium** | **10 · 10 · 10 = 10.0** | 8.3 | 7.7 |
| Sonnet high | 7 · 6 · 7 = 6.7 | 7.3 | 7.7 |
| Haiku medium | 5 · 4 · 5 = 4.7 | 6.0 | 6.7 |

Readings:
- **The real Darija judge separates the models much more than either AI judge:** Opus is perfect for the user,
  Sonnet high is clearly weaker (−3.3), Haiku medium is not usable (4.7).
- The worry that the Opus judge over-favoured Opus on Darija is **dismissed**: both AI judges actually
  *under*-rated Opus and *over*-rated Haiku and Sonnet. The Sonnet judge could not tell the difference at all.
- **Rule: Darija → Opus medium, no exceptions.** AI judges are not reliable graders of Darija quality; the user (or
  a native speaker) is the reference for Darija.

### 2.11 Step 2, test #1 — which model should the Chief run on (done 2026-11-10, `runner_chief.py`)
8-turn Darija chat (decision, pasted ~35k-token transcript, code fix, Darija reel, preference, task switch, site
plan, quick question); `delegate` tool to cheap/mid/top; Opus judge per turn (/80); 3 runs each.

| Chief config | Judge /80 (runs) | Routing /8 | Cost per chat (incl. helpers) |
|---|---|---|---|
| **Opus 5.5 medium** | **69.7** (68, 71, 70) | 7 | $0.63 |
| Opus 5.5 high | 67.3 (68, 67, 67) | 7 | $0.64 |
| Sonnet 5.5 high | 58.0 (64, 57, 53) | 6–7 | $0.55 |
| Sonnet 5.5 medium | 57.7 (56, 56, 61) | 4–6 | $0.36 |
| Haiku 5.5 high | 52.7 (52, 53, 53) | 4 | $0.024 |

Readings:
- **Chief = Opus medium.** Best and most stable quality; high adds cost and no quality.
- Sonnet as Chief is cheaper only a little (it delegated decision/Darija/plan to Opus anyway, so it pays for Opus
  plus itself) and **fell into the decision trap 3 of 6 runs** (3–5/10). Haiku as Chief: weak Darija and decisions.
- Every Chief **kept the pasted transcript itself** instead of delegating it to the cheap tier (context grew to
  ~60–70k for the rest of the chat). Rule to add: pasted bulk material → save to a file, hand the file to a cheap
  helper, keep only the result. (Then the context stays small.)
- The Chief's own context is the main cost (Opus chief $0.55–0.67 of $0.56–0.77): keeping its chat short
  (new session per task + handoff) is where the saving is, not a cheaper Chief model.

### 2.12 Step 2, test #2 — how many reviewers on the same work (done 2026-11-10, `runner_review.py`)
General test (any review: fact-check, code review, plan review). 16 planted errors in 3 artifacts (memo vs source 6,
code vs spec 4, plan vs facts 6). Independent reviews: Sonnet medium ×9, Haiku medium ×5, Opus medium ×5 per artifact;
Opus judge (given the planted list) counted caught errors and false alarms. Multi-reviewer arms = union of independent reviews.

| Arm | Errors caught /16 (worst) | False alarms | Cost |
|---|---|---|---|
| **ONE Opus medium** | **16.0** (16) | **0** | $0.058 |
| ONE Haiku medium | 15.4 (15) | 0.2 | **$0.002** |
| TWO Haiku medium | 15.7 (15) | 0.4 | $0.004 |
| ONE Sonnet medium | 14.4 (13) | 0.56 | $0.019 |
| TWO Sonnet medium | 15.1 (14) | 1.11 | $0.038 |
| THREE Sonnet medium | 15.5 (14) | 1.67 | $0.057 |
| GATED Sonnet medium (2nd only if 1st says "low confidence") | 14.4 | 0.56 | $0.019 — never fired: 0 of 27 reviews said low |

Readings:
- **One reviewer on the right model beats several on a weaker one.** Three Sonnet reviewers cost the same as one Opus
  ($0.057 vs $0.058), caught fewer errors (15.5 vs 16) and brought 1.67 false alarms vs 0.
- Each extra reviewer adds false alarms (Sonnet: 0.56 → 1.11 → 1.67), so duplicates also cost the user's time.
- **Self-reported confidence is useless as a gate:** no reviewer ever said "low", even when it missed errors.
- Haiku medium is a strong cheap reviewer here (15.4/16 at $0.002); Sonnet medium was the weakest single.
- Rule: **one reviewer per piece of work; pick the reviewer's model by the stakes** (cheap tier for routine checks,
  top tier for work that gets published or decided on). A second reviewer only when there is a real signal
  (a failed test, a disagreement with the author, a high-stakes release) — never by default, never "for safety".

### 2.13 Step 2 — bulk pasted material as a file (done 2026-11-10, `AB_ATTACH=1 runner_chief.py opus.medium`)
Same 8-turn Chief chat; the 35k-token transcript arrives as an attached file path instead of pasted text, and the
Chief hands it to a cheap helper (delegate `files` field) and keeps only the result.

| Opus medium Chief | Judge /80 | Routing /8 | Max context | Cost per chat |
|---|---|---|---|---|
| Transcript pasted in chat | 69.7 (68, 71, 70) | 7 | ~62k | $0.63 |
| **Transcript as file → cheap helper** | 66.7 (67, 67, 66) | **8** | **~12k** | **$0.27 (−57%)** |

The −3 points sit mostly on turns the file change does not touch (turn 1 decision 9.0 vs 7.7 with the same prompt;
code 8.7 vs 7.7) → run-to-run noise; the extract turn itself was equal (8.3 vs 8.0). Reading: **large inputs must
reach the Chief as files (host attachment or adapter), never as chat text** — the context stays ~5× smaller for the
rest of the chat. This needs a host feature or adapter: once text is pasted into the chat, it stays in every later call.

### 2.14 Step 2 — cheap tier past its price step (done, `runs_xl_haiku/`, Haiku 5.5 medium, 8 long transcripts, 2 runs)
Haiku 5.5 bills 5× for prompts over 100k tokens.

| Arm | Quality | Calls over 100k | Cost (with step) | Cost if there were no step |
|---|---|---|---|---|
| Never renew (max 425k) | 48/48 · 24/24 | 17 of 20 | $0.51 | $0.11 |
| New session at 150k | 48/48 · 24/24 | 14–15 of 25 | $0.30 | $0.08 |
| **New session every task (max 58k)** | 48/48 · 24/24 | 0 | **$0.05 (−90%)** | $0.05 |

Reading: past the step the cheap tier costs about **4.7×**; a cheap agent must hand off **before** its step
(Haiku: under 100k). The 150k rule is too late for Haiku. (Sonnet on the same work: never renew $5.80, every task $1.05.)

### 2.15 Step 2 — code graph (Graphify) on the real repo (done 2026-11-10, after fixing a harness bug)
Graphify 0.9.105 built a local graph of click (3,498 nodes, 6,759 edges, no model, ~1 min).

**Harness bug found 2026-11-10 (fixed):** the graph prompt showed an absolute path inside the test folder; some agents
followed it, found the shared fixture `big/click` and **edited the fixture itself** (first edit 14:48 UTC). Every
test-L run that copied the fixture after that started from a half-done, wrong base (Duration as an instance). Those
runs are invalid and moved to `runs_l_contaminated/` (G2, G4–G6, N4–N6, F1–F6). The fixture was restored with git
and is now read-only; runs copy it and make the copy writable; the graph command is a plain `graphify` on PATH.
All other fixtures were checked by timestamp: untouched. Earlier test-L runs (before 14:48) are valid.

**Retraction:** the "Haiku misreads task 1 ~40%" correction (written just before) came from the contaminated runs and
is withdrawn. Clean Haiku runs: task 1 correct in 20 of 20 (K1–3, N1–3, N7–12, G1, G3, F1–6).

Clean results (Haiku 5.5 medium, reset + handoff, same batch for F and N7–N12; fixture checked untouched after the run):

| Arm | Hidden tests | Judge /60 | Graph calls per run | Cost/run |
|---|---|---|---|---|
| F — graph + rule "query it first" (6 runs) | 24/24 × 6 | 55.3 (53–57) | 11–16 | $0.030 |
| N — no graph (9 runs: N1–3, N7–12) | 24/24 × 9 | 56.1 (53–57) | — | $0.025 |
| G — graph optional (G1, G3) | 24/24 × 2 | 56 (55, 57) | 0 (not used) | $0.025 |

Reading: on a 29k-line repo the graph **adds ~21% cost and no quality** (judge −0.8, within noise): the agent queries
it, then still reads and greps. A code graph is not worth it at this size; it may pay only on repos too big to grep
(not tested). Haiku task-1 result on clean runs: correct in 20 of 20.

### 2.16 Step 2 — re-plan checkpoint (every 25 calls without progress): not testable here
No run in any test went 25 calls without progress (longest task ~20 calls with steady progress). Kept as a free
guard; no evidence for or against.

### 2.17 Step 3 — remaining design items (2026-11-10)

**Huge outputs (OUT, `runner_ops.py`):** build log of 6,000 lines with one error at line 4,124; host cap 30k chars.

| Arm | Fixed | Max context | Cost Haiku / Sonnet medium |
|---|---|---|---|
| P plain | 6/6 | ~16–17k | $0.0026 / $0.048 |
| **R "filter big outputs (grep/tail)"** | 6/6 | **~2–3k** | **$0.0010 (−63%) / $0.012 (−75%)** |
→ the output rule **works**: same result, context 6× smaller. Without a host cap the gap is bigger.

**Polling (POLL):** a deploy that finishes after 75 s. Plain 5–6 calls, rule "wait inside one call" 4 calls; cost the
same (tiny). Agents mostly waited sensibly already → rule kept as cheap guard; saving small here.

**Loop trap (LOOP):** the file the test reads is regenerated from a template on every test run. No model fell for
it (4 calls, 12/12 fixed the template). Rule: no effect measurable — kept as a free guard.

**Planning rule (PL, test L, Haiku medium, 6 runs):** "short plan in PROGRESS.md before multi-file tasks": hidden 24/24 ×6,
judge 54.3 vs 55.4 without (9 runs), cost $0.026 vs $0.024 (+7%). → **no gain on clear tasks**; keep planning only for big,
unclear work (not testable here), never as a rule for every task.

**Tools (test L, Haiku medium, 3 runs each):** all 40 extra tool schemas loaded (WH) $0.033 (+36%), judge 57.0;
**deferred loading** (only a search tool, DF) $0.023 (−8% vs none, = no extra tools), judge 56.3; none (N, 9 runs) $0.024, 55.4.
→ every loaded schema rides every call; **deferred loading removes the cost** (the measured +36% is for ~7k tokens of
schemas on a cheap model; tool servers that wrap a CLI should be skills/deferred).

**Helpers inheriting CORE-lite (FORCE_H vs FORCE_H0, forced delegation, Haiku helpers):** helpers with the rules (short
summary, long result in the file) + summary cap: $0.126 per delegated run vs $0.165 with a plain helper prompt (−24%),
same quality 100%. Only 2 delegated runs per arm → weak evidence, consistent direction.

**Files across 5 sessions (Opus Chief, 3 runs each, judge /40):**

| Arm | Judge /40 | Cost (5 sessions) | Files at the end |
|---|---|---|---|
| 0 no rule | 30.0 (32, 28, 30) | $0.28 | the Chief made one project file by itself |
| A one PROGRESS.md handoff | 28.0 (29, 28, 27) | **$0.45** | PROGRESS 5–6k chars, rewritten every session |
| **B USER + PROJECT + DECISIONS + PROGRESS** | 29.0 (32, 29, 26) | **$0.25 (−45% vs A)** | small files, DECISIONS append-only |
- Quality equal across arms (session-5 summary lost points in every arm: the price was given as a "fact", not a
  "decision" — a test-design artifact, same for all). **Split files cost 45% less than one growing handoff** (A rewrites
  and re-reads a long PROGRESS every session). A strong model kept notes even without a rule (arm 0), but that is not
  guaranteed for other models/hosts; the rule makes it deterministic.

**Notifications in the Chief's chat (3 notices ~1.3k tokens per turn, 3 runs):** judge 69.7 (= base 69.7), cost $0.585 vs
$0.63 base → **no measurable effect** in a chat already ~60k (+2% tokens). They matter in short chats and over long
days (they accumulate); keep the rule (notifications go elsewhere), low priority.

**Heartbeat through the model (Opus medium, 11k fixed prompt, cold cache):** $0.061 per "nothing new" run →
every 30 min = **~$2.95/day per agent** for nothing; a skip gate (compare a hash/mtime first) = $0. → rule confirmed.

**Gemini 3.8 Flash** (free-tier key; Argon/Carbon not available on free tier: 429): first 4 answers fine (English
reel judge 8/8, Darija reel 7/7, no Arabic script); then Google returned 503 "high demand", and on the re-run 429 "quota exceeded" (free-tier daily limit). Stopped
at 4 of 36 answers → **Gemini not tested properly; needs a paid key.** **OpenAI:** no key → not tested.

**How the subscription counts usage (13.1) — clean test done 2026-11-10 18:29–19:08 UTC (`runner_usage.py`, nothing else
running, 39% → 42% of the week).** Each phase ran between two ticks of the weekly counter (exactly 1%).

| Phase (1% of the week each) | API-price dollars | Tokens |
|---|---|---|
| A: Opus 5.5, agent-like (50k cached prefix, short answers) | **$32.8** | 130M cache read ($26.1), 329k output ($6.6) |
| B: Sonnet 5.5, output-heavy (long writing, no cache) | **$14.7** | 1.47M output ($14.7) |

Readings:
- **The plan does not count like API prices.** Per API dollar, output-heavy work used **2.2×** more of the limit than
  cache-read-heavy work. If output counts at its API price, cache reads count at only ~0.3× theirs (model and token
  type are mixed in this test — one run each; the earlier by-model snapshot showed models weighted like their prices).
- **1% of this weekly limit ≈ $33 of agent-like work, ≈ $15 of output-heavy work.**
- Meaning for the design: on a subscription, long cached chats are cheaper than API math says, and **output (high
  effort, thinking, long writing, verbose helpers) is the expensive part** — supports "medium effort, no xhigh/max",
  short helper summaries, and filtering outputs. Session resets still pay (cache writes and the growth of every call).

**Visibility tool (rule 10):** `usage_report.py` built and run on the test logs: per-agent/model table + alerts
(long chat > 150k, cheap-tier price step, > 300 calls) — it flagged every long-session arm and Haiku's 100k step.

## 3. Routing table — current recommendation (top quality first, then lowest price)

| Kind of work | Default | Why | Route up when |
|---|---|---|---|
| Clear task with a check (bug fix, small feature with tests, extraction, fact-check, scheduling, format) | **Haiku medium**, with the real check + escalation as safety net | same quality as Opus here, 10–80× cheaper, also on the hard set (3-file bug, 12 tricky claims, unique schedule, 36k-token extraction); on the real repo (test L) Haiku code judged 56/60 = Sonnet high, Opus 58 | real check (tests / exact answer) fails → Sonnet high → Opus medium (cascade works only here) |
| Small code design, clear spec | **Haiku medium/high** | judge 7.7–8 = best; simple code | big/multi-file architecture → Opus medium |
| Data analysis memo | Sonnet medium (Haiku ok for quick internal) | 9.0 vs 8.3 | numbers drive a decision → Opus medium |
| Writing English (public) | **Sonnet high** | 9.0, keeps word limits | — |
| **Writing Darija** | **Opus medium, always** | **native-speaker blind rating: Opus 10/10 on 3 of 3, Sonnet high 6.7, Haiku 4.7**; AI judges under-rate the gap; Sonnet medium worst (Arabic script, limits) | — (rule checks and AI judges can't catch weak Darija: route directly) |
| **Hard decisions, project planning (Chief's planning)** | **Opus medium** | decision: only config never trapped (8.3; Sonnet judge 9.0); project-plan test: all configs 9/10 (rubric too easy) | — (route directly) |
| **The Chief itself (the agent the user talks to)** | **Opus medium** | Chief test 69.7/80 vs Sonnet 58, Haiku 53; Sonnet fell into the decision trap 3/6 | — |
| Partner thinking / brainstorm | **Sonnet medium** | 8.7 under both judges, best reliable and cheap | — (route directly) |
| Large pasted inputs | arrive as a **file** handed to a cheap helper, never chat text | Chief chat −57%, context 62k → 12k, quality within noise | — |
| Cheap-tier context | hand off **before 100k** (Haiku price step) | past 100k Haiku costs ~4.7×; every-task reset −90% | — |
| Long sessions | **new session per task + save pasted inputs to files (SAVE_RULE) + handoff with reasons**; compaction only when inputs can't be saved | XL2: 24/24 reasons at −90% (vs 0/24 without saving); L: −38…−43%; XL: −82% | — |
| Effort | medium default; high only where the table says; never low for real work; xhigh/max not used | low failed runs; xhigh/max 3–17× cost, no gain (Opus max $10.34/run); **Haiku max returned empty answers in 5/6 long-reasoning runs** | — |
| Cache | 5-min default; 1-hour only across long pauses in one session | 1-hour cost +11% in continuous work | — |
| Reviews / fact-checks / QA | **one reviewer**; cheap tier for routine, top tier for published/decided work | one Opus 16/16, 0 false alarms = cost of three Sonnet (15.5, 1.67 false alarms); self-reported confidence never fired | 2nd reviewer only on a real signal (failed test, disagreement, high-stakes release) |
| Big command outputs | **filter before reading** (grep/tail/quiet) | −63…−75% cost, context 6× smaller, same result | — |
| Tool schemas | only the tools the job needs; **deferred loading** for the rest | 40 loaded schemas +36% on a cheap model; deferred = 0 | — |
| Project memory | **USER / PROJECT / DECISIONS / PROGRESS** split | −45% vs one growing handoff over 5 sessions, same quality | — |
| Heartbeats | **skip gate** before the model | $0.061 per empty Opus run (~$3/day/agent at 30 min) vs $0 | — |
| Subagents | not for saving; only isolation/parallel/huge context | forced delegation 1.5–5.7× cost | — |

Key rule from the cascade analysis: **a check only protects the quality it measures.** Use the cheap-first cascade only
where a real check exists; route judgment kinds (Darija, decisions, partner, public writing) directly by kind.

Caveats: tasks are short and clear; two judges (Opus, Sonnet) agree within 1 point on 91% of answers but Opus may
favour Opus on Darija; 3 runs per cell. Even the hard set of checkable kinds did not break Haiku medium — its limit
on those kinds is still unknown (larger, multi-day work).

## 5. Open items (next)
1. ~~Blind judge on test L arms~~ — done (§2.10): Haiku medium/high code ≈ Sonnet high (~56/60); Sonnet medium + reset weakest (51.7).
2. ~~Finish XL2 group 2~~ — done (§2.4). Fix test (RTS/R150S with SAVE_RULE) running.
3. ~~Project-planning test~~ — done (hard set): all configs 9/10 except Haiku max; rubric too easy to separate models.
4. ~~Harder variants of the easy kinds~~ — done (hard set): Haiku medium still 100%. Limit still unknown.
4b. ~~Blind native-speaker rating of Darija~~ — done: Opus 10, Sonnet high 6.7, Haiku 4.7.
4c. ~~Finish effort sweep~~ and ~~XL2 fix~~ — done.
5. Write the final report + move the routing table into DESIGN.md §9/§12b.
6. Monthly refresh step: Artificial Analysis (artificialanalysis.ai) for candidates → small gauge test → update the table.

### 2.18 Kit test (kit/AGENTS.md + ROUTING + templates used as the prompt) — 2026-11-10

**v1** (3 runs each, Opus 5.5 medium main agent with a user-chosen name, transcript as file):
| Test | Kit v1 | Reference (test prompt) |
|---|---|---|
| Chief chat /80 | 58, 63, 65 = **62.0**, routing 6–7/8, $0.267 | attach arm 66.7, routing 8/8, $0.27 |
| Files, 5 sessions /40 | 31, 32, 30 = **31.0**, $0.415 | split files B 29.0, $0.25 |

Failures found in v1: the main agent did the code task itself instead of a cheap helper; sent a tiny "note my
preference" reply to a helper; passed a helper's extraction on without checking it (6/10 in 3/3 runs); no new-session
offer on a topic switch; PROGRESS.md grew to 1.9–3.5k (cost +66% vs split files). Run 1 decision 4/10 (recommended
the wrong option; run-to-run variance seen before).
**Fixes in v2:** check helper results before passing them on; checkable work → cheap helper, small replies itself;
one-line session offer on every topic switch; PROGRESS.md ~30 lines, handoff replaced not appended; read MAP.md only
when needed; create missing files. v1 runs in `runs_kit_v1/`.

**v2** (`runs_kit_v2/`): Chief chat 63, 66, 64 = **64.3/80**, routing 7, 8, 7 /8, $0.33 (ref 66.7, 8/8, $0.27) —
helper checks and topic-switch offers now happen; extraction 7/10 (was 6); remaining routing miss = "note my
preference" sent to a helper (in this harness the main agent has no file tool, so it delegates the USER.md write —
a harness limit). Within noise of the reference (Opus Chief runs ranged 66–72 before). Files 31, 30, 28 = **29.7/40**
(ref 29.0) but $0.40 (ref $0.25, +60%): the kit makes the agent write more (MAP.md, extra plan files, PROGRESS.md
1.3–1.8k) — output is the costly part.
**Fix v3:** PROGRESS.md max ~15 lines, rewritten not appended; files hold short lines; no extra files (no MAP.md for
one project, no answer copies) unless asked. 
- **v3** (`runs_kit_v3/`): files 28, 29, 28 = 28.3/40, $0.34 (+36%). PROGRESS.md still 1.4–1.6k.
- **v4** (section 4 rewritten: decisions/preferences/facts to their files at once, PROGRESS.md = task + next step
  ≤10 lines, handoff only what is not in other files, read start files in one call, no extra files):
  files 27, 30, 29 = **28.7/40, $0.297**.
- **Control BK** = full kit rules but section 4 swapped for the proven B memory rule + "read files first" start
  line: 30, 27, 29 = **28.7/40, $0.272**.
- Reading: all arms 28.3–29.7 = same quality (noise ±1.5). Cost vs the bare B prompt ($0.25): the rest of the
  kit's rules (sections 1–3, 5–8, ~1.3k tokens on every call) add ~+9%; kit v4's own memory section adds ~+9% more,
  within run-to-run spread (K 0.29–0.31, BK 0.25–0.30). Those rules are the ones that save −45…−90% elsewhere
  (sessions, routing, outputs), so on the whole flow the kit pays for itself. **Kit v4 accepted**; an adapter that
  injects the "read files first" start line should close the rest (BK has it).

- **Why not near 40/40 (question):** session 5 ("summary of all decisions") scored 4–6 in **every** arm,
  even with no files. Two causes: (1) test bug — the checklist wanted "price 900 MAD" as a decision with a reason,
  but the user gave it as a fact with no reason, and read "kol jem3a" only as Friday; fixed (4 decisions, price =
  settled fact, weekly or Friday both fine). (2) real rule gaps — agents logged "1500?" as an open price question
  and reopened it; one run (v5 K_2) never logged the first-message decisions (DECISIONS.md 119 chars) → 23/40;
  the session-offer line at the top broke "opinion in the first line".
- **v5 → v6 kit fixes:** session offer goes at the end; answer only what was asked, do not reopen settled things;
  log **every** decision with its reason at once, even several in the first message; a "what if we changed X?"
  question is not a decision.
- **Fixed checklist, `runs_files_v5/`:** B (bare memory rule) 30, 32, 30 = **30.7/40, $0.255**.
  **Kit v6 (6 runs):** 31, 34, 33, 32, 33, 32 = **32.5/40, $0.270** (+6% cost, +1.8 quality); session 5 now 6–8.
  Remaining point losses = judge strictness on extras/padding. **Kit v6 accepted.**


### 2.20 Jev (TypeSafe) on OpenRouter (done 2026-11-10, `runner_jev.py`, `analyze_jev.py`, `jev_gates.py`, `runs_jev/`, `jev_analysis.txt`)
**Part 1 — `typesafe/jev-router`** (Jev picks model + reasoning effort per request, and per turn in tool loops) on all 18
matrix kinds × 3 runs, same prompts, same checkers, same blind judge (Opus 5.5 high, Anthropic direct). Two arms:
**JR-any** (no restriction, Jev default policy = cost_tier medium) and **JR-claude** (plugin `jev-router` with
`models` = Haiku/Sonnet/Opus 5.5 + hard `excluded_models` for every other author and older Claude models; it held:
only Haiku 5.5 and Opus 5.5 were ever served). Reference = our routing table (§3) on the stored §2.9 results.
Router cost = OpenRouter `usage.cost` summed over every call of the task; reference cost = harness price table
(OpenRouter's Claude prices are the same list prices). q = judge/10 or exact checker.

| Kind | Ref (our route) q / $ | JR-any q / $ / served | JR-claude q / $ / served |
|---|---|---|---|
| bug | 1.00 / $0.0029 (haiku.medium) | 1.00 / $0.0265 / {'gpt-6.1-sol': 7, 'opus': 6} eff {'medium': 1, 'low': 6, 'high': 1} | 1.00 / $0.0325 / {'opus': 10} eff {'low': 8} |
| bug_hard | 1.00 / $0.0016 (haiku.medium) | 1.00 / $0.0154 / {'gpt-6.1-terra': 10, 'gpt-6.1-sol': 15} eff {'low': 9, 'medium': 16} | 1.00 / $0.0367 / {'opus': 11} eff {'medium': 6, 'low': 5} |
| factcheck | 1.00 / $0.0002 (haiku.medium) | 1.00 / $0.0002 / {'haiku': 2, 'gpt-6-luna': 1} eff {'medium': 3} | 1.00 / $0.0002 / {'haiku': 3} eff {'medium': 2} |
| factcheck_hard | 1.00 / $0.0003 (haiku.medium) | 1.00 / $0.0003 / {'deepseek-v4.1-flash-1017': 2, 'haiku': 1} eff {'high': 2, 'medium': 1} | 1.00 / $0.0003 / {'haiku': 3} eff {'medium': 3} |
| plan | 1.00 / $0.0006 (haiku.medium) | 1.00 / $0.0005 / {'haiku': 1, 'deepseek-v4.1-flash-1017': 2} eff {'medium': 1, 'high': 2} | 1.00 / $0.0005 / {'haiku': 3} eff {'medium': 3} |
| plan_hard | 1.00 / $0.0015 (haiku.medium) | 1.00 / $0.0146 / {'gemini-3.8-flash': 3} eff {'medium': 3} | 0.67 / $0.0019 / {'haiku': 3} eff {'medium': 3} |
| extract | 1.00 / $0.0051 (haiku.medium) | 1.00 / $0.0177 / {'gemini-3.8-flash': 3} eff {'medium': 3} | 1.00 / $0.0029 / {'haiku': 3} eff {'medium': 3} |
| extract_hard | 1.00 / $0.0034 (haiku.medium) | 1.00 / $0.0498 / {'gemini-3.8-flash': 3} eff {'medium': 3} | 1.00 / $0.0034 / {'haiku': 3} eff {'medium': 3} |
| design | 0.77 / $0.0030 (haiku.medium) | 0.70 / $0.0368 / {'opus': 7, 'gpt-6.1-sol': 7} eff {'low': 7, 'medium': 7} | 0.70 / $0.0488 / {'opus': 11} eff {'low': 7, 'medium': 4} |
| analysis | 0.90 / $0.0136 (sonnet.medium) | 0.90 / $0.0009 / {'haiku': 2, 'deepseek-v4.1-flash-1017': 1} eff {'medium': 2, 'high': 1} | 0.90 / $0.0010 / {'haiku': 3} eff {'medium': 3} |
| partner | 0.87 / $0.0153 (sonnet.medium) | 0.70 / $0.0085 / {'gemini-3.8-flash': 3} eff {'medium': 3} | 0.80 / $0.0010 / {'haiku': 3} eff {'medium': 3} |
| write_en | 0.90 / $0.0102 (sonnet.high) | 0.87 / $0.0004 / {'haiku': 2, 'deepseek-v4.1-flash-1017': 1} eff {'medium': 2, 'high': 1} | 0.87 / $0.0005 / {'haiku': 3} eff {'medium': 3} |
| write_dar | 0.80 / $0.0175 (opus.medium) | 0.63 / $0.0008 / {'haiku': 2, 'deepseek-v4.1-flash-1017': 1} eff {'medium': 2, 'high': 1} | 0.37 / $0.0008 / {'haiku': 3} eff {'medium': 3} |
| dar_reply | 0.87 / $0.0147 (opus.medium) | 0.63 / $0.0005 / {'haiku': 2, 'deepseek-v4.1-flash-1017': 1} eff {'high': 3} | 0.60 / $0.0006 / {'haiku': 3} eff {'high': 3} |
| dar_explain | 0.83 / $0.0191 (opus.medium) | 0.67 / $0.0002 / {'haiku': 2, 'gpt-6-luna': 1} eff {'low': 3} | 0.63 / $0.0004 / {'haiku': 3} eff {'low': 3} |
| dar_caption | 0.77 / $0.0176 (opus.medium) | 0.60 / $0.0049 / {'gemini-3.8-flash': 3} eff {'medium': 3} | 0.57 / $0.0006 / {'haiku': 3} eff {'medium': 3} |
| decision | 0.83 / $0.0828 (opus.medium) | 0.73 / $0.0109 / {'gemini-3.8-flash': 3} eff {'medium': 3} | 0.73 / $0.0028 / {'haiku': 3} eff {'medium': 3} |
| project_plan | 0.90 / $0.0759 (opus.medium) | 0.87 / $0.0021 / {'deepseek-v4.1-flash-1017': 3} eff {'high': 3} | 0.90 / $0.0021 / {'haiku': 3} eff {'medium': 3} |

| Subset | Reference (our route) | JR-any | JR-claude |
|---|---|---|---|
| Checkable kinds + design (9) | q 0.974, $0.0185 per pass | q 0.967, $0.162 (**8.7×**) | q 0.930, $0.127 (**6.9×**) |
| Judgment kinds (9: writing, Darija ×4, decision, partner, analysis, project plan) | q 0.852, $0.267 | q 0.733 (**−0.12**), $0.029 (0.11×) | q 0.707 (**−0.15**), $0.010 (0.04×) |
| Darija only (4) | q 0.817 | q 0.633 (−0.18) | q 0.542 (−0.28) |
| All 18 | q 0.913, $0.285 | q 0.850, $0.191 (0.67×) | q 0.819, $0.137 (0.48×) |

Readings:
- **The router inverts our table.** On checkable code work it over-buys (bug fixes → Opus 5.5 or GPT-6.1-sol, 7–20×
  Haiku-medium price, same 100%); on judgment work it under-buys (Darija, decision, partner → Haiku / Gemini 3.8 Flash
  / DeepSeek, quality −0.10…−0.43). Only `analysis`, `write_en`, `project_plan`, extraction and fact-check were
  equal-quality and as cheap or cheaper.
- Darija is worse than the numbers show: the AI judge under-rates the gap (native-speaker blind rating §2.9: Haiku 4.7/10 vs
  Opus 10/10), and JR-claude sent all 12 Darija runs to Haiku.
- JR-claude plan_hard 2/3 (Haiku medium, the same config that scored 3/3 in §2.9: run-to-run noise, not routing).
- Jev's task labels were sensible (`code:debugging`, `qa_knowledge`, `conversational_reply` …); the miss is the
  difficulty/benefit estimate from the prompt alone — the same failure the paired study reports.
- Latency: median 14.5 s per task (tool loops included); router overhead per call not separable here.
- **Verdict: fail** (quality first: −0.06 / −0.09 mean, up to −0.43 on Darija). Keep our fixed routing by kind.

**Part 2 — `~typesafe/jev-latest`** (served as `typesafe/jev-1.14-20261014`) on the Decisions API
(`POST /api/alpha/decisions`; it is not callable on chat/completions). Output tokens free; pay per input token.

*Tier classifier* — one `choice` question per matrix prompt (haiku/sonnet/opus = "cheapest tier that completes the
task reliably in one attempt"), 3 runs. "Needed tier" = cheapest model whose medium or high config reached the best
§2.9 mean −0.05; Darija set to Opus by the user's blind rating.

jrany: mean q 0.850 vs ref 0.913; total $/task-set 0.1910 vs ref 0.2852 (0.67x); kinds worse by >0.05: ['design 0.70<0.77', 'partner 0.70<0.87', 'write_dar 0.63<0.80', 'dar_reply 0.63<0.87', 'dar_explain 0.67<0.83', 'dar_caption 0.60<0.77', 'decision 0.73<0.83']; calls by model {'gpt-6.1-sol': 5, 'opus': 4, 'gpt-6.1-terra': 2, 'haiku': 14, 'gpt-6-luna': 2, 'deepseek-v4.1-flash-1017': 11, 'gemini-3.8-flash': 18}
jrclaude: mean q 0.819 vs ref 0.913; total $/task-set 0.1370 vs ref 0.2852 (0.48x); kinds worse by >0.05: ['plan_hard 0.67<1.00', 'design 0.70<0.77', 'partner 0.80<0.87', 'write_dar 0.37<0.80', 'dar_reply 0.60<0.87', 'dar_explain 0.63<0.83', 'dar_caption 0.57<0.77', 'decision 0.73<0.83']; calls by model {'opus': 9, 'haiku': 45}

- **33% = chance with 3 options.** Unlike the paper's "cheap 99.5%", Jev 1.14 mostly said *sonnet* (34/54), but
  it under-tiered every Darija and decision prompt (15 answers = quality risk) and over-tiered code/extraction
  (21 = waste; long extraction prompts → *opus*). Stable across runs (probabilities move ±0.03), so it is
  consistently wrong, not noisy. Not usable as a per-prompt tier router.

*Cheap gates* — 3 hand-labelled sets of 30 (15 yes / 15 no), `noul` question, vs Haiku 5.5 medium asked YES/NO:

| Kind | needed tier (2.9 data) | Jev choice (3 runs) | match |
|---|---|---|---|
| bug | haiku | sonnet, sonnet, sonnet | 0/3 |
| bug_hard | haiku | sonnet, sonnet, sonnet | 0/3 |
| factcheck | haiku | haiku, haiku, haiku | 3/3 |
| factcheck_hard | haiku | haiku, haiku, haiku | 3/3 |
| plan | haiku | haiku, haiku, haiku | 3/3 |
| plan_hard | haiku | sonnet, sonnet, sonnet | 0/3 |
| extract | haiku | opus, opus, opus | 0/3 |
| extract_hard | haiku | opus, opus, opus | 0/3 |
| design | haiku | haiku, haiku, haiku | 3/3 |
| analysis | sonnet | sonnet, sonnet, sonnet | 3/3 |
| partner | sonnet | sonnet, sonnet, sonnet | 3/3 |
| write_en | haiku | sonnet, sonnet, sonnet | 0/3 |
| write_dar | opus | sonnet, sonnet, sonnet | 0/3 |
| dar_reply | opus | sonnet, sonnet, sonnet | 0/3 |
| dar_explain | opus | sonnet, haiku, haiku | 0/3 |
| dar_caption | opus | sonnet, sonnet, sonnet | 0/3 |
| decision | opus | sonnet, sonnet, sonnet | 0/3 |
| project_plan | haiku | sonnet, sonnet, sonnet | 0/3 |
tier accuracy 18/54 = 33%; under-tier (quality risk) 15, over-tier (waste) 21; latency median 1.14s; cost/question $0.000212; choices {'haiku': 14, 'sonnet': 34, 'opus': 6}

- Both 100% on all three sets: **the sets are too easy to separate them** (Jev's closest call: the transcript-extraction
  case at p = 0.52 on "checkable"). Jev is ~2× cheaper per call than Haiku medium and similar latency here (0.7–1.6 s
  over the network, not the advertised ~20–100 ms). For gates the saving vs Haiku is fractions of a cent; the real
  saving of a heartbeat gate is skipping the big model (§2.17), which either can do.
- Matches the independent paired study **arXiv 2610.02267** (Jev and Laya at chance on zero-shot model routing, Jev
  "cheap" 99.5%; good on tool choice, injection and safety gates): routing fails here too; simple gates work.

Harness note: the router arms do not get the Claude Code system prefix that `llm.call` adds (OpenAI-format shim).

### 2.19 Memory backend: files + grep vs Cognee — done (2026-11-10)
Fixture `mem_fixture/` (gen.py): 936 notes, ~38k tokens, 6 months, 5 projects, Darija+English, changing facts,
20 questions (current value, reasons in other words, multi-hop, counts, 4 not-in-memory). One session per question,
Opus judge vs reference answers (`runner_mem.py`; reference fixed: Darija "m3tlin" = late).
| Arm | Score /20 (3 runs) | Cost / 20 questions |
|---|---|---|
| F: Haiku 5.5 medium + grep | 18, 18, 18 | $0.03 |
| F: Opus 5.5 medium + grep | 19, 19, 19 | $0.57 |
Misses: Darija question wording ("3lach w9efna l-pub" read as "how much"), one added unsupported fact. No made-up
answers on the 4 not-in-memory questions.
Cognee 1.6.7 (local mode: GLiNER2 + bge-small embeddings, no LLM): installed CPU-only (the default pulls CUDA
torch, several GB). First smoke test (2 notes) hung >20 min at "Loading local model gliner2.5-base-v1" at ~4% CPU
with open network sockets; cause found: the 774 MB GLiNER weights download had
been cut by the slow WiFi (.incomplete file) and Cognee waited silently. After a full download: 2 notes stored in
15 s, recall 0.2 s, right passage returned.
**Full build incident (21:59 UTC):** batches of 100 notes used >4.4 GB RAM; at 300/936 the kernel OOM-killed it, and
because it ran inside the hermes-serve cgroup the host agent's backend restarted (down ~10 s, back 22:00:05).
Re-run in its own systemd scope (MemoryMax=3G, no swap) with batches of 25. **Pitfall: run heavy local models in a
capped scope, never inside the agent's service.**
Build result: needed ~5.5 GB RAM and still grew until killed (memory not released between batches): 7 OOM kills
inside the cap, each re-run resumed where it stopped; total ~35 min of build for 936 notes (~38k tokens), $0
tokens. Recall: 0.2–3.8 s, returns a ready "answer from this context" prompt with ~10 passages (many noise logs).

Results (3 runs each; references widened after review: "m3tlin" = late or damaged both fine; "no Confluence seats,
Notion was chosen" counted correct; all 18 runs re-judged with the same reference):
| Arm | Haiku 5.5 medium /20 | cost/20 q | Opus 5.5 medium /20 | cost/20 q |
|---|---|---|---|---|
| F: files + grep | 18, 18, 18 = **18.0** | $0.029 | 19, 19, 19 = **19.0** | $0.57 |
| C: Cognee recall only | 17, 18, 18 = 17.7 | $0.021 | 20, 20, 20 = **20.0** | $0.76 (+33%) |
| FC: both | 19, 18, 17 = 18.0 | $0.023 | 20, 20, 20 = **20.0** | $0.64 (+12%) |
Reading: for Haiku, Cognee adds nothing (its misses are Darija reading, not finding). For Opus, +1/20: semantic
recall surfaced the TikTok "stop ads" note for the Darija "3lach w9efna l-pub" question that grep runs misread.
Costs: Cognee build ~35 min, ~5.5 GB RAM with 7 OOM restarts (local mode, $0 tokens); recall replies carry ~10
passages incl. noise, so agent tokens per answer go up for Opus. Fixture is small (~38k tokens), where grep is
enough; the gain may grow with much larger memory but the RAM cost grows too.
**Verdict:** not in the default kit. Optional memory backend for large memories on a machine with RAM to spare,
used by the top-tier agent, together with grep (FC), not instead of it.


### 2.21 Kit skills + adapters built (2026-11-10)
- `kit/skills/`: handoff, new-session, delegate, save-sources, new-agent, filter-output; `kit/SETUP.md` per host.
- Hermes plugin `adapters/hermes/frugal-bridge/`: 13/13 unit tests; loaded by Hermes's real plugin manager in an
  isolated HERMES_HOME (all 4 hooks registered, `pre_llm_call` returned the 170k notice, a 4,000-line terminal output
  became 1.2k chars with the error line kept, `/frugal` registered; the hermes shim checksum unchanged). Not installed
  on the user's live Hermes yet (needs the user's yes).
- Claude Code hook `adapters/claude-code/frugal_hook.py`: fake-transcript checks pass (150k once; Haiku 100k; missing
  transcript silent; start hint only when files exist); one real `claude -p` (Haiku, subscription, $0.04): context
  injected, agent read USER.md + PROGRESS.md and answered from them.
- Not yet measured: the adapters' effect on real weekly usage (phase 4 week test).


### 2.22 Proxy adapter (any host with a base URL) — 2026-11-10
`adapters/proxy/frugal_proxy.py` (stdlib only) + `adapters/proxy/test_proxy.py`.
- Unit/E2E with a fake upstream: **18/18 pass** (Anthropic Messages stream + JSON, OpenAI Chat stream, OpenAI
  Responses; key pass-through; warn once / hard / cheap threshold; notice only on a real user turn; loop guard incl.
  noisy `description` fields and same-error-different-call; deterministic output filter, file reads not cut;
  `.kits.json` start slots; CORE once; bad JSON + unknown route; report; no key in the log).
- Real host without adapter = Claude Code 2.1.287 through the proxy (`ANTHROPIC_BASE_URL`, subscription OAuth,
  Haiku, warn lowered to 50k for the test):
  - pass-through OK (HEAD/count_tokens/messages), cache intact (72,323 cache read on the notice call).
  - context watch: at ~72k the agent ended its reply with "new session with handoff (default) / compact / carry on?".
  - loop guard: user asked for 5 retries of a failing `cat`; after 2 identical results the notice fired and the agent
    stopped and asked the user instead of retrying 3 more times.
- Bugs found and fixed during the real runs: filter was cutting file reads (now shell-like tools only);
  loop signature broke on Claude Code's per-call `description` (noise keys dropped); HEAD unsupported (added);
  conversation id held account ids (now hashed).
- Codex 0.159.3 via custom provider (`/chatgpt` route, ChatGPT login): request reached the backend through the
  proxy and the notice was injected, but the account hit its Codex usage limit (429 until 2026-11-13) → Codex
  real run pending.
- Not covered: hosts that cannot change the base URL (chat apps); the proxy cannot start a new session itself.

### 2.23 Coexistence fixes built (2026-11-11)
- Adapters (Hermes plugin, Claude Code hook, proxy) share one `slots()` resolver: `.kits.json` slots (project folder
  + up to 3 parents), else PROGRESS.md / USER.md; read order now → user.
- Proxy race fixed: usage was recorded after the last chunk was sent, so a fast client's next request could miss the
  context notice (1 failure in ~5 runs of the Codex-style test). Now recorded before the final chunk: 0 failures in
  25 full runs.
- `kit/setup.py` install / check / uninstall: marked block in AGENTS.md (after the base block if present), pointer
  files `@AGENTS.md`, slots (none created when a base folder is registered), Claude hooks merged into
  `.claude/settings.json` by key, skills `frugal-*`, Hermes plugin copy (enable left to the user), size check (whole
  AGENTS.md vs 32 KiB), backups. `kit/test_setup.py` 12/12: fresh, re-run byte-identical, install→uninstall = original
  tree, user text byte-identical (3 line-ending shapes), existing pointer untouched, JSON merge keeps other hooks/keys
  and restores exactly, invalid JSON refused, base-first (no slot files, block after base, base untouched), edited
  slot files kept on uninstall, old version without registry, size check, Hermes copy.
- All adapter + kit tests: 49/49 (`pytest -q adapters kit`).
- AGENTS.md change: one paragraph "default names; if `.kits.json` exists use its slots" (no behaviour change for a
  Frugal-only setup; not re-run through the kit test).

### 2.24 "Set it up for me" — agent-driven install (2026-11-11)
- `INSTALL.md` (repo root): steps written for an AI agent — ask 4 things in one message, detect its own host, set
  tiers, run `setup.py install --hosts …`, fill USER.md (not when a base folder owns it), optional proxy, `check`,
  report enforced vs followed rules + undo. README starts with "AI agent: read INSTALL.md".
- Real test: a fresh project with the user's own `AGENTS.md`, Claude Code (Sonnet 5.5) given only "Here is a repo …
  Set up Frugal-Bridge for me … name Sara; English, short; Claude Haiku/Sonnet/Opus": 5 turns, $0.10, `check` OK,
  user text kept above the block, `CLAUDE.md` = `@AGENTS.md`, hooks + skills + USER.md filled. A cold new session
  (Haiku) answered "I'm Sara … in English, in short answers" → rules load in new sessions.
- Not run with a real Hermes agent installing itself (it would enable a plugin on a live gateway); the Hermes path
  is covered by `setup.py` tests with an isolated home.
- Public repo cleaned by `public/scrub.py` (run by `publish.sh`): drops the discussion appendix, the real-setup
  evidence (E1/E2), the process index, plan-usage notes, account/credit lines; "user" → "user".

### 2.25 One adapter for everything (2026-11-11)
- User: nothing may suggest Frugal-Bridge works only with a few named tools. `adapters/claude-code|hermes|proxy` →
  `adapter/` with three mechanisms named by what the tool allows: `hooks/`, `plugin/`, `proxy/`. Tool names appear only
  as examples inside docs.
- `setup.py --hosts auto` (default): detects agent tools (env vars, binaries, project folders) and installs the
  strongest mechanism each allows; prints "Enforcement on this machine" (hooks / plugin copied, enable = user's yes /
  proxy available for …). `--hosts none` = rules only. Tests 51/51 (+ detection, + rules-only CLI).
- README leads with "any AI agent, app, or provider" and a table by kind of place (agent folder, hooks/plugins, base
  URL, chat apps, own app); INSTALL.md no longer asks the agent which product it is — setup decides.
- Real test: Claude Code (Sonnet 5.5) from one sentence, answers in French: auto-installed hooks, copied the plugin to
  the (test) plugin home without enabling it, listed the proxy for Codex, check OK, $0.11, 5 turns.

### 2.26 External routing playbooks (2026-11-11)
Sources: "Model Routing Playbook" (Notion, @donimas, checked 2026-10-05) + repo donimas/ai-routing (23★, templates:
triage/quick/build/deep/verifier subagents, Stop-hook test gate); celiktech24-cell/smart-task-router (30★, MIT, skill +
5 agents: scout writes CONTEXT.md, Opus plans with contracts, Haiku/Sonnet build, check, escalate); murphmaxxing
"Omega" (Opus xhigh boss + Haiku workers, "Done when:" check per brief, autocompact 40%, reflect skill).
Most of it is already in the kit and measured (effort before model, one tier below top, cheap + real check + escalate,
handoff files, one reviewer, plan for multi-file). New claims tested on test L (click repo, 6 tasks, 24 hidden tests):

| Arm | Setup | Hidden tests (runs) | Cost/run |
|---|---|---|---|
| X (now 6 runs) | Haiku low | 24·4·24·24·24·24 | $0.017 |
| XE | Haiku low → re-run at Haiku medium when the task check fails ("low everywhere, re-run failures") | 24×5 (0 escalations) | $0.017 |
| XS | Haiku low + Stop gate (repo suite must pass before DONE) | 4·24·24·24·24 (gate fired 0×) | $0.017 |
| SS | Sonnet low + Stop gate | 10·10·10 (gate fired 0×) | $0.138 |
| SE | Sonnet low → re-run at Sonnet high when the task check fails | 9·9·24 (escalated 3 tasks/run) | $0.267 |
| K (ref) | Haiku medium | 24×3 | $0.024 |
| Z (ref) | Sonnet high | 24×3 | $0.266 |
| E (ref) | tiers, re-run one model up | 24×3 | $0.146 |

Readings:
- **Stop gate on the agent's own tests: no effect** — fired 0 times in 8 runs; every failure was a misread spec and the
  agent's own tests passed. Not added. A gate only helps with an independent check (CI / acceptance tests).
- **"Low + re-run failures at high effort": not reproduced.** Sonnet low→high cost the same as Sonnet high everywhere
  and still failed 2 of 3 runs (the same misread twice). Re-running one *model* up (arm E) fixed it. → Kit line added:
  escalate to a bigger model, and the check must come from the task.
- Haiku low: 1 failure in 6 runs → stays "risky"; Haiku medium stays the default for checkable work.
- Not tested, already covered: Opus xhigh boss (xhigh = 3–8× cost, no gain, §2.8), autocompact 40% (our 150k
  handoff/compact, §2.x), triage subagent per task (extra call; main-agent routing 7/8), scout CONTEXT.md (= MAP.md arm
  M, no gain). Not testable short-term: reflect skill (needs weeks of real use) — candidate.
- Auto routers in the playbook (LiteLLM, OpenRouter, Jev…): its own sources say they often lose to the best single
  model; agrees with our Jev test. Not added.

### 2.27 Install once, works everywhere (`setup.py --global`, 2026-11-11)
- User: after "set it up", it must work by itself — not per folder. New default: `install --global` writes the rules
  block into each found tool's own user-level instruction file (Claude Code `~/.claude/CLAUDE.md`, Codex
  `~/.codex/AGENTS.md`, Gemini CLI `~/.gemini/GEMINI.md`, OpenCode `~/.config/opencode/AGENTS.md`, Hermes
  `$HERMES_HOME/SOUL.md`), user-level hooks/skills, plugin copy (enable = user's yes). One user file
  `~/.frugal-bridge/USER.md`; the hook/plugin/proxy fall back to it when a project has none. Project files are created
  only when needed. Uninstall restores every user file; folder install still exists.
- Tests 53/53 (+ global install/idempotent/uninstall-restores, + adapter finds the global user file).
- Real test (isolated HOME): Claude Code Sonnet 5.5, one sentence → global install for Claude Code + Codex + Hermes,
  USER.md filled (Nora, French, short), plugin not enabled, project folder untouched, 7 turns $0.10. Then a **new
  session in another, empty folder** (Haiku): "Je m'appelle Nora, et je réponds en français, de façon courte." The
  real home was not touched.

### 2.28 Global install + knowledge base, any order (2026-11-11)
- Gap found before the first live install: `--global` made `~/.frugal-bridge/USER.md` even when a knowledge base was
  connected at user level → a second copy of the user's files (against the coexistence contract).
- Fix: setup finds a connected base from its block (`Path: <dir>` + `.kits.json` with `base-folder`) in the tools'
  user-level files. Base first → Frugal's block goes after the base block, points to the base slots, makes no
  USER.md. Frugal first → re-run switches to the base and tells the user to move the old USER.md content in. Hook /
  plugin / proxy fall back to the base slots from `global.json`. Check flags a recorded base that is gone.
- Tests 55/55 (+ base first, + Frugal first then base). Read-only check on this server: the base is detected.

### 2.29 Hook marker fix (2026-11-11)
- Bug (reported from a review): own hooks were recognised by the `.frugal-bridge/` path; with `FRUGAL_HOME` named
  differently every `install --global` re-run added the two hooks again (reproduced: 2 per event after 2 runs).
- Fix: every hook Frugal writes carries the tag `# frugal-bridge-hook`; old entries are recognised by the script name
  (`frugal_hook.py`), so upgrades replace them. One helper (`merge_hooks` / `drop_hooks`) is the rule for any tool's
  JSON hooks, project and global. Tests 59/59 (+ custom FRUGAL_HOME re-run byte-identical, + upgrade from old-style
  hooks, + uninstall leaves other hooks intact, + marker does not match foreign hooks). Repro now: 1 per event after 3 runs.
