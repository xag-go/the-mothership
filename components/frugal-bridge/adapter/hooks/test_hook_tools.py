"""frugal_hook.py per tool: input shapes, the replace-output field each tool reads, once per event when a tool also
runs Claude Code's hooks, usage logging. Every run has its own HOME and FRUGAL_HOME."""
import json, os, subprocess, sys, shutil

import pytest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frugal_hook.py")
BIG = "\n".join(f"line {i}" + (" ERROR boom" if i == 500 else "") for i in range(3000))


def run(home, ev, *args):
    env = dict(os.environ, HOME=str(home), FRUGAL_HOME=str(home / ".fb"))
    for k in ("GEMINI_SESSION_ID", "GEMINI_PROJECT_DIR"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, HOOK, *args], input=json.dumps(ev), capture_output=True, text=True, env=env,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def j(s):
    return json.loads(s) if s else None


def cut_ok(text):
    return "[frugal-bridge] output cut" in text and "ERROR boom" in text and "full output saved" in text


@pytest.mark.parametrize("tool,ev,get", [
    ("claude-code", {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "a",
                     "tool_response": {"stdout": BIG, "stderr": "", "interrupted": False, "isImage": False}},
     lambda o: o["hookSpecificOutput"]["updatedToolOutput"]["stdout"]),
    ("junie", {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "a", "tool_response": BIG},
     lambda o: o["hookSpecificOutput"]["updatedToolOutput"]),
    ("copilot", {"sessionId": "a", "toolName": "bash", "toolResult": {"resultType": "success", "textResultForLlm": BIG}},
     lambda o: o["modifiedResult"]["textResultForLlm"]),
    ("crush", {"hook_event_name": "PostToolUse", "tool_name": "bash", "session_id": "a", "tool_response": BIG},
     lambda o: o["updated_output"]),
    ("gemini", {"hook_event_name": "AfterTool", "tool_name": "run_shell_command", "session_id": "a",
                "tool_response": {"llmContent": BIG, "returnDisplay": BIG}}, lambda o: o["reason"]),
    ("codex", {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "a", "tool_response": BIG},
     lambda o: o["reason"]),
])
def test_output_filter_in_each_tools_field(tool, ev, get, tmp_path):
    o = j(run(tmp_path, ev, "--tool", tool, "--event", "post_tool"))
    assert cut_ok(get(o))
    if tool == "gemini":
        assert o["decision"] == "deny"
    if tool == "codex":
        assert o["decision"] == "block"


def test_small_or_non_shell_output_untouched(tmp_path):
    assert run(tmp_path, {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s",
                          "tool_response": {"stdout": "ok"}}, "--tool", "claude-code") == ""
    assert run(tmp_path, {"hook_event_name": "PostToolUse", "tool_name": "Read", "session_id": "s",
                          "tool_response": BIG}, "--tool", "junie", "--event", "post_tool") == ""


def start_env(tmp_path):
    (tmp_path / "USER.md").write_text("u"); (tmp_path / "PROGRESS.md").write_text("p")


@pytest.mark.parametrize("tool,parse", [
    ("codex", lambda s: json.loads(s)["hookSpecificOutput"]["additionalContext"]),
    ("copilot", lambda s: json.loads(s)["additionalContext"]),
    ("cursor", lambda s: json.loads(s)["additional_context"]),
    ("kiro", lambda s: s),
    ("cline", lambda s: json.loads(s)["contextModification"]),
])
def test_start_files_in_each_tools_shape(tool, parse, tmp_path):
    start_env(tmp_path)
    ev = {"cwd": str(tmp_path), "session_id": "x"} if tool != "cline" else {"clineVersion": "4", "workspaceRoots": [str(tmp_path)], "taskId": "t"}
    if tool == "cursor":
        ev["cursor_version"] = "3"
    out = parse(run(tmp_path, ev, "--tool", tool, "--event", "start"))
    assert "PROGRESS.md" in out and "USER.md" in out
    if tool == "cline":
        assert json.loads(run(tmp_path, dict(ev, taskId="u"), "--tool", tool, "--event", "start"))["cancel"] is False


def test_cursor_start_brings_the_rules(tmp_path):
    (tmp_path / ".fb").mkdir(); (tmp_path / ".fb" / "RULES.md").write_text("<!-- frugal-bridge:start v6 -->\nRULES\n")
    out = json.loads(run(tmp_path, {"cursor_version": "3", "conversation_id": "c", "workspace_roots": [str(tmp_path)]},
                         "--tool", "cursor", "--event", "start"))["additional_context"]
    assert out.startswith("<!-- frugal-bridge:start")


def test_claude_entry_stands_down_when_the_tool_has_its_own(tmp_path):
    start_env(tmp_path)
    (tmp_path / ".fb").mkdir(); (tmp_path / ".fb" / "global.json").write_text(json.dumps({"native_hooks": ["cursor"]}))
    ev = {"hook_event_name": "SessionStart", "cursor_version": "3", "conversation_id": "c", "cwd": str(tmp_path)}
    assert run(tmp_path, ev) == ""                                         # Claude-settings entry, run by Cursor
    assert "additional_context" in run(tmp_path, ev, "--tool", "cursor", "--event", "start")


def test_same_event_twice_runs_once(tmp_path):
    start_env(tmp_path)
    ev = {"hook_event_name": "SessionStart", "session_id": "dup", "cwd": str(tmp_path)}
    assert run(tmp_path, ev, "--tool", "claude-code") != ""
    assert run(tmp_path, ev, "--tool", "devin") == ""                      # the second entry for the same event
    assert run(tmp_path, dict(ev, session_id="other"), "--tool", "devin") != ""


def test_codex_usage_logged_and_drives_context_watch(tmp_path):
    ev = {"hook_event_name": "PostModelRequest", "session_id": "cx", "model": "gpt-6.1-sol", "status": "completed",
          "token_usage": {"input_tokens": 170000, "cached_input_tokens": 150000, "output_tokens": 900}}
    assert run(tmp_path, ev, "--tool", "codex", "--event", "usage") == ""
    rec = json.loads((tmp_path / ".fb" / "usage.jsonl").read_text().splitlines()[0])
    assert (rec["tool"], rec["model"], rec["input"], rec["cache_read"], rec["output"], rec["context"]) == \
        ("codex", "gpt-6.1-sol", 20000, 150000, 900, 170000)
    o = json.loads(run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "cx", "prompt": "hi"},
                       "--tool", "codex", "--event", "prompt"))
    assert "170k" in o["hookSpecificOutput"]["additionalContext"]


def test_claude_stop_logs_each_message_once(tmp_path):
    t = tmp_path / "t.jsonl"
    msg = lambda i: json.dumps({"type": "assistant", "message": {"id": f"m{i}", "model": "claude-opus-5-5", "usage": {
        "input_tokens": 3, "cache_read_input_tokens": 1000 * i, "cache_creation_input_tokens": 10, "output_tokens": 7}}})
    t.write_text(msg(1) + "\n" + msg(1) + "\n" + msg(2) + "\n")         # same message split over two lines
    ev = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": str(t)}
    run(tmp_path, ev)
    with open(t, "a") as f:
        f.write(msg(3) + "\n")
    run(tmp_path, ev)
    recs = [json.loads(x) for x in (tmp_path / ".fb" / "usage.jsonl").read_text().splitlines()]
    assert [r["cache_read"] for r in recs] == [1000, 2000, 3000] and all(r["tool"] == "claude-code" for r in recs)


def test_cursor_precompact_context_logged(tmp_path):
    run(tmp_path, {"hook_event_name": "preCompact", "conversation_id": "c", "model": "m", "cursor_version": "3",
                   "context_tokens": 123456, "context_window_size": 200000}, "--tool", "cursor", "--event", "precompact")
    rec = json.loads((tmp_path / ".fb" / "usage.jsonl").read_text())
    assert rec["context"] == 123456 and rec["tool"] == "cursor"


def test_garbage_input_never_fails(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), FRUGAL_HOME=str(tmp_path / ".fb"))
    r = subprocess.run([sys.executable, HOOK, "--tool", "codex"], input="not json", capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""


# ------------------------------------------------------------------ JS plugins (node, when present)
NODE = shutil.which("node")
JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin-js")


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_js_plugins_filter_v1_v2_amp(tmp_path):
    for f in ("frugal-bridge.js", "amp.js"):
        src = open(os.path.join(JS, f)).read().replace("__FRUGAL_HOOK__", HOOK).replace(
            "__FRUGAL_HOME__", str(tmp_path / "fb")).replace("__FRUGAL_TOOL__", "opencode")
        (tmp_path / f.replace(".js", ".mjs")).write_text(src)
    start_env(tmp_path)
    big = json.dumps(BIG)
    test = f"""
import oc from "./frugal-bridge.mjs"
import amp from "./amp.mjs"
const out = {{}}
const h = await oc.server({{ directory: {json.dumps(str(tmp_path))} }})
const o1 = {{ output: {big} }}; await h["tool.execute.after"]({{ tool: "bash" }}, o1); out.v1 = o1.output.includes("output cut")
const o2 = {{ output: {big} }}; await h["tool.execute.after"]({{ tool: "read" }}, o2); out.v1read = o2.output.length
const sys1 = {{ system: [] }}; await h["experimental.chat.system.transform"]({{ sessionID: "s" }}, sys1); out.hint = sys1.system.join(" ")
await h.event({{ event: {{ type: "message.updated", properties: {{ info: {{ id: "m", role: "assistant", sessionID: "s", modelID: "claude-haiku-5-5",
  time: {{ completed: 1 }}, tokens: {{ input: 5, output: 6, reasoning: 1, cache: {{ read: 100, write: 2 }} }} }} }} }} }})
const hooks = {{}}
await oc.setup({{ tool: {{ hook: async (n, cb) => {{ hooks["tool." + n] = cb }} }}, session: {{ hook: async (n, cb) => {{ hooks["s." + n] = cb }} }}, location: {{ directory: {json.dumps(str(tmp_path))} }} }})
const ev = {{ status: "completed", tool: "bash", result: {{ output: {big}, title: "t" }} }}; hooks["tool.execute.after"](ev); out.v2 = ev.result.output.includes("output cut") && ev.result.title === "t"
const handlers = {{}}; amp({{ on: (n, cb) => {{ handlers[n] = cb }} }})
const r = await handlers["tool.result"]({{ tool: "Bash", status: "done", output: {big} }}); out.amp = r.output.includes("output cut")
out.ampSmall = await handlers["tool.result"]({{ tool: "Bash", status: "done", output: "ok" }})
console.log(JSON.stringify(out))
"""
    (tmp_path / "t.mjs").write_text(test)
    r = subprocess.run([NODE, str(tmp_path / "t.mjs")], capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
                       env=dict(os.environ, HOME=str(tmp_path), FRUGAL_HOME=str(tmp_path / "fb")))
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["v1"] and o["v2"] and o["amp"] and o["v1read"] == len(BIG) and o.get("ampSmall") is None
    assert "PROGRESS.md" in o["hint"]
    rec = json.loads((tmp_path / "fb" / "usage.jsonl").read_text())
    assert (rec["tool"], rec["context"], rec["cache_read"], rec["output"]) == ("opencode", 107, 100, 7)
