"""The first-turn start-file hint in every install order, checked in all three adapters (plugin, hooks, proxy) and
against the files each install writes. Each test runs in its own temporary HOME (conftest), with HERMES_HOME /
FRUGAL_HOME inside it; subprocesses get a clean environment (env -i style), so the real home is never read or
written. The real Skeleton Base (brain.py) and The Mothership (install.py) are used when found next to this repo or
via SKELETON_BASE_SRC / MOTHERSHIP_SRC; those cases are skipped otherwise."""
import importlib.util
import itertools
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SETUP = os.path.join(ROOT, "kit", "setup.py")
PLUGIN_SRC = os.path.join(HERE, "plugin", "frugal-bridge")
_REAL = os.path.expanduser("~")      # read at import, before the fixture isolates HOME
SB = os.environ.get("SKELETON_BASE_SRC") or os.path.join(_REAL, "skeleton-base")
MS = os.environ.get("MOTHERSHIP_SRC") or os.path.join(_REAL, "the-mothership")
BRAIN = os.path.join(SB, "tools", "brain.py")
need_sb = pytest.mark.skipif(not os.path.isfile(BRAIN), reason="Skeleton Base not found (set SKELETON_BASE_SRC)")
need_ms = pytest.mark.skipif(not os.path.isfile(os.path.join(MS, "install.py")),
                             reason="The Mothership not found (set MOTHERSHIP_SRC)")
_SID = itertools.count()


@pytest.fixture
def home(_isolated_home, monkeypatch):
    h = _isolated_home
    (h / ".claude").mkdir()
    (h / ".hermes").mkdir()
    (h / ".hermes" / "SOUL.md").write_text("You are the user's assistant.\n")   # Frugal only adds to an existing one
    monkeypatch.setenv("HERMES_HOME", str(h / ".hermes"))
    b = h / ".bin"; b.mkdir()
    for tool in ("python3", "git"):
        if shutil.which(tool):
            os.symlink(shutil.which(tool), b / tool)
    return h


def env(home, **extra):
    e = {"HOME": str(home), "PATH": str(home / ".bin"), "FRUGAL_HOME": str(home / ".frugal-bridge"),
         "HERMES_HOME": str(home / ".hermes"), "FRUGAL_BRIDGE_KIT": ROOT, "PYTHONDONTWRITEBYTECODE": "1",
         "LANG": "C.UTF-8", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
         "GIT_COMMITTER_EMAIL": "t@t"}
    if os.environ.get("FRUGAL_BASE"):
        e["FRUGAL_BASE"] = os.environ["FRUGAL_BASE"]
    e.update(extra)
    return e


def run(home, *cmd, ok=True, **extra):
    r = subprocess.run([sys.executable, *map(str, cmd)], env=env(home, **extra), cwd=str(home), capture_output=True,
                       text=True, timeout=300)
    if ok:
        assert r.returncode == 0, (cmd, r.stdout[-3000:], r.stderr[-3000:])
    return r


def frugal(home, *args, **kw):
    return run(home, SETUP, *args, **kw)


def brain(home, *args, **kw):
    return run(home, BRAIN, *args, **kw)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def plugin(home, path=None):
    m = load(os.path.join(path or PLUGIN_SRC, "__init__.py"), f"fbp{next(_SID)}")
    m._home = lambda: str(home / ".hermes")
    return m


def plugin_hint(m):
    r = m.on_pre_llm_call(session_id=f"s{next(_SID)}", user_message="hi", is_first_turn=True, model="m")
    return r["context"] if r else None


def hook_hint(home, cwd, repo=False):
    hook = home / ".frugal-bridge" / "frugal_hook.py"
    hook = hook if hook.is_file() and not repo else os.path.join(HERE, "hooks", "frugal_hook.py")
    r = subprocess.run([sys.executable, str(hook)], input=json.dumps({"hook_event_name": "SessionStart",
                       "cwd": str(cwd)}), env=env(home), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else None


def proxy_hint():
    sys.path.insert(0, os.path.join(HERE, "proxy"))
    try:
        fp = load(os.path.join(HERE, "proxy", "frugal_proxy.py"), f"fpx{next(_SID)}")
    finally:
        sys.path.pop(0)
    return fp.start_hint(None, fp.TAG)


def hints(home, m=None, repo=False):
    """The hint from the Hermes plugin (installed copy when there is one, unless repo=True), the hook (from an empty
    project folder) and the proxy (no project_dir). All three must agree."""
    copied = home / ".hermes" / "plugins" / "frugal-bridge"
    m = m or plugin(home, str(copied) if (copied / "__init__.py").is_file() and not repo else None)
    proj = home / "work" / "some project"; proj.mkdir(parents=True, exist_ok=True)
    got = plugin_hint(m), hook_hint(home, proj, repo), proxy_hint()
    assert got[0] == got[1] == got[2], got
    return got[0]


def base_files(b):
    me = sorted(str(p) for p in (b / "wiki" / "me").rglob("*.md"))
    assert me, "the base has files in its user slot"
    return [str(b / "hot.md")] + me


def assert_names(hint, files, absent=()):
    assert hint and "Session start" in hint and "one call" in hint
    for f in files:
        assert f in hint and os.path.isfile(f), f
    for f in absent:
        assert str(f) not in hint, f
    assert len(files) == 1 or hint.index(files[0]) < hint.index(files[-1])        # now first, then user


def assert_plugin_copy_current(home):
    dst = home / ".hermes" / "plugins" / "frugal-bridge"
    for f in ("__init__.py", "plugin.yaml"):
        assert (dst / f).read_bytes() == open(os.path.join(PLUGIN_SRC, f), "rb").read(), f


def assert_global_files(home, base, user_from_before=False):
    reg = json.loads((home / ".frugal-bridge" / "global.json").read_text())
    soul = (home / ".hermes" / "SOUL.md").read_text()
    assert soul.count("<!-- frugal-bridge:start") == 1 and "hermes" in reg["tools"]
    assert_plugin_copy_current(home)
    if base:
        assert reg.get("base") == str(base)
        # no second user file (a Frugal-first USER.md is merged into the base and only left for the user to delete)
        assert user_from_before or not (home / ".frugal-bridge" / "USER.md").exists()
        assert soul.index("<!-- base-folder:start") < soul.index("<!-- frugal-bridge:start")
        assert f"{base}/wiki/me/" in soul
    else:
        assert "base" not in reg and (home / ".frugal-bridge" / "USER.md").is_file()


def new_base(home, name):
    b = home / name
    brain(home, "init", b, "--frugal=no")
    brain(home, "connect", "--base", b)
    return b


NAMES = ["kb", "My Base Folder"]   # g: every order also runs with a base path that has spaces


# ---------------------------------------------------------------- a. base first, then Frugal --global

@need_sb
@pytest.mark.parametrize("name", NAMES)
def test_a_base_first_then_frugal_global(home, name):
    b = new_base(home, name)
    frugal(home, "install", "--global")
    assert_global_files(home, b)
    assert frugal(home, "check", "--global").stdout.startswith("OK")
    assert_names(hints(home), base_files(b), absent=[home / ".frugal-bridge" / "USER.md"])
    assert not (home / ".hermes" / "frugal-bridge" / "config.json").exists()    # no project config needed


# ---------------------------------------------------------------- b + c. Frugal first, base later, base removed

@need_sb
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("remove", ["disconnect", "uninstall"])
def test_b_c_frugal_first_then_base_then_base_removed(home, name, remove):
    frugal(home, "install", "--global")
    assert_global_files(home, None)
    user = str(home / ".frugal-bridge" / "USER.md")
    m = plugin(home, str(home / ".hermes" / "plugins" / "frugal-bridge"))   # loaded once: Hermes is not restarted
    assert_names(hints(home, m), [user])
    b = new_base(home, name)                                       # connect re-runs Frugal for its tools
    assert_global_files(home, b, user_from_before=True)
    assert_names(hints(home, m), base_files(b), absent=[user])     # same loaded plugin, next session: base files
    if remove == "disconnect":
        brain(home, "disconnect", "--base", b)
    else:
        brain(home, "uninstall", b, "--no-backup")
    assert not (home / ".config" / "skeleton-base" / "base").exists()
    assert_global_files(home, None)
    assert_names(hints(home, m), [user], absent=[b / "hot.md"])


@need_sb
def test_b_base_added_later_without_any_frugal_rerun(home):
    """The Frugal kit is not findable when the base connects, so nothing re-installs Frugal: the adapters still
    switch to the base (pointer file / base block), with no re-install."""
    frugal(home, "install", "--global")
    m = plugin(home, str(home / ".hermes" / "plugins" / "frugal-bridge"))
    user = str(home / ".frugal-bridge" / "USER.md")
    b = home / "Later Base"
    brain(home, "init", b, "--frugal=no", FRUGAL_BRIDGE_KIT=str(home / "nowhere"))
    brain(home, "connect", "--base", b, FRUGAL_BRIDGE_KIT=str(home / "nowhere"))
    assert "base" not in json.loads((home / ".frugal-bridge" / "global.json").read_text())   # Frugal not re-run
    assert_names(hints(home, m), base_files(b), absent=[user])
    shutil.rmtree(b)                                              # removed by hand: back to USER.md, no crash
    assert_names(hints(home, m), [user])


# ---------------------------------------------------------------- d. The Mothership

@need_ms
@pytest.mark.parametrize("name", NAMES)
def test_d_mothership_install(home, name):
    b = home / name
    run(home, os.path.join(MS, "install.py"), "install", "--yes", "--base", b)
    reg = json.loads((home / ".frugal-bridge" / "global.json").read_text())
    assert reg.get("base") == str(b) and not (home / ".frugal-bridge" / "USER.md").exists()
    assert (home / ".hermes" / "plugins" / "frugal-bridge" / "__init__.py").is_file()
    copied = home / ".hermes" / "plugins" / "frugal-bridge"
    vendored_new = "def start_hint" in (copied / "__init__.py").read_text()   # until it vendors this Frugal: repo copy
    assert_names(hints(home, repo=not vendored_new), base_files(b))


# ---------------------------------------------------------------- e. project install, inside and outside a base

@need_sb
def test_e_project_install_inside_a_base(home):
    b = new_base(home, "My KB")
    frugal(home, "install", b, "--hosts", "hermes", "--hermes-home", home / ".hermes")
    assert json.loads((home / ".hermes" / "frugal-bridge" / "config.json").read_text())["base_dir"] == str(b)
    assert "frugal-bridge" in json.loads((b / ".kits.json").read_text())["kits"]
    assert not (b / "USER.md").exists()                            # the base owns the slots
    assert_plugin_copy_current(home)
    assert_names(plugin_hint(plugin(home, str(home / ".hermes" / "plugins" / "frugal-bridge"))), base_files(b))
    assert_names(hook_hint(home, b / "wiki"), base_files(b))     # a folder inside the base


@need_sb
def test_e_project_install_outside_a_base(home):
    b = new_base(home, "My KB")
    p = home / "proj x"
    frugal(home, "install", p, "--hosts", "hermes", "--hermes-home", home / ".hermes")
    assert (p / "USER.md").is_file() and (p / "PROGRESS.md").is_file()
    assert json.loads((home / ".hermes" / "frugal-bridge" / "config.json").read_text())["base_dir"] == str(p)
    m = plugin(home, str(home / ".hermes" / "plugins" / "frugal-bridge"))
    assert_names(plugin_hint(m), [str(p / "PROGRESS.md"), str(p / "USER.md")], absent=[b / "hot.md"])
    shutil.rmtree(p)                                               # project gone: the base takes over, no crash
    assert_names(plugin_hint(m), base_files(b))


def test_e_project_install_no_base(home):
    p = home / "proj"
    frugal(home, "install", p, "--hosts", "hermes", "--hermes-home", home / ".hermes")
    assert_names(plugin_hint(plugin(home)), [str(p / "PROGRESS.md"), str(p / "USER.md")])


# ---------------------------------------------------------------- f. no base / nothing at all

def test_f_no_base_global_user_file(home):
    frugal(home, "install", "--global")
    assert_global_files(home, None)
    assert_names(hints(home), [str(home / ".frugal-bridge" / "USER.md")])


def test_f_nothing_installed_no_hint_no_crash(home):
    assert hints(home) is None
    m = plugin(home)
    assert m.on_pre_llm_call(session_id="x", is_first_turn=True) is None
    (home / ".frugal-bridge").mkdir()
    (home / ".frugal-bridge" / "global.json").write_text("{not json")       # broken files never crash
    (home / ".config" / "skeleton-base").mkdir(parents=True)
    (home / ".config" / "skeleton-base" / "base").write_text(str(home / "gone") + "\n")
    assert hints(home) is None


# ---------------------------------------------------------------- folder slots, cap, quoting, base discovery parity

def _fake_base(path, n_me=3):
    (path / "wiki" / "me").mkdir(parents=True)
    (path / "hot.md").write_text("now")
    for i in range(n_me):
        (path / "wiki" / "me" / f"{i:02d}-me.md").write_text("me")
    (path / "wiki" / "me" / "notes.txt").write_text("not md")
    (path / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {}}, "slots": {"user": "wiki/me/", "now": "hot.md"}}))
    return path


def test_folder_slot_expands_sorted_and_capped(home, monkeypatch):
    b = _fake_base(home / "big base", 11)
    monkeypatch.setenv("FRUGAL_BASE", str(b))
    h = hints(home)
    me = sorted(str(p) for p in (b / "wiki" / "me").glob("*.md"))
    assert_names(h, [str(b / "hot.md")] + me[:8], absent=me[8:] + [str(b / "wiki" / "me" / "notes.txt")])
    assert f"3 more .md in `{b / 'wiki' / 'me'}/` when needed" in h
    assert f"`{b / 'hot.md'}`" in h                                   # paths with spaces are quoted


def test_discovery_order_matches_setup(home, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "kit"))
    try:
        S = load(SETUP, f"setup{next(_SID)}")
    finally:
        sys.path.pop(0)
    m = plugin(home)
    bases = {k: _fake_base(home / f"base {k}") for k in ("env", "reg", "path", "ptr", "unit")}
    fh = home / ".frugal-bridge"; fh.mkdir()
    (fh / "global.json").write_text(json.dumps({"base": str(bases["reg"])}))
    (home / ".claude" / "CLAUDE.md").write_text(
        f"<!-- base-folder:start v2 -->\n## KB\nPath: `{bases['path']}`\n<!-- base-folder:end -->\n")
    (home / ".config" / "skeleton-base").mkdir(parents=True)
    (home / ".config" / "skeleton-base" / "base").write_text(str(bases["ptr"]) + "\n")
    u = home / ".config" / "systemd" / "user"; u.mkdir(parents=True)
    (u / "skeleton-base-watch.service").write_text(f'[Service]\nExecStart=/usr/bin/python3 brain.py watch --base "{bases["unit"]}"\n')
    monkeypatch.setenv("FRUGAL_BASE", str(bases["env"]))
    files = [os.path.join(t[0], t[1]) for t in S.global_targets().values()]
    reg = lambda: json.loads((fh / "global.json").read_text()).get("base")   # noqa: E731
    for k in ("env", "reg", "path", "ptr", "unit"):
        want = S.find_base(files, str(home), (os.environ.get("FRUGAL_BASE"), reg()))
        assert m.find_base() == want == str(bases[k]), k
        assert str(bases[k] / "hot.md") in plugin_hint(m)
        shutil.rmtree(bases[k])                                    # next source takes over, nothing cached
    assert m.find_base() is None and plugin_hint(m) is None


def test_adapter_copies_of_the_resolver_are_identical():
    def block(p):
        t = open(p).read()
        return t[t.index("# >>> frugal-bridge start-files"):t.index("# <<< frugal-bridge start-files")]
    got = {p: block(os.path.join(HERE, p)) for p in ("hooks/frugal_hook.py", "plugin/frugal-bridge/__init__.py",
                                                     "proxy/frugal_proxy.py")}
    assert len(set(got.values())) == 1, list(got)
