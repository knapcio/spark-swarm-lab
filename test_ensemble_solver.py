import argparse
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import threading
import unittest

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


if __name__ == "__main__":
    unittest.main()
