import argparse
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import unittest

import harness as h
from direct_solver import run_direct
from unittest.mock import patch


class DirectTests(unittest.TestCase):
    def trial(self, result):
        class Client:
            calls = []
            def call(self, agent, stage, prompt, **context):
                self.calls.append(stage)
                return result
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            events = h.Events(path, "direct")
            args = argparse.Namespace(agents=1, target=24, rounds=3,
                                      allow_fractions=False, seed=1)
            client = Client()
            experiment = h.Experiment(args, client, events)
            try:
                outcome = run_direct(experiment, (F(2), F(3), F(7), F(8)), "test")
            finally:
                experiment.pool.shutdown()
                events.close()
            return outcome, [json.loads(line) for line in path.read_text().splitlines()], client.calls

    def test_terminal_prefix_needs_one_model_call(self):
        result, rows, calls = self.trial({"moves": [{"i": 1, "j": 3, "op": "*"},
                                                   {"i": 99, "j": 0, "op": "+"}]})
        self.assertTrue(result["solved"])
        self.assertEqual(calls, ["plan"])
        self.assertEqual(sum(r["type"] == "proposal" for r in rows), 1)

    def test_invalid_plan_and_illegal_arithmetic_do_not_solve(self):
        for plan in ({"moves": []}, {"moves": [{"i": 0, "j": 1, "op": "/"}]},
                     {"moves": [{"i": 1, "j": 3, "op": "*"}] * 4}):
            with self.subTest(plan=plan):
                result, rows, calls = self.trial(plan)
                self.assertFalse(result["solved"])
                self.assertEqual(calls, ["plan"])
                self.assertFalse(any(r["type"] == "chosen" for r in rows))

    def test_default_prompt_unchanged_and_opt_in_feedback_is_bounded(self):
        class Client:
            def __init__(self): self.prompts = []
            def call(self, agent, stage, prompt, **context):
                self.prompts.append(prompt)
                return {"moves": []}
        with tempfile.TemporaryDirectory() as directory:
            events = h.Events(Path(directory) / "events.jsonl", "direct")
            args = argparse.Namespace(agents=1, target=24, rounds=3, allow_fractions=False, seed=1)
            client = Client()
            experiment = h.Experiment(args, client, events)
            try:
                state = tuple(map(F, (2, 3, 7, 8)))
                result = run_direct(experiment, state, "same-puzzle")
                run_direct(experiment, state, "same-puzzle", feedback_text="x" * 10000)
            finally:
                experiment.pool.shutdown()
                events.close()
        expected = ("Target 24. Current indexed numbers: {0: '2', 1: '3', 2: '7', 3: '8'}. "
            "Give one complete plan to reach the target using any subset of numbers. "
            "Each move consumes two different indexed numbers and appends their result; "
            "remaining numbers keep their order and are reindexed from zero. "
            "Use +,-,*,/. Every intermediate result must be positive integer. "
            "Use at most 3 moves. Return only a JSON object with key moves, "
            "an array of objects with integer indices i,j and single-character operator op.")
        self.assertEqual(client.prompts[0], expected)
        self.assertEqual(client.prompts[1], expected + "\n" + "x" * 3999)
        self.assertEqual(result["plan"], {"moves": []})
        self.assertEqual(result["validation_error"], "Expected a bounded nonempty moves array")

    def test_plan_code_is_data_not_executed(self):
        with patch("os.system") as system:
            result, _, _ = self.trial({"moves": [{"i": 0, "j": 1, "op": "__import__('os').system('id')"}]})
        system.assert_not_called()
        self.assertFalse(result["solved"])
        self.assertEqual(result["validation_error"], "unsupported operator")


if __name__ == "__main__":
    unittest.main()
