"""Shared fake-machine builder for the per-tool tests: a fake HOME with each tool's own config (every format) and
fake binaries on PATH (shutil.which patched)."""
import json
import os

# tool -> files a real install would have (relative to HOME), with user content Frugal must give back byte-identical
USER_FILES = {
    "claude-code": {".claude/settings.json": '{\n  "model": "opus",\n  "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}\n}\n',
                    ".claude/CLAUDE.md": "# my rules\n"},
    "codex": {".codex/config.toml": '# my codex config\napproval_policy = "on-request"\n'},
    "gemini": {".gemini/settings.json": '{\n  // my comment\n  "theme": "dark"\n}\n'},
    "antigravity": {".gemini/antigravity-ide/installation_id": "x\n"},
    "qwen": {".qwen/settings.json": '{"model": {"name": "claude-sonnet-5.5"}}\n'},
    "opencode": {".config/opencode/opencode.jsonc": '{\n  "$schema": "https://opencode.ai/config.json",\n  // mine\n  "model": "anthropic/claude-opus-5-5"\n}\n'},
    "hermes": {".hermes/config.yaml": "model:\n  default: claude-opus-5-5\n  provider: anthropic\n",
               ".hermes/SOUL.md": "You are Kai.\n"},
    "openclaw": {".openclaw/openclaw.json": '{"agents": {"defaults": {}}}\n', ".openclaw/workspace/AGENTS.md": "# seeded\n"},
    "grok": {".grok/config.toml": '[models]\ndefault = "claude-sonnet-5.5"\n\n[ui]\ntheme = "x"\n'},
    "copilot": {".copilot/settings.json": '{\n  "model": "claude-sonnet-5.5",\n  "theme": "dim"\n}\n'},
    "crush": {".config/crush/crushrc": "option theme dark\n"},
    "goose": {".config/goose/config.yaml": "GOOSE_PROVIDER: anthropic\nGOOSE_MODEL: claude-opus-5-5\nextensions: {}\n"},
    "amp": {".config/amp/settings.json": '{"amp.theme": "x"}\n'},
    "aider": {".aider.conf.yml": "model: sonnet\nread:\n  - CONVENTIONS.md\n"},
    "kilo": {".config/kilo/kilo.jsonc": '{\n  "model": "anthropic/claude-opus-5-5" // mine\n}\n'},
    "droid": {".factory/settings.json": '{"model": "claude-opus-5.5"}\n'},
    "warp": {".config/warp-terminal/cli/settings.toml": "x = 1\n"},
    "cursor": {".cursor/cli-config.json": '{"model": "claude-opus-5.5", "version": 1}\n'},
    "devin": {".config/devin/config.json": '{\n  // devin\n  "agent": {"model": "x"}\n}\n'},
    "kiro": {".kiro/settings/cli.json": '{"chat.defaultModel": "claude-sonnet-4.6"}\n'},
    "cline": {".cline/data/settings/global-settings.json": "{}\n"},
    "continue": {".continue/config.yaml": "name: mine\nmodels: []\n"},
    "zed": {".config/zed/settings.json": '// zed\n{\n  "theme": "One"\n}\n'},
    "junie": {".junie/config.json": '{"mcp": {}}\n'},
}


def build(home, tools, monkeypatch, S, hosts, files=True):
    bins = set()
    for t in tools:
        bins.update(hosts.H[t]["bins"][:1])
        if files:
            for rel, text in USER_FILES.get(t, {}).items():
                p = os.path.join(str(home), rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(text)
    monkeypatch.setattr(S.shutil, "which", lambda b: f"/fake/bin/{b}" if b in bins else None)
    return bins


def snapshot(home, skip=(".frugal-bridge",)):
    out = {}
    for root, dirs, files in os.walk(str(home)):
        for f in files:
            p = os.path.join(root, f)
            if not any(s in p for s in skip):
                out[os.path.relpath(p, str(home))] = open(p, "rb").read()
    return out


def dirs(home, skip=(".frugal-bridge",)):
    return sorted(os.path.relpath(r, str(home)) for r, _, _ in os.walk(str(home)) if not any(s in r for s in skip))


def jload(p):
    return json.load(open(p))
