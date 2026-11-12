"""Tests for frugal_hook.py. Run: pytest -q adapters/claude-code/test_hook.py"""
import json, os, subprocess, sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frugal_hook.py")


def run(ev, home):
    env = dict(os.environ, HOME=str(home))
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(ev), capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else None


def transcript(p, model, ctx):
    p.write_text(json.dumps({"type": "assistant", "message": {"model": model, "usage": {"input_tokens": 1, "cache_read_input_tokens": ctx, "output_tokens": 1}}}) + "\n")


def test_context_watch(tmp_path):
    t = tmp_path / "t.jsonl"; transcript(t, "claude-opus-5-5", 160000)
    ev = {"hook_event_name": "UserPromptSubmit", "session_id": "a", "transcript_path": str(t)}
    assert "160k" in run(ev, tmp_path)
    assert run(ev, tmp_path) is None
    transcript(t, "claude-opus-5-5", 310000)
    assert "plainly" in run(ev, tmp_path)


def test_haiku_threshold(tmp_path):
    t = tmp_path / "h.jsonl"; transcript(t, "claude-haiku-5-5", 101000)
    assert run({"hook_event_name": "UserPromptSubmit", "session_id": "h", "transcript_path": str(t)}, tmp_path)


def test_start_default_files(tmp_path):
    (tmp_path / "USER.md").write_text("u"); (tmp_path / "PROGRESS.md").write_text("p")
    r = run({"hook_event_name": "SessionStart", "cwd": str(tmp_path)}, tmp_path)
    assert r.index("PROGRESS.md") < r.index("USER.md")


def test_start_kits_slots(tmp_path):
    (tmp_path / "hot.md").write_text("n"); (tmp_path / "USER.md").write_text("stale")
    (tmp_path / ".kits.json").write_text(json.dumps({"slots": {"now": "hot.md", "user": "missing.md"}}))
    r = run({"hook_event_name": "SessionStart", "cwd": str(tmp_path)}, tmp_path)
    assert "hot.md" in r and "USER.md" not in r


def test_silent_without_files(tmp_path):
    assert run({"hook_event_name": "SessionStart", "cwd": str(tmp_path)}, tmp_path) is None


def test_state_follows_claude_config_dir(tmp_path):
    cfg, home = tmp_path / "worker-claude", tmp_path / "home"
    home.mkdir()
    t = tmp_path / "t.jsonl"; transcript(t, "claude-opus-5-5", 160000)
    ev = {"hook_event_name": "UserPromptSubmit", "session_id": "cfg", "transcript_path": str(t)}
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(cfg))
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(ev), capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "160k" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert (cfg / "frugal-bridge" / "state.json").is_file()        # the warn flag lives in the Claude dir in use
    assert not (home / ".claude").exists()                         # and ~/.claude is never created
