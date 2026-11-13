"""Codex usage from the rollout (JSONL) on Stop, with a per-session offset, so each model response is logged once.
Fixtures are made-up rollout lines in the shape Codex CLI 0.159.x writes (no real content, no real ids)."""
import json, os, subprocess, sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frugal_hook.py")
SID = "11111111-2222-7333-8444-555555555555"


def line(t, payload, ordinal):
    return json.dumps({"timestamp": "2026-11-08T15:00:00.000Z", "ordinal": ordinal, "type": t, "payload": payload}) + "\n"


def usage(inp, cached, out):
    return {"input_tokens": inp, "cached_input_tokens": cached, "cache_write_input_tokens": 0,
            "output_tokens": out, "reasoning_output_tokens": 0, "total_tokens": inp + out}


def response(rid, inp, cached, out, ordinal):
    """A token_usage_record (one model response) and the token_count event Codex writes beside it."""
    return (line("token_usage_record", {"thread_id": SID, "turn_id": "t1", "session_id": SID, "root_turn_id": "t1",
                                        "response_id": rid, "usage": usage(inp, cached, out),
                                        "turn_token_usage": usage(inp, cached, out),
                                        "thread_token_usage": usage(inp, cached, out)}, ordinal)
            + line("event_msg", {"type": "token_count", "info": {"total_token_usage": usage(inp, cached, out),
                                                               "last_token_usage": usage(inp, cached, out),
                                                               "model_context_window": 475000}}, ordinal + 1))


def header(model="gpt-6.1-sol"):
    return (line("session_meta", {"id": SID, "session_id": SID, "cli_version": "0.159.3", "originator": "codex_exec",
                                  "model_provider": "openai", "cwd": "/tmp/made-up"}, 0)
            + line("task_started", {"type": "task_started", "turn_id": "t1", "model_context_window": 475000}, 1)
            + line("turn_context", {"turn_id": "t1", "cwd": "/tmp/made-up", "model": model,
                                    "approval_policy": "never"}, 2))


def run(ev, home, event="usage"):
    env = {k: v for k, v in os.environ.items() if k not in ("FRUGAL_HOME", "CODEX_HOME")}
    env.update(HOME=str(home), FRUGAL_HOME=str(home / ".fb"))
    r = subprocess.run([sys.executable, HOOK, "--tool", "codex", "--event", event], input=json.dumps(ev),
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def rows(home):
    p = home / ".fb" / "usage.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def ev(name, tp, **kw):
    return dict({"hook_event_name": name, "session_id": SID, "transcript_path": str(tp), "cwd": "/tmp/made-up"}, **kw)


def test_stop_logs_each_response_with_codex_tool_and_model(tmp_path):
    t = tmp_path / "rollout.jsonl"
    t.write_text(header() + response("resp_a", 14000, 0, 170, 3) + response("resp_b", 16800, 14336, 112, 6))
    assert run(ev("Stop", t, model="gpt-6.1-sol", stop_hook_active=False), tmp_path) == ""
    r = rows(tmp_path)
    assert [(x["tool"], x["model"], x["input"], x["cache_read"], x["output"], x["context"]) for x in r] == [
        ("codex", "gpt-6.1-sol", 14000, 0, 170, 14000),
        ("codex", "gpt-6.1-sol", 2464, 14336, 112, 16800)]
    assert sum(x["input"] + x["cache_read"] for x in r) == 16800 + 14000   # the rollout's input totals, no more


def test_stop_reads_only_new_responses(tmp_path):
    t = tmp_path / "rollout.jsonl"
    t.write_text(header() + response("resp_a", 14000, 0, 170, 3))
    run(ev("Stop", t), tmp_path)
    run(ev("Stop", t), tmp_path)                                  # nothing new: nothing logged twice
    assert len(rows(tmp_path)) == 1
    with open(t, "a") as fh:
        fh.write(response("resp_b", 15000, 14000, 90, 6))
    run(ev("Stop", t), tmp_path)
    r = rows(tmp_path)
    assert len(r) == 2 and r[1]["output"] == 90 and r[1]["input"] == 1000


def test_partial_last_line_waits_for_its_newline(tmp_path):
    t = tmp_path / "rollout.jsonl"
    second = response("resp_b", 2000, 0, 7, 6)
    cut = second.index("\n") // 2                                 # half of the token_usage_record line is written
    t.write_text(header() + response("resp_a", 1000, 0, 5, 3) + second[:cut])
    run(ev("Stop", t), tmp_path)
    assert [x["output"] for x in rows(tmp_path)] == [5]
    with open(t, "a") as fh:
        fh.write(second[cut:])
    run(ev("Stop", t), tmp_path)
    assert [x["output"] for x in rows(tmp_path)] == [5, 7]


def test_postmodelrequest_with_rollout_does_not_double_count(tmp_path):
    """Newer Codex may also send PostModelRequest. With the rollout path, both events read the same offset, so
    a response is counted once whichever arrives first."""
    t = tmp_path / "rollout.jsonl"
    t.write_text(header() + response("resp_a", 14000, 0, 170, 3))
    pmr = ev("PostModelRequest", t, model="gpt-6.1-sol", status="completed",
             token_usage={"input_tokens": 14000, "cached_input_tokens": 0, "output_tokens": 170})
    run(pmr, tmp_path)
    run(ev("Stop", t), tmp_path)
    run(pmr, tmp_path)
    assert [x["output"] for x in rows(tmp_path)] == [170]


def test_no_rollout_path_logs_the_event_usage_once_per_event(tmp_path):
    e = {"hook_event_name": "PostModelRequest", "session_id": SID, "model": "gpt-6.1-sol", "status": "completed",
         "token_usage": {"input_tokens": 170000, "cached_input_tokens": 150000, "output_tokens": 900}}
    run(e, tmp_path)
    r = rows(tmp_path)
    assert (r[0]["tool"], r[0]["input"], r[0]["cache_read"], r[0]["context"]) == ("codex", 20000, 150000, 170000)


def test_missing_fields_and_missing_file_are_safe(tmp_path):
    assert run({"hook_event_name": "Stop", "session_id": SID}, tmp_path) == ""              # no path, no usage
    assert run({"hook_event_name": "Stop", "session_id": SID, "transcript_path": str(tmp_path / "gone.jsonl"),
                "model": "x"}, tmp_path) == ""
    assert run({"hook_event_name": "Stop", "transcript_path": 42}, tmp_path) == ""         # wrong type, no crash
    assert rows(tmp_path) == []
    t = tmp_path / "junk.jsonl"
    t.write_text("not json\n[1, 2]\n" + line("token_usage_record", {"usage": "bad"}, 1))
    assert run(ev("Stop", t), tmp_path) == ""
    assert rows(tmp_path) == []


def test_context_watch_uses_the_codex_stop_context(tmp_path):
    t = tmp_path / "rollout.jsonl"
    t.write_text(header() + response("resp_a", 170000, 150000, 900, 3))
    run(ev("Stop", t), tmp_path)
    out = run({"hook_event_name": "UserPromptSubmit", "session_id": SID, "prompt": "hi"}, tmp_path, "prompt")
    assert "170k" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
