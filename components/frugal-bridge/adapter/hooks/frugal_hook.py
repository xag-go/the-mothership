#!/usr/bin/env python3
"""Frugal-Bridge hook for Claude Code (SessionStart + UserPromptSubmit).

SessionStart: tell the agent to read the "now" and "user" slot files first, in one call (project .kits.json slots or
PROGRESS.md / USER.md, else the connected knowledge base's slots, else Frugal's own USER.md; folders expanded).
UserPromptSubmit: read the transcript's last assistant usage; past 150k context tokens (100k on Haiku), once per
threshold, ask Claude to offer a new session + handoff at the end of its reply; at 300k say it plainly.
State: ~/.claude/frugal-bridge/state.json. Install: see ../README.md.
"""
import json, os, sys

WARN, HARD, WARN_CHEAP = 150000, 300000, 100000
STATE = os.path.expanduser("~/.claude/frugal-bridge/state.json")


# >>> frugal-bridge start-files (shared: identical copy in adapter/hooks, adapter/plugin, adapter/proxy; a test checks)
# Which files a new session reads first. Resolved fresh on every call (no cache), so a knowledge base connected or
# removed later is picked up without re-installing. Base discovery follows kit/setup.py find_base: FRUGAL_BASE, the
# base recorded in $FRUGAL_HOME/global.json, the 'Path:' line of a base block in any tool's user-level rules file,
# the pointer file ~/.config/skeleton-base/base, the base's systemd user units (--base DIR). Each candidate must have
# a .kits.json registering `base-folder`. No base: Frugal's own $FRUGAL_HOME/USER.md. A slot that is a folder
# (e.g. user = wiki/me/) expands to its .md files (sorted, capped).
import json, os, re, shlex  # noqa: E401,F811

START_DIR_CAP = 8
_BASE_PATH_RE = re.compile(r"<!-- base-folder:start[^>]*-->.*?^Path:[ \t]*(.+?)[ \t]*$", re.S | re.M)


def _sf_text(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _sf_json(p):
    try:
        v = json.loads(_sf_text(p) or "")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def frugal_home():
    return os.environ.get("FRUGAL_HOME") or os.path.expanduser("~/.frugal-bridge")


def _sf_is_base(d):
    k = _sf_json(os.path.join(d, ".kits.json")) if d else {}
    return isinstance(k.get("kits"), dict) and "base-folder" in k["kits"]


def _sf_rule_files():
    e, h = os.environ.get, os.path.expanduser
    return [os.path.join(e("CLAUDE_CONFIG_DIR") or h("~/.claude"), "CLAUDE.md"),
            os.path.join(e("CODEX_HOME") or h("~/.codex"), "AGENTS.md"), h("~/.gemini/GEMINI.md"),
            h("~/.config/opencode/AGENTS.md"), os.path.join(e("HERMES_HOME") or h("~/.hermes"), "SOUL.md")]


def _sf_path_value(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "`\"'" and raw[0] in raw[1:]:
        return raw[1:raw.index(raw[0], 1)]
    return raw


def _sf_unit_bases(home):
    d = os.path.join(home, ".config", "systemd", "user")
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for f in names:
        if not (f.startswith("skeleton-base") and f.endswith(".service")):
            continue
        for line in (_sf_text(os.path.join(d, f)) or "").splitlines():
            if line.startswith("ExecStart="):
                try:
                    w = shlex.split(line[len("ExecStart="):].replace("%%", "%").replace("$$", "$"))
                except ValueError:
                    continue
                if "--base" in w and w.index("--base") + 1 < len(w):
                    out.append(w[w.index("--base") + 1])
    return out


def find_base():
    """The connected knowledge base folder, or None (same sources and order as kit/setup.py find_base)."""
    home = os.path.expanduser("~")
    cands = [os.environ.get("FRUGAL_BASE"), _sf_json(os.path.join(frugal_home(), "global.json")).get("base")]
    for f in _sf_rule_files():
        m = _BASE_PATH_RE.search(_sf_text(f) or "")
        if m:
            cands.append(_sf_path_value(m.group(1)))
    cands += (_sf_text(os.path.join(home, ".config", "skeleton-base", "base")) or "").strip().splitlines()[:1]
    cands += _sf_unit_bases(home)
    for c in cands:
        if c and isinstance(c, str):
            d = os.path.abspath(os.path.expanduser(c))
            if _sf_is_base(d):
                return d
    return None


def slots(project_dir=None):
    """Slot paths to read first ({"now": path, "user": path}, existing only; a path may be a folder). The project's
    `.kits.json` (project_dir or up to 3 parents) or its PROGRESS.md / USER.md first; what is still missing comes from
    the knowledge base's slots, else Frugal's own USER.md."""
    out, root, k = {}, None, {}
    if project_dir:
        d = root = os.path.abspath(project_dir)
        for _ in range(4):
            if os.path.isfile(os.path.join(d, ".kits.json")):
                k, root = _sf_json(os.path.join(d, ".kits.json")), d
                break
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
        s = {"now": "PROGRESS.md", "user": "USER.md"}
        s.update({x: y for x, y in (k.get("slots") or {}).items() if x in s and isinstance(y, str) and y})
        for x in ("now", "user"):
            f = os.path.join(root, s[x])
            if os.path.exists(f):
                out[x] = f
    if "user" not in out:
        base = find_base()
        if base:
            bs = _sf_json(os.path.join(base, ".kits.json")).get("slots") or {}
            for x in ("now", "user"):
                v = bs.get(x)
                f = os.path.join(base, v) if isinstance(v, str) and v else ""
                if x not in out and f and os.path.exists(f):
                    out[x] = f
        elif os.path.isfile(os.path.join(frugal_home(), "USER.md")):
            out["user"] = os.path.join(frugal_home(), "USER.md")
    return {x: out[x] for x in ("now", "user") if x in out}


def _sf_md_files(folder, cap):
    found = []
    for d, dirs, files in os.walk(folder):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        found += [os.path.join(d, f) for f in sorted(files) if f.endswith(".md") and not f.startswith(".")]
    return found[:cap], max(len(found) - cap, 0)


def start_files(project_dir=None, cap=START_DIR_CAP):
    """Real files to read first, in read order (now, then user). Returns (files, notes about capped folders)."""
    files, notes = [], []
    for p in slots(project_dir).values():
        if os.path.isdir(p):
            got, more = _sf_md_files(p, cap)
            files += got
            if more:
                notes.append(f"{more} more .md in {_sf_quote(p)} when needed")
        elif os.path.isfile(p):
            files.append(p)
    return list(dict.fromkeys(files)), notes


def _sf_quote(p):
    if " " not in p and not any(c in p for c in "`\"'"):
        return p
    q = next((c for c in "`\"'" if c not in p), "`")
    return q + p + q


def start_hint(project_dir=None, tag="[frugal-bridge]"):
    """The first-turn instruction naming the start files, or None when there are none."""
    files, notes = start_files(project_dir)
    if not files:
        return None
    extra = ("; " + "; ".join(notes)) if notes else ""
    return (f"{tag} Session start: read {', '.join(_sf_quote(f) for f in files)} in one call before answering "
            f"(project facts and past decisions only when the task needs them; paths in .kits.json{extra}).")
# <<< frugal-bridge start-files


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
        out = start_hint(d)
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
