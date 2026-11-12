#!/usr/bin/env python3
"""Frugal-Bridge hook: one script for every agent tool with command hooks.

    python3 frugal_hook.py [--tool NAME] [--event start|prompt|post_tool|usage|precompact]   (event JSON on stdin)

Tools: claude-code (default), codex, gemini, qwen, copilot, junie, droid, devin, continue, cursor, kiro, crush, cline,
grok. The event comes from --event, else from the payload's own event name. What it does:
- start: tell the agent which "now" / "user" files to read first, in one call (start-files block below); Cursor has no
  global rules file, so there the rules text ($FRUGAL_HOME/RULES.md) comes with it.
- prompt: context watch: past 150k tokens (100k on cheap models), once per threshold, ask the agent to offer a new
  session with a handoff; at 300k say it plainly. Context = the transcript's last usage, else the last usage logged.
- post_tool: shell output over ~12k chars is cut to head + error lines + tail (full text saved, path given), in the
  tool's own replace-output field (Claude Code updatedToolOutput, Junie updatedToolOutput, Copilot modifiedResult,
  Crush updated_output, Gemini AfterTool deny+reason, Codex PostToolUse block+reason). Tools without one: nothing.
- usage: token usage of each model call to $FRUGAL_HOME/usage.jsonl (same record as the Hermes plugin, plus `tool`):
  Claude-style transcripts (Stop), Codex PostModelRequest token_usage, Cursor preCompact context tokens.
Runs once per event: tools that also run Claude Code's hooks (Cursor, Grok, Devin, Continue cn, Copilot with a
repo .claude/settings.json) would call it twice; the Claude entry stands down when the calling tool has its own
Frugal entry, and a short-lived marker per event payload drops any second call. Never fails the tool: any error =
no output, exit 0.
"""
import hashlib, json, os, re, sys, time

WARN, HARD, WARN_CHEAP = 150000, 300000, 100000
OUT_LIMIT = 12000
CHEAP = ("haiku", "flash", "mini", "luna", "nano")
ERR = re.compile(r"(error|exception|traceback|failed|fail\b|fatal|panic|denied|not found|warning)", re.I)


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


_SF_NO_ENGINE = {"", "any", "none", "unset", "-"}
_SF_BLOCK_RE = re.compile(r"<!-- (base-folder|frugal-bridge):start[^>]*-->.*?<!-- \1:end -->", re.S)


def _sf_fm_list(text, key):
    """Frontmatter values of key: `[a, b]`, a block list of `- a` lines, or one plain value."""
    if not (text or "").startswith("---\n") or text.find("\n---", 4) < 0:
        return []
    lines = text[4:text.find("\n---", 4)].splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^" + re.escape(key) + r"\s*:(.*)$", line)
        if not m:
            continue
        v = m.group(1).split(" #")[0].strip()
        if v.startswith("[") and v.endswith("]"):
            return [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip().strip("\"'")]
        if v:
            return [v.strip("\"'")]
        out = []
        for l in lines[i + 1:]:
            mm = re.match(r"^\s*-\s*(.*)$", l)
            if not mm:
                break
            out.append(mm.group(1).split(" #")[0].strip().strip("\"'"))
        return [x for x in out if x]
    return []


def role_file(host=None, project_dir=None, identity_files=()):
    """The base's agents/ROLE file for this host, only when it is safe: the host is known, it has no own identity
    (a project ROLE.md, or an identity file with text outside the kits' blocks) and exactly ONE role file lists it
    in `engines:` (or the old `engine:`). Anything else: None, never a guess."""
    if not host:
        return None
    if project_dir and os.path.isfile(os.path.join(os.path.abspath(project_dir), "ROLE.md")):
        return None
    for f in identity_files:
        if _SF_BLOCK_RE.sub("", _sf_text(f) or "").strip():
            return None
    base = find_base()
    if not base:
        return None
    a = os.path.join(base, "agents")
    try:
        names = sorted(n for n in os.listdir(a) if n.endswith(".md"))
    except OSError:
        return None
    hits = []
    for n in names:
        t = _sf_text(os.path.join(a, n)) or ""
        eng = [e for e in _sf_fm_list(t, "engines") + _sf_fm_list(t, "engine") if e.lower() not in _SF_NO_ENGINE]
        if host in eng:
            hits.append(os.path.join(a, n))
    return hits[0] if len(hits) == 1 else None


def start_hint(project_dir=None, tag="[frugal-bridge]", host=None, identity_files=()):
    """The first-turn instruction naming the start files, or None when there are none. The role file joins them
    only when role_file() finds exactly one safe match for this host."""
    files, notes = start_files(project_dir)
    rf = role_file(host, project_dir, identity_files)
    if rf and rf not in files:
        files.append(rf)
        notes.append(f"your role and name: {_sf_quote(rf)}")
    if not files:
        return None
    extra = ("; " + "; ".join(notes)) if notes else ""
    return (f"{tag} Session start: read {', '.join(_sf_quote(f) for f in files)} in one call before answering "
            f"(project facts and past decisions only when the task needs them; paths in .kits.json{extra}).")
# <<< frugal-bridge start-files


# ---------------------------------------------------------------- state, once-guard, host
def state_file():
    """Warn flags, resolved on every call: $CLAUDE_CONFIG_DIR/frugal-bridge/state.json when set (a second Claude dir
    keeps its own flags), else ~/.claude/frugal-bridge/state.json (older installs keep their file)."""
    d = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(os.path.expanduser(d), "frugal-bridge", "state.json")


def load_state():
    try:
        return json.load(open(state_file()))
    except Exception:
        return {}


def save_state(s):
    path = state_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(s, open(path, "w"))


def _hstate_path():
    return os.path.join(frugal_home(), "hook-state.json")


def load_hstate():
    v = _sf_json(_hstate_path())
    return v if isinstance(v, dict) else {}


def save_hstate(s):
    try:
        os.makedirs(frugal_home(), exist_ok=True)
        tmp = _hstate_path() + f".{os.getpid()}"
        json.dump(s, open(tmp, "w"))
        os.replace(tmp, _hstate_path())
    except OSError:
        pass


def once(event, raw, ev=None):
    """True for the first call with this event payload (and transcript state) in the last two minutes: a second
    hook entry for the same event gets False."""
    ev = ev or {}
    if not any(ev.get(k) for k in ("session_id", "sessionId", "conversation_id", "taskId")):
        return True          # no session id: cannot tell a second entry from a new session, so never drop
    d = os.path.join(frugal_home(), "once")
    tp = ev.get("transcript_path")
    try:
        st = os.stat(tp) if isinstance(tp, str) and tp else None
        raw = raw + (f"\0{st.st_size}:{st.st_mtime_ns}".encode() if st else b"")
    except OSError:
        pass
    try:
        os.makedirs(d, exist_ok=True)
        now = time.time()
        for f in os.listdir(d):
            try:
                if now - os.path.getmtime(os.path.join(d, f)) > 120:
                    os.remove(os.path.join(d, f))
            except OSError:
                pass
        key = hashlib.sha256((event + "\0").encode() + raw).hexdigest()[:32]
        fd = os.open(os.path.join(d, key), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return True


def native_hooks():
    return set(_sf_json(os.path.join(frugal_home(), "global.json")).get("native_hooks") or [])


def detect_host(ev, tool):
    """The tool that is really calling (payload marks), else the --tool the entry was written for."""
    if "cursor_version" in ev:
        return "cursor"
    if "clineVersion" in ev:
        return "cline"
    if "sessionId" in ev and "hook_event_name" not in ev and "session_id" not in ev:
        return "copilot"
    if tool == "claude-code" and (os.environ.get("GEMINI_SESSION_ID") or os.environ.get("GEMINI_PROJECT_DIR")):
        return "gemini"
    return tool


EVENTS = {"SessionStart": "start", "sessionStart": "start", "TaskStart": "start", "TaskResume": "start",
          "UserPromptSubmit": "prompt", "userPromptSubmitted": "prompt", "BeforeAgent": "prompt",
          "PostToolUse": "post_tool", "postToolUse": "post_tool", "AfterTool": "post_tool",
          "Stop": "usage", "PostModelRequest": "usage", "SubagentStop": "usage",
          "preCompact": "precompact", "PreCompact": "precompact"}
NATIVE_NAME = {("gemini", "prompt"): "BeforeAgent", ("gemini", "post_tool"): "AfterTool"}


def native_event(host, ev_kind, ev):
    return (ev.get("hook_event_name") or ev.get("hookEventName") or NATIVE_NAME.get((host, ev_kind))
            or {"start": "SessionStart", "prompt": "UserPromptSubmit", "post_tool": "PostToolUse"}.get(ev_kind, ""))


# ---------------------------------------------------------------- usage
def norm_usage(u):
    """Any tool's token counts -> (input w/o cache, output, cache_read, cache_write, context)."""
    if not isinstance(u, dict):
        return None
    g = lambda *ks: next((int(u[k]) for k in ks if isinstance(u.get(k), (int, float))), 0)
    for k in ("last_token_usage", "last", "usage", "usageMetadata"):
        if isinstance(u.get(k), dict):
            u = u[k]
            break
    cr = g("cache_read_input_tokens", "cached_input_tokens", "cachedContentTokenCount", "cache_read")
    cw = g("cache_creation_input_tokens", "cache_write")
    out = g("output_tokens", "completion_tokens", "candidatesTokenCount", "output")
    if "cache_read_input_tokens" in u or "cache_creation_input_tokens" in u:   # Anthropic: input excludes cache
        inp = g("input_tokens")
    else:                                                                       # OpenAI / Gemini: input includes it
        inp = max(g("input_tokens", "prompt_tokens", "promptTokenCount", "input") - cr, 0)
    if not (inp or out or cr or cw):
        return None
    return inp, out, cr, cw, inp + cr + cw


def log_usage(tool, session, model, n, provider=""):
    inp, out, cr, cw, ctx = n
    rec = dict(ts=time.time(), session=session, model=model, provider=provider, context=ctx, input=inp, output=out,
               cache_read=cr, cache_write=cw, tool=tool)
    try:
        os.makedirs(frugal_home(), exist_ok=True)
        with open(os.path.join(frugal_home(), "usage.jsonl"), "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def transcript_usages(path, offset=0):
    """New assistant usages in a Claude-style JSONL transcript from byte offset: ([(id, model, usage)], new offset)."""
    out = []
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except (OSError, TypeError):
        return out, offset
    end = data.rfind(b"\n") + 1
    for line in data[:end].splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        m = r.get("message") if isinstance(r, dict) else None
        if isinstance(m, dict) and r.get("type") == "assistant" and isinstance(m.get("usage"), dict):
            out.append((m.get("id") or r.get("uuid") or "", m.get("model", ""), m["usage"]))
    return out, offset + end


def last_usage(path):
    """(context tokens, model) of the transcript's last assistant message."""
    us, _ = transcript_usages(path)
    if not us:
        return 0, ""
    n = norm_usage(us[-1][2])
    return (n[4] if n else 0), us[-1][1]


def is_cheap(model):
    return any(k in (model or "").lower() for k in CHEAP)


# ---------------------------------------------------------------- output filter
def filter_output(text, limit=OUT_LIMIT, label="shell"):
    """Cut a big output to head + error lines + tail; save the full text. Returns new text or None."""
    if not isinstance(text, str) or len(text) <= limit:
        return None
    lines = text.splitlines()
    head, tail = lines[:40], lines[-60:]
    errs = [f"{i + 1}: {l[:300]}" for i, l in enumerate(lines[40:-60], start=40) if ERR.search(l)][:40]
    path = ""
    try:
        d = os.path.join(frugal_home(), "outputs")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{time.strftime('%Y%m%d-%H%M%S')}-{label}-{os.getpid()}.log")
        open(path, "w").write(text)
    except OSError:
        path = ""
    out = ["\n".join(head), f"\n[frugal-bridge] output cut: {len(lines)} lines, {len(text)} chars."]
    if errs:
        out.append("Error-looking lines in the cut part:\n" + "\n".join(errs))
    out.append("... last 60 lines:\n" + "\n".join(tail))
    if path:
        out.append(f"[full output saved: {path} — grep it instead of re-running]")
    return "\n".join(out)


SHELL = re.compile(r"^(bash|shell|run_shell_command|terminal|exec|local_shell|execute_command|powershell)$", re.I)


def tool_output(host, ev):
    """(tool name, output text or {stdout, stderr} dict) of a post-tool event."""
    if host == "copilot":
        r = ev.get("toolResult") or {}
        return ev.get("toolName", ""), r.get("textResultForLlm") if isinstance(r, dict) else None
    name = ev.get("tool_name") or ev.get("toolName") or ""
    r = ev.get("tool_response", ev.get("tool_result"))
    if host == "gemini" and isinstance(r, dict):
        r = r.get("llmContent") if isinstance(r.get("llmContent"), str) else r.get("returnDisplay")
    if isinstance(r, dict) and "text_result_for_llm" in r:
        r = r["text_result_for_llm"]
    return name, r


def post_tool(host, ev):
    name, r = tool_output(host, ev)
    if name and not SHELL.match(name):
        return None
    if host == "claude-code" and isinstance(r, dict):
        so, se = filter_output(r.get("stdout")), filter_output(r.get("stderr"), label="stderr")
        if not (so or se):
            return None
        new = dict(r, stdout=so or r.get("stdout", ""), stderr=se or r.get("stderr", ""))
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new}}
    if isinstance(r, dict):
        r = "\n".join(str(r.get(k) or "") for k in ("stdout", "stderr", "output") if r.get(k))
    cut = filter_output(r)
    if not cut:
        return None
    if host in ("claude-code", "junie"):
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": cut}}
    if host == "copilot":
        return {"modifiedResult": {"resultType": "success", "textResultForLlm": cut}}
    if host == "crush":
        return {"updated_output": cut}
    if host == "gemini":
        return {"decision": "deny", "reason": cut}
    if host == "codex":
        return {"decision": "block", "reason": cut}
    return None


# ---------------------------------------------------------------- context watch
def context_notice(host, ev):
    sid = ev.get("session_id") or ev.get("sessionId") or ev.get("conversation_id") or ev.get("taskId") or "?"
    ctx, model = last_usage(ev.get("transcript_path") or "")
    if not ctx:
        st = (load_hstate().get("ctx") or {}).get(f"{host}:{sid}") or {}
        ctx, model = st.get("ctx", 0), st.get("model", "")
    warn = WARN_CHEAP if is_cheap(model) else WARN
    s = load_state(); done = set(s.get(sid, [])); out = None
    if ctx >= HARD and "hard" not in done:
        done |= {"hard", "warn"}
        out = (f"[frugal-bridge] This chat is at ~{ctx // 1000}k tokens. Finish the current step, then tell the user "
               "plainly (one line, end of reply) that a new session is needed, and write the handoff first.")
    elif ctx >= warn and "warn" not in done:
        done.add("warn")
        out = (f"[frugal-bridge] This chat is at ~{ctx // 1000}k tokens. At the end of your reply add one short line "
               "offering: new session with handoff (default) / compact / carry on.")
    if out:
        s[sid] = sorted(done); save_state(s)
    return out


def remember_ctx(host, sid, model, ctx):
    s = load_hstate()
    c = s.setdefault("ctx", {})
    c[f"{host}:{sid}"] = {"ctx": ctx, "model": model, "ts": time.time()}
    if len(c) > 500:
        for k in sorted(c, key=lambda k: c[k].get("ts", 0))[:-300]:
            del c[k]
    save_hstate(s)


def usage(host, ev):
    sid = ev.get("session_id") or ev.get("sessionId") or ev.get("conversation_id") or "?"
    if ev.get("token_usage") is not None or host == "codex":
        n = norm_usage(ev.get("token_usage"))
        if n:
            log_usage(host, sid, ev.get("model", ""), n); remember_ctx(host, sid, ev.get("model", ""), n[4])
        return
    tp = ev.get("transcript_path")
    if tp:
        s = load_hstate(); offs = s.setdefault("offsets", {}); seen = s.setdefault("seen", {})
        key = f"{host}:{sid}"
        us, new = transcript_usages(tp, offs.get(key, 0))
        ids = set(seen.get(key, []))
        for mid, model, u in us:
            if mid and mid in ids:
                continue
            n = norm_usage(u)
            if n:
                log_usage(host, sid, model, n)
            ids.add(mid)
        offs[key] = new; seen[key] = sorted(ids)[-200:]
        save_hstate(s)


def precompact(host, ev):
    ctx = ev.get("context_tokens")
    if isinstance(ctx, (int, float)) and ctx:
        sid = ev.get("conversation_id") or ev.get("session_id") or "?"
        log_usage(host, sid, ev.get("model", ""), (0, 0, 0, 0, int(ctx)))
        remember_ctx(host, sid, ev.get("model", ""), int(ctx))


# ---------------------------------------------------------------- output per tool
def emit(host, kind, ev, text):
    if host == "kiro":
        return text                                   # Kiro: plain stdout is added to the context
    if host == "cline":
        return json.dumps({"cancel": False, "contextModification": text})
    if host == "cursor":
        return json.dumps({"additional_context": text})
    if host == "copilot":
        return json.dumps({"additionalContext": text})
    return json.dumps({"hookSpecificOutput": {"hookEventName": native_event(host, kind, ev), "additionalContext": text}})


def start_text(host, ev):
    d = ev.get("cwd") or (ev.get("workspace_roots") or ev.get("workspaceRoots") or [None])[0] or os.getcwd()
    hint = start_hint(d, host=host)
    if host == "cursor":   # no global rules file in Cursor: the rules come with the session start
        rules = _sf_text(os.path.join(frugal_home(), "RULES.md"))
        return "\n\n".join(x for x in (rules, hint) if x) or None
    return hint


def run(argv, raw):
    tool = argv[argv.index("--tool") + 1] if "--tool" in argv else "claude-code"
    try:
        ev = json.loads(raw or b"{}")
    except Exception:
        ev = {}
    ev = ev if isinstance(ev, dict) else {}
    kind = argv[argv.index("--event") + 1] if "--event" in argv else EVENTS.get(
        ev.get("hook_event_name") or ev.get("hookEventName") or ev.get("hookName") or "", "")
    host = detect_host(ev, tool)
    if tool == "claude-code" and host != "claude-code" and host in native_hooks():
        return None                                    # that tool runs its own Frugal entry: stand down
    if not kind or not once(kind, raw or b"", ev):
        return None
    if kind == "start":
        t = start_text(host, ev)
        return emit(host, kind, ev, t) if t else None
    if kind == "prompt":
        t = context_notice(host, ev)
        return emit(host, kind, ev, t) if t else None
    if kind == "post_tool":
        o = post_tool(host, ev)
        return json.dumps(o) if o else None
    if kind == "usage":
        usage(host, ev)
    elif kind == "precompact":
        precompact(host, ev)
    return None


def main():
    try:
        out = run(sys.argv, sys.stdin.buffer.read())
    except Exception:
        out = None
    if out:
        print(out)


if __name__ == "__main__":
    main()
