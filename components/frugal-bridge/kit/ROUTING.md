# ROUTING.md — tiers mapped to real models (filled at setup, per provider)

Change this file when new models ship (check an independent benchmark for candidates, then run the gauge).
Effort column = default; see AGENTS.md section 2 for when to raise it.

| Tier | Anthropic | OpenAI | Google | Effort |
|---|---|---|---|---|
| cheap | Claude Haiku 5.5 | GPT-6 Luna or GPT-6.1 Terra (untested) | Gemini 3.8 Flash (partly tested) | medium |
| mid | Claude Sonnet 5.5 | GPT-6.1 Sol (untested) | — | medium; high for public English writing |
| top | Claude Opus 5.5 | GPT-6.1 Sol high or GPT-6 Astra (untested) | Gemini 4 Argon/Carbon (untested) | medium |

Price steps (hand off before): Claude Haiku 5.5 at 100k tokens; GPT-6 Astra at 272k.

Cache:
- Anthropic: 5 min default; 1 h only for chats with pauses of 5–60 min.
- OpenAI: default (30 min); 12 h only for stable material reused across long gaps.
- Google: implicit; put large stable content first.
