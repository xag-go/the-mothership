# INSTALL.md — instructions for an AI agent

You are an AI agent and the user asked you to **set up Frugal-Bridge** for them. Follow these steps in order. Talk to
the user in their language. Ask questions only in step 1, all in one message. Do not ask for API keys; never write
keys into any file.

## 0. What you are installing
Frugal-Bridge = working rules that cut token use without lowering quality (`kit/AGENTS.md`) + an adapter that
enforces them on this machine. `kit/setup.py` does the file work; it is safe to re-run and fully reversible
(`uninstall`), it edits only inside its own marked block and keeps backups of every file it touches.

By default it is installed **for the user, not for one folder**: every agent tool found on the machine loads the rules
by itself in every folder and every new session. Nothing has to be repeated per project.

## 1. Ask the user (one message)
1. **A name for the main agent** (any name; e.g. "Sara").
2. **Language and answer style** (e.g. "English, short", "Darija in Latin letters, short").
3. **Which models** they can use, if you can't tell yourself (e.g. Claude Haiku/Sonnet/Opus, GPT, Gemini).
4. Only if relevant: **everywhere** (default) **or one folder only**?
Use sensible defaults for anything they skip.

## 2. If you have no shell
If you cannot run commands (a chat app), tell the user to paste `kit/AGENTS.md` and `kit/ROUTING.md` into the app's
custom instructions (or project instructions) — that is the whole setup there — and stop.

## 3. Set the model tiers
Open `kit/ROUTING.md` (in this repository) and make the `cheap / mid / top` rows match the models the user has.
If only one provider is available, fill only that column. Keep effort defaults (medium; high only for public writing).

## 4. Install
```bash
python3 kit/setup.py install --global            # everywhere (default)
python3 kit/setup.py install "<folder>"          # only if the user chose one folder
```
Setup finds the agent tools on this machine by itself and installs in the strongest way each tool allows: the rules in
the tool's own user-level instruction file, plus hooks, skills or a plugin where the tool has them. The report must
start with `OK`; if it says `PROBLEMS`, show the lines to the user and stop. It never overwrites the user's text, and
if a settings file is not valid JSON it stops without changing it — tell the user, don't "fix" their file.
If the user has a knowledge base that setup did not find, re-run with `--base <its folder>`.
If it finds no agent tool, ask the user which one they use and re-run with `--hosts <name>`
(`claude-code, codex, gemini, opencode, hermes`).

The report ends with "Enforcement on this machine". Three lines may need the user:
- **NEEDS USER — … SOUL.md does not exist**: some tools keep their identity in a user file (e.g. Hermes `SOUL.md`);
  setup never creates it, because that would replace the tool's default identity. Tell the user; if they want the
  rules there, they create the file with their own identity text and you re-run `install --global` (or they paste
  the printed block into it).
- **plugin copied … enable it**: enabling restarts that tool's gateway (running chats pause a few seconds). Ask, then
  run the enable command the tool documents (e.g. `hermes plugins enable frugal-bridge`, then restart its gateway).
- **proxy available for …**: see step 6.

## 5. Fill the user file
- Everywhere: open `~/.frugal-bridge/USER.md` (the path is in the report). One-folder install: `<folder>/USER.md` —
  but if `<folder>/.kits.json` lists `base-folder`, a knowledge base owns the user files: do not create or edit them.
- Fill: main agent name, language and script, answer style. Leave the other lines for later.

## 6. Optional: proxy (tools with a configurable API base URL)
Only if setup listed tools for the proxy, the user wants the rules enforced there, and agrees to run a small local server:
```bash
python3 adapter/proxy/frugal_proxy.py --port 8790      # keep it running (e.g. a user service)
```
Then point the tool at it — examples in `adapter/README.md`. Keys pass through untouched; the proxy stores none.
Skip this step if unsure.

## 7. Check and report
```bash
python3 kit/setup.py check --global              # or: check "<folder>"
```
Tell the user, briefly: what was installed and where, which rules are **enforced** on this machine (from the
"Enforcement" lines) and that all other rules are **followed** by the agent, the main agent's name, and how to undo:
`python3 kit/setup.py uninstall --global` (plus the tool's disable command if a plugin was enabled).
From the next new session on, it works by itself — nothing to repeat.
