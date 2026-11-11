"""Frugal-Bridge adapter for Hermes: enforces the kit rules that a prompt alone cannot guarantee.

- Context watch: tracks each session's context size; past 150k tokens (100k on cheap-tier models) it asks the agent,
  once per threshold, to offer the user a new session with a handoff (one line at the end of its reply). At 300k it
  says it plainly.
- Start files: on the first turn, if a base folder is configured, it tells the agent to read the "now" and "user"
  slot files first, in one call (paths from .kits.json; default PROGRESS.md / USER.md).
- Output filter: terminal output over ~12k chars is cut to error lines + head + tail; the full text is saved to a
  file whose path is given to the agent.
- Usage log + /frugal: every main-model API request is logged (model, input, cache, output); `/frugal` shows a
  per-model table for today and the last 7 days, with alerts.

Config (optional): $HERMES_HOME/frugal-bridge/config.json
  {"base_dir": "/path/with/USER.md", "ctx_warn": 150000, "ctx_hard": 300000, "ctx_warn_cheap": 100000,
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
    if is_first_turn and c.get("base_dir"):
        have = slots(c["base_dir"])
        if have:
            paths = " ".join(have.values())
            parts.append(f"[frugal-bridge] Session start: read {paths} in one call before answering "
                         "(project facts and past decisions only when the task needs them; paths in .kits.json).")
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
