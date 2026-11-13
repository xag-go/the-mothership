"""End-to-end tests for frugal_proxy: a fake upstream server + the real proxy over HTTP."""
import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
import frugal_proxy as fp  # noqa: E402

SEEN = []          # bodies + headers the fake upstream received
USAGE = {"ctx": 1000}


class Fake(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n))
        SEEN.append({"path": self.path, "body": body, "headers": dict(self.headers)})
        ctx = USAGE["ctx"]
        stream = body.get("stream")
        if self.path.endswith("/messages"):
            if stream:
                ev = [{"type": "message_start", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": ctx - 10, "output_tokens": 1}}},
                      {"type": "content_block_delta", "delta": {"text": "hi"}},
                      {"type": "message_delta", "usage": {"output_tokens": 7}}]
                out = "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in ev).encode()
                ctype = "text/event-stream"
            else:
                out = json.dumps({"type": "message", "content": [{"type": "text", "text": "hi"}],
                                  "usage": {"input_tokens": ctx, "output_tokens": 5}}).encode()
                ctype = "application/json"
        elif self.path.endswith("/chat/completions"):
            ev = [{"choices": [{"delta": {"content": "hi"}}]},
                  {"choices": [], "usage": {"prompt_tokens": ctx, "completion_tokens": 3}}]
            out = ("".join(f"data: {json.dumps(e)}\n\n" for e in ev) + "data: [DONE]\n\n").encode()
            ctype = "text/event-stream"
        else:
            ev = [{"type": "response.output_text.delta", "delta": "hi"},
                  {"type": "response.completed", "response": {"usage": {"input_tokens": ctx, "output_tokens": 4,
                                                                        "input_tokens_details": {"cached_tokens": ctx - 5}}}}]
            out = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in ev).encode()
            ctype = "text/event-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def start(server_cls, handler):
    s = server_cls(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


TMP = tempfile.mkdtemp(prefix="fbproxy-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)  # the module-level dir must not outlive the run
UP = start(ThreadingHTTPServer, Fake)
cfgp = os.path.join(TMP, "proxy.json")
json.dump({"port": 0, "data_dir": os.path.join(TMP, "data"), "ctx_warn": 150000, "ctx_hard": 300000,
           "upstreams": {"fake": f"http://127.0.0.1:{UP.server_address[1]}/base"}}, open(cfgp, "w"))
fp.load_config(cfgp)
PX = start(ThreadingHTTPServer, fp.Handler)
URL = f"http://127.0.0.1:{PX.server_address[1]}/fake"


def post(path, body, headers=None):
    h = {"Content-Type": "application/json", "x-api-key": "SECRET-KEY", **(headers or {})}
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(), headers=h, method="POST")
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


def last_text_anthropic(body):
    c = body["messages"][-1]["content"]
    return c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict))


def reset():
    SEEN.clear(); fp._STATE.clear(); USAGE["ctx"] = 1000


# ------------------------------------------------------------------ tests

def test_passthrough_unchanged_below_threshold():
    reset()
    body = {"model": "claude-opus", "max_tokens": 10, "messages": [{"role": "user", "content": "hello A"}]}
    st, out = post("/v1/messages", body)
    assert st == 200 and b"hi" in out
    got = SEEN[-1]
    assert got["path"] == "/base/v1/messages"            # route prefix replaced by upstream base path
    assert got["body"] == body                            # nothing changed
    assert {k.lower(): v for k, v in got["headers"].items()}.get("x-api-key") == "SECRET-KEY"  # key passed through


def test_anthropic_warn_once_then_hard():
    reset()
    msgs = [{"role": "user", "content": "task B"}]
    USAGE["ctx"] = 160000
    post("/v1/messages", {"model": "claude-opus", "stream": True, "messages": msgs})     # learns ctx=160k
    assert "[frugal-bridge]" not in last_text_anthropic(SEEN[-1]["body"])
    msgs2 = msgs + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}]
    post("/v1/messages", {"model": "claude-opus", "stream": True, "messages": msgs2})
    t = last_text_anthropic(SEEN[-1]["body"])
    assert "160k" in t and "new session with handoff" in t
    msgs3 = msgs2 + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "more"}]
    post("/v1/messages", {"model": "claude-opus", "stream": True, "messages": msgs3})
    assert "[frugal-bridge]" not in last_text_anthropic(SEEN[-1]["body"])  # only once
    USAGE["ctx"] = 310000
    post("/v1/messages", {"model": "claude-opus", "stream": True, "messages": msgs3})
    post("/v1/messages", {"model": "claude-opus", "stream": True, "messages": msgs3})
    assert "new session is needed" in last_text_anthropic(SEEN[-1]["body"])


def test_cheap_model_lower_threshold():
    reset()
    USAGE["ctx"] = 110000
    m = [{"role": "user", "content": "cheap C"}]
    post("/v1/messages", {"model": "claude-haiku-4-5", "messages": m})
    post("/v1/messages", {"model": "claude-haiku-4-5", "messages": m + [{"role": "assistant", "content": "a"}, {"role": "user", "content": "b"}]})
    assert "110k" in last_text_anthropic(SEEN[-1]["body"])


def test_no_notice_on_tool_turn_only_user_turn():
    reset()
    USAGE["ctx"] = 200000
    base = [{"role": "user", "content": "task D"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "ls", "input": {"p": "/"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a b"}]}]
    post("/v1/messages", {"model": "opus", "messages": base})
    post("/v1/messages", {"model": "opus", "messages": base})
    assert "k tokens" not in json.dumps(SEEN[-1]["body"])   # deferred
    post("/v1/messages", {"model": "opus", "messages": base + [{"role": "assistant", "content": "done"}, {"role": "user", "content": "thanks"}]})
    assert "200k tokens" in last_text_anthropic(SEEN[-1]["body"])


def test_loop_guard_anthropic():
    reset()
    call = lambda i: {"role": "assistant", "content": [{"type": "tool_use", "id": i, "name": "bash", "input": {"cmd": "make"}}]}
    res = lambda i: {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": "error: no rule"}]}
    m = [{"role": "user", "content": "build E"}, call("a"), res("a")]
    post("/v1/messages", {"model": "opus", "messages": m})
    assert "same tool call" not in json.dumps(SEEN[-1]["body"])
    m += [call("b"), res("b")]
    post("/v1/messages", {"model": "opus", "messages": m})
    assert "same tool call" in json.dumps(SEEN[-1]["body"]["messages"][-1])
    post("/v1/messages", {"model": "opus", "messages": m})
    assert "same tool call" not in json.dumps(SEEN[-1]["body"])  # once per signature


def test_loop_guard_not_triggered_when_result_differs():
    reset()
    m = [{"role": "user", "content": "F"},
         {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "cat", "input": {"f": "x"}}]},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "v1"}]},
         {"role": "assistant", "content": [{"type": "tool_use", "id": "b", "name": "cat", "input": {"f": "x"}}]},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b", "content": "v2"}]}]
    post("/v1/messages", {"model": "opus", "messages": m})
    assert "same tool call" not in json.dumps(SEEN[-1]["body"])


def test_output_filter_deterministic_and_saved():
    reset()
    big = "\n".join(f"line {i}" + (" ERROR boom" if i == 500 else "") for i in range(3000))
    m = [{"role": "user", "content": "G"},
         {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "bash", "input": {}}]},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": big}]}]
    post("/v1/messages", {"model": "opus", "messages": m})
    c1 = SEEN[-1]["body"]["messages"][2]["content"][0]["content"]
    post("/v1/messages", {"model": "opus", "messages": m})
    c2 = SEEN[-1]["body"]["messages"][2]["content"][0]["content"]
    assert c1 == c2 and len(c1) < 12000 and "ERROR boom" in c1 and "output cut" in c1
    path = c1.split("[full output saved: ")[1].split(" ")[0]
    assert open(path).read() == big


def test_openai_chat_stream_usage_and_notice():
    reset()
    USAGE["ctx"] = 170000
    m = [{"role": "system", "content": "sys"}, {"role": "user", "content": "H"}]
    post("/v1/chat/completions", {"model": "gpt-5", "stream": True, "messages": m})
    assert SEEN[-1]["body"]["stream_options"]["include_usage"] is True
    m2 = m + [{"role": "assistant", "content": "x"}, {"role": "user", "content": "go"}]
    post("/v1/chat/completions", {"model": "gpt-5", "stream": True, "messages": m2})
    assert "170k tokens" in SEEN[-1]["body"]["messages"][-1]["content"]


def test_openai_chat_loop_guard_appends_user_after_tool():
    reset()
    tc = lambda i: {"role": "assistant", "content": None, "tool_calls": [{"id": i, "type": "function", "function": {"name": "f", "arguments": "{}"}}]}
    tr = lambda i: {"role": "tool", "tool_call_id": i, "content": "same"}
    m = [{"role": "user", "content": "I"}, tc("a"), tr("a"), tc("b"), tr("b")]
    post("/v1/chat/completions", {"model": "gpt-5", "messages": m})
    last = SEEN[-1]["body"]["messages"][-1]
    assert last["role"] == "user" and "same tool call" in last["content"]


def test_responses_api_codex_style():
    reset()
    USAGE["ctx"] = 155000
    inp = [{"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "dev"}]},
           {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "J"}]}]
    post("/responses", {"model": "gpt-5.5", "stream": True, "prompt_cache_key": "conv-J", "input": inp})
    inp2 = inp + [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "x"}]},
                  {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "again"}]}]
    post("/responses", {"model": "gpt-5.5", "stream": True, "prompt_cache_key": "conv-J", "input": inp2})
    last = SEEN[-1]["body"]["input"][-1]
    assert last["role"] == "user" and "155k tokens" in last["content"][0]["text"]
    assert len(SEEN[-1]["body"]["input"]) == len(inp2) + 1   # appended at the end, prefix untouched
    assert SEEN[-1]["body"]["input"][:len(inp2)] == inp2


def test_responses_loop_and_filter():
    reset()
    fc = lambda i: {"type": "function_call", "name": "shell", "arguments": '{"cmd":"x"}', "call_id": i}
    fo = lambda i, o: {"type": "function_call_output", "call_id": i, "output": o}
    big = "y" * 50000
    inp = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "K"}]}, fc("1"), fo("1", big), fc("2"), fo("2", big)]
    post("/responses", {"model": "gpt-5.5", "input": inp})
    b = SEEN[-1]["body"]["input"]
    assert "output cut" in b[2]["output"] and b[2]["output"] == b[4]["output"]
    assert "same tool call" in b[-1]["content"][0]["text"]


def test_start_files_from_kits_json():
    reset()
    pd = os.path.join(TMP, "proj"); os.makedirs(pd, exist_ok=True)
    open(os.path.join(pd, "hot.md"), "w").write("now")
    os.makedirs(os.path.join(pd, "wiki/me"), exist_ok=True)
    open(os.path.join(pd, "wiki/me/README.md"), "w").write("me")
    json.dump({"slots": {"now": "hot.md", "user": "wiki/me/README.md"}}, open(os.path.join(pd, ".kits.json"), "w"))
    fp.CFG["project_dir"] = pd
    try:
        post("/v1/messages", {"model": "opus", "messages": [{"role": "user", "content": "L"}]})
        t = last_text_anthropic(SEEN[-1]["body"])
        assert "hot.md" in t and "wiki/me/README.md" in t
    finally:
        fp.CFG["project_dir"] = ""


def test_core_file_added_once():
    reset()
    core = os.path.join(TMP, "core.md")
    open(core, "w").write("<!-- frugal-bridge:start v6 -->\nRULES\n<!-- frugal-bridge:end -->")
    fp.CFG["core_file"] = core
    try:
        post("/v1/messages", {"model": "opus", "system": "host sys", "messages": [{"role": "user", "content": "M"}]})
        s = SEEN[-1]["body"]["system"]
        assert s.startswith("host sys") and "RULES" in s
        post("/v1/messages", {"model": "opus", "system": s, "messages": [{"role": "user", "content": "M"}]})
        assert SEEN[-1]["body"]["system"].count("RULES") == 1
    finally:
        fp.CFG["core_file"] = ""


def test_non_json_and_unknown_route():
    reset()
    req = urllib.request.Request(URL + "/v1/messages", data=b"not json", headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req)
    except Exception:
        pass
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PX.server_address[1]}/nope/x")
        assert False
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_usage_log_and_report():
    rep = urllib.request.urlopen(f"http://127.0.0.1:{PX.server_address[1]}/frugal/report").read().decode()
    assert "claude-opus" in rep and "Rules applied" in rep and "notice" in rep
    log = open(os.path.join(TMP, "data", "usage.jsonl")).read()
    assert "SECRET-KEY" not in log


def test_filter_skips_file_reads():
    reset()
    big = "\n".join(f"line {i}" for i in range(3000))
    m = [{"role": "user", "content": "N"},
         {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "Read", "input": {"f": "x"}}]},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": big}]}]
    post("/v1/messages", {"model": "opus", "messages": m})
    assert SEEN[-1]["body"]["messages"][2]["content"][0]["content"] == big


def test_loop_guard_ignores_description_field():
    reset()
    c = lambda i, d: {"role": "assistant", "content": [{"type": "tool_use", "id": i, "name": "Bash", "input": {"command": "cat x", "description": d}}]}
    r = lambda i: {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": "cat: x: No such file"}]}
    m = [{"role": "user", "content": "O"}, c("a", "Read x"), r("a"), c("b", "Read x (retry)"), r("b")]
    post("/v1/messages", {"model": "opus", "messages": m})
    assert "same tool call" in json.dumps(SEEN[-1]["body"]["messages"][-1])


def test_loop_guard_same_error_different_calls():
    reset()
    c = lambda i, f: {"role": "assistant", "content": [{"type": "tool_use", "id": i, "name": "Bash", "input": {"command": f}}]}
    r = lambda i: {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": "Error: permission denied"}]}
    m = [{"role": "user", "content": "P"}, c("a", "rm a"), r("a"), c("b", "rm b"), r("b")]
    post("/v1/messages", {"model": "opus", "messages": m})
    assert "failed with the same error" in json.dumps(SEEN[-1]["body"]["messages"][-1])
