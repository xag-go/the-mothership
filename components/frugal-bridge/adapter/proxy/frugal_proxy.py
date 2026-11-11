#!/usr/bin/env python3
"""Frugal-Bridge proxy: an adapter for ANY host that lets you change the API base URL.

The host (Codex, Cursor, Aider, OpenCode, a custom app...) talks to this proxy instead of the provider. The proxy
forwards every request unchanged (keys pass through, nothing stored) except for these rule enforcements:

1. Context watch: tracks each conversation's real context size from the provider's usage numbers. Past ctx_warn
   (ctx_warn_cheap on cheap models), once, it adds a one-line notice to the next real user turn: offer the user
   new session + handoff / compact / carry on. At ctx_hard it says it plainly.
2. Loop guard: the same tool call with the same result seen twice -> once, a notice "stop and rethink".
3. Output filter: tool results over out_limit chars are cut to head + error lines + tail; the full text is saved to
   a file (name = hash of the text, so the cut is identical on every request and the prompt cache stays valid).
4. Start files: on the first user turn the agent is told to read the "now"/"user" slot files first (optional
   project_dir's .kits.json, else the connected knowledge base's slots, else Frugal's own USER.md; resolved per request).
5. CORE (optional core_file): appended to the system prompt when the host gives no rules file of its own.
6. Usage log (JSONL) + GET /frugal/report.

Notices are appended at the END of the request, never at the start, so the cached prompt prefix is untouched.
Supported wire formats: Anthropic Messages, OpenAI Chat Completions, OpenAI Responses. Anything else = pure pass-through.
Standard library only. Run: python3 frugal_proxy.py [--config proxy.json]
"""
import argparse
import copy
import datetime as _dt
import hashlib
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8790,
    "upstreams": {
        "anthropic": "https://api.anthropic.com",
        "openai": "https://api.openai.com",
        "chatgpt": "https://chatgpt.com/backend-api/codex",
        "openrouter": "https://openrouter.ai/api",
        "gemini": "https://generativelanguage.googleapis.com",
        "xai": "https://api.x.ai",
    },
    "ctx_warn": 150000, "ctx_hard": 300000, "ctx_warn_cheap": 100000,
    "cheap_models": ["haiku", "flash", "mini", "nano", "lite"],
    "out_limit": 12000,
    "filter_outputs": True,
    # only outputs of shell-like tools are cut (file reads stay whole: the agent asked for that content)
    "filter_tools": ["bash", "shell", "terminal", "exec", "command", "run", "local_shell"],
    "loop_guard": True,
    "project_dir": "",
    "core_file": "",
    "data_dir": os.path.expanduser("~/.local/share/frugal-bridge/proxy"),
    "timeout": 600,
    "dump_dir": "",  # debug only: save each forwarded request + raw response here
}

TAG = "[frugal-bridge]"
CFG = dict(DEFAULTS)
_LOCK = threading.Lock()
_STATE = {}  # conv_id -> {"ctx": int, "model": str, "done": set(), "started": bool}


def load_config(path=None):
    c = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("FRUGAL_PROXY_CONFIG") or os.path.expanduser("~/.config/frugal-bridge/proxy.json")
    if path and os.path.exists(path):
        user = json.load(open(path))
        ups = user.pop("upstreams", None)
        c.update(user)
        if ups:
            c["upstreams"].update(ups)
    CFG.clear(); CFG.update(c)
    os.makedirs(CFG["data_dir"], exist_ok=True)
    return CFG


# ------------------------------------------------------------------ helpers

def kind_of(path):
    p = path.split("?")[0]
    if p.endswith("/messages") and "/count_tokens" not in p:
        return "anthropic"
    if p.endswith("/chat/completions"):
        return "chat"
    if p.endswith("/responses"):
        return "responses"
    return None


def is_cheap(model):
    m = (model or "").lower()
    return any(k in m for k in CFG["cheap_models"])


def _h(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:16]


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                out.append(b["text"])
            elif isinstance(b, str):
                out.append(b)
        return "\n".join(out)
    return ""


NOISE_KEYS = {"description", "reason", "reasoning", "explanation", "justification", "thought", "summary", "title", "comment"}


def _sig_args(a):
    """Tool arguments without free-text noise fields (hosts add a fresh 'description' to every call)."""
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except Exception:
            return a
    if isinstance(a, dict):
        a = {k: v for k, v in a.items() if k.lower() not in NOISE_KEYS}
    return json.dumps(a, sort_keys=True)


def conv_id(kind, body, headers):
    """Stable id per conversation: host-given ids first, else hash of model + first user message."""
    if body.get("prompt_cache_key"):
        return "k:" + str(body["prompt_cache_key"])
    md = body.get("metadata") or {}
    if isinstance(md, dict) and md.get("user_id"):
        return "u:" + _h(str(md["user_id"]))  # hashed: user_id may hold account ids
    for h in ("session_id", "x-session-id", "conversation_id"):
        if headers.get(h):
            return "h:" + headers[h]
    first = ""
    items = body.get("messages") if kind != "responses" else body.get("input")
    if isinstance(items, str):
        first = items
    elif isinstance(items, list):
        for m in items:
            if isinstance(m, dict) and m.get("role") == "user":
                first = _text_of(m.get("content"))
                break
    return "f:" + _h(str(body.get("model", "")) + "|" + first[:4000])


ERR = re.compile(r"(error|exception|traceback|failed|fail\b|fatal|panic|denied|not found|warning)", re.I)


def filter_output(text, limit, save_dir):
    """Deterministic cut: same text -> same output (cache-safe). Full text saved under its hash."""
    if not isinstance(text, str) or len(text) <= limit or text.startswith(TAG):
        return None
    lines = text.splitlines()
    if len(lines) < 120:  # few very long lines: cut by characters
        head, tail, errs = [text[: limit // 3]], [text[-limit // 3:]], []
    else:
        head, tail = lines[:40], lines[-60:]
        errs = [f"{i + 1}: {l[:300]}" for i, l in enumerate(lines[40:-60], start=40) if ERR.search(l)][:40]
    path = os.path.join(save_dir, _h(text) + ".log")
    try:
        if not os.path.exists(path):
            os.makedirs(save_dir, exist_ok=True)
            open(path, "w").write(text)
    except OSError:
        path = ""
    out = [f"{TAG} output cut: {len(lines)} lines, {len(text)} chars.", "\n".join(head)]
    if errs:
        out.append("Error-looking lines in the cut part:\n" + "\n".join(errs))
    out.append("... end:\n" + "\n".join(tail))
    if path:
        out.append(f"[full output saved: {path} — grep it instead of re-running]")
    return "\n".join(out)


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

# ------------------------------------------------------------------ per-format views

class View:
    """Uniform access to the three wire formats: last-turn type, tool calls/results, append a notice, filter."""

    def __init__(self, kind, body):
        self.kind, self.b = kind, body

    # list of (signature, result_text) for tool calls, in order
    def tool_pairs(self):
        calls, results = {}, {}
        order = []
        if self.kind == "anthropic":
            for m in self.b.get("messages") or []:
                c = m.get("content")
                if not isinstance(c, list):
                    continue
                for blk in c:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "tool_use":
                        calls[blk.get("id")] = blk.get("name", "") + _sig_args(blk.get("input"))
                        order.append(blk.get("id"))
                    elif blk.get("type") == "tool_result":
                        results[blk.get("tool_use_id")] = _text_of(blk.get("content"))
        elif self.kind == "chat":
            for m in self.b.get("messages") or []:
                for tc in m.get("tool_calls") or []:
                    f = tc.get("function") or {}
                    calls[tc.get("id")] = f.get("name", "") + _sig_args(f.get("arguments"))
                    order.append(tc.get("id"))
                if m.get("role") == "tool":
                    results[m.get("tool_call_id")] = _text_of(m.get("content"))
        else:
            inp = self.b.get("input")
            for it in inp if isinstance(inp, list) else []:
                if not isinstance(it, dict):
                    continue
                t = it.get("type")
                if t in ("function_call", "custom_tool_call", "local_shell_call"):
                    calls[it.get("call_id")] = (it.get("name") or t) + _sig_args(it.get("arguments") or it.get("input") or it.get("action"))
                    order.append(it.get("call_id"))
                elif t in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                    o = it.get("output")
                    results[it.get("call_id")] = o if isinstance(o, str) else json.dumps(o, sort_keys=True)
        return [(calls[i], results.get(i)) for i in order if i in calls]

    def last_turn(self):
        """'user' = a real user message, 'tool' = tool results, None = other."""
        if self.kind == "anthropic":
            ms = self.b.get("messages") or []
            if not ms or ms[-1].get("role") != "user":
                return None
            c = ms[-1].get("content")
            if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
                return "tool"
            return "user"
        if self.kind == "chat":
            ms = self.b.get("messages") or []
            if not ms:
                return None
            return {"user": "user", "tool": "tool"}.get(ms[-1].get("role"))
        inp = self.b.get("input")
        if isinstance(inp, str):
            return "user"
        if not isinstance(inp, list) or not inp:
            return None
        last = inp[-1]
        if last.get("type", "message") == "message" and last.get("role") == "user":
            return "user"
        if str(last.get("type", "")).endswith("_output"):
            return "tool"
        return None

    def first_user_turn(self):
        if self.kind == "responses":
            inp = self.b.get("input")
            if isinstance(inp, str):
                return True
            items = inp or []
            return not any(isinstance(i, dict) and (i.get("role") == "assistant" or str(i.get("type", "")).endswith("call")) for i in items)
        return not any(m.get("role") == "assistant" for m in self.b.get("messages") or [])

    def append_notice(self, text):
        if self.kind == "anthropic":
            last = self.b["messages"][-1]
            c = last.get("content")
            if isinstance(c, str):
                last["content"] = [{"type": "text", "text": c}, {"type": "text", "text": text}]
            else:
                c.append({"type": "text", "text": text})
        elif self.kind == "chat":
            ms = self.b["messages"]
            if ms[-1].get("role") == "user" and isinstance(ms[-1].get("content"), str):
                ms[-1]["content"] += "\n\n" + text
            elif ms[-1].get("role") == "user" and isinstance(ms[-1].get("content"), list):
                ms[-1]["content"].append({"type": "text", "text": text})
            else:
                ms.append({"role": "user", "content": text})
        else:
            if isinstance(self.b.get("input"), str):
                self.b["input"] = [{"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": self.b["input"]}]}]
            self.b["input"].append({"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": text}]})

    def tool_names(self):
        names = {}
        if self.kind == "anthropic":
            for m in self.b.get("messages") or []:
                c = m.get("content")
                for blk in c if isinstance(c, list) else []:
                    if isinstance(blk, dict) and blk.get("type") == "tool_use":
                        names[blk.get("id")] = blk.get("name", "")
        elif self.kind == "chat":
            for m in self.b.get("messages") or []:
                for tc in m.get("tool_calls") or []:
                    names[tc.get("id")] = (tc.get("function") or {}).get("name", "")
        else:
            inp = self.b.get("input")
            for it in inp if isinstance(inp, list) else []:
                if isinstance(it, dict) and str(it.get("type", "")).endswith("call"):
                    names[it.get("call_id")] = it.get("name") or it.get("type")
        return names

    def filter_tool_outputs(self, limit, save_dir, tools=None):
        n = 0
        names = self.tool_names()
        ok = lambda i: tools is None or any(t in (names.get(i) or "").lower() for t in tools)
        if self.kind == "anthropic":
            for m in self.b.get("messages") or []:
                c = m.get("content")
                for blk in c if isinstance(c, list) else []:
                    if isinstance(blk, dict) and blk.get("type") == "tool_result" and ok(blk.get("tool_use_id")):
                        tc = blk.get("content")
                        if isinstance(tc, str):
                            r = filter_output(tc, limit, save_dir)
                            if r:
                                blk["content"] = r; n += 1
                        elif isinstance(tc, list):
                            for sub in tc:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    r = filter_output(sub.get("text"), limit, save_dir)
                                    if r:
                                        sub["text"] = r; n += 1
        elif self.kind == "chat":
            for m in self.b.get("messages") or []:
                if m.get("role") == "tool" and isinstance(m.get("content"), str) and ok(m.get("tool_call_id")):
                    r = filter_output(m["content"], limit, save_dir)
                    if r:
                        m["content"] = r; n += 1
        else:
            inp = self.b.get("input")
            for it in inp if isinstance(inp, list) else []:
                if isinstance(it, dict) and str(it.get("type", "")).endswith("_output") and isinstance(it.get("output"), str) and ok(it.get("call_id")):
                    r = filter_output(it["output"], limit, save_dir)
                    if r:
                        it["output"] = r; n += 1
        return n

    def add_core(self, core):
        marker = "frugal-bridge:start"
        if self.kind == "anthropic":
            s = self.b.get("system")
            if marker in json.dumps(s or ""):
                return False
            if isinstance(s, list):
                s.append({"type": "text", "text": core})
            else:
                self.b["system"] = ((s + "\n\n") if s else "") + core
        elif self.kind == "chat":
            ms = self.b.setdefault("messages", [])
            if ms and ms[0].get("role") in ("system", "developer"):
                if marker in json.dumps(ms[0].get("content")):
                    return False
                if isinstance(ms[0].get("content"), str):
                    ms[0]["content"] += "\n\n" + core
                else:
                    ms[0]["content"].append({"type": "text", "text": core})
            else:
                ms.insert(0, {"role": "system", "content": core})
        else:
            ins = self.b.get("instructions") or ""
            if marker in ins:
                return False
            self.b["instructions"] = (ins + "\n\n" if ins else "") + core
        return True


# ------------------------------------------------------------------ the rules

def apply_rules(kind, body, headers):
    """Mutates body. Returns (conv_id, list of applied rule names)."""
    v = View(kind, body)
    cid = conv_id(kind, body, headers)
    model = str(body.get("model", ""))
    applied = []
    if CFG["filter_outputs"]:
        n = v.filter_tool_outputs(CFG["out_limit"], os.path.join(CFG["data_dir"], "outputs"), CFG.get("filter_tools"))
        if n:
            applied.append(f"filter:{n}")
    if CFG.get("core_file") and os.path.isfile(CFG["core_file"]):
        core = open(CFG["core_file"]).read()
        if v.add_core(core):
            applied.append("core")
    turn = v.last_turn()
    notices = []
    with _LOCK:
        st = _STATE.setdefault(cid, {"ctx": 0, "model": model, "done": set()})
        if not st["ctx"]:
            st["ctx"] = len(json.dumps(body)) // 4  # rough estimate until real usage arrives
        if turn == "user" and v.first_user_turn():
            sl = start_hint(CFG.get("project_dir") or None, TAG) if "start" not in st["done"] else None
            if sl:
                st["done"].add("start")
                notices.append(sl)
        if turn == "user":
            warn = CFG["ctx_warn_cheap"] if is_cheap(model) else CFG["ctx_warn"]
            ctx = st["ctx"]
            if ctx >= CFG["ctx_hard"] and "hard" not in st["done"]:
                st["done"] |= {"hard", "warn"}
                notices.append(f"{TAG} This chat is at ~{ctx // 1000}k tokens; every message re-reads all of it. Finish "
                               "the current step, then tell the user plainly (one line, end of reply) that a new session "
                               "is needed, and write the handoff first (save pasted sources to files).")
            elif ctx >= warn and "warn" not in st["done"]:
                st["done"].add("warn")
                notices.append(f"{TAG} This chat is at ~{ctx // 1000}k tokens. At the end of your reply add one short "
                               "line offering: new session with handoff (default) / compact / carry on.")
        if turn == "tool" and CFG["loop_guard"]:
            pairs = v.tool_pairs()
            if len(pairs) >= 2:
                sig, res = pairs[-1]
                key = "loop:" + _h(sig + "|" + str(res))
                same_call = any(s_ == sig and r == res for s_, r in pairs[:-1])
                prev = pairs[-2][1]
                same_err = (res is not None and res == prev and ERR.search(res or "") is not None)
                if key not in st["done"] and (same_call or same_err):
                    st["done"].add(key)
                    what = "the same tool call twice and got the same result" if same_call else "two calls that failed with the same error"
                    notices.append(f"{TAG} You made {what}. Stop and rethink before the next call: what is "
                                   "different this time? Change the approach or tell the user what blocks you.")
    if notices:
        v.append_notice("\n".join(notices))
        applied += ["notice:" + n.split(":")[0][len(TAG) + 1:][:20] for n in notices]
    return cid, applied


def usage_from_obj(kind, o):
    """Return (context_tokens, output_tokens, cache_read, cache_write) from a usage dict, or None."""
    if not isinstance(o, dict):
        return None
    if kind == "anthropic":
        i, cr, cw = o.get("input_tokens") or 0, o.get("cache_read_input_tokens") or 0, o.get("cache_creation_input_tokens") or 0
        return (i + cr + cw, o.get("output_tokens") or 0, cr, cw)
    if kind == "chat":
        det = o.get("prompt_tokens_details") or {}
        return (o.get("prompt_tokens") or 0, o.get("completion_tokens") or 0, det.get("cached_tokens") or 0, 0)
    det = o.get("input_tokens_details") or {}
    return (o.get("input_tokens") or 0, o.get("output_tokens") or 0, det.get("cached_tokens") or 0, 0)


class UsageSniffer:
    """Feeds on response bytes (SSE or JSON) and keeps the last usage numbers seen."""

    def __init__(self, kind):
        self.kind, self.buf, self.ctx, self.out, self.cr, self.cw, self.raw = kind, b"", 0, 0, 0, 0, []

    def _take(self, d):
        u = None
        if self.kind == "anthropic":
            if d.get("type") == "message_start":
                u = (d.get("message") or {}).get("usage")
            elif d.get("type") == "message_delta":
                u = d.get("usage")
            elif d.get("type") == "message":
                u = d.get("usage")
            if u:
                # message_delta may carry only output_tokens: keep input side from message_start
                if self.ctx and not any(u.get(k) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")):
                    self.out = u.get("output_tokens") or self.out
                    return
        elif self.kind == "chat":
            u = d.get("usage")
        else:
            u = d.get("usage") or ((d.get("response") or {}).get("usage") if isinstance(d.get("response"), dict) else None)
        r = usage_from_obj(self.kind, u)
        if r and (r[0] or r[1]):
            self.ctx, self.out, self.cr, self.cw = r[0] or self.ctx, r[1] or self.out, r[2] or self.cr, r[3] or self.cw

    def feed(self, chunk):
        self.buf += chunk
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.strip()
            if line.startswith(b"data:"):
                try:
                    self._take(json.loads(line[5:].strip()))
                except Exception:
                    pass
            else:
                self.raw.append(line)

    def finish(self):
        rest = b"\n".join(self.raw) + self.buf
        if rest.strip().startswith(b"{"):
            try:
                self._take(json.loads(rest))
            except Exception:
                pass


def record(cid, model, sn, applied, status):
    with _LOCK:
        st = _STATE.setdefault(cid, {"ctx": 0, "model": model, "done": set()})
        if sn.ctx:
            st["ctx"] = sn.ctx
        st["model"] = model or st["model"]
    rec = dict(ts=time.time(), conv=cid, model=model, status=status, context=sn.ctx, output=sn.out,
               cache_read=sn.cr, cache_write=sn.cw, rules=applied)
    try:
        with open(os.path.join(CFG["data_dir"], "usage.jsonl"), "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def report(days=7):
    path = os.path.join(CFG["data_dir"], "usage.jsonl")
    if not os.path.exists(path):
        return "Frugal-Bridge proxy: no usage logged yet."
    now, rows, convs, rules = time.time(), {}, {}, {}
    for line in open(path):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if now - r.get("ts", 0) > days * 86400:
            continue
        a = rows.setdefault(r.get("model") or "?", dict(calls=0, output=0, cache_read=0, context=0))
        a["calls"] += 1; a["output"] += r.get("output", 0); a["cache_read"] += r.get("cache_read", 0); a["context"] += r.get("context", 0)
        c = convs.setdefault(r.get("conv"), dict(calls=0, maxctx=0, model=r.get("model")))
        c["calls"] += 1; c["maxctx"] = max(c["maxctx"], r.get("context", 0))
        for x in r.get("rules", []):
            rules[x.split(":")[0]] = rules.get(x.split(":")[0], 0) + 1
    out = [f"Frugal-Bridge proxy, last {days} days", "| model | calls | context read | cache read | output |", "|---|---|---|---|---|"]
    for k, a in sorted(rows.items(), key=lambda x: -x[1]["context"]):
        out.append(f"| {k} | {a['calls']} | {a['context']:,} | {a['cache_read']:,} | {a['output']:,} |")
    out.append("Rules applied: " + (", ".join(f"{k} x{v}" for k, v in sorted(rules.items())) or "none"))
    alerts = [f"- conversation {k[:20]}: context reached {c['maxctx'] // 1000}k ({c['model']})"
              for k, c in convs.items() if c["maxctx"] > (CFG["ctx_warn_cheap"] if is_cheap(c["model"]) else CFG["ctx_warn"])]
    alerts += [f"- conversation {k[:20]}: {c['calls']} calls" for k, c in convs.items() if c["calls"] > 300]
    if alerts:
        out.append("Alerts:\n" + "\n".join(alerts[:15]))
    return "\n".join(out)


# ------------------------------------------------------------------ HTTP

HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "accept-encoding", "proxy-connection", "upgrade", "te"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        if os.environ.get("FRUGAL_PROXY_DEBUG"):
            sys.stderr.write("frugal-proxy: " + fmt % a + "\n")

    def _send_text(self, code, text, ctype="text/plain; charset=utf-8"):
        b = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _route(self):
        parts = self.path.lstrip("/").split("/", 1)
        base = CFG["upstreams"].get(parts[0])
        if not base:
            return None, None
        rest = "/" + (parts[1] if len(parts) > 1 else "")
        u = urllib.parse.urlsplit(base)
        return u, (u.path.rstrip("/") + rest)

    def do_GET(self):
        if self.path.startswith("/frugal/health"):
            return self._send_text(200, "ok")
        if self.path.startswith("/frugal/report"):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return self._send_text(200, report(int((q.get("days") or ["7"])[0])))
        self._proxy(None)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self._proxy(self.rfile.read(n) if n else b"")

    do_PUT = do_POST
    do_PATCH = do_POST

    def do_DELETE(self):
        self._proxy(None)

    do_HEAD = do_DELETE
    do_OPTIONS = do_DELETE

    def _proxy(self, body):
        u, path = self._route()
        if not u:
            return self._send_text(404, f"frugal-proxy: unknown route. Use /<{'|'.join(CFG['upstreams'])}>/...")
        kind = kind_of(path)
        cid, applied, model = None, [], ""
        if kind and body:
            try:
                obj = json.loads(body)
                model = str(obj.get("model", ""))
                if kind == "chat" and obj.get("stream") and not (obj.get("stream_options") or {}).get("include_usage"):
                    obj.setdefault("stream_options", {})["include_usage"] = True
                cid, applied = apply_rules(kind, obj, {k.lower(): v for k, v in self.headers.items()})
                body = json.dumps(obj, ensure_ascii=False).encode()
            except Exception as e:  # never break the host: forward the original body
                applied = [f"error:{type(e).__name__}"]
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Accept-Encoding"] = "identity"
        if body is not None:
            headers["Content-Length"] = str(len(body))
        Conn = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = Conn(u.hostname, u.port, timeout=CFG["timeout"])
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
        except Exception as e:
            return self._send_text(502, f"frugal-proxy: upstream error: {e}")
        self.send_response(resp.status, resp.reason)
        for k, v in resp.getheaders():
            if k.lower() not in HOP:
                self.send_header(k, v)
        if self.command == "HEAD" or resp.status in (204, 304):
            self.send_header("Content-Length", resp.getheader("Content-Length") or "0")
            self.end_headers()
            conn.close()
            return
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        sn = UsageSniffer(kind) if kind else None
        dump = []
        recorded = False
        try:
            while True:
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not chunk:
                    break
                if sn:
                    sn.feed(chunk)
                if CFG.get("dump_dir"):
                    dump.append(chunk)
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            # Record usage BEFORE the final chunk: a client may send its next request the moment the body ends.
            if sn and cid:
                sn.finish()
                record(cid, model, sn, applied, resp.status)
                recorded = True
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()
        if CFG.get("dump_dir") and kind:
            os.makedirs(CFG["dump_dir"], exist_ok=True)
            stem = os.path.join(CFG["dump_dir"], f"{time.time():.3f}-{kind}")
            open(stem + ".req.json", "wb").write(body or b"")
            open(stem + ".resp.txt", "wb").write(b"".join(dump))
        if sn and cid and not recorded:
            sn.finish()
            record(cid, model, sn, applied, resp.status)


def main():
    ap = argparse.ArgumentParser(description="Frugal-Bridge proxy adapter")
    ap.add_argument("--config")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    load_config(a.config)
    if a.port:
        CFG["port"] = a.port
    srv = ThreadingHTTPServer((CFG["host"], CFG["port"]), Handler)
    srv.daemon_threads = True
    print(f"frugal-proxy on http://{CFG['host']}:{CFG['port']}  routes: {', '.join('/' + k for k in CFG['upstreams'])}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
