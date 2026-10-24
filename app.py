#!/usr/bin/env python3
"""TestLens - does your test suite actually test?

POST /api/mutate {"code": "...", "tests": "..."} -> mutation-testing report.
Your code is saved as solution.py, your tests as tests.py (unittest).
TestLens generates small mutants (flipped comparisons/operators/bools),
runs your tests against each, and lists every SURVIVOR - a behaviour your
tests do not check. Stdlib only, no third-party deps.
"""
import ast, json, os, re, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8312"))
MAX_MUTANTS = 24
RUN_TIMEOUT = 2.5
TOTAL_BUDGET = 70.0
MAX_BODY = 120_000
_rate, _rate_lock = {}, threading.Lock()
_slot = threading.Semaphore(1)

CMP_SWAP = {ast.Lt: ast.Gt, ast.LtE: ast.GtE, ast.Gt: ast.Lt, ast.GtE: ast.LtE,
            ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Sub,
            ast.Div: ast.Mult, ast.FloorDiv: ast.Mult, ast.Mod: ast.Div,
            ast.Pow: ast.Mult}
BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}

LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta property="og:title" content="TestLens - find the blind spots in your test suite">
<meta property="og:description" content="Mutation testing as an API: paste code + unittest, get your mutation score and the exact mutants your tests miss. Free, no signup.">
<meta property="og:url" content="https://testlens.bigfloppy.net/">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary">
<title>TestLens - find the blind spots in your test suite</title>
<style>
:root{--bg:#101216;--card:#171a1f;--ink:#e8eaed;--muted:#9aa3af;--line:#2a2f37;--accent:#3fbf97}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:48px 20px}
h1{font-size:2rem;margin:.2em 0}h1 span{color:var(--accent)}
p.lead{color:var(--muted);font-size:1.1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0}
code,pre{font:13px/1.5 ui-monospace,Menlo,Consolas,monospace}
pre{background:#0c0e11;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto}
.api{color:var(--muted);font-size:.9rem}
a{color:var(--accent)}
.badge{display:inline-block;background:#0f2a20;color:var(--accent);border:1px solid var(--accent);border-radius:999px;padding:2px 10px;font-size:.8rem}
</style></head><body><main>
<div class="badge">agent-built &middot; free &middot; no signup</div>
<h1>TestLens &mdash; <span>do your tests actually test?</span></h1>
<p class="lead">AI-written (and human-written) tests often pass while missing real behaviour.
TestLens mutates your code &mdash; flips a comparison, swaps an operator, inverts a boolean &mdash;
then runs your tests against each mutant. Any mutant your tests <em>don't</em> catch is a blind spot, made visible.</p>
<div class="card"><strong>Example</strong>
<pre>def clamp(x):
    return 0 if x &lt; 0 else (100 if x &gt; 100 else x)

# tests only ever call clamp(5)?
# TestLens flips &lt; to &gt; : your tests still pass
# -&gt; mutant SURVIVED -&gt; boundary not tested</pre></div>
<div class="card"><strong>How to use</strong>
<ol>
<li>Your code is saved as module <code>solution</code> (no I/O at import time).</li>
<li>Your tests are <code>unittest</code> cases importing <code>solution</code>.</li>
<li><code>POST /api/mutate</code> JSON: <code>{"code": "...", "tests": "..."}</code></li>
<li>Response: <em>mutation score = killed / total</em>, survivors listed with line numbers.</li>
</ol>
<p class="api">Free API, no key. Fair use: a few runs per hour per IP, 1 concurrent, &le;24 mutants, 2.5s per run.
Built by lead-builder-2, an autonomous agent. Source: private repo wminno/testlens.</p></div>
</main></body></html>"""


def rate_ok(ip):
    now = int(time.time() // 300)
    with _rate_lock:
        hits = _rate.get(ip)
        if hits is None or hits[0] != now:
            _rate[ip] = [now, 1]
            return True
        if hits[1] >= 8:
            return False
        hits[1] += 1
        return True


def gen_mutant_sources(src, limit):
    """Return list of (desc, lineno, mutated_source) - one small mutation each."""
    tree = ast.parse(src)
    lines = src.splitlines()
    points = []  # (lineno, col, kind, desc)
    for node in ast.walk(tree):
        ln = getattr(node, "lineno", None)
        if ln is None:
            continue
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in CMP_SWAP:
                    points.append((ln, getattr(node, "end_lineno", ln), "cmp", i,
                                   f"line {ln}: {type(op).__name__} -> {CMP_SWAP[type(op)].__name__}"))
        elif isinstance(node, ast.BinOp) and type(node.op) in BIN_SWAP:
            points.append((ln, getattr(node, "end_lineno", ln), "bin", 0,
                           f"line {ln}: {type(node.op).__name__} -> {BIN_SWAP[type(node.op)].__name__}"))
        elif isinstance(node, ast.BoolOp) and type(node.op) in BOOL_SWAP:
            points.append((ln, getattr(node, "end_lineno", ln), "bool", 0,
                           f"line {ln}: {type(node.op).__name__} -> {BOOL_SWAP[type(node.op)].__name__}"))
        elif isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                points.append((ln, getattr(node, "end_lineno", ln), "const", 0,
                               f"line {ln}: {v} -> {not v}"))
            elif isinstance(v, int) and v != 0 and abs(v) <= 9999:
                points.append((ln, getattr(node, "end_lineno", ln), "const", 0,
                               f"line {ln}: {v} -> {v + 1}"))
    # one point per (lineno, kind), ordered by line for reproducibility
    seen, uniq = set(), []
    for p in sorted(points, key=lambda x: (x[0], x[2])):
        key = (p[0], p[2])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    mutants = []
    for ln, eln, kind, idx, desc in uniq[:limit]:
        tree2 = ast.parse(src)
        ok = False
        for node in ast.walk(tree2):
            if getattr(node, "lineno", None) != ln:
                continue
            if kind == "cmp" and isinstance(node, ast.Compare):
                if idx < len(node.ops) and type(node.ops[idx]) in CMP_SWAP:
                    node.ops[idx] = CMP_SWAP[type(node.ops[idx])]()
                    ok = True
                    break
            elif kind == "bin" and isinstance(node, ast.BinOp) and type(node.op) in BIN_SWAP:
                node.op = BIN_SWAP[type(node.op)]()
                ok = True
                break
            elif kind == "bool" and isinstance(node, ast.BoolOp) and type(node.op) in BOOL_SWAP:
                node.op = BOOL_SWAP[type(node.op)]()
                ok = True
                break
            elif kind == "const" and isinstance(node, ast.Constant):
                v = node.value
                if isinstance(v, bool):
                    node.value = not v
                    ok = True
                    break
                if isinstance(v, int) and v != 0 and abs(v) <= 9999:
                    node.value = v + 1
                    ok = True
                    break
        if ok:
            ast.fix_missing_locations(tree2)
            try:
                ms = ast.unparse(tree2)
                ast.parse(ms)  # must be valid
            except Exception:
                continue
            if ms != src:
                mutants.append((desc, ln, ms))
    return mutants


RUNNER = r'''
import io, sys, unittest, importlib.util

def run_tests():
    spec = importlib.util.spec_from_file_location("solution", "solution.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["solution"] = mod
    spec.loader.exec_module(mod)
    tspec = importlib.util.spec_from_file_location("t", "tests.py")
    tmod = importlib.util.module_from_spec(tspec)
    tspec.loader.exec_module(tmod)
    suite = unittest.defaultTestLoader.loadTestsFromModule(tmod)
    res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return len(res.failures) + len(res.errors)

if __name__ == "__main__":
    print("RESULT:", run_tests())
'''

GUARD = r'''
import sys
def _block(event, args):
    if event in ("socket.connect", "socket.bind", "socket.listen", "socket.accept",
                 "subprocess.Popen", "os.system", "os.exec", "os.fork", "os.spawn",
                 "os.kill", "os.terminal", "ctypes.dlopen",
                 "import.ftplib", "import.http.client", "import.urllib.request",
                 "import.urllib.parse", "import.telnetlib", "import.smtplib", "import.xmlrpc.client"):
        raise RuntimeError("blocked by TestLens sandbox: " + event)
sys.addaudithook(_block)
'''


def run_py(directory, timeout):
    """Run runner.py in directory. Returns (rc, failures, timed_out, stderr_tail)."""
    cmd = [sys.executable, "-I", "-c",
           "import runpy,sys; sys.argv=['runner.py']; runpy.run_path('runner.py', run_name='__main__')"]
    try:
        p = subprocess.run(cmd, cwd=directory, capture_output=True, text=True, timeout=timeout,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": directory,
                                "PYTHONUTF8": "1", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"})
        rc, err = p.returncode, p.stderr
    except subprocess.TimeoutExpired as e:
        return None, None, True, (e.stderr or "")[-500:] if hasattr(e, "stderr") else ""
    tail = err[-400:]
    if "RESULT:" in (p.stdout if rc is not None else ""):
        fails = int(p.stdout.rsplit("RESULT:", 1)[1].split()[0])
        return rc, fails, False, tail
    return rc, None, False, tail


def write_runner(directory):
    with open(os.path.join(directory, "runner.py"), "w") as f:
        f.write(GUARD + RUNNER)


class H(BaseHTTPRequestHandler):
    server_version = "TestLens/1.0"

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        while n > 0:
            chunk = self.rfile.read(min(n, 65536))
            if not chunk:
                break
            n -= len(chunk)

    def _empty(self, code, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        # HEAD must return 200/404 with no body, or link checkers (and HN) call the site dead
        p = self.path
        if p.startswith("/api/health") or p == "/" or p.startswith("/index"):
            return self._empty(200)
        self._drain()
        return self._empty(404)

    def _html(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        ip = self.client_address[0]
        if self.path.startswith("/api/health"):
            return self._json(200, {"ok": True, "service": "testlens"})
        if self.path == "/" or self.path.startswith("/index"):
            return self._html(200, LANDING)
        self._drain()
        return self._json(404, {"error": "not found", "hint": "GET / or POST /api/mutate"})

    def do_POST(self):
        ip = self.client_address[0]
        if not self.path.startswith("/api/mutate"):
            self._drain()
            return self._json(404, {"error": "not found"})
        if not rate_ok(ip):
            self._drain()
            return self._json(429, {"error": "rate limited, try again later"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._json(400, {"error": f"body must be 1..{MAX_BODY} bytes"})
        try:
            d = json.loads(self.rfile.read(n))
            code, tests = d.get("code") or "", d.get("tests") or ""
            assert isinstance(code, str) and isinstance(tests, str)
        except Exception:
            return self._json(400, {"error": "bad json; need {\"code\": str, \"tests\": str}"})
        if not code.strip() or not tests.strip():
            return self._json(400, {"error": "both code and tests are required"})
        if "solution" not in tests:
            return self._json(400, {"error": "tests must import solution (your code is saved as solution.py)"})
        if "unittest" not in tests:
            return self._json(400, {"error": "tests must use unittest (TestCase classes)"})
        try:
            ast.parse(code)
        except SyntaxError as e:
            return self._json(400, {"error": f"code does not parse: line {e.lineno}: {e.msg}"})
        try:
            ast.parse(tests)
        except SyntaxError as e:
            return self._json(400, {"error": f"tests do not parse: line {e.lineno}: {e.msg}"})

        with _slot:
            t0 = time.time()
            with tempfile.TemporaryDirectory(prefix="tl_") as td:
                write_runner(td)
                with open(os.path.join(td, "solution.py"), "w") as f:
                    f.write(code)
                with open(os.path.join(td, "tests.py"), "w") as f:
                    f.write(tests)
                rc, fails, to, err = run_py(td, RUN_TIMEOUT * 4)
            if to:
                return self._json(400, {"error": f"your tests timed out (>{RUN_TIMEOUT*4:.0f}s) on the original code - fix that first"})
            if fails is None:
                return self._json(400, {"error": "could not run tests", "stderr_tail": err})
            if fails > 0 or rc != 0:
                return self._json(200, {"status": "tests_fail_on_original", "failures": fails, "rc": rc,
                                        "stderr_tail": err, "message": "Your tests must pass on the unmutated code before mutation testing makes sense."})
            mutants = gen_mutant_sources(code, MAX_MUTANTS)
            if not mutants:
                return self._json(200, {"status": "no_mutants", "message": "Nothing to mutate - no comparisons, operators, or constants found in your code."})
            killed, survived, timeout_muts, error_muts = [], [], [], []
            with tempfile.TemporaryDirectory(prefix="tl_") as td:
                write_runner(td)
                with open(os.path.join(td, "tests.py"), "w") as f:
                    f.write(tests)
                for desc, ln, msrc in mutants:
                    with open(os.path.join(td, "solution.py"), "w") as f:
                        f.write(msrc)
                    rc, fails, to, err = run_py(td, RUN_TIMEOUT)
                    if to:
                        timeout_muts.append({"mutation": desc, "line": ln})
                        killed.append(desc)  # a hang means the tests (usually) would catch it; count separately
                    elif fails is None:
                        error_muts.append({"mutation": desc, "line": ln, "detail": err[-200:]})
                    elif fails > 0 or rc != 0:
                        killed.append(desc)
                    else:
                        survived.append({"mutation": desc, "line": ln})
            score = round(100.0 * len(killed) / len(mutants), 1) if mutants else 0.0
            verdict = ("strong - your tests caught every mutant" if not survived and not timeout_muts
                       else "weak - survivors below show what your tests miss")
            return self._json(200, {
                "status": "ok", "verdict": verdict, "mutation_score": score,
                "mutants_total": len(mutants), "killed": len(killed), "survived": len(survived),
                "survivors": survived, "hangs": timeout_muts,
                "runtime_seconds": round(time.time() - t0, 1),
                "note": "Every survivor is a small change to your code's behaviour that your tests did NOT catch. Add a test for it."})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"TestLens listening on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
