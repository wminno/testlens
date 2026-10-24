#!/usr/bin/env python3
"""TestLens MCP server (stdio, JSON-RPC 2.0).

Exposes the TestLens mutation-testing API as MCP tools:
  - testlens_mutate: run your tests against auto-generated mutants of your code
  - testlens_health: check the API is up

TestLens is free, no key, fair use (a few runs/hour per IP, <=24 mutants,
2.5s per run). This wrapper only talks to https://testlens.bigfloppy.net.

Run:  python3 mcp_server.py   (stdio transport)
"""
import json
import sys
import urllib.request

API = "https://testlens.bigfloppy.net"
SERVER_INFO = {"name": "testlens-mcp", "version": "1.0.0"}

TOOLS = [
    {
        "name": "testlens_mutate",
        "description": (
            "Mutation-test Python code: POSTs your code + unittest tests to TestLens, "
            "which generates small mutants (operators, comparisons, constants) and reports "
            "which ones your tests catch. Returns verdict (strong/weak), mutation_score "
            "0-100, and survivors - each survivor is a behaviour change your tests miss. "
            "code is saved as solution.py; tests must 'import solution' and use unittest. "
            "Free API, no key; fair use a few runs/hour per IP."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to test (saved as solution.py)"},
                "tests": {"type": "string", "description": "unittest tests that 'import solution'"},
            },
            "required": ["code", "tests"],
        },
    },
    {
        "name": "testlens_health",
        "description": "Check the TestLens API is up. Returns {ok: true, service: 'testlens'}.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _post(path, payload, timeout=120):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(path, timeout=15):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def call_tool(name, args):
    if name == "testlens_mutate":
        code, tests = args.get("code"), args.get("tests")
        if not isinstance(code, str) or not isinstance(tests, str):
            return {"isError": True, "content": [{"type": "text", "text": "need string 'code' and string 'tests'"}]}
        try:
            out = _post("/api/mutate", {"code": code, "tests": tests})
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": "TestLens API error: %r" % (e,)}]}
        return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}
    if name == "testlens_health":
        try:
            out = _get("/api/health")
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": "TestLens API error: %r" % (e,)}]}
        return {"content": [{"type": "text", "text": json.dumps(out)}]}
    return {"isError": True, "content": [{"type": "text", "text": "unknown tool: " + name}]}


def dispatch(msg):
    method = msg.get("method", "")
    mid = msg.get("id")
    if method == "initialize":
        return {"id": mid, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }}
    if method == "ping":
        return {"id": mid, "result": {}}
    if method == "tools/list":
        return {"id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        p = msg.get("params", {})
        return {"id": mid, "result": call_tool(p.get("name", ""), p.get("arguments") or {})}
    if method.startswith("notifications/"):
        return None
    if mid is not None:
        return {"id": mid, "error": {"code": -32601, "message": "method not found: " + method}}
    return None


def main():
    reader = sys.stdin.buffer
    while True:
        line = reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            out = dispatch(msg)
        except Exception as e:
            out = {"id": msg.get("id"), "error": {"code": -32603, "message": "internal error: %r" % (e,)}}
        if out is not None:
            # newline-delimited JSON (framing used by current stdio MCP clients)
            body = json.dumps(out).encode()
            sys.stdout.buffer.write(body + b"\n")
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
