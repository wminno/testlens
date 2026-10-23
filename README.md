# TestLens — does your test suite actually test?

Mutation-testing verifier for Python `unittest` suites, built by lead-builder-2 (autonomous agent).

**The problem:** tests written (by humans or AI) against an implementation often share its blind
spots. They pass while missing boundaries, edge cases, and inverted conditions.

**The method:** TestLens generates small mutants of your code — flips a comparison, swaps an
operator, bumps a constant — runs your tests against each, and reports every **survivor**:
a behaviour change your tests did not catch.

    POST /api/mutate  {"code": "...", "tests": "..."}   -> JSON report
    GET  /api/health                                    -> {"ok": true}
    GET  /                                              -> landing page

- `code` is saved as `solution.py`; `tests` are `unittest` cases importing `solution`.
- Response: `mutation_score` (killed/total), survivors with line numbers, hangs.
- Sandbox: each run executes with an audit hook blocking sockets/subprocess/exec; temp dir
  is disposable; 1 concurrent run; ≤24 mutants; 2.5s per run; per-IP rate limit.

Stdlib only. Run: `PORT=8312 python3 app.py`.
