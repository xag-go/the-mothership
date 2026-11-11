# Frugal-Bridge

> **If you are an AI agent asked to set this up: read [`INSTALL.md`](INSTALL.md) and follow it.**
> Humans: give your agent this repo link and say "set up Frugal-Bridge for me".

**Spend fewer tokens on AI agents without losing quality — with any AI agent, app, or provider.**
A small set of working rules your AI follows, plus one adapter that enforces them wherever the tool allows it.
Coding agents, agent frameworks, chat apps, your own app on any API: the rules are plain Markdown any model can read.

Every rule here was A/B tested (3+ runs per cell, real checks first — hidden tests, exact answers — then a blind
judge, and a human rater for language). Rules that saved tokens but lowered quality were dropped.
Numbers: [`docs/RESULTS.md`](docs/RESULTS.md). Reasoning, rejected ideas and open items: [`docs/DESIGN.md`](docs/DESIGN.md).

## What it does
| Lever | Measured effect (our tests) |
|---|---|
| New session per task + a short handoff (save pasted material to files first) | −51% to −90% on long work, decisions and reasons kept |
| Route work by kind: checkable work to the cheap tier (with escalation on a failed check), judgment work straight to the right tier | cheap tier 10–50× cheaper on checkable tasks at the same quality |
| Medium effort by default; no xhigh/max | xhigh/max 3–17× cost, no gain; max sometimes returned nothing |
| Filter big tool outputs before they enter the context | −63% to −75%, same result |
| Split memory files (USER / PROJECT / DECISIONS / PROGRESS) instead of one growing handoff | −45%, same quality |
| One reviewer picked by the stakes instead of several | −66% to −96%, fewer false alarms |
| Large pasted inputs as files handed to a cheap helper | −57% in the main chat |
| Load only the tools a job needs (deferred loading) | +36% avoided on a cheap model |
| Heartbeats check for changes before calling a model | $0 per empty run |

Also found: on one subscription plan, output weighed ~2.2× more than cached input per API dollar — so effort and
verbose output are the main levers there.

## Set it up
**Easiest:** give your AI agent this repo and say *"set up Frugal-Bridge for me"*. It follows [`INSTALL.md`](INSTALL.md):
asks you a few short questions, installs, checks, and tells you what is enforced on your machine.
Install once: from then on it works by itself in every project and every new session.

**By hand:**
```bash
git clone <this repository's URL> frugal-bridge && cd frugal-bridge
python3 kit/setup.py install --global      # once: every agent tool on this machine, every folder, every new session
python3 kit/setup.py check --global
python3 kit/setup.py uninstall --global    # restores your files
# one folder only: python3 kit/setup.py install /path/to/project
```
Before installing, edit `kit/ROUTING.md` with the models you use (re-run `install` after any change).

## Works with everything
| Where your AI runs | How Frugal-Bridge reaches it |
|---|---|
| Any agent that reads a project folder | rules file `AGENTS.md` (+ one-line pointers for tools that use another file name), skills, templates |
| Tools with hooks or plugins | the adapter enforces the rules automatically (context watch, start files, output filter, usage report) |
| Any tool that lets you set the API base URL — any provider | the adapter's local proxy enforces them (plus a loop guard) |
| Chat apps | paste `kit/AGENTS.md` into the project instructions (followed, not enforced) |
| Your own app / API | put `kit/AGENTS.md` in the system prompt, or route through the proxy |

You don't pick an adapter: `setup.py` detects what is on the machine and uses the strongest way each tool allows.
Details: [`adapter/README.md`](adapter/README.md), [`kit/SETUP.md`](kit/SETUP.md). Works alone or next to a
knowledge-base folder, in any install order: [`docs/COEXISTENCE.md`](docs/COEXISTENCE.md).

## What's inside
- `kit/AGENTS.md` — the rules (~7 KB). `kit/ROUTING.md` — cheap / mid / top tiers → your models.
- `kit/templates/` — USER, PROJECT, PROGRESS, DECISIONS, MAP, ROLE, helper BRIEF.
- `kit/skills/frugal-*` — handoff, new-session, delegate, save-sources, new-agent, filter-output.
- `kit/setup.py` — install / check / uninstall (idempotent, reversible, backups).
- `adapter/` — one adapter: hooks, plugin and proxy mechanisms, picked automatically.

## Tests
```bash
python3 -m pip install pytest
python3 -m pytest -q kit adapter
```

## Limits (honest)
- Tested mostly on Anthropic models (Claude Haiku / Sonnet / Opus 5.5); OpenAI and Google tiers in `ROUTING.md` are
  candidates, not yet measured.
- Chat apps cannot be enforced (no hooks, no base URL): the rules are followed there, not enforced.
- The test harness and raw runs are not published (they contain private material); `docs/RESULTS.md` has every number.

License: MIT.
