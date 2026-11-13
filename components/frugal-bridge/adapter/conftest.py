"""Every test runs with its own HOME and FRUGAL_HOME, so a real install on this machine (e.g. ~/.frugal-bridge/
global.json, ~/.claude, ~/.hermes) can never change a result, and no test can touch the real home."""
import shutil

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


@pytest.fixture(scope="session", autouse=True)
def _remove_pytest_basetemp(request, tmp_path_factory):
    """pytest keeps the last three runs' basetemp dirs under $TMPDIR; remove this run's, its pytest-current link and
    the empty pytest-of-<user> parent at session end (a --basetemp given by the caller is left alone)."""
    yield
    if request.config.getoption("basetemp") is None:
        base = tmp_path_factory.getbasetemp()
        shutil.rmtree(base, ignore_errors=True)
        root = base.parent
        link = root / "pytest-current"
        if link.is_symlink():
            link.unlink()
        try:
            root.rmdir()
        except OSError:
            pass
