"""Offline tests for the bugbench agent side (agents.py, run_agents.py).

No model endpoint, SSH or Docker.  A fake transport tokenizes at ~4 chars/token and
replays scripted generations through the real budget-forcing Caller; self-checks and
grades run the trusted CHILD in a local subprocess.
"""
import io
import json
import math
import os
import re
import sys
import tempfile
import threading
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents as a  # noqa: E402
import bugbench_grader as g  # noqa: E402
import run_agents as r  # noqa: E402

B1 = "stockroom-b1-tier-boundary"
B3 = "stockroom-b3-rollback-order"
PROTOTYPE_CASES = [f"{p}-{c}" for p, c in [
    ("agenda", "b1-slot-grid-default"), ("agenda", "b2-weekday-order"), ("agenda", "b3-split-cancelled-count"),
    ("inkwell", "b1-round-half-even"), ("inkwell", "b2-and-or-precedence"), ("inkwell", "b3-trim-line-drift"),
    ("stockroom", "b1-tier-boundary"), ("stockroom", "b2-snapshot-alias"), ("stockroom", "b3-rollback-order")]]
FORCE = [7, 7, 7]


def gen(answer, think="I reason about the code.", closes=True):
    """A scripted generation: thinking, then (optionally) </think> and the answer."""
    return dict(think=think, answer=answer, closes=closes)


def toks(text, per=4):
    return int(math.ceil(len(text) / per))


class FakeTransport:
    """Streams scripted generations with real cap semantics (``length`` cuts, forced continuation)."""

    def __init__(self, responder, name="fake0", chars_per_token=4, fail_on=None):
        self.responder, self.endpoint, self.base, self.per = responder, name, name, chars_per_token
        self.prompts, self.requests, self.lock, self.fail_on = [], [], threading.Lock(), fail_on

    def tokenize_chat(self, messages):
        text = messages[0]["content"] + messages[1]["content"]
        with self.lock:
            self.prompts.append(dict(messages=messages, user=messages[1]["content"], item=None, emitted=""))
            key = len(self.prompts) - 1
        return [100000 + key] + [1] * (toks(text, self.per) + 9)

    def force_ids(self):
        return list(FORCE)

    def _emit(self, text, max_tokens):
        if toks(text) <= max_tokens:
            return text, "stop"
        return text[:max_tokens * 4], "length"

    def complete(self, prompt_ids, max_tokens, seed, temperature=0.8):
        state = self.prompts[prompt_ids[0] - 100000]
        base = toks(state["messages"][0]["content"] + state["user"], self.per) + 10
        phase = "think" if len(prompt_ids) == base else ("forced" if prompt_ids[-3:] == FORCE else "continued")
        with self.lock:
            self.requests.append(dict(user=state["user"], phase=phase, max_tokens=max_tokens, seed=seed,
                                      prompt_len=len(prompt_ids)))
        if self.fail_on and self.fail_on(state["user"], phase):
            return dict(text="", token_ids=[], finish_reason=None, usage={}, error="TimeoutError: idle 120 s")
        if phase == "think":
            state["item"] = self.responder(state["user"], seed)
            item = state["item"]
            full = item["think"] + (a.END_THINK + item["answer"] if item["closes"] else "")
            text, finish = self._emit(full, max_tokens)
        elif phase == "forced":
            text, finish = self._emit(state["item"]["answer"], max_tokens)
        else:
            full = state["item"]["think"] + a.END_THINK + state["item"]["answer"]
            text, finish = self._emit(full[len(state["emitted"]):], max_tokens)
        state["emitted"] += text
        ids = list(range(toks(text)))
        return dict(text=text, token_ids=ids, finish_reason=finish,
                    usage=dict(prompt_tokens=len(prompt_ids), completion_tokens=len(ids)), error=None)


class Script:
    """Pops scripted generations in order (single chain)."""

    def __init__(self, items):
        self.items = list(items)

    def __call__(self, user, seed):
        return self.items.pop(0)


def pool_of(responder, n=1, **kwargs):
    transports = [FakeTransport(responder, name=f"fake{i}", **kwargs) for i in range(n)]
    return a.EndpointPool(transports, per_endpoint=4), transports


def context(case_id, responder, n=1, selfcheck=None, budget=None, **kwargs):
    bundle = g.agent_bundle(case_id)
    pool, transports = pool_of(responder, n, **kwargs)
    events = a.Events()
    caller = a.Caller(pool, events, budget or a.Budget(), "seed1")
    ctx = a.Context(bundle, caller, selfcheck or a.make_selfcheck(bundle["project"]), events)
    return ctx, transports


def buggy(case_id):
    return g.buggy_files(g.load_case(case_id))


def plan_json(files, hypothesis="pricing tiers"):
    return json.dumps({"files": files, "hypothesis": hypothesis, "notes": "start"})


def patch_answer(files, location=("stockroom/pricing.py", "PricingEngine.unit_price"), hypothesis="fix"):
    head = json.dumps({"action": "patch", "location": {"file": location[0], "function": location[1]},
                       "hypothesis": hypothesis, "notes": "patched"})
    return head + "\n" + g.patch_from_files(files)


def reference_answer(case_id, **kw):
    return patch_answer(g.parse_patch(g.reference_patch(g.load_case(case_id))), **kw)


def broken_pricing():
    files = buggy(B1)
    text = files["stockroom/pricing.py"]
    assert text.count("price = tier.unit_price") == 1
    return {"stockroom/pricing.py": text.replace("price = tier.unit_price", "pass")}


def harmless_pricing(tag):
    """A wrong but public-test-passing edit (the bug stays)."""
    return {"stockroom/pricing.py": buggy(B1)["stockroom/pricing.py"] + f"\n_UNUSED_{tag} = 1\n"}


def all_prompts(transports):
    return [p["user"] for t in transports for p in t.prompts]


# --- parsing --------------------------------------------------------------------------------------
class ParsingTests(unittest.TestCase):
    def test_extract_json_tolerates_prose_fences_and_ignores_code(self):
        self.assertEqual(a.extract_json('Sure.\n```json\n{"files": ["a.py"], "hypothesis": "x"}\n```\nbye',
                                        keys=("files",)), {"files": ["a.py"], "hypothesis": "x"})
        text = '{"action": "patch", "location": {"file": "f", "function": "g"}}\n=== FILE: x.py ===\nD = {"action": 1}\n'
        self.assertEqual(a.extract_json(text, keys=("action",))["location"]["function"], "g")
        code_only = 'blah\n=== FILE: x.py ===\nD = {"action": "read"}\n=== END FILE ===\n'
        self.assertIsNone(a.extract_json(code_only, keys=("action",)))

    def test_extract_json_truncated_or_garbled(self):
        self.assertIsNone(a.extract_json('{"files": ["stockroom/pri', keys=("files",)))
        self.assertIsNone(a.extract_json("no json at all {{{ ]]", keys=("files",)))
        self.assertIsNone(a.extract_json(None, keys=("files",)))
        # a truncated outer object must not be replaced by an inner fragment
        self.assertIsNone(a.extract_json('{"action": "patch", "location": {"file": "f", "function": "g"}, "hyp',
                                         keys=("action", "files")))

    def test_patch_answer_validation(self):
        files, editable = buggy(B1), g.agent_bundle(B1)["editable_paths"]
        ref = reference_answer(B1)
        ok = a.parse_patch_answer(ref, files, editable, allowed=["stockroom/pricing.py"])
        self.assertTrue(ok["valid"])
        self.assertFalse(ok["no_op"])
        truncated = a.parse_patch_answer(ref[: len(ref) // 2], files, editable)
        self.assertFalse(truncated["valid"])
        self.assertIn("truncated", truncated["error"])
        unseen = a.parse_patch_answer(ref, files, editable, allowed=["stockroom/orders.py"])
        self.assertIn("not shown", unseen["error"])
        tests = a.parse_patch_answer(g.patch_from_files({"tests/test_public.py": "x = 1\n"}), files, editable)
        self.assertIn("not editable", tests["error"])
        self.assertFalse(a.parse_patch_answer(None, files, editable)["valid"])
        self.assertFalse(a.parse_patch_answer("garbage ```", files, editable)["valid"])
        comment = {"stockroom/pricing.py": files["stockroom/pricing.py"].replace(
            "            if quantity > tier.min_quantity:\n", "            if quantity > tier.min_quantity:  # c\n")}
        self.assertTrue(a.parse_patch_answer(g.patch_from_files(comment), files, editable)["no_op"])


# --- budget / caps -------------------------------------------------------------------------------
class CapTests(unittest.TestCase):
    def test_caps_vs_prompt_length(self):
        self.assertEqual(a.compute_caps(2000, 3, 2800), (8192, 5392))
        self.assertEqual(a.compute_caps(7800, 3, 2800), (8192, 5392))
        self.assertEqual(a.compute_caps(10000, 3, 2800), (5997, 3197))
        self.assertEqual(a.compute_caps(10000, 3, 1024), (5997, 4973))
        with self.assertRaises(a.PromptTooLong):
            a.compute_caps(12200, 3, 2800)
        for prompt in range(1000, 12000, 250):
            total, think = a.compute_caps(prompt, 3, 2800)
            self.assertLessEqual(prompt + 3 + total, a.CONTEXT_LIMIT)
            self.assertLessEqual(total, a.MAX_COMPLETION)
            self.assertEqual(total - think, 2800)

    def test_patch_reserve_fits_largest_module(self):
        files = buggy(B1)
        self.assertGreaterEqual(a.patch_reserve(files, ["stockroom/errors.py"]), a.PATCH_ANSWER_RESERVE)
        big = max(g.agent_bundle(B1)["editable_paths"], key=lambda p: len(files[p]))
        self.assertGreater(a.patch_reserve(files, [big]), len(files[big]) / 3.6)

    def _caller(self, item, budget=None):
        pool, (t,) = pool_of(lambda user, seed: item)
        return a.Caller(pool, a.Events(), budget or a.Budget(), "s"), t

    def test_closed_thinking_needs_one_request(self):
        caller, t = self._caller(gen('{"files": []}'))
        out = caller.call("x", "plan", "short prompt", answer_reserve=1024)
        self.assertEqual(out["answer"], '{"files": []}')
        self.assertEqual([q["phase"] for q in t.requests], ["think"])
        self.assertEqual(t.requests[0]["max_tokens"], out["think_cap"])
        self.assertEqual(out["total_cap"], 8192)

    def test_forced_continuation_respects_window(self):
        prompt = "p" * 4 * 9000  # ~9K prompt tokens
        caller, t = self._caller(gen("ANSWER " * 50, think="t" * 4 * 20000))
        out = caller.call("x", "step", prompt, answer_reserve=2800)
        first, second = t.requests
        self.assertEqual((first["phase"], second["phase"]), ("think", "forced"))
        self.assertTrue(out["forced"])
        self.assertEqual(out["answer"].strip(), ("ANSWER " * 50).strip())
        total = a.CONTEXT_LIMIT - first["prompt_len"] - len(FORCE)
        self.assertEqual(first["max_tokens"], total - 2800)
        self.assertEqual(second["max_tokens"], total - first["max_tokens"])
        self.assertLessEqual(second["prompt_len"] + second["max_tokens"], a.CONTEXT_LIMIT)
        self.assertLessEqual(first["prompt_len"] + first["max_tokens"] + second["max_tokens"], a.CONTEXT_LIMIT)

    def test_cut_answer_is_continued_without_suffix_and_marked_truncated(self):
        caller, t = self._caller(gen("A" * 4 * 9000, think="t" * 4 * 100))
        out = caller.call("x", "step", "short", answer_reserve=2800)
        self.assertEqual([q["phase"] for q in t.requests], ["think", "continued"])
        self.assertFalse(out["forced"])
        self.assertTrue(out["truncated"])
        self.assertEqual(out["completion_tokens"], 8192)
        self.assertTrue(out["answer"].startswith("A" * 100))

    def test_prompt_too_long_spends_nothing(self):
        budget = a.Budget()
        caller, t = self._caller(gen("x"), budget)
        with self.assertRaises(a.PromptTooLong):
            caller.call("x", "step", "p" * 4 * 13000)
        self.assertEqual(t.requests, [])
        self.assertEqual(budget.snapshot()["calls"], 0)

    def test_budget_exhaustion_is_an_outcome_and_idle_timeout_a_fault(self):
        caller, _ = self._caller(gen("ok"), a.Budget(max_calls=1))
        self.assertIsNotNone(caller.call("x", "a", "p"))
        self.assertIsNone(caller.call("x", "b", "p"))
        pool, _ = pool_of(lambda u, s: gen("ok"), fail_on=lambda user, phase: True)
        events = a.Events()
        with self.assertRaises(a.InfrastructureFault):
            a.Caller(pool, events, a.Budget(), "s").call("x", "a", "p")
        self.assertIn("idle", events.of("request_end")[0]["error"])

    def test_events_log_tokens_hashes_ids_and_raw_text(self):
        caller, _ = self._caller(gen("the answer", think="hmm"))
        caller.call("agent7", "plan", "the prompt", answer_reserve=1024)
        ev = caller.events
        self.assertEqual(ev.of("prompt_text")[0]["text"], "the prompt")
        start, end = ev.of("request_start")[0], ev.of("request_end")[0]
        self.assertEqual(start["request_id"], end["request_id"])
        self.assertIn("prompt_ids_sha256", start)
        self.assertEqual(end["text"], "hmm</think>the answer")
        self.assertEqual(end["usage"]["completion_tokens"], end["completion_tokens"])
        self.assertEqual(ev.of("call_start")[0]["prompt_sha256"], a.sha("the prompt"))


# --- S1 -------------------------------------------------------------------------------------------------
class NavigatorTests(unittest.TestCase):
    def test_request_files_patch_selfcheck_repair(self):
        script = Script([
            gen(plan_json(["stockroom/orders.py", "stockroom/catalog.py"])),
            gen(json.dumps({"action": "read", "files": ["stockroom/pricing.py"], "notes": "look at tiers"})),
            gen(patch_answer(broken_pricing())),
            gen(reference_answer(B1)),
        ])
        ctx, (t,) = context(B1, script)
        out = a.policy_s1(ctx, calls=6)
        trace = out["agents"]["s1"]["trace"]
        self.assertEqual([e["stage"] for e in trace], ["plan", "step", "step", "repair"])
        self.assertEqual(trace[1]["files"], ["stockroom/pricing.py"])
        checks = ctx.events.of("selfcheck")
        self.assertEqual([c["ok"] for c in checks], [False, True])
        self.assertEqual(out["agents"]["s1"]["calls"], 4)
        final = out["candidates"][0]
        self.assertEqual(final["stage"], "repair")
        self.assertEqual(g.grade(B1, final["patch_text"])["status"], "passed")
        prompts = all_prompts([t])
        self.assertIn("--- BEGIN stockroom/orders.py ---", prompts[1])
        self.assertIn("--- BEGIN stockroom/pricing.py ---", prompts[2])
        self.assertIn("look at tiers", prompts[2])
        self.assertIn("Self-check failed", prompts[3])
        self.assertIn("test_large_order_gets_tier_price", prompts[3])

    def test_passing_selfcheck_stops_and_only_one_repair(self):
        ctx, _ = context(B1, Script([gen(plan_json(["stockroom/pricing.py"])), gen(reference_answer(B1))]))
        out = a.policy_s1(ctx, calls=6)
        self.assertEqual(out["agents"]["s1"]["calls"], 2)
        ctx, _ = context(B1, Script([gen(plan_json(["stockroom/pricing.py"])), gen(patch_answer(broken_pricing())),
                                     gen(patch_answer(broken_pricing()))]))
        out = a.policy_s1(ctx, calls=6)
        self.assertEqual(out["agents"]["s1"]["calls"], 3)  # no second repair
        self.assertFalse(out["candidates"][0]["selfcheck"]["ok"])

    def test_garbled_and_truncated_output_never_crash_and_yield_no_patch(self):
        ref = reference_answer(B1)
        script = Script([
            gen("I think the bug is somewhere. {not json"),          # garbled plan -> README
            gen(json.dumps({"action": "read", "files": ["nope.py", 3]})),  # no valid file
            gen("", think="t" * 4 * 30000, closes=False),            # never closes -> forced, empty answer
            gen(ref[: len(ref) // 2]),                                # truncated patch
            gen(json.dumps({"action": "patch", "location": {"file": "x", "function": "y"}})),  # claim, no blocks
            gen("=== END FILE ==="),
        ])
        ctx, (t,) = context(B1, script)
        out = a.policy_s1(ctx, calls=6)
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["agents"]["s1"]["calls"], 6)
        self.assertIn("--- BEGIN README.md ---", t.prompts[1]["user"])
        self.assertIn("named no existing file", t.prompts[2]["user"])
        self.assertIn("truncated", t.prompts[4]["user"])
        self.assertIn("You must choose Option B", t.prompts[5]["user"])
        selected, info = a.select(out["candidates"])
        self.assertIsNone(selected)
        self.assertEqual(info["rule"], "no_valid_patch")

    def test_prompt_too_long_drops_second_file(self):
        script = Script([gen(plan_json(["stockroom/journal.py", "stockroom/inventory.py"])),
                         gen(json.dumps({"action": "read", "files": ["stockroom/pricing.py"]}))])
        ctx, (t,) = context(B1, script, chars_per_token=1.6)
        nav = a.Navigator(ctx, "s1", max_calls=2)
        nav.run()
        self.assertEqual(nav.trace[1]["shown"], ["stockroom/journal.py"])
        self.assertEqual(ctx.caller.budget.snapshot()["calls"], 2)


# --- S3 -------------------------------------------------------------------------------------------------
class IndependenceTests(unittest.TestCase):
    def test_chains_share_nothing_and_use_distinct_seeds_and_replicas(self):
        markers, lock = [], threading.Lock()

        def responder(user, seed):
            found = re.findall(r"CHAIN-[0-9a-f]{8}", user)
            if "`files` lists 1 or 2 paths" in user:
                assert not found
                marker = "CHAIN-" + uuid.uuid4().hex[:8]
                with lock:
                    markers.append(marker)
                return gen(json.dumps({"files": ["stockroom/pricing.py"], "hypothesis": marker, "notes": marker}))
            assert len(set(found)) == 1, found  # each chain sees only its own notes
            return gen(reference_answer(B1))
        ctx, transports = context(B1, responder, n=4)
        out = a.policy_s3(ctx, k=8, calls=3)
        self.assertEqual(len(set(markers)), 8)
        self.assertEqual(len(out["candidates"]), 8)
        self.assertEqual(len({c["agent"] for c in out["candidates"]}), 8)
        plan_seeds = [q["seed"] for t in transports for q in t.requests if "`files` lists" in q["user"]]
        self.assertEqual(len(set(plan_seeds)), 8, "identical first prompts must get distinct seeds")
        self.assertGreater(sum(1 for t in transports if t.requests), 1)
        for prompt in all_prompts(transports):
            self.assertLessEqual(len(set(re.findall(r"CHAIN-[0-9a-f]{8}", prompt))), 1)
        selected, info = a.select(out["candidates"])
        self.assertEqual(info["cluster_size"], 8)
        self.assertEqual(info["rule"], "vote")

    def test_fault_in_one_chain_aborts_the_attempt(self):
        def responder(user, seed):
            return gen(plan_json(["stockroom/pricing.py"]))
        ctx, _ = context(B1, responder, n=2, fail_on=lambda user, phase: "--- BEGIN" in user)
        with self.assertRaises(a.InfrastructureFault):
            a.policy_s3(ctx, k=4, calls=3)
        self.assertTrue(ctx.caller.abort.is_set())


# --- W1 -------------------------------------------------------------------------------------------------
class ShardingTests(unittest.TestCase):
    def test_aggregation_sums_suspicion_and_breaks_ties_by_mentions(self):
        reports = [
            dict(file="m/a.py", function="f", suspicion=0.4, evidence="ea1", also_check=[]),
            dict(file="m/a.py", function="f", suspicion=0.4, evidence="ea2", also_check=[]),
            dict(file="m/b.py", function="g", suspicion=0.8, evidence="eb", also_check=["m/c.py"]),
            dict(file="m/c.py", function="h", suspicion=0.1, evidence="ec", also_check=[]),
            dict(file="m/d.py", function="", suspicion=0.0, evidence="", also_check=[]),
        ]
        agg = a.aggregate_scouts(reports)
        self.assertEqual([(e["file"], e["mentions"]) for e in agg["ranked"][:2]], [("m/a.py", 2), ("m/b.py", 1)])
        self.assertEqual(agg["modules"], ["m/a.py", "m/b.py"])
        self.assertEqual(agg["claim"], {"file": "m/a.py", "function": "f"})
        self.assertEqual([n["evidence"] for n in agg["evidence"]], ["eb", "ea1", "ea2"])

    def test_scout_parsing_clamps_and_truncates(self):
        files = {"m/a.py": "", "m/b.py": ""}
        parsed = a.parse_scout('```json\n{"suspicion": 7, "function": "m/a.py::K.run()", "evidence": "' +
                               "w " * 200 + '", "also_check": ["m/b.py", "zzz", 3]}\n```', "m/a.py", files)
        self.assertEqual((parsed["suspicion"], parsed["function"], parsed["also_check"]), (1.0, "K.run", ["m/b.py"]))
        self.assertEqual(len(parsed["evidence"].split()), 80)
        self.assertEqual(a.parse_scout("garbage", "m/a.py", files)["suspicion"], 0.0)
        self.assertEqual(a.parse_scout('{"suspicion": "high"}', "m/a.py", files)["suspicion"], 0.0)

    def test_w1_end_to_end(self):
        def responder(user, seed):
            if "Several reviewers" in user:
                module = re.search(r"# Your module: (\S+)", user).group(1)
                hot = module == "stockroom/pricing.py"
                return gen(json.dumps({"suspicion": 0.9 if hot else 0.05,
                                       "function": "PricingEngine.unit_price" if hot else "x",
                                       "evidence": "tier uses > instead of >=" if hot else "fine"}))
            assert "tier uses > instead of >=" in user and "--- BEGIN stockroom/pricing.py ---" in user
            return gen(reference_answer(B1))
        ctx, transports = context(B1, responder, n=4)
        out = a.policy_w1(ctx, fixers=4, fixer_calls=2)
        modules = len(ctx.editable)
        self.assertEqual(len(out["scouts"]), modules)
        self.assertEqual(out["aggregate"]["modules"][0], "stockroom/pricing.py")
        self.assertEqual(ctx.caller.budget.snapshot()["calls"], modules + 4)
        self.assertEqual(len(out["candidates"]), 4)
        selected, info = a.select(out["candidates"])
        self.assertEqual(info["cluster_size"], 4)
        self.assertEqual(g.grade(B1, selected["patch_text"])["status"], "passed")


# --- selection and oracle ------------------------------------------------------------------------------
def cand(order, key, ok=True, valid=True, no_op=False, agent="x"):
    return dict(order=order, key=key, valid=valid, no_op=no_op, agent=agent, patch_text=f"p{order}",
                selfcheck=dict(ok=ok))


class SelectionTests(unittest.TestCase):
    def test_rule_order(self):
        sel, info = a.select([cand(1, "A"), cand(2, "B"), cand(3, "B")])
        self.assertEqual((sel["order"], info["rule"]), (2, "vote"))
        sel, _ = a.select([cand(1, "A", ok=False), cand(2, "A", ok=False), cand(3, "B")])
        self.assertEqual(sel["order"], 3, "public-test pass outranks cluster size")
        sel, info = a.select([cand(5, "A"), cand(4, "B")])
        self.assertEqual((sel["order"], info["rule"]), (4, "earliest"))
        late_chain0, early_chain1 = dict(cand(9, "A"), rank=0), dict(cand(2, "B"), rank=1)
        self.assertEqual(a.select([early_chain1, late_chain0])[0]["order"], 9, "earliest = chain index, not clock")
        sel, _ = a.select([cand(1, None, valid=False), cand(2, "Z", no_op=True), cand(3, "C", ok=False)])
        self.assertEqual(sel["order"], 3)
        self.assertIsNone(a.select([cand(1, None, valid=False), None])[0])

    def test_normalization_ignores_formatting_and_comments(self):
        files = buggy(B1)
        fix = g.parse_patch(g.reference_patch(g.load_case(B1)))["stockroom/pricing.py"]
        variant = fix.replace("if quantity >= tier.min_quantity:", "if quantity>=tier.min_quantity:  # inclusive")
        self.assertNotEqual(fix, variant)
        key = a.normalized_key(files, {"stockroom/pricing.py": fix})
        self.assertEqual(key, a.normalized_key(files, {"stockroom/pricing.py": variant}))
        other = fix.replace("quantity >= tier.min_quantity", "tier.min_quantity <= quantity")
        self.assertNotEqual(key, a.normalized_key(files, {"stockroom/pricing.py": other}))
        self.assertIsNone(a.normalized_key(files, {"stockroom/pricing.py": files["stockroom/pricing.py"] + "\n# x\n"}))

    def test_oracle_never_influences_selection(self):
        """Majority = public-test-passing wrong patch; minority = real fix.  Selection must pick the majority
        and the single hidden grade must follow the frozen selection; oracle sees the fix afterwards."""
        wrong = patch_answer(harmless_pricing("a"))

        def responder(user, seed):
            if "`files` lists 1 or 2 paths" in user:
                return gen(plan_json(["stockroom/pricing.py"]))
            with lock:
                first = not served
                served.append(1)
            return gen(reference_answer(B1) if first else wrong)  # exactly one chain finds the real fix
        served, lock = [], threading.Lock()
        pool, _ = pool_of(responder, n=2)
        calls = []

        def grade_fn_for(record_events):
            def grade_fn(patch):
                calls.append((patch, [e["type"] for e in record_events()]))
                return g.grade(B1, patch)
            return grade_fn
        holder = {}
        real_events = a.Events

        class SpyEvents(real_events):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                holder["events"] = self
        a.Events = SpyEvents
        try:
            record = a.run_attempt(B1, "S3", 1, pool, grade_fn=grade_fn_for(lambda: holder["events"].records),
                                   k=6, calls=3)
            served.clear()
            again = a.run_attempt(B1, "S3", 1, a.EndpointPool(pool.transports, 4), oracle=False,
                                  grade_fn=lambda p: g.grade(B1, p), k=6, calls=3)
        finally:
            a.Events = real_events
        self.assertEqual(record["status"], "completed")
        self.assertGreater(record["selection"]["cluster_size"], 1)
        self.assertFalse(record["fixed"])
        self.assertTrue(record["oracle"]["any_passed"], "the hindsight oracle sees the minority fix")
        self.assertIn("ORACLE", record["oracle"]["label"])
        self.assertEqual(calls[0][0], g.patch_from_files(harmless_pricing("a")))
        self.assertIn("selection_frozen", calls[0][1], "selection is frozen before any hidden grade")
        self.assertEqual(sum(1 for e in record["events"].of("hidden_grade")), 1)
        oracle_events = record["events"].of("oracle_grade")
        self.assertTrue(all("never used for selection" in e["label"] for e in oracle_events))
        self.assertEqual(record["selected"]["key"], again["selected"]["key"])
        self.assertIsNone(again["oracle"])


# --- information boundary ---------------------------------------------------------------------------------------
class LeakageTests(unittest.TestCase):
    def secrets(self, case_id):
        case = g.load_case(case_id)
        project = g.load_project(case["project"])
        expected = g.load_expected(case["project"])["probes"]
        tree = "".join(buggy(case_id).values())
        values = [json.dumps(expected[n].get("value")) for n in case["target_probes"]]
        anchors = [m["old"].strip() for m in case["mutations"] if len(m["old"].strip()) >= 15]
        return ([project["canary"], "BUGBENCH-HIDDEN-CANARY", "probe_", "expected.json", "case.json", "target_probes",
                 "gold"] + list(case["target_probes"]) + [v for v in values if len(v) >= 12]
                + [x for x in anchors if x not in tree])

    def responder_for(self, case_id):
        bundle = g.agent_bundle(case_id)
        editable = bundle["editable_paths"]
        files = bundle["files"]

        def responder(user, seed):
            if "`files` lists 1 or 2 paths" in user:
                return gen(plan_json(editable[:2]))
            if "Several reviewers" in user:
                module = re.search(r"# Your module: (\S+)", user).group(1)
                return gen(json.dumps({"suspicion": 0.5, "function": "f", "evidence": f"look at {module}"}))
            if "Self-check failed" in user:
                return gen("I give up")
            shown = re.findall(r"--- BEGIN (\S+) ---", user)
            read = re.search(r"Files read so far: (.*)", user).group(1).split(", ")
            unseen = [p for p in editable if p not in read and p not in shown]
            if "This is call 5 of" in user or "You must choose Option B" in user or not unseen:
                target = next(p for p in shown if p in editable)
                return gen(patch_answer({target: files[target] + "\nraise RuntimeError('broken')\n"},
                                        location=(target, "f")))
            return gen(json.dumps({"action": "read", "files": unseen[:2], "notes": "keep reading"}))
        return responder

    def test_no_hidden_material_in_any_prompt(self):
        # Pinned to the 9 prototype cases (as in test_bugbench.py) so projects being authored concurrently
        # cannot make this test flaky; add new cases here once they are frozen.
        for case_id in PROTOTYPE_CASES:
            with self.subTest(case_id):
                responder = self.responder_for(case_id)
                prompts = []
                for policy, kwargs in (("S1", {}), ("S3", dict(k=2, calls=4)), ("W1", dict(fixers=2))):
                    pool, transports = pool_of(responder, n=2)
                    record = a.run_attempt(case_id, policy, 1, pool, oracle=False,
                                           grade_fn=lambda p: dict(status="failed"), **kwargs)
                    self.assertEqual(record["status"], "completed", record.get("error"))
                    prompts += all_prompts(transports)
                    if policy == "S1":
                        self.assertTrue(any("Self-check failed" in p for p in all_prompts(transports)))
                        read = set(re.findall(r"--- BEGIN (\S+) ---", "".join(all_prompts(transports))))
                        self.assertGreaterEqual(len(read), 8)
                self.assertGreater(len(prompts), 15)
                blob = "\n".join(prompts)
                for secret in self.secrets(case_id):
                    self.assertNotIn(secret, blob)


# --- runner ---------------------------------------------------------------------------------------------------
class RunnerTests(unittest.TestCase):
    def test_plan_only_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
                self.assertEqual(r.main(["--cases", B1, B3, "--seeds", "1", "2", "--out", out]), 0)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(len(plan["attempts"]), 2 * 2 * 3)
            self.assertFalse(os.path.exists(out))
            with self.assertRaises(SystemExit):
                r.main(["--run", "--cases", B1, "--out", out])  # no docker host
            os.makedirs(out)
            with self.assertRaises(SystemExit):
                r.main(["--run", "--cases", B1, "--out", out, "--docker-host", "Spark_01"])  # exists

    def test_execute_writes_logs_and_halts_admission_on_fault(self):
        state = {"n": 0}
        lock = threading.Lock()

        def fail_on(user, phase):
            with lock:
                state["n"] += 1
                return state["n"] > 2

        def responder(user, seed):
            return gen(plan_json(["stockroom/pricing.py"]) if "`files` lists" in user else reference_answer(B1))
        pool, _ = pool_of(responder, n=1, fail_on=fail_on)
        args = r.argparse.Namespace(cases=[B1], policies=["S1"], seeds=[1, 2, 3, 4], endpoints=["fake0"],
                                    model="m", per_endpoint=1, parallel_attempts=1, docker_host=None,
                                    no_oracle=False, idle_timeout=120, max_calls=48, max_completion_tokens=256000)
        plan = r.build_plan(args)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            summary = r.execute(plan, out, pool, parallel=1, log=lambda *_: None)
            self.assertTrue(summary["halted"])
            self.assertEqual(len(summary["not_started"]), 2)
            rows = [json.loads(line) for line in open(os.path.join(out, "attempts.jsonl"))]
            self.assertEqual([row["status"] for row in rows], ["completed", "infrastructure_fault"])
            self.assertTrue(rows[0]["fixed"])
            self.assertEqual(summary["policies"]["S1"]["fixed"], 1)
            events = [json.loads(line) for line in open(os.path.join(out, "attempts", rows[0]["attempt_id"] + ".jsonl"))]
            types = [e["type"] for e in events]
            self.assertLess(types.index("selection_frozen"), types.index("hidden_grade"))
            with self.assertRaises(FileExistsError):
                r.execute(plan, out, pool, parallel=1, log=lambda *_: None)



# --- T1/T3/V3: agent-written tests, cross-validation, review ---------------------------------------------
REPRO_HEAD = """import datetime
import unittest

from stockroom import Money, Store


def price(quantity):
    store = Store("PLN")
    store.add_product("WID-001", "Widget", "2.50", tiers=[(10, "2.30"), (50, "2.10")])
    store.receive("WID-001", 100, "1.20", datetime.date(2026, 3, 1))
    return store.pricing.quote([("WID-001", quantity)]).line("WID-001").unit_price


class Repro(unittest.TestCase):
"""


def repro(*pairs):
    return REPRO_HEAD + "".join(f"    def test_{n}_units(self):\n        self.assertEqual(price({n}), Money(\"{p}\", "
                                f"\"PLN\"))\n" for n, p in pairs)


GOOD = repro((10, "2.30"), (50, "2.10"))   # the report's behaviour at every boundary
TEN_ONLY = repro((10, "2.30"))             # the report's example only
WEAK = repro((11, "2.30"))                 # already passes on the buggy code
WRONG = repro((10, "2.10"))                # contradicts the report (fails before AND after the real fix)
BROKEN = "import unittest\nfrom stockroom import NoSuchName\n\n\nclass R(unittest.TestCase):\n    def test_x(self):\n        pass\n"
EMPTY = "import unittest\n"


def test_answer(text, path="tests/test_repro_x.py", files=("stockroom/pricing.py",), action="test"):
    head = json.dumps({"action": action, "expected": "2.30 from 10 units", "files": list(files),
                       "suspect": {"file": "stockroom/pricing.py", "function": "PricingEngine.unit_price"},
                       "notes": "tiers"})
    return f"{head}\n=== TEST: {path} ===\n{text}=== END TEST ===\n"


def hack_pricing():
    """Special-cases the report's example: passes TEN_ONLY, fails GOOD at 50 units."""
    text = buggy(B1)["stockroom/pricing.py"]
    old = "            if quantity > tier.min_quantity:\n"
    return {"stockroom/pricing.py": text.replace(old, "            if quantity > tier.min_quantity or quantity == tier.min_quantity == 10:\n")}


def reference_files():
    return g.parse_patch(g.reference_patch(g.load_case(B1)))


class SpyExecutor:
    """Local CHILD runner that records every payload sent to the sandbox."""

    def __init__(self):
        self.payloads, self.lock = [], threading.Lock()

    def __call__(self, payload, timeout):
        with self.lock:
            self.payloads.append(payload)
        result, error = g.run_child(payload, timeout)
        return result, error, {"executor": "spy", "failure_kind": g._local_failure_kind(error),
                               "provenance": "candidate"}


class HiddenTripwire:
    """Make every hidden-material reader raise while active."""
    NAMES = ("load_expected", "probe_payload", "observe", "grade", "compare", "load_case", "verify_case")

    def __enter__(self):
        self.saved = {name: getattr(g, name) for name in self.NAMES}

        def trip(name):
            def boom(*args, **kwargs):
                raise AssertionError(f"hidden material read during the agent phase: g.{name}")
            return boom
        for name in self.NAMES:
            setattr(g, name, trip(name))
        return self

    def __exit__(self, *exc):
        for name, fn in self.saved.items():
            setattr(g, name, fn)


def t_context(responder, n=1, executor=None, budget=None):
    ctx, transports = context(B1, responder, n=n, budget=budget)
    ctx.tester = a.make_agent_tester(ctx.bundle, executor)
    return ctx, transports


class AgentTestSandboxTests(unittest.TestCase):
    def test_classification_on_original_and_patched_trees(self):
        tests = {"tests/test_repro_a.py": GOOD, "tests/test_repro_b.py": WEAK, "tests/test_repro_c.py": BROKEN,
                 "tests/test_repro_d.py": EMPTY}
        before = g.run_agent_tests(B1, None, tests)
        self.assertEqual({p: r["classification"] for p, r in before["tests"].items()},
                         {"tests/test_repro_a.py": "fail", "tests/test_repro_b.py": "pass",
                          "tests/test_repro_c.py": "broken", "tests/test_repro_d.py": "empty"})
        self.assertTrue(before["public"]["ok"])
        after = g.run_agent_tests(B1, g.reference_patch(g.load_case(B1)), {"tests/test_repro_a.py": GOOD})
        self.assertEqual(after["tests"]["tests/test_repro_a.py"]["classification"], "pass")
        self.assertTrue(after["public"]["ok"])
        hacked = g.run_agent_tests(B1, hack_pricing(), {"tests/test_repro_a.py": GOOD, "tests/test_repro_t.py": TEN_ONLY},
                                   include_public=False)
        self.assertEqual([hacked["tests"][p]["classification"] for p in sorted(hacked["tests"])], ["fail", "pass"])
        self.assertIsNone(hacked["public"])

    def test_sandbox_never_runs_probes_or_reads_expected(self):
        bundle = g.agent_bundle(B1)
        canary = g.load_project("stockroom")["canary"]
        spy, fix = SpyExecutor(), reference_files()
        with HiddenTripwire():
            result = g.run_agent_tests(bundle, fix, {"tests/test_repro_a.py": GOOD,
                                                                  "tests/test_repro_b.py": WEAK}, executor=spy)
        self.assertEqual(result["provenance"], "candidate")
        self.assertEqual(len(spy.payloads), 3)  # two isolated agent-test runs + one public-test run
        for payload in spy.payloads:
            self.assertEqual(payload["mode"], "public_tests")
            self.assertNotIn("probes", payload)
            self.assertNotIn("probe_names", payload)
            blob = json.dumps(payload)
            for secret in (canary, "BUGBENCH-HIDDEN-CANARY", "expected.json", "def probe_"):
                self.assertNotIn(secret, blob)
        isolated = [p for p in spy.payloads if any(k.startswith("tests/test_repro") for k in p["files"])]
        self.assertEqual(len(isolated), 2)
        for payload in isolated:
            self.assertNotIn("tests/test_public.py", payload["files"])
            self.assertEqual(sum(k.startswith("tests/test_repro") for k in payload["files"]), 1)

    def test_rejects_bad_paths_and_test_edits(self):
        for path in ("stockroom/test_x.py", "tests/test_public.py", "tests/helper.py", "tests/../x.py"):
            with self.assertRaises(g.PatchError):
                g.run_agent_tests(B1, None, {path: GOOD})
        with self.assertRaises(g.PatchError):
            g.run_agent_tests(B1, {"tests/test_public.py": "x = 1\n"}, {})

    def test_parse_test_block(self):
        text, err = a.parse_test_block(test_answer(GOOD))
        self.assertEqual((text, err), (GOOD, None))
        fenced = 'x\n=== TEST: tests/test_a.py ===\n```python\nimport unittest\n```\n=== END TEST ===\n'
        self.assertEqual(a.parse_test_block(fenced)[0], "import unittest\n")
        cut = test_answer(GOOD)
        self.assertIn("truncated", a.parse_test_block(cut[: cut.index("class Repro")])[1])
        as_file = "=== FILE: tests/test_r.py ===\nimport unittest\n=== END FILE ===\n"
        self.assertIsNone(a.parse_test_block(as_file)[0])
        self.assertEqual(a.parse_test_block(as_file, allow_file=True)[0], "import unittest\n")
        code_file = "=== FILE: stockroom/pricing.py ===\nx = 1\n=== END FILE ===\n"
        self.assertIsNone(a.parse_test_block(code_file, allow_file=True)[0])
        mixed = test_answer(GOOD) + g.patch_from_files(reference_files())
        self.assertNotIn("=== TEST:", a.strip_test_blocks(mixed))
        self.assertTrue(a.parse_patch_answer(a.strip_test_blocks(mixed), buggy(B1),
                                             g.agent_bundle(B1)["editable_paths"])["valid"])
        self.assertIn("pytest", a.check_test_source("import pytest\n"))
        self.assertIn("SyntaxError", a.check_test_source("def (:\n"))


class TestFirstTests(unittest.TestCase):
    def test_repro_must_fail_before_and_pass_after(self):
        script = Script([
            gen(plan_json(["stockroom/pricing.py", "tests/test_public.py"])),
            gen(test_answer(WEAK)),                     # passes on the buggy tree -> told so, one revision
            gen(test_answer(GOOD)),                     # fails on the buggy tree -> adopted
            gen(patch_answer(broken_pricing())),        # breaks public tests and still fails the repro
            gen(reference_answer(B1)),                  # repair
        ])
        ctx, (t,) = t_context(script)
        out = a.policy_t1(ctx, calls=8)
        summary = out["agents"]["t1"]
        self.assertEqual([e["stage"] for e in summary["trace"]], ["plan", "test", "test", "step", "repair"])
        self.assertEqual([w["status"] for w in summary["tests_written"]], ["pass", "fail"])
        self.assertTrue(summary["repro_fails_before"] and summary["repro_passes_after"] and summary["public_ok"])
        self.assertEqual(summary["calls"], 5)
        prompts = all_prompts([t])
        self.assertIn("PASSED on the current (buggy) code", prompts[2])
        self.assertIn("# Your previous test", prompts[2])
        self.assertIn("You must write the test", prompts[2])
        self.assertIn("Result on the current code: it FAILS", prompts[3])
        self.assertIn("Visible project tests (they pass on the original code): FAIL", prompts[4])
        self.assertIn("Your reproduction test tests/test_repro_t1.py: FAIL", prompts[4])
        selected = out["selected"]
        self.assertEqual(selected["stage"], "repair")
        self.assertEqual(out["selection"]["tier"], "own_repro")
        runs = ctx.events.of("agent_test_run")
        self.assertEqual([e["purpose"] for e in runs if e["target"] == "agent_test"],
                         ["repro_on_original", "repro_on_original", "own_on_patch", "own_on_patch"])
        self.assertEqual([e["classification"] for e in runs if e["target"] == "agent_test"], ["pass", "fail", "fail", "pass"])
        self.assertEqual([e["ok"] for e in runs if e["target"] == "public_tests"], [False, True])
        self.assertEqual(len(ctx.events.of("agent_test_text")), 2)
        self.assertEqual(g.grade(B1, selected["patch_text"])["status"], "passed")

    def test_own_test_failure_drives_repair(self):
        script = Script([gen(plan_json(["stockroom/pricing.py"])), gen(test_answer(GOOD)),
                         gen(patch_answer(harmless_pricing("x"))), gen(reference_answer(B1))])
        ctx, (t,) = t_context(script)
        out = a.policy_t1(ctx, calls=8)
        repair_prompt = all_prompts([t])[3]
        self.assertIn("Visible project tests (they pass on the original code): PASS", repair_prompt)
        self.assertIn("Your reproduction test tests/test_repro_t1.py: FAIL", repair_prompt)
        self.assertIn("AssertionError", repair_prompt)
        self.assertEqual(out["agents"]["t1"]["calls"], 4)
        self.assertEqual(len(out["agents"]["t1"]["trace"]), 4)
        self.assertTrue(out["selected"]["repro_passes_after"])
        first = [c for c in ctx.patches if c["stage"] == "patch"][0]
        self.assertTrue(first["public_ok"])
        self.assertFalse(first["repro_passes_after"])

    def test_test_only_repair_keeps_patch_and_rejects_non_reproducing_test(self):
        def test_only(text):
            return json.dumps({"action": "patch", "notes": "the test was wrong"}) + \
                f"\n=== TEST: tests/test_repro_t1.py ===\n{text}=== END TEST ===\n"
        script = Script([gen(plan_json(["stockroom/pricing.py"])), gen(test_answer(WRONG)),
                         gen(reference_answer(B1)),        # real fix, but the wrong test still fails
                         gen(test_only(WEAK)),             # rejected: passes on the original code
                         gen(test_only(GOOD))])            # adopted: fails on original, passes on the kept fix
        ctx, (t,) = t_context(script)
        out = a.policy_t1(ctx, calls=8)
        self.assertIn("Your corrected test was rejected", all_prompts([t])[4])
        self.assertEqual(len(ctx.patches), 1, "a test-only repair keeps the current patch")
        summary = out["agents"]["t1"]
        self.assertEqual([w["status"] for w in summary["tests_written"]], ["fail", "pass", "fail"])
        self.assertEqual(summary["test_sha256"], a.sha(GOOD))
        self.assertTrue(summary["repro_passes_after"])
        self.assertEqual(out["selected"]["own_test_sha256"], a.sha(GOOD))
        self.assertEqual(summary["calls"], 5)

    def test_garbage_never_crashes_and_respects_call_cap(self):
        script = Script([gen("{not json"), gen("nothing", think="t" * 4 * 30000, closes=False), gen("no test"),
                         gen("=== END FILE ==="), gen("x"), gen('{"action": "patch"}'), gen("y"), gen("z")])
        ctx, (t,) = t_context(script)
        out = a.policy_t1(ctx, calls=8)
        self.assertEqual(out["candidates"], [])
        self.assertIsNone(out["selected"])
        self.assertEqual(out["selection"]["rule"], "no_valid_patch")
        self.assertEqual(out["agents"]["t1"]["calls"], 8)
        self.assertFalse(out["agents"]["t1"]["repro_fails_before"])
        self.assertIn("no usable test", t.prompts[2]["user"])
        self.assertIn("(none: rely on the bug report)", t.prompts[4]["user"])
        self.assertIn("You must choose Option B", t.prompts[7]["user"])


def tcand(agent, key, order, rank=0, public=True, before=True, after=True):
    return dict(agent=agent, key=key, order=order, rank=rank, valid=True, no_op=False, patch_text=f"p{order}",
                public_ok=public, repro_fails_before=before, repro_passes_after=after, selfcheck=dict(ok=public))


class CrossValidationTests(unittest.TestCase):
    def test_scoring_excludes_own_test_and_beats_cluster(self):
        cands = [tcand("c0", "K1", 1, 0), tcand("c1", "K2", 2, 1), tcand("c2", "K2", 3, 2),
                 tcand("c3", "K3", 4, 3, after=False)]
        tests = {"c0": {}, "c1": {}, "c2": {}, "c3": {}}
        passes = {("K1", t): True for t in tests}
        passes.update({("K2", "c0"): False, ("K2", "c1"): True, ("K2", "c2"): True, ("K2", "c3"): False})
        best, info = a.select_crossval(cands, tests, passes)
        self.assertEqual((best["agent"], info["rule"], info["tier"]), ("c0", "crossval", "own_repro"))
        scores = {row["agent"]: row["score"] for row in info["scores"]}
        self.assertEqual(scores, {"c0": 3, "c1": 1, "c2": 1}, "own test excluded; c3 not qualified")
        only_own = {("K1", "c0"): True}
        best, info = a.select_crossval([tcand("c0", "K1", 1, 0), tcand("c1", "K2", 2, 1)], tests, only_own)
        self.assertEqual(info["selected_score"], 0, "passing only one's own test earns nothing")
        self.assertEqual(info["rule"], "earliest")

    def test_ties_go_to_cluster_then_earliest_and_tiers_fall_back(self):
        tests = {"c0": {}, "c1": {}, "c2": {}}
        cands = [tcand("c0", "K1", 1, 0), tcand("c1", "K2", 2, 1), tcand("c2", "K2", 3, 2)]
        best, info = a.select_crossval(cands, tests, {})
        self.assertEqual((best["agent"], info["rule"], info["cluster_size"]), ("c1", "vote", 2))
        best, info = a.select_crossval([tcand("c1", "K2", 9, 1), tcand("c0", "K1", 5, 0)], tests, {})
        self.assertEqual((best["agent"], info["rule"]), ("c0", "earliest"))
        best, info = a.select_crossval([tcand("c0", "K1", 1, 0, before=False), tcand("c1", "K2", 2, 1, public=False)],
                                       tests, {})
        self.assertEqual((best["agent"], info["tier"]), ("c0", "public_only"))
        best, info = a.select_crossval([tcand("c0", "K1", 1, 0, public=False)], tests, {})
        self.assertEqual(info["tier"], "valid_only")
        self.assertIsNone(a.select_crossval([None, dict(tcand("c0", "K", 1), valid=False)], tests, {})[0])

    def responder_t3(self):
        """t3c0, t3c1: report-example hack + example-only test (self-consistent, wrong);
        t3c2: real fix + boundary test; t3c3: good test, wrong patch it never repairs."""
        plans = {"t3c0": (TEN_ONLY, hack_pricing()), "t3c1": (TEN_ONLY, hack_pricing()),
                 "t3c2": (GOOD, reference_files()), "t3c3": (GOOD, harmless_pricing("w"))}

        def responder(user, seed):
            if "(test-first method)" in user:
                return gen(plan_json(["stockroom/pricing.py"]))
            chain = re.search(r"test_repro_(t3c\d)", user).group(1)
            test, patch = plans[chain]
            if "Phase 1 of 2" in user:
                return gen(test_answer(test, path=f"tests/test_repro_{chain}.py"))
            return gen(patch_answer(patch))
        return responder

    def test_t3_cross_validation_beats_self_consistent_majority(self):
        spy = SpyExecutor()
        pool, transports = pool_of(self.responder_t3(), n=2)
        order = []
        holder = {}
        real_events = a.Events

        class SpyEvents(real_events):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                holder["events"] = self

        def grade_fn(patch):
            order.append([e["type"] for e in holder["events"].records])
            return g.grade(B1, patch)
        a.Events = SpyEvents
        try:
            record = a.run_attempt(B1, "T3", 1, pool, executor=spy, grade_fn=grade_fn, k=4, calls=5)
        finally:
            a.Events = real_events
        self.assertEqual(record["status"], "completed", record.get("error"))
        sel = record["selection"]
        self.assertEqual((sel["selected_agent"], sel["rule"], sel["tier"]), ("t3c2", "crossval", "own_repro"))
        self.assertEqual({r["agent"]: r["score"] for r in sel["scores"]}, {"t3c0": 1, "t3c1": 1, "t3c2": 3})
        self.assertEqual(sel["own_repro_qualified"], 3)
        self.assertTrue(record["fixed"])
        chains = record["evidence"]["chains"]
        self.assertFalse(chains["t3c3"]["repro_passes_after"])
        self.assertTrue(chains["t3c3"]["repro_fails_before"])
        self.assertEqual(len(record["evidence"]["valid_tests"]), 4)
        self.assertEqual(len(record["evidence"]["matrix"]), 2 * 4)
        types = [e["type"] for e in record["events"].records]
        self.assertLess(types.index("selection_evidence"), types.index("selection_frozen"))
        self.assertLess(types.index("selection_frozen"), types.index("hidden_grade"))
        self.assertIn("selection_frozen", order[0])
        self.assertTrue(any(e["purpose"] == "crossval" for e in record["events"].of("agent_test_run")))
        self.assertTrue(all(p["mode"] == "public_tests" for p in spy.payloads))
        self.assertIn("ORACLE", record["oracle"]["label"])
        for c in record["candidates"]:
            self.assertIn("repro_passes_after", c)
        # the plain S3 rule would have picked the self-consistent hack cluster
        self.assertEqual(a.select([dict(c, selfcheck=dict(ok=True)) for c in
                                   [dict(tcand("t3c0", "H", 1, 0)), dict(tcand("t3c1", "H", 2, 1)),
                                    dict(tcand("t3c2", "R", 3, 2))]])[0]["key"], "H")

    def test_selection_never_reads_hidden_material(self):
        bundle = g.agent_bundle(B1)
        spy = SpyExecutor()
        for policy, kw, responder in (("T3", dict(k=4, calls=5), self.responder_t3()),
                                      ("V3", dict(k=2, calls=3), V3Tests.responder(approve_fix=True)),
                                      ("T1", dict(calls=5), self.responder_t3_single())):
            with self.subTest(policy):
                pool, _ = pool_of(responder, n=2)
                events = a.Events()
                with HiddenTripwire():
                    out = a.run_policy(bundle, policy, pool, events, 1, a.make_selfcheck("stockroom", spy),
                                       tester=a.make_agent_tester(bundle, spy), **kw)
                self.assertIsNotNone(out["selected"])
                self.assertEqual(events.of("hidden_grade") + events.of("oracle_grade"), [])
        self.assertTrue(spy.payloads)
        self.assertTrue(all(p["mode"] == "public_tests" and "probes" not in p for p in spy.payloads))

    def responder_t3_single(self):
        fix = reference_answer(B1)

        def responder(user, seed):
            if "(test-first method)" in user:
                return gen(plan_json(["stockroom/pricing.py"]))
            if "Phase 1 of 2" in user:
                return gen(test_answer(GOOD))
            return gen(fix)
        return responder


class V3Tests(unittest.TestCase):
    @staticmethod
    def responder(approve_fix=True, approve_all=False):
        served, lock = [], threading.Lock()
        fix, wrong = reference_answer(B1), patch_answer(harmless_pricing("a"))

        def responder(user, seed):
            if "A colleague proposes the change" in user:
                fixed = "+            if quantity >= tier.min_quantity:" in user
                ok = approve_all or (fixed and approve_fix)
                return gen(json.dumps({"fixes_report": ok, "risk": "none" if ok else "does not touch the tiers"}))
            if "`files` lists 1 or 2 paths" in user:
                return gen(plan_json(["stockroom/pricing.py"]))
            with lock:
                first = not served
                served.append(1)
            return gen(fix if first else wrong)
        return responder

    def test_review_overrides_wrong_majority(self):
        pool, transports = pool_of(self.responder(), n=2)
        record = a.run_attempt(B1, "V3", 1, pool, grade_fn=lambda p: g.grade(B1, p), k=4, calls=3)
        self.assertEqual(record["status"], "completed", record.get("error"))
        sel = record["selection"]
        self.assertEqual((sel["rule"], sel["selected_approved"], sel["reviewed_keys"]), ("review", True, 2))
        self.assertEqual(sel["clusters"], [3, 1])
        self.assertTrue(record["fixed"])
        reviews = [p for p in all_prompts(transports) if "A colleague proposes the change" in p]
        self.assertEqual(len(reviews), 2)
        for prompt in reviews:
            self.assertIn("# Proposed change (unified diff)", prompt)
            self.assertIn("--- BEGIN stockroom/pricing.py ---", prompt)
        self.assertEqual(len(record["evidence"]["reviews"]), 2)
        self.assertEqual(len(record["events"].of("review")), 2)

    def test_all_approved_falls_back_to_cluster(self):
        pool, _ = pool_of(self.responder(approve_all=True), n=2)
        record = a.run_attempt(B1, "V3", 1, pool, grade_fn=lambda p: dict(status="failed"), oracle=False, k=4, calls=3)
        self.assertEqual((record["selection"]["rule"], record["selection"]["cluster_size"]), ("vote", 3))
        self.assertEqual(a.parse_review('{"fixes_report": "yes", "risk": "x"}')["fixes_report"], True)
        self.assertIsNone(a.parse_review("garbage")["fixes_report"])


class NewPolicyLeakageTests(unittest.TestCase):
    """No hidden material in any prompt (incl. sandbox outputs) of T1/T3/V3, on all 9 prototype cases."""

    def responder_for(self, case_id):
        bundle = g.agent_bundle(case_id)
        editable, files, package = bundle["editable_paths"], bundle["files"], g.load_project(bundle["project"])["package"]
        base = LeakageTests().responder_for(case_id)
        test = (f"import unittest\nimport {package}\n\n\nclass R(unittest.TestCase):\n    def test_x(self):\n"
                f"        self.assertEqual({package}.__name__, 'x')\n")

        def responder(user, seed):
            if "(test-first method)" in user:
                return gen(plan_json(editable[:2]))
            if "Phase 1 of 2" in user:
                return gen(test_answer(test, files=editable[:1]))
            if "Phase 2 of 2" in user:
                target = re.findall(r"--- BEGIN (\S+) ---", user)[0]
                return gen(patch_answer({target: files[target] + "\nraise RuntimeError('broken')\n"},
                                        location=(target, "f")))
            if ": repair." in user:
                return gen("I give up")
            if "A colleague proposes the change" in user:
                return gen('{"fixes_report": false, "risk": "breaks import"}')
            return base(user, seed)
        return responder

    def test_no_hidden_material_in_prompts_or_sandbox_payloads(self):
        for case_id in PROTOTYPE_CASES:
            with self.subTest(case_id):
                responder = self.responder_for(case_id)
                prompts, spy = [], SpyExecutor()
                for policy, kwargs in (("T1", dict(calls=5)), ("T3", dict(k=2, calls=5)), ("V3", dict(k=2, calls=3))):
                    pool, transports = pool_of(responder, n=2)
                    record = a.run_attempt(case_id, policy, 1, pool, oracle=False, executor=spy,
                                           grade_fn=lambda p: dict(status="failed"), **kwargs)
                    self.assertEqual(record["status"], "completed", record.get("error"))
                    prompts += all_prompts(transports)
                blob = "\n".join(prompts)
                self.assertIn("Result on the current code: it FAILS", blob)
                self.assertIn("Test results on your patched code", blob)
                self.assertIn("A colleague proposes the change", blob)
                secrets = LeakageTests().secrets(case_id)
                for secret in secrets:
                    self.assertNotIn(secret, blob)
                self.assertTrue(all(p["mode"] == "public_tests" and "probes" not in p for p in spy.payloads))
                payloads = json.dumps(spy.payloads)
                for secret in secrets[:2]:
                    self.assertNotIn(secret, payloads)


class NewPolicyRunnerTests(unittest.TestCase):
    def args(self, **kw):
        base = dict(cases=[B1], policies=["S1", "T1", "T3", "V3"], seeds=[1], endpoints=["fake0"], model="m",
                    per_endpoint=1, parallel_attempts=1, docker_host=None, no_oracle=True, idle_timeout=120,
                    max_calls=None, max_completion_tokens=None)
        return r.argparse.Namespace(**dict(base, **kw))

    def test_per_policy_budgets_and_choices(self):
        plan = r.build_plan(self.args())
        self.assertEqual(plan["policies"]["S1"], dict(kwargs=dict(calls=6), nominal_max_calls=6))
        self.assertEqual(r.attempt_budget(plan, "S1"), (48, 256_000))
        self.assertEqual(r.attempt_budget(plan, "T1"), (48, 256_000))
        self.assertEqual(r.attempt_budget(plan, "T3"), (64, 512_000))
        self.assertEqual(r.attempt_budget(plan, "V3"), (56, 320_000))
        self.assertIn("OTHER agents", plan["policies"]["T3"]["selection"])
        capped = r.build_plan(self.args(max_calls=30))
        self.assertEqual(r.attempt_budget(capped, "T3"), (30, 512_000))
        self.assertEqual(r.attempt_budget(capped, "S1"), (30, 256_000))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            r.main(["--policies", "T9"])

    def test_execute_t1_writes_agent_test_runs_to_attempt_log(self):
        def responder(user, seed):
            if "(test-first method)" in user:
                return gen(plan_json(["stockroom/pricing.py"]))
            if "Phase 1 of 2" in user:
                return gen(test_answer(GOOD))
            return gen(reference_answer(B1))
        pool, _ = pool_of(responder, n=1)
        plan = r.build_plan(self.args(policies=["T1"], no_oracle=False))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            summary = r.execute(plan, out, pool, parallel=1, log=lambda *_: None)
            self.assertEqual(summary["policies"]["T1"]["fixed"], 1)
            row = json.loads(open(os.path.join(out, "attempts.jsonl")).readline())
            self.assertEqual(row["budget"]["max_calls"], 48)
            self.assertTrue(row["evidence"]["chains"]["t1"]["repro_passes_after"])
            events = [json.loads(line) for line in open(os.path.join(out, "attempts", row["attempt_id"] + ".jsonl"))]
            types = [e["type"] for e in events]
            self.assertIn("agent_test_run", types)
            self.assertIn("agent_test_text", types)
            self.assertLess(types.index("selection_evidence"), types.index("hidden_grade"))
            self.assertTrue(any(e["type"] == "oracle_grade" for e in events))


if __name__ == "__main__":
    unittest.main()
