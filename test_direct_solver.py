import argparse
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import unittest

import harness as h
from direct_solver import run_direct


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


if __name__ == "__main__":
    unittest.main()
