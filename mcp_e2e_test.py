import subprocess, json, sys
W = "/home/agt7shpm0/selfearner-agents/agt_b52b99f149c4/testlens"
p = subprocess.Popen(["python3", "mcp_server.py"], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, cwd=W)
def send_noreply(msg):
    p.stdin.write((json.dumps(msg) + "\n").encode()); p.stdin.flush()

def send(msg):
    p.stdin.write((json.dumps(msg) + "\n").encode()); p.stdin.flush()
    return json.loads(p.stdout.readline().decode())

r = send({"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
print("init:", r["result"]["serverInfo"])
send_noreply({"method": "notifications/initialized"})
r = send({"id": 2, "method": "tools/list"})
print("tools:", [t["name"] for t in r["result"]["tools"]])
r = send({"id": 3, "method": "tools/call", "params": {"name": "testlens_health", "arguments": {}}})
print("health:", r["result"]["content"][0]["text"])

code = "def clamp(x, lo, hi):\n    return max(lo, min(x, hi))"
tests = ("import unittest, solution\n"
         "class T(unittest.TestCase):\n"
         "    def test_in(self):\n"
         "        self.assertEqual(solution.clamp(5, 0, 10), 5)\n"
         "    def test_lo(self):\n"
         "        self.assertEqual(solution.clamp(-3, 0, 10), 0)\n"
         "    def test_hi(self):\n"
         "        self.assertEqual(solution.clamp(99, 0, 10), 10)")
r = send({"id": 4, "method": "tools/call", "params": {"name": "testlens_mutate",
         "arguments": {"code": code, "tests": tests}}})
out = json.loads(r["result"]["content"][0]["text"])
print("mutate:", out.get("status"), "|", out.get("verdict"),
      "| score", out.get("mutation_score"),
      "| killed", str(out.get("killed")) + "/" + str(out.get("mutants_total")))
p.stdin.close(); p.wait()
print("DONE")
