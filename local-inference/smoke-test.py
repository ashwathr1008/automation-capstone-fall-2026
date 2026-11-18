"""Prove native tool calls work, without accessing research data."""
import argparse
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:18080"

def request(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18080)
    parser.add_argument('--model', default='qwen3.5-4b')
    parser.add_argument('--output', default='smoke-test.json')
    args = parser.parse_args()
    BASE = 'http://127.0.0.1:' + str(args.port)
    destination = (ROOT / args.output).resolve()
    if not destination.is_relative_to(ROOT):
        raise ValueError('Smoke report must stay in local-inference')
    print(request("/health"))
    model = request("/v1/models")
    body = {"model": args.model, "messages": [
        {"role": "system", "content": "Use the supplied lookup tool to answer the user. Do not invent the value."},
        {"role": "user", "content": "What is the stored value for sample DEMO-17?"}
    ], "tools": [{"type": "function", "function": {"name": "lookup_demo", "description": "Look up a fictional demo sample value.", "parameters": {"type": "object", "properties": {"sample_id": {"type": "string"}}, "required": ["sample_id"], "additionalProperties": False}}}], "temperature": 0.2, "max_tokens": 1024, "stream": False}
    started = time.monotonic()
    first = request("/v1/chat/completions", body)
    message = first["choices"][0]["message"]
    calls = message.get("tool_calls", [])
    assert len(calls) == 1, first
    function = calls[0]["function"]
    assert function["name"] == "lookup_demo", function
    assert json.loads(function["arguments"]) == {"sample_id": "DEMO-17"}, function
    body["messages"].extend([message, {"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps({"sample_id": "DEMO-17", "value": 42, "unit": "demo_units"})}])
    second = request("/v1/chat/completions", body)
    final = second["choices"][0]["message"]["content"]
    assert "42" in final, final
    report = {"passed": True, "elapsed_seconds": round(time.monotonic()-started, 3), "models": model, "first_response": first, "second_response": second}
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "elapsed_seconds": report["elapsed_seconds"], "tool": function, "answer": final}))
