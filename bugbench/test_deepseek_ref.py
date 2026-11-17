"""Offline tests for policy R (deepseek_ref.py) and its run_agents.py wiring.

No model endpoint, SSH or Docker.  A fake chat transport replaces only ``ChatTransport._open`` and streams
scripted SSE chunks, so the real streaming parser, budget, events, selection, self-check (local CHILD
subprocess) and grading run unchanged.
"""
import io
import json
import math
import os
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents as a  # noqa: E402
import bugbench_grader as g  # noqa: E402
import deepseek_ref as dr  # noqa: E402
import run_agents as r  # noqa: E402

B1 = "stockroom-b1-tier-boundary"
HERE = os.path.dirname(os.path.abspath(__file__))


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


with open(os.path.join(HERE, "EVAL_PLAN.json"), encoding="utf-8") as _plan:
    EVAL_CASES = json.load(_plan)["cases"]


def reply(content, reasoning="I read the whole project.", finish="stop", usage=True, **kw):
    return dict(content=content, reasoning=reasoning, finish=finish, usage=usage, **kw)


def sse(spec, body):
    """Scripted SSE stream: reasoning deltas, content deltas, finish, usage chunk, [DONE]."""
    def line(obj):
        return ("data: " + json.dumps(obj) + "\n").encode()
    yield b": keep-alive\n"
    if spec.get("error"):
        yield line({"error": {"message": spec["error"]}})
        return
    for i in range(0, len(spec["reasoning"]), 700):
        yield line({"choices": [{"index": 0, "delta": {"reasoning_content": spec["reasoning"][i:i + 700]}}]})
        if spec.get("hang"):
            raise TimeoutError("timed out")
    for i in range(0, len(spec["content"]), 900):
        yield line({"choices": [{"index": 0, "delta": {"content": spec["content"][i:i + 900]}}]})
    if not spec.get("no_finish"):
        yield line({"choices": [{"index": 0, "delta": {}, "finish_reason": spec["finish"]}]})
    if spec["usage"]:
        prompt = math.ceil(sum(len(m["content"]) for m in body["messages"]) / 4)
        done = math.ceil((len(spec["reasoning"]) + len(spec["content"])) / 4)
        yield line({"choices": [], "usage": {"prompt_tokens": prompt, "completion_tokens": done,
                                              "total_tokens": prompt + done}})
    yield b"data: [DONE]\n"


class FakeChat(dr.ChatTransport):
    def __init__(self, responder, **kw):
        super().__init__("http://fake-deepseek/v1", dr.MODEL, **kw)
        self.responder, self.bodies, self.lock = responder, [], threading.Lock()

    def _open(self, wire):
        body = json.loads(wire)
        with self.lock:
            self.bodies.append(body)
        return nullcontext(sse(self.responder(body), body))


class Script:
    def __init__(self, *items):
        self.items = list(items)

    def __call__(self, body):
        return self.items.pop(0)


def pool_of(responder, limit=8, **kw):
    transport = FakeChat(responder, **kw)
    return dr.ChatPool(transport, limit), transport


def patch_answer(files, location=("stockroom/pricing.py", "PricingEngine.unit_price")):
    head = json.dumps({"location": {"file": location[0], "function": location[1]}, "hypothesis": "fix"})
    return head + "\n" + g.patch_from_files(files)


def reference_answer(case_id):
    return patch_answer(g.parse_patch(g.reference_patch(g.load_case(case_id))))


def broken_answer(case_id):
    """Valid patch that breaks every public test (the module raises on import)."""
    bundle = g.agent_bundle(case_id)
    target = next(p for p in bundle["editable_paths"] if not p.endswith("__init__.py"))
    return patch_answer({target: bundle["files"][target] + "\nraise RuntimeError('broken by the fake model')\n"},
                        location=(target, "f"))


def attempt(case_id, responder, budget=None, grade=True, oracle=True, **kw):
    pool, transport = pool_of(responder, **kw)
    grade_fn = (lambda p: g.grade(case_id, p)) if grade else (lambda p: dict(status="failed"))
    record = dr.run_attempt(case_id, "R", 1, pool, grade_fn=grade_fn, budget=budget, oracle=oracle)
    return record, transport


def secrets(case_id):
    case = g.load_case(case_id)
    project = g.load_project(case["project"])
    expected = g.load_expected(case["project"])["probes"]
    tree = "".join(g.buggy_files(case).values())
    with open(os.path.join(project["hidden"], "probes.py"), encoding="utf-8") as handle:
        probe_names = g.probe_names(handle.read())
    values = [json.dumps(expected[n].get("value")) for n in case["target_probes"]]
    anchors = [m["old"].strip() for m in case["mutations"] if len(m["old"].strip()) >= 15]
    return ([project["canary"], "BUGBENCH-HIDDEN-CANARY", "probe_", "expected.json", "case.json", "target_probes",
             case_id, "hint_variant"] + list(case["target_probes"]) + [n for n in probe_names if len(n) >= 8]
            + [v for v in values if len(v) >= 12] + [x for x in anchors if x not in tree])


# --- prompt / information boundary ---------------------------------------------------------------------------
class PromptTests(unittest.TestCase):
    def test_whole_bundle_in_prompt_and_no_hidden_material(self):
        for case_id in g.list_cases():
            with self.subTest(case_id):
                bundle = g.agent_bundle(case_id)
                prompt = dr.prompt_r(bundle)
                for path, text in bundle["files"].items():
                    self.assertIn(f"--- BEGIN {path} ---\n{text}", prompt)
                self.assertTrue(any(p.startswith("tests/") for p in bundle["files"]))
                self.assertIn("README.md", bundle["files"])
                for part in (bundle["report"].strip(), bundle["repo_map"], bundle["patch_format"]):
                    self.assertIn(part, prompt)
                for path in bundle["editable_paths"]:
                    self.assertIn(path + "\n", prompt)
                for secret in secrets(case_id):
                    self.assertNotIn(secret, prompt)

    def test_live_attempt_requests_carry_no_hidden_material(self):
        """Full fake attempts with a repair turn: every request body (both calls) is checked."""
        for case_id in EVAL_CASES:
            with self.subTest(case_id):
                broken = broken_answer(case_id)
                record, transport = attempt(case_id, Script(reply(broken), reply(broken)), grade=False,
                                            oracle=False)
                self.assertEqual(record["status"], "completed", record.get("error"))
                self.assertEqual(len(transport.bodies), 2, "self-check failed -> exactly one repair")
                blob = json.dumps(transport.bodies)
                for secret in secrets(case_id):
                    self.assertNotIn(json.dumps(secret)[1:-1], blob)


# --- policy -----------------------------------------------------------------------------------------------------
class PolicyTests(unittest.TestCase):
    def test_passing_first_patch_gets_no_repair(self):
        record, transport = attempt(B1, Script(reply(reference_answer(B1))))
        self.assertEqual(record["status"], "completed")
        self.assertEqual(len(transport.bodies), 1)
        self.assertTrue(record["fixed"])
        self.assertEqual(record["selected"]["stage"], "patch")
        self.assertTrue(record["selected"]["selfcheck"]["ok"])
        self.assertEqual(record["selection"]["rule"], "final_valid")
        self.assertEqual(record["oracle"]["distinct"], 1)
        self.assertEqual(record["localization"]["selected_claim"]["function_hit"], True)
        types = [e["type"] for e in record["events"].records]
        self.assertLess(types.index("selection_frozen"), types.index("hidden_grade"))
        self.assertEqual(len(record["events"].of("hidden_grade")), 1)
        self.assertEqual(len(record["events"].of("selfcheck")), 1)

    def test_failing_selfcheck_triggers_one_repair_turn(self):
        first = broken_answer(B1)
        record, transport = attempt(B1, Script(reply(first), reply(reference_answer(B1))))
        self.assertEqual(len(transport.bodies), 2)
        repair = transport.bodies[1]["messages"]
        self.assertEqual([m["role"] for m in repair], ["system", "user", "assistant", "user"])
        self.assertEqual(repair[:2], transport.bodies[0]["messages"], "same conversation prefix")
        self.assertEqual(repair[2]["content"], first)
        self.assertIn("Self-check failed", repair[3]["content"])
        self.assertIn("broken by the fake model", repair[3]["content"])
        self.assertIn("reverts to its ORIGINAL content", repair[3]["content"])
        self.assertTrue(record["fixed"])
        self.assertEqual(record["selected"]["stage"], "repair")
        self.assertEqual([c["stage"] for c in record["candidates"]], ["patch", "repair"])
        self.assertFalse(record["candidates"][0]["selfcheck"]["ok"])
        self.assertTrue(record["candidates"][1]["selfcheck"]["ok"])
        self.assertEqual(record["oracle"]["distinct"], 2)
        self.assertEqual(record["oracle"]["passed"], 1)
        self.assertEqual(record["usage"]["calls"], 2)

    def test_invalid_repair_keeps_first_valid_patch_and_never_repairs_twice(self):
        first = broken_answer(B1)
        record, transport = attempt(B1, Script(reply(first), reply("I am not sure.")))
        self.assertEqual(len(transport.bodies), 2)
        self.assertFalse(record["fixed"])
        self.assertEqual(record["selected"]["stage"], "patch")
        self.assertEqual(record["selection"]["rule"], "final_valid")
        self.assertFalse(record["agents"]["r"]["trace"][1]["patch_valid"])

    def test_failing_repair_is_still_the_final_valid_patch(self):
        record, transport = attempt(B1, Script(reply(broken_answer(B1)), reply(broken_answer(B1) + "\n")))
        self.assertEqual(len(transport.bodies), 2)
        self.assertEqual(record["selected"]["stage"], "repair")
        self.assertEqual(len(record["events"].of("selfcheck")), 2)

    def test_invalid_or_noop_first_answer_gets_no_repair(self):
        files = g.agent_bundle(B1)["files"]
        noop = patch_answer({"stockroom/pricing.py": files["stockroom/pricing.py"]})
        for content in ("garbage without blocks", '{"location": 1}', noop,
                        patch_answer({"tests/test_public.py": files["tests/test_public.py"] + "\n"})):
            with self.subTest(content[:30]):
                record, transport = attempt(B1, Script(reply(content)))
                self.assertEqual(record["status"], "completed")
                self.assertEqual(len(transport.bodies), 1)
                self.assertIsNone(record["selected"])
                self.assertEqual(record["selection"]["rule"], "no_valid_patch")
                self.assertFalse(record["fixed"])
                self.assertEqual(record["events"].of("hidden_grade"), [])
                self.assertEqual(record["events"].of("selfcheck"), [])

    def test_truncated_and_unclosed_outputs_are_outcomes(self):
        cut = reference_answer(B1)[:1500]
        record, transport = attempt(B1, Script(reply(cut, finish="length")))
        self.assertEqual(record["status"], "completed")
        self.assertEqual(len(transport.bodies), 1)
        self.assertIsNone(record["selected"])
        self.assertEqual(record["usage"]["truncated"], 1)
        trace = record["agents"]["r"]["trace"][0]
        self.assertTrue(trace["truncated"])
        self.assertIn("missing END FILE", trace["patch_error"])
        # all budget spent on thinking: empty content, finish=length
        record, _ = attempt(B1, Script(reply("", reasoning="x" * 5000, finish="length")))
        trace = record["agents"]["r"]["trace"][0]
        self.assertFalse(trace["closed_thinking"])
        self.assertIn("thinking never closed", trace["patch_error"])
        # thinking leaked into content (inline <think>): answer after the LAST </think>
        record, _ = attempt(B1, Script(reply("<think>a</think>b</think>\n" + reference_answer(B1), reasoning="")))
        self.assertTrue(record["fixed"])
        record, _ = attempt(B1, Script(reply("<think>never closed " + reference_answer(B1), reasoning="",
                                             finish="length")))
        self.assertIsNone(record["selected"])

    def test_json_claim_is_optional_and_fences_are_tolerated(self):
        blocks = g.reference_patch(g.load_case(B1)).replace("=== FILE: stockroom/pricing.py ===\n",
                                                            "=== FILE: stockroom/pricing.py ===\n```python\n")
        blocks = blocks.replace("=== END FILE ===", "```\n=== END FILE ===")
        record, _ = attempt(B1, Script(reply("Here is the fix.\n" + blocks)))
        self.assertTrue(record["fixed"])
        self.assertIsNone(record["selected"]["claim"])


# --- transport, budget, accounting ---------------------------------------------------------------------------
class TransportTests(unittest.TestCase):
    def test_request_body_and_seed(self):
        record, transport = attempt(B1, Script(reply(reference_answer(B1))))
        body = transport.bodies[0]
        self.assertEqual(body["model"], "deepseek-v4.1-flash")
        self.assertEqual(body["max_tokens"], 32768)
        self.assertTrue(body["stream"])
        self.assertEqual(body["stream_options"], {"include_usage": True})
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(body["temperature"], 0.8)
        self.assertIsInstance(body["seed"], int)
        self.assertEqual(body["messages"][0], {"role": "system", "content": a.SYSTEM})
        _, again = attempt(B1, Script(reply(reference_answer(B1))))
        self.assertEqual(again.bodies[0]["seed"], body["seed"], "seed is derived, not random")
        pool, other = pool_of(Script(reply(reference_answer(B1))))
        dr.run_attempt(B1, "R", 2, pool, grade_fn=lambda p: dict(status="failed"), oracle=False)
        self.assertNotEqual(other.bodies[0]["seed"], body["seed"])
        start = record["events"].of("request_start")[0]
        self.assertNotIn("messages", start["request_body"])
        self.assertEqual(start["request_body_sha256"], a.sha(json.dumps(body)))
        self.assertEqual(len(record["events"].of("prompt_text")), 1)

    def test_usage_accounting_reported_and_missing(self):
        first, second = broken_answer(B1), reference_answer(B1)
        record, transport = attempt(B1, Script(reply(first, reasoning="r" * 4000), reply(second)))
        expected = [math.ceil((4000 + len(first)) / 4), math.ceil((len("I read the whole project.") + len(second)) / 4)]
        self.assertEqual(record["budget"]["completion_tokens"], sum(expected))
        self.assertEqual(record["budget"]["calls"], 2)
        self.assertEqual(record["usage"]["completion_tokens"], sum(expected))
        prompts = [math.ceil(sum(len(m["content"]) for m in b["messages"]) / 4) for b in transport.bodies]
        self.assertEqual(record["usage"]["prompt_tokens"], sum(prompts))
        self.assertFalse(record["usage"]["prompt_tokens_estimated"])
        self.assertFalse(record["usage"]["completion_tokens_estimated"])
        ends = record["events"].of("request_end")
        self.assertEqual(ends[0]["reasoning"], "r" * 4000)
        self.assertEqual(ends[0]["text"], first)
        # missing usage: charged at max_tokens and flagged
        record, _ = attempt(B1, Script(reply(reference_answer(B1), usage=False)))
        self.assertEqual(record["budget"]["completion_tokens"], 32768)
        self.assertTrue(record["usage"]["completion_tokens_estimated"])
        self.assertTrue(record["usage"]["prompt_tokens_estimated"])
        self.assertGreater(record["usage"]["prompt_tokens"], 5000)

    def test_budget_exhaustion_skips_the_repair(self):
        for budget in (a.Budget(max_calls=1, max_completion_tokens=10**6),
                       a.Budget(max_calls=2, max_completion_tokens=40_000)):
            with self.subTest(budget.snapshot()):
                # the first call reports ~9.6K tokens, so 40K cannot reserve a second 32,768-token call
                record, transport = attempt(B1, Script(reply(broken_answer(B1), reasoning="r" * 30000),
                                                       reply(reference_answer(B1))), budget=budget)
                self.assertEqual(record["status"], "completed")
                self.assertEqual(len(transport.bodies), 1)
                self.assertEqual(len(record["events"].of("budget_exhausted")), 1)
                self.assertEqual(record["selected"]["stage"], "patch")
                self.assertFalse(record["fixed"])

    def test_plan_budget_is_two_calls(self):
        self.assertEqual(dr.POLICIES["R"]["budget"], dict(max_calls=2, max_completion_tokens=65536))

    def test_transport_faults_are_infrastructure(self):
        good = reference_answer(B1)
        cases = {"error": reply(good, error="engine overloaded"), "no_finish": reply(good, no_finish=True),
                 "idle": reply(good, reasoning="x" * 2000, hang=True)}
        for name, spec in cases.items():
            with self.subTest(name):
                record, _ = attempt(B1, Script(spec))
                self.assertEqual(record["status"], "infrastructure_fault")
                self.assertEqual(record["events"].of("hidden_grade"), [])
                self.assertIsNotNone(record["events"].of("request_end")[0]["error"])
                self.assertEqual(record["usage"]["completion_tokens"], 32768, "faulted call charged at max_tokens")

    def test_wall_limit_per_call(self):
        ticks = iter(range(0, 10**6, 600))
        record, _ = attempt(B1, Script(reply(reference_answer(B1), reasoning="x" * 7000)),
                            clock=lambda: next(ticks))
        self.assertEqual(record["status"], "infrastructure_fault")
        self.assertIn("wall limit 1800", record["error"])

    def test_concurrency_limit(self):
        state = dict(now=0, peak=0)
        lock = threading.Lock()
        gate = threading.Event()

        def responder(body):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            gate.wait(0.2)
            with lock:
                state["now"] -= 1
            return reply("no patch")
        pool, _ = pool_of(responder, limit=2)
        threads = [threading.Thread(target=dr.run_attempt, args=(B1, "R", s, pool),
                                    kwargs=dict(grade_fn=lambda p: dict(status="failed"), oracle=False))
                   for s in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(state["peak"], 2)


# --- runner -----------------------------------------------------------------------------------------------------
class RunnerTests(unittest.TestCase):
    def test_plan_only_for_r(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
                self.assertEqual(r.main(["--policies", "R", "--cases", *EVAL_CASES, "--seeds", "1", "2",
                                         "--endpoint", "http://127.0.0.1:18889/v1", "--out", out]), 0)
            plan = json.loads(buffer.getvalue())
            self.assertFalse(os.path.exists(out))
            self.assertEqual(len(plan["attempts"]), 36)
            self.assertEqual(plan["model"], "deepseek-v4.1-flash")
            self.assertEqual(plan["endpoints"], ["http://127.0.0.1:18889/v1"])
            self.assertEqual(plan["deepseek"]["max_tokens_per_call"], 32768)
            self.assertIn("deepseek_ref.py", plan["source_sha256"])
            self.assertEqual(r.attempt_budget(plan, "R"), (2, 65536))
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    r.main(["--policies", "R", "S1", "--cases", B1])
                r.main(["--policies", "S1", "--cases", B1])  # Nemotron plans keep their shape and model

    def test_nemotron_plan_unchanged(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
            r.main(["--policies", "S1", "--cases", B1])
        plan = json.loads(buffer.getvalue())
        self.assertEqual(plan["model"], a.MODEL)
        self.assertEqual(plan["endpoints"], list(a.ENDPOINTS))
        self.assertNotIn("deepseek", plan)
        self.assertNotIn("deepseek_ref.py", plan["source_sha256"])

    def test_execute_writes_attempts_jsonl(self):
        pool, _ = pool_of(lambda body: reply(reference_answer(B1)))
        args = r.argparse.Namespace(cases=[B1], policies=["R"], seeds=[1, 2], endpoints=["x"], endpoint="http://f/v1",
                                    model=dr.MODEL, per_endpoint=8, parallel_attempts=2, docker_host=None,
                                    no_oracle=False, idle_timeout=120, max_calls=None, max_completion_tokens=None)
        plan = r.build_plan(args)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            summary = r.execute(plan, out, pool, parallel=2, log=lambda *_: None)
            self.assertFalse(summary["halted"])
            self.assertEqual(summary["policies"]["R"]["fixed"], 2)
            rows = read_jsonl(os.path.join(out, "attempts.jsonl"))
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["selected_grade"]["status"], "passed")
                self.assertEqual(row["budget"]["max_calls"], 2)
                self.assertTrue(row["oracle"]["any_passed"])
                events = read_jsonl(os.path.join(out, "attempts", row["attempt_id"] + ".jsonl"))
                types = [e["type"] for e in events]
                self.assertLess(types.index("selection_frozen"), types.index("hidden_grade"))
                self.assertIn("prompt_text", types)


if __name__ == "__main__":
    unittest.main()
