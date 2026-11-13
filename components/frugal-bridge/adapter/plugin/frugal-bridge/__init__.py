"""Frugal-Bridge adapter for Hermes: enforces the kit rules that a prompt alone cannot guarantee.

- Context watch: tracks each session's context size; past 150k tokens (100k on cheap-tier models) it asks the agent,
  once per threshold, to offer the user a new session with a handoff (one line at the end of its reply). At 300k it
  says it plainly.
- Start files: on the first turn it tells the agent to read the "now" and "user" slot files first, in one call:
  config base_dir (project install) slots, else the connected knowledge base (found like kit/setup.py does, fresh each
  session), else Frugal's own USER.md. A folder slot (e.g. wiki/me/) is expanded to its .md files.
- Output filter: terminal output over ~12k chars is cut to error lines + head + tail; the full text is saved to a
  file whose path is given to the agent.
- Usage log + /frugal: every main-model API request is logged (model, input, cache, output); `/frugal` shows a
  per-model table for today and the last 7 days, with alerts.

Config (optional): $HERMES_HOME/frugal-bridge/config.json
  {"base_dir": "/project/folder (optional; project install writes it)", "ctx_warn": 150000, "ctx_hard": 300000, "ctx_warn_cheap": 100000,
   "cheap_models": ["haiku", "flash", "mini", "luna"], "out_limit": 12000}
"""
import datetime as _dt
import json
import os
import re
import threading
import time

_LOCK = threading.Lock()
_CTX = {}      # session_id -> last known context tokens
_WARNED = {}   # session_id -> set of thresholds already announced
_MODEL = {}    # session_id -> model

DEFAULTS = {"base_dir": "", "ctx_warn": 150000, "ctx_hard": 300000, "ctx_warn_cheap": 100000,
            "cheap_models": ["haiku", "flash", "mini", "luna", "nano"], "out_limit": 12000}


def _home():
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        return str(get_hermes_home())
    except Exception:
        return os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def _dir():
    d = os.path.join(_home(), "frugal-bridge")
    os.makedirs(d, exist_ok=True)
    return d


def cfg():
    c = dict(DEFAULTS)
    p = os.path.join(_dir(), "config.json")
    if os.path.exists(p):
        try:
            c.update(json.load(open(p)))
        except Exception:
            pass
    return c


def _num(u, *names):
    for n in names:
        v = u.get(n) if isinstance(u, dict) else getattr(u, n, None)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _usage_fields(usage):
    if usage is None:
        return None
    if not isinstance(usage, dict) and hasattr(usage, "model_dump"):
        try:
            usage = usage.model_dump()
        except Exception:
            pass
    inp = _num(usage, "input_tokens", "prompt_tokens")
    out = _num(usage, "output_tokens", "completion_tokens")
    cr = _num(usage, "cache_read_input_tokens", "cache_read_tokens", "cached_tokens")
    if not cr and isinstance(usage, dict):
        det = usage.get("prompt_tokens_details") or {}
        cr = _num(det, "cached_tokens")
    cw = _num(usage, "cache_creation_input_tokens", "cache_write_tokens")
    return dict(input=inp, output=out, cache_read=cr, cache_write=cw)


def is_cheap(model, c=None):
    c = c or cfg()
    m = (model or "").lower()
    return any(k in m for k in c["cheap_models"])


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
    """FRUGAL_HOME; else the folder of this file when it is the global install's copy (global.json beside it), so a
    home moved with FRUGAL_HOME keeps working for callers started without the variable; else ~/.frugal-bridge."""
    e = os.environ.get("FRUGAL_HOME")
    if e:
        return e
    here = os.path.dirname(os.path.realpath(__file__))
    return here if os.path.isfile(os.path.join(here, "global.json")) else os.path.expanduser("~/.frugal-bridge")


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


# ---------------------------------------------------------------- hooks

def on_pre_api_request(session_id="", model="", approx_input_tokens=0, **kw):
    if session_id and approx_input_tokens:
        with _LOCK:
            _CTX[session_id] = max(int(approx_input_tokens), 0)
            if model:
                _MODEL[session_id] = model


def on_post_api_request(session_id="", model="", usage=None, provider="", **kw):
    f = _usage_fields(usage)
    if not f:
        return
    # Hermes passes CanonicalUsage: input_tokens excludes cache; prompt_tokens = input + cache read + cache write.
    ctx = _num(usage, "prompt_tokens") if isinstance(usage, dict) and "prompt_tokens" in usage else f["input"] + f["cache_read"] + f["cache_write"]
    with _LOCK:
        if session_id:
            _CTX[session_id] = ctx
            if model:
                _MODEL[session_id] = model
    rec = dict(ts=time.time(), session=session_id, model=model, provider=provider, context=ctx, **f)
    try:
        with open(os.path.join(_dir(), "usage.jsonl"), "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def notice_for(session_id, model, c=None):
    """The one-line instruction to inject this turn, or None (pure function of state; unit-tested)."""
    c = c or cfg()
    ctx = _CTX.get(session_id, 0)
    model = model or _MODEL.get(session_id, "")
    warn = c["ctx_warn_cheap"] if is_cheap(model, c) else c["ctx_warn"]
    done = _WARNED.setdefault(session_id, set())
    if ctx >= c["ctx_hard"] and "hard" not in done:
        done.add("hard"); done.add("warn")
        return (f"[frugal-bridge] This chat is at ~{ctx // 1000}k tokens. Every message now re-reads all of it. "
                "Finish the current step, then tell the user plainly (one line, end of reply) that a new session is "
                "needed, and run the handoff (save sources, update USER/DECISIONS/PROGRESS).")
    if ctx >= warn and "warn" not in done:
        done.add("warn")
        return (f"[frugal-bridge] This chat is at ~{ctx // 1000}k tokens. At the end of your reply add one short line "
                "offering: new session with handoff (default) / compact / carry on.")
    return None


def on_pre_llm_call(session_id="", user_message="", is_first_turn=False, model="", **kw):
    c = cfg()
    parts = []
    if is_first_turn:
        # resolved now, every session: config base_dir (project install) > FRUGAL_BASE > global.json base >
        # Path: lines > pointer file > units; else Frugal's own USER.md (never cached, so later changes apply)
        hh = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
        h = start_hint(c.get("base_dir") or None, host="hermes", identity_files=(os.path.join(hh, "SOUL.md"),))
        if h:
            parts.append(h)
    with _LOCK:
        n = notice_for(session_id, model, c)
    if n:
        parts.append(n)
    return {"context": "\n".join(parts)} if parts else None


ERR = re.compile(r"(error|exception|traceback|failed|fail\b|fatal|panic|denied|not found|warning)", re.I)


def filter_output(text, limit, save_dir=None, label="out"):
    """Cut a big output to error lines + head + tail; save the full text. Returns new text or None."""
    if not isinstance(text, str) or len(text) <= limit:
        return None
    lines = text.splitlines()
    head, tail = lines[:40], lines[-60:]
    errs = [f"{i + 1}: {l[:300]}" for i, l in enumerate(lines[40:-60], start=40) if ERR.search(l)][:40]
    path = ""
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{label}-{os.getpid()}-{threading.get_ident() % 10000}.log")
        try:
            open(path, "w").write(text)
        except Exception:
            path = ""
    out = ["\n".join(head), f"\n[frugal-bridge] output cut: {len(lines)} lines, {len(text)} chars."]
    if errs:
        out.append("Error-looking lines in the cut part:\n" + "\n".join(errs))
    out.append("... last 60 lines:\n" + "\n".join(tail))
    if path:
        out.append(f"[full output saved: {path} — grep it instead of re-running]")
    return "\n".join(out)


def on_transform_terminal_output(command="", output="", **kw):
    c = cfg()
    return filter_output(output, c["out_limit"], os.path.join(_dir(), "outputs"), "terminal")


# ---------------------------------------------------------------- report

PRICE = {  # $ per 1M tokens: input, output, cache read, cache write (5 min). API list prices; plans weigh differently.
    "opus": (5, 25, 0.5, 6.25), "sonnet": (3, 15, 0.3, 3.75), "haiku": (1, 5, 0.1, 1.25),
}


def _price(model):
    m = (model or "").lower()
    for k, v in PRICE.items():
        if k in m:
            return v
    return None


def report(days=7, path=None):
    path = path or os.path.join(_dir(), "usage.jsonl")
    if not os.path.exists(path):
        return "Frugal-Bridge: no usage logged yet."
    now = time.time()
    rows = {}
    sessions = {}
    for line in open(path):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if now - r.get("ts", 0) > days * 86400:
            continue
        k = r.get("model") or "?"
        a = rows.setdefault(k, dict(calls=0, input=0, output=0, cache_read=0, cache_write=0, cost=0.0, today=0))
        a["calls"] += 1
        for f in ("input", "output", "cache_read", "cache_write"):
            a[f] += r.get(f, 0)
        p = _price(k)
        if p:
            a["cost"] += (r["input"] * p[0] + r["output"] * p[1] + r["cache_read"] * p[2] + r["cache_write"] * p[3]) / 1e6
        if now - r["ts"] < 86400:
            a["today"] += 1
        s = sessions.setdefault(r.get("session") or "?", dict(calls=0, maxctx=0, model=k))
        s["calls"] += 1; s["maxctx"] = max(s["maxctx"], r.get("context", 0))
    out = [f"Frugal-Bridge usage, last {days} days (cost at API list prices; subscriptions weigh output ~2x more)",
           "| model | calls (24h) | output | cache read | input+write | ~$ |", "|---|---|---|---|---|---|"]
    for k, a in sorted(rows.items(), key=lambda x: -x[1]["cost"]):
        out.append(f"| {k} | {a['calls']} ({a['today']}) | {a['output']:,} | {a['cache_read']:,} | "
                   f"{a['input'] + a['cache_write']:,} | {a['cost']:.2f} |")
    c = cfg()
    alerts = []
    for sid, s in sessions.items():
        lim = c["ctx_warn_cheap"] if is_cheap(s["model"], c) else c["ctx_warn"]
        if s["maxctx"] > lim:
            alerts.append(f"- session {sid[:18]}: context reached {s['maxctx'] // 1000}k ({s['model']}) → hand off earlier")
        if s["calls"] > 300:
            alerts.append(f"- session {sid[:18]}: {s['calls']} calls → split the work into sessions")
    if alerts:
        out.append("\nAlerts:\n" + "\n".join(alerts[:15]))
    return "\n".join(out)


def _cmd(raw_args=""):
    a = (raw_args or "").strip()
    days = int(a) if a.isdigit() else 7
    return report(days)


def register(ctx):
    ctx.register_hook("pre_api_request", on_pre_api_request)
    ctx.register_hook("post_api_request", on_post_api_request)
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("transform_terminal_output", on_transform_terminal_output)
    ctx.register_command("frugal", handler=_cmd, description="Frugal-Bridge: token usage table + alerts", args_hint="[days]")
