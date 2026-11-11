"""Every test runs with its own HOME and FRUGAL_HOME, so a real install on this machine (e.g. ~/.frugal-bridge/
global.json, ~/.claude, ~/.hermes) can never change a result, and no test can touch the real home."""
import pytest

ISOLATE_UNSET = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "HERMES_HOME", "HERMES_AGENT", "FRUGAL_BASE", "FRUGAL_BRIDGE_KIT",
                 "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "GEMINI_CLI", "BRAIN_ROOT")


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FRUGAL_HOME", str(home / ".frugal-bridge"))
    for e in ISOLATE_UNSET:
        monkeypatch.delenv(e, raising=False)
    yield home
