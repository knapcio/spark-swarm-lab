import argparse
from contextlib import redirect_stderr
from fractions import Fraction as F
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import harness as h


class EnsembleTests(unittest.TestCase):
    def trial(self, method, initial, target):
        class Client:
            def __init__(self):
                self.thinking, self.max_tokens = False, 192
                self.calls, self.lock = [], threading.Lock()
            def call(self, agent, stage, prompt, **context):
                with self.lock:
                    self.calls.append((agent, stage, self.thinking, self.max_tokens))
                if stage == "plan":
                    return {"moves": [{"i": 1, "j": 3, "op": "*"}]}
                return {"i": 0, "j": 1, "op": "+"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            events, client = h.Events(path, method), Client()
            args = argparse.Namespace(agents=4, target=target, rounds=5,
                                      allow_fractions=False, seed=1)
            e = h.Experiment(args, client, events)
            try:
                outcome = e.run(tuple(map(F, initial)), "test", method)
            finally:
                e.pool.shutdown()
                events.close()
            return outcome, client, [json.loads(line) for line in path.read_text().splitlines()]

    def test_parallel_plans_preserve_agent_identity_and_exact_verification(self):
        outcome, client, rows = self.trial("ensemble", [2, 3, 7, 8], 24)
        self.assertTrue(outcome["solved"])
        self.assertEqual({r[0] for r in client.calls}, set(range(4)))
        self.assertEqual(len(client.calls), 4)
        self.assertTrue(all(r["solved"] for r in outcome["outcomes"]))
        ids = [r["proposal_id"] for r in rows if r["type"] == "proposal"]
        self.assertEqual(len(set(ids)), 4)

    def test_cascade_skips_expensive_stage_on_cheap_success(self):
        outcome, client, _ = self.trial("cascade", [1, 2], 3)
        self.assertTrue(outcome["solved"])
        self.assertFalse(outcome["fallback_used"])
        self.assertFalse(any(call[1] == "plan" for call in client.calls))

    def test_cascade_fallback_records_budget_mode_and_restores_client(self):
        outcome, client, rows = self.trial("cascade", [2, 3, 7, 8], 24)
        self.assertTrue(outcome["solved"])
        self.assertTrue(outcome["fallback_used"])
        self.assertEqual([c[2:] for c in client.calls if c[1] == "plan"], [(True, 8192)])
        self.assertEqual((client.thinking, client.max_tokens), (False, 192))
        phases = [r["phase"] for r in rows if r["type"] == "phase_start"]
        self.assertEqual(phases, ["cheap_parallel_search", "reasoning_full_plan"])


class RefineTests(unittest.TestCase):
    def trial(self, plans):
        class Client:
            thinking, max_tokens = True, 8192
            def __init__(self): self.calls = []
            def call(self, agent, stage, prompt, **context):
                self.calls.append(dict(agent=agent, stage=stage, prompt=prompt, **context))
                return plans[min(len(self.calls) - 1, len(plans) - 1)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            events, client = h.Events(path, "refine"), Client()
            args = argparse.Namespace(agents=1, target=24, rounds=5, allow_fractions=False, seed=7)
            e = h.Experiment(args, client, events)
            try:
                result = e.run(tuple(map(F, (2, 3, 7, 8))), "unchanged-puzzle", "refine")
            finally:
                e.pool.shutdown()
                events.close()
            return result, client.calls, [json.loads(line) for line in path.read_text().splitlines()]

    def test_illegal_complete_plan_is_revised_using_only_own_exact_feedback(self):
        illegal = {"moves": [{"i": 0, "j": 0, "op": "+"}]}
        valid = {"moves": [{"i": 1, "j": 3, "op": "*"}]}
        result, calls, rows = self.trial([illegal, valid])
        self.assertTrue(result["solved"])
        self.assertEqual(result["plan_attempts"], 2)
        self.assertEqual(result["plan"], valid)
        self.assertEqual({row["agent"] for row in calls}, {0})
        self.assertEqual({row["puzzle_id"] for row in calls}, {"unchanged-puzzle"})
        self.assertEqual([row["plan_revision"] for row in calls], [0, 1])
        self.assertIn("Full-plan attempt 2 of 4", calls[1]["prompt"])
        self.assertIn("i and j must be distinct integer indices", calls[1]["prompt"])
        self.assertIn(json.dumps(illegal), calls[1]["prompt"])
        self.assertIn('Verified final state: ["2", "3", "7", "8"]', calls[1]["prompt"])
        self.assertLessEqual(len(calls[1]["prompt"]) - len(calls[0]["prompt"]), 4000)
        self.assertEqual([row["solved"] for row in rows if row["type"] == "reward"], [False, True])

    def test_first_correct_plan_stops_without_a_second_request(self):
        result, calls, rows = self.trial([{"moves": [{"i": 1, "j": 3, "op": "*"}]}])
        self.assertTrue(result["solved"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(row["type"] == "plan_revision" for row in rows), 1)

    def test_four_plan_cap_and_attempt_specific_prompts(self):
        result, calls, _ = self.trial([{"moves": []}])
        self.assertFalse(result["solved"])
        self.assertEqual(result["plan_attempts"], 4)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len({row["prompt"] for row in calls}), 4)
        self.assertEqual([row["plan_revision"] for row in calls], [0, 1, 2, 3])

    def test_benchmark_arm_is_single_reasoning_agent_with_8k_profile(self):
        from run_benchmark import ARMS
        self.assertEqual(ARMS["solo_refine_thinking_8k"], ("refine", 1, True))

    def test_cli_refine_rejects_multiple_agents_before_transport(self):
        with patch("urllib.request.urlopen") as transport, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                h.main(["--method", "refine", "--agents", "2", "--endpoint", "http://127.0.0.1:1/v1",
                        "--model", "unused", "--events", "unused.jsonl"])
        self.assertEqual(error.exception.code, 2)
        transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
