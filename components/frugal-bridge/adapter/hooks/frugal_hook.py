#!/usr/bin/env python3
"""Frugal-Bridge hook for Claude Code (SessionStart + UserPromptSubmit).

SessionStart: tell Claude to read the "now" and "user" slot files first, in one call (.kits.json slots, else
PROGRESS.md / USER.md in the project dir).
UserPromptSubmit: read the transcript's last assistant usage; past 150k context tokens (100k on Haiku), once per
threshold, ask Claude to offer a new session + handoff at the end of its reply; at 300k say it plainly.
State: ~/.claude/frugal-bridge/state.json. Install: see ../README.md.
"""
import json, os, sys

WARN, HARD, WARN_CHEAP = 150000, 300000, 100000
STATE = os.path.expanduser("~/.claude/frugal-bridge/state.json")


def slots(project_dir):
    """Slot files to read first, per the coexistence contract: `.kits.json` slots (searched in project_dir and up to
    3 parent folders) else Frugal's own defaults (PROGRESS.md = now, USER.md = user). Returns existing files only,
    in read order: now first, then user."""
    if not project_dir:
        return {}
    root, k = project_dir, {}
    d = os.path.abspath(project_dir)
    for _ in range(4):
        p = os.path.join(d, ".kits.json")
        if os.path.isfile(p):
            try:
                k = json.load(open(p)); root = d
            except Exception:
                k = {}
            break
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    s = {"now": "PROGRESS.md", "user": "USER.md"}
    s.update({x: y for x, y in (k.get("slots") or {}).items() if x in ("now", "user") and isinstance(y, str)})
    out = {}
    for x in ("now", "user"):
        f = os.path.join(root, s[x])
        if os.path.isfile(f):
            out[x] = f
    if "user" not in out:  # user-level install (setup.py --global): the knowledge base's slots, else one USER.md
        fh = os.environ.get("FRUGAL_HOME") or os.path.expanduser("~/.frugal-bridge")
        try:
            base = json.load(open(os.path.join(fh, "global.json"))).get("base")
            bs = json.load(open(os.path.join(base, ".kits.json"))).get("slots") or {} if base else {}
        except Exception:
            base, bs = None, {}
        if base:
            for x in ("now", "user"):
                f = os.path.join(base, bs.get(x, ""))
                if x not in out and bs.get(x) and os.path.exists(f):
                    out[x] = f
        elif os.path.isfile(os.path.join(fh, "USER.md")):
            out["user"] = os.path.join(fh, "USER.md")
    return out


def last_usage(path):
    ctx, model = 0, ""
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                m = r.get("message") or {}
                u = m.get("usage") if isinstance(m, dict) else None
                if r.get("type") == "assistant" and u:
                    ctx = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                           + u.get("cache_creation_input_tokens", 0))
                    model = m.get("model", model)
    except OSError:
        pass
    return ctx, model


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"))


def main():
    ev = json.load(sys.stdin)
    name = ev.get("hook_event_name", "")
    out = None
    if name == "SessionStart":
        d = ev.get("cwd") or os.getcwd()
        have = slots(d)
        if have:
            out = (f"[frugal-bridge] Session start: read {' and '.join(have.values())} in one call before answering "
                   "(project facts and past decisions only when the task needs them; paths in .kits.json).")
    elif name == "UserPromptSubmit":
        ctx, model = last_usage(ev.get("transcript_path", ""))
        warn = WARN_CHEAP if "haiku" in (model or "").lower() else WARN
        s = load_state(); sid = ev.get("session_id", "?"); done = set(s.get(sid, []))
        if ctx >= HARD and "hard" not in done:
            done |= {"hard", "warn"}
            out = (f"[frugal-bridge] This chat is at ~{ctx // 1000}k tokens. Finish the current step, then tell the user "
                   "plainly (one line, end of reply) that a new session is needed, and write the handoff first.")
        elif ctx >= warn and "warn" not in done:
            done.add("warn")
            out = (f"[frugal-bridge] This chat is at ~{ctx // 1000}k tokens. At the end of your reply add one short line "
                   "offering: new session with handoff (default) / compact / carry on.")
        s[sid] = sorted(done); save_state(s)
    if out:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": out}}))


if __name__ == "__main__":
    main()
