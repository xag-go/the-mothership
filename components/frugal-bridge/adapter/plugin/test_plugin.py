"""Unit tests for the Frugal-Bridge Hermes adapter (no Hermes needed). Run: pytest -q adapters/hermes/test_plugin.py"""
import importlib.util, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def load(tmp_path, monkeypatch, config=None):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("fb", os.path.join(HERE, "frugal-bridge", "__init__.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m._home = lambda: str(tmp_path)
    if config:
        os.makedirs(tmp_path / "frugal-bridge", exist_ok=True)
        (tmp_path / "frugal-bridge" / "config.json").write_text(json.dumps(config))
    return m


def usage(inp, cr, cw, out):
    return dict(input_tokens=inp, cache_read_tokens=cr, cache_write_tokens=cw, output_tokens=out,
                prompt_tokens=inp + cr + cw, total_tokens=inp + cr + cw + out)


def test_no_notice_below_threshold(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.on_post_api_request(session_id="s", model="claude-opus-5-5", usage=usage(100, 90000, 500, 300))
    assert m.on_pre_llm_call(session_id="s", model="claude-opus-5-5") is None


def test_warn_once_at_150k_then_hard_at_300k(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.on_post_api_request(session_id="s", model="claude-opus-5-5", usage=usage(10, 155000, 0, 10))
    r = m.on_pre_llm_call(session_id="s", model="claude-opus-5-5")
    assert r and "155k" in r["context"] and "new session" in r["context"]
    assert m.on_pre_llm_call(session_id="s", model="claude-opus-5-5") is None  # only once
    m.on_post_api_request(session_id="s", model="claude-opus-5-5", usage=usage(10, 305000, 0, 10))
    r = m.on_pre_llm_call(session_id="s", model="claude-opus-5-5")
    assert r and "plainly" in r["context"]
    assert m.on_pre_llm_call(session_id="s", model="claude-opus-5-5") is None


def test_cheap_model_warns_at_100k(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.on_post_api_request(session_id="h", model="claude-haiku-5-5", usage=usage(10, 101000, 0, 10))
    assert m.on_pre_llm_call(session_id="h", model="claude-haiku-5-5")
    m.on_post_api_request(session_id="o", model="claude-opus-5-5", usage=usage(10, 101000, 0, 10))
    assert m.on_pre_llm_call(session_id="o", model="claude-opus-5-5") is None


def test_sessions_are_separate(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.on_post_api_request(session_id="a", model="claude-opus-5-5", usage=usage(10, 200000, 0, 10))
    assert m.on_pre_llm_call(session_id="b", model="claude-opus-5-5") is None
    assert m.on_pre_llm_call(session_id="a", model="claude-opus-5-5")


def test_pre_api_request_estimate_counts(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.on_pre_api_request(session_id="s", model="claude-opus-5-5", approx_input_tokens=160000)
    assert m.on_pre_llm_call(session_id="s", model="claude-opus-5-5")


def test_start_files_hint(tmp_path, monkeypatch):
    base = tmp_path / "base"; base.mkdir()
    (base / "USER.md").write_text("x"); (base / "PROGRESS.md").write_text("y")
    m = load(tmp_path, monkeypatch, {"base_dir": str(base)})
    r = m.on_pre_llm_call(session_id="s", is_first_turn=True, model="m")
    assert "USER.md" in r["context"] and "PROGRESS.md" in r["context"] and "one call" in r["context"]
    assert m.on_pre_llm_call(session_id="s", is_first_turn=False, model="m") is None


def test_no_start_hint_without_files(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch, {"base_dir": str(tmp_path / "nothing")})
    assert m.on_pre_llm_call(session_id="s", is_first_turn=True, model="m") is None


def test_filter_small_output_untouched(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    assert m.on_transform_terminal_output(command="ls", output="a\nb\n") is None


def test_filter_big_output_keeps_errors_and_saves(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    lines = [f"ok line {i}" for i in range(5000)]
    lines[2500] = "E   AssertionError: expected 3 got 4"
    lines[3100] = "Traceback (most recent call last):"
    big = "\n".join(lines)
    r = m.on_transform_terminal_output(command="pytest", output=big)
    assert r and len(r) < len(big) // 5
    assert "AssertionError" in r and "Traceback" in r
    assert "ok line 0" in r and "ok line 4999" in r
    path = r.split("[full output saved: ")[1].split(" ")[0]
    assert open(path).read() == big


def test_usage_log_and_report(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    for i in range(3):
        m.on_post_api_request(session_id="s1", model="claude-opus-5-5", usage=usage(1000, 160000, 2000, 500))
    m.on_post_api_request(session_id="s2", model="claude-haiku-5-5", usage=usage(500, 20000, 0, 200))
    rep = m.report(7)
    assert "claude-opus-5-5 | 3 (3)" in rep and "claude-haiku-5-5 | 1 (1)" in rep
    assert "Alerts" in rep and "160k" in rep or "163k" in rep
    assert m._cmd("") == rep


def test_report_without_log(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    assert "no usage" in m.report()


def test_bad_usage_shapes_do_not_crash(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.on_post_api_request(session_id="s", model="x", usage=None)
    m.on_post_api_request(session_id="s", model="x", usage={"weird": 1})
    m.on_pre_api_request(session_id="", approx_input_tokens=0)
    assert m.on_pre_llm_call(session_id="s", model="x") is None


def test_register(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    got = {}
    class Ctx:
        def register_hook(self, n, f): got[n] = f
        def register_command(self, n, handler, description="", args_hint=""): got["/" + n] = handler
    m.register(Ctx())
    assert set(got) == {"pre_api_request", "post_api_request", "pre_llm_call", "transform_terminal_output", "/frugal"}


def test_start_hint_uses_kits_slots(tmp_path, monkeypatch):
    base = tmp_path / "base"; (base / "wiki/me").mkdir(parents=True)
    (base / "hot.md").write_text("now"); (base / "wiki/me/README.md").write_text("me")
    (base / "USER.md").write_text("stale copy")  # must be ignored when .kits.json points elsewhere
    (base / ".kits.json").write_text(json.dumps({"kits": {"base-folder": {}}, "slots": {"now": "hot.md", "user": "wiki/me/README.md"}}))
    m = load(tmp_path, monkeypatch, {"base_dir": str(base / "sub")})  # .kits.json found in a parent
    (base / "sub").mkdir()
    r = m.on_pre_llm_call(session_id="s", is_first_turn=True, model="m")["context"]
    assert "hot.md" in r and "wiki/me/README.md" in r and "USER.md" not in r
    assert r.index("hot.md") < r.index("README.md")  # now first, then user
