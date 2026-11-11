"""Frugal-Bridge tiers: a delegation provider that gives each subagent a cheap / mid / top model.

Adds two per-task parameters to the host's delegate tool: `tier` (cheap|mid|top) and `effort` (low|medium|high).
A tier maps to a model of the PARENT's provider family, from Frugal-Bridge's ROUTING.md (kept as `tiers.json` next
to this file; a test keeps the two in step). No tier = the default route (the parent's model, as before).
A family or tier the table does not cover = the default route plus a label note (never refused for a missing entry).

Settings (optional), `delegation.backends.frugal-tiers` in the host config, e.g.
    cheap: {model: claude-haiku-5-5}                    # same provider as the parent, another model
    mid:   {provider: openrouter, model: anthropic/claude-sonnet-5.5, effort: high}
    top:   some-model-id                                # shorthand for {model: ...}

Regenerate the table after editing ROUTING.md:  python3 __init__.py --regen path/to/ROUTING.md
Standard library only; no network calls.
"""
from __future__ import annotations

import json
import os
import re
import sys

try:  # inside Hermes
    from agent.delegation_provider import DelegationProvider, DelegationRouteError
except Exception:  # pragma: no cover - outside Hermes (tests, --regen): same contract, no host
    class DelegationRouteError(ValueError):
        pass

    class DelegationProvider:  # minimal stand-in with the host's settings() rule
        def settings(self, config):
            b = config.get("backends") if isinstance(config, dict) else None
            own = b.get(self.name) if isinstance(b, dict) else None
            return own if isinstance(own, dict) else {}

        def is_available(self):
            return True

NAME = "frugal-tiers"
TIERS = ("cheap", "mid", "top")
EFFORTS = ("low", "medium", "high")
FAMILIES = ("anthropic", "openai", "google")
HERE = os.path.dirname(os.path.abspath(__file__))
TABLE_FILE = os.path.join(HERE, "tiers.json")

# provider name -> family; native ids (no "vendor/" prefix). Anthropic's native API writes versions with dashes.
NATIVE = {
    "anthropic": "anthropic",
    "openai": "openai", "openai-api": "openai", "openai-codex": "openai", "codex": "openai", "chatgpt": "openai",
    "gemini": "google", "google": "google", "google-gemini": "google", "google-ai-studio": "google",
}
# "vendor/model" ids (aggregators such as OpenRouter, Nous, AI gateways, Vertex): vendor -> family
VENDOR = {"anthropic": "anthropic", "openai": "openai", "google": "google"}
GUESS = (("claude-", "anthropic"), ("gpt-", "openai"), ("gemini-", "google"))

DESCRIPTION = (
    "Frugal tiers: set `tier` on each task. cheap = checkable work (code with tests, exact answers, extraction, "
    "formatting, lookups); mid = public writing (effort high), data memos, partner thinking; top = decisions, plans, "
    "architecture, hard languages.\n"
    "`effort`: medium by default, high for public writing or a retry after a failed check; never low for real work. "
    "A failed check moves the task one tier up (cheap -> mid high -> top), not only more effort.\n"
    "No tier = the parent's own model.")


# ------------------------------------------------------------------ ROUTING.md -> table
def _slug(name):
    return re.sub(r"\s+", "-", name.strip().lower())


def _cell(text):
    """One ROUTING.md cell -> {name, id, effort?, untested?} or None ('—' / empty)."""
    t = text.strip()
    if not t or t in ("—", "-", "–"):
        return None
    out = {}
    if re.search(r"\(.*untested.*\)", t):
        out["untested"] = True
    t = re.sub(r"\([^)]*\)", "", t).strip()
    t = re.split(r"\s+or\s+", t)[0].strip()       # first option wins
    t = t.split("/")[0].strip()                   # "Gemini 4 Argon/Carbon" -> "Gemini 4 Argon"
    m = re.match(r"^(.*?)\s+(low|medium|high)$", t, re.I)
    if m:
        t, out["effort"] = m.group(1).strip(), m.group(2).lower()
    out["name"] = t
    out["id"] = _slug(t)
    return out


def parse_routing(text):
    """The tier table of ROUTING.md as {tier: {"effort": .., family: {name, id, ...}}}."""
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    head = [c.strip().lower() for c in rows[0].strip().strip("|").split("|")]
    table = {}
    for ln in rows[1:]:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not cells or set(cells[0]) <= set("-: "):
            continue
        tier = cells[0].lower()
        if tier not in TIERS:
            continue
        row = {}
        for col, val in zip(head[1:], cells[1:]):
            if col == "effort":
                row["effort"] = (re.match(r"\s*(low|medium|high)", val.lower()) or [None, "medium"])[1]
            elif col in FAMILIES:
                c = _cell(val)
                if c:
                    row[col] = c
        table[tier] = row
    return table


def load_table():
    try:
        with open(TABLE_FILE, encoding="utf-8") as f:
            return json.load(f).get("tiers") or {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ parent identity
def parent_identity(config):
    """(provider, model) of the default route: the `delegation` pin when set, else the host's main model."""
    prov = str(config.get("provider") or "").strip().lower()
    model = str(config.get("model") or "").strip()
    if prov and model:
        return prov, model
    main = {}
    try:
        from hermes_cli.config import load_config_readonly
        m = (load_config_readonly() or {}).get("model")
        main = m if isinstance(m, dict) else {"default": m} if isinstance(m, str) else {}
    except Exception:
        pass
    return (prov or str(main.get("provider") or "").strip().lower(),
            model or str(main.get("default") or main.get("model") or "").strip())


def family_of(provider, model):
    """(family, style) where style is 'native-dash', 'native' or 'vendor/<v>'; (None, why) when unknown."""
    model = model or ""
    if "/" in model:
        vendor = model.split("/", 1)[0].lower()
        if vendor in VENDOR:
            return VENDOR[vendor], "vendor/" + vendor
        return None, f"model vendor '{vendor}' not in the table"
    if provider in NATIVE:
        fam = NATIVE[provider]
        return fam, "native-dash" if fam == "anthropic" else "native"
    if provider in ("", "auto"):
        for pre, fam in GUESS:
            if model.lower().startswith(pre):
                return fam, "native-dash" if fam == "anthropic" else "native"
    return None, f"provider '{provider or 'unknown'}' not in the table"


def model_id(entry_id, style):
    if style == "native-dash":
        return entry_id.replace(".", "-")
    if style.startswith("vendor/"):
        return style.split("/", 1)[1] + "/" + entry_id
    return entry_id


# ------------------------------------------------------------------ route
def default_route(config):
    return {k: v for k, v in config.items() if k not in ("service_tier", "backend", "backends")}


def route(task, config, settings, table=None, parent=None):
    """The route for one task (pure: table, settings and parent passed in)."""
    tier, effort = task.get("tier"), task.get("effort")
    if tier is not None and tier not in TIERS:
        raise DelegationRouteError(f"Unknown tier {tier!r}: use one of {', '.join(TIERS)} (or no tier).")
    if effort is not None and effort not in EFFORTS:
        raise DelegationRouteError(f"Unknown effort {effort!r}: use one of {', '.join(EFFORTS)}.")
    base = default_route(config)
    if tier is None:
        if effort:
            base["reasoning_effort"] = effort
        return base
    table = load_table() if table is None else table
    row = table.get(tier) or {}
    over = settings.get(tier)
    if isinstance(over, str):
        over = {"model": over}
    if isinstance(over, dict) and over.get("model"):
        r = dict(base)
        if over.get("provider"):   # another provider: drop the inherited endpoint, take the override's
            for k in ("provider", "base_url", "api_key", "api_mode"):
                r.pop(k, None)
        for k in ("provider", "model", "base_url", "api_key", "api_mode"):
            if over.get(k):
                r[k] = over[k]
        r["reasoning_effort"] = effort or over.get("effort") or row.get("effort") or "medium"
        r["label"] = f"{tier}: {r['model']} (override)"
        return r
    prov, model = parent if parent is not None else parent_identity(config)
    fam, style = family_of(prov, model)
    entry = row.get(fam) if fam else None
    if not entry:
        why = style if not fam else f"no {tier} model for {fam} in ROUTING.md"
        r = dict(base)
        if effort:
            r["reasoning_effort"] = effort
        r["label"] = f"{tier}: parent model kept ({why})"
        return r
    r = dict(base)
    r["model"] = model_id(entry["id"], style)
    r["reasoning_effort"] = effort or entry.get("effort") or row.get("effort") or "medium"
    r["label"] = f"{tier}: {r['model']}" + (" (untested)" if entry.get("untested") else "")
    return r


class FrugalTiers(DelegationProvider):
    @property
    def name(self):
        return NAME

    @property
    def display_name(self):
        return "Frugal tiers"

    @property
    def summary(self):
        return "Per-subagent tier (cheap/mid/top) mapped to a model of the parent's provider (Frugal-Bridge ROUTING.md)."

    def is_available(self):
        return os.path.isfile(TABLE_FILE)

    def task_parameters(self, config):
        return {
            "tier": {"type": "string", "enum": list(TIERS),
                     "description": "Model tier for this subagent: cheap (checkable work), mid (writing, memos), "
                                    "top (decisions, plans). Omit to use the parent's model."},
            "effort": {"type": "string", "enum": list(EFFORTS),
                       "description": "Reasoning effort: medium by default; high for public writing or a retry; "
                                      "low only for trivial lookups."},
        }

    def description(self, config):
        return DESCRIPTION

    def route_task(self, task, config):
        return route(task, config, self.settings(config))


def register(ctx):
    ctx.register_delegation_provider(FrugalTiers())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--regen":
        tbl = parse_routing(open(sys.argv[2], encoding="utf-8").read())
        with open(TABLE_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps({"source": "kit/ROUTING.md", "tiers": tbl}, indent=2, sort_keys=True) + "\n")
        print(f"wrote {TABLE_FILE}")
    else:
        print(json.dumps(load_table(), indent=2))
