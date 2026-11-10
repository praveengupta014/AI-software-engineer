"""Runs the real Anthropic SDK through AnthropicLLM against a local fake endpoint, to check
the request we send and that every response field we read actually exists on the SDK's
objects. The tool schemas are also checked against strict-mode rules."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.agents import AGENTS, tool_definitions
from app.llm import AnthropicLLM, check_key


def sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


TOOL_INPUT = {"path": "README.md"}
EVENTS = [
    {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 1, "cache_read_input_tokens": 80,
                  "cache_creation_input_tokens": 0}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": "Reading it."}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {
        "type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "input_json_delta", "partial_json": json.dumps(TOOL_INPUT)}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
     "usage": {"output_tokens": 42}},
    {"type": "message_stop"},
]


@pytest.fixture
def endpoint(monkeypatch):
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            captured["body"] = json.loads(self.rfile.read(size))
            captured["headers"] = dict(self.headers)
            captured["path"] = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("request-id", "req_abc")
            self.end_headers()
            self.wfile.write(sse(EVENTS))

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield captured
    server.shutdown()


def test_request_and_response_contract(endpoint):
    spec = AGENTS["coder"]
    turn = AnthropicLLM("test-key", "claude-opus-5-5").turn(
        agent="coder", system="SYS", messages=[{"role": "user", "content": "hi"}],
        tools=tool_definitions(spec), effort="high",
    )

    body = endpoint["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}
    assert body["fallbacks"] == "default"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert all(t["strict"] is True for t in body["tools"])
    assert "temperature" not in body and "tool_choice" not in body
    assert "server-side-fallback-2026-07-01" in endpoint["headers"]["anthropic-beta"]

    assert turn.stop_reason == "tool_use"
    assert turn.text == "Reading it."
    assert [(c.id, c.name, c.input) for c in turn.tool_calls] == [
        ("toolu_1", "read_file", TOOL_INPUT)
    ]
    assert (turn.input_tokens, turn.output_tokens, turn.cache_read_tokens) == (120, 42, 80)
    assert turn.request_id == "req_abc"
    assert turn.model == "claude-opus-5-5"
    assert turn.refusal == {}


def assert_strict(schema, where):
    if not isinstance(schema, dict):
        return
    assert "default" not in schema, f"{where}: strict schemas cannot use default"
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False, where
        assert set(schema.get("required", [])) == set(schema["properties"]), where
    for key, value in schema.items():
        if isinstance(value, dict):
            assert_strict(value, f"{where}.{key}")
            for sub_key, sub in value.items():
                assert_strict(sub, f"{where}.{key}.{sub_key}")


@pytest.mark.parametrize("agent", list(AGENTS))
def test_tool_schemas_meet_strict_rules(agent):
    for tool in tool_definitions(AGENTS[agent]):
        assert_strict(tool["input_schema"], f"{agent}.{tool['name']}")


def test_assistant_content_round_trips_into_the_next_request(endpoint):
    llm = AnthropicLLM("test-key", "claude-opus-5-5")
    tools = tool_definitions(AGENTS["coder"])
    first = llm.turn(agent="coder", system="S", tools=tools, effort="high",
                     messages=[{"role": "user", "content": "hi"}])
    llm.turn(
        agent="coder", system="S", tools=tools, effort="high",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": first.assistant_content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                          "content": "file", "is_error": False}]},
        ],
    )
    sent = endpoint["body"]["messages"][1]["content"]
    assert [b["type"] for b in sent] == ["text", "tool_use"]
    assert sent[1] == {"type": "tool_use", "id": "toolu_1", "name": "read_file",
                       "input": TOOL_INPUT}


@pytest.mark.parametrize("status, expected", [
    (200, None),
    (401, "Anthropic rejected this API key"),
    (404, "cannot use the model"),
    (500, "Anthropic returned an error (500)"),
])
def test_check_key_reports_each_outcome(monkeypatch, status, expected):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ok = {"id": "m", "type": "model", "display_name": "M",
                  "created_at": "2026-01-01T00:00:00Z"}
            err = {"type": "error", "error": {"type": "x", "message": "m"}}
            body = json.dumps(ok if status == 200 else err).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    problem = check_key("key", "claude-opus-5-5")
    server.shutdown()
    assert problem is None if expected is None else expected in problem
