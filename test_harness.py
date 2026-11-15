import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from fractions import Fraction as F
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

import harness as h


class ArithmeticTests(unittest.TestCase):
    def test_exact_fraction_and_consumption(self):
        state = (F(3), F(2), F(5))
        self.assertEqual(h.apply_action(state, {"i": 0, "j": 1, "op": "/"}, True), (F(5), F(3, 2)))
        self.assertEqual(state, (F(3), F(2), F(5)))
        with self.assertRaises(h.InvalidMove):
            h.apply_action(state, {"i": 0, "j": 1, "op": "/"})

    def test_illegal_moves(self):
        cases = [None, {}, {"i": 0, "j": 0, "op": "+"},
                 {"i": True, "j": 1, "op": "+"}, {"i": -1, "j": 1, "op": "+"},
                 {"i": 0, "j": 8, "op": "+"}, {"i": 0, "j": 1, "op": "**"},
                 {"i": 0, "j": 1, "op": "+", "code": "evil"},
                 {"i": 0, "j": 1, "op": "-"}]
        for action in cases:
            with self.subTest(action=action), self.assertRaises(h.InvalidMove):
                h.apply_action((F(2), F(3)), action)
        with self.assertRaises(h.InvalidMove):
            h.apply_action((F(2), F(0)), {"i": 0, "j": 1, "op": "/"})

    def test_real_952_solution(self):
        # ((100+3)*6*75/50)+25 = 952.
        state = tuple(map(F, (25, 50, 75, 100, 3, 6)))
        for action in [dict(i=3,j=4,op="+"), dict(i=3,j=4,op="*"),
                       dict(i=2,j=3,op="*"), dict(i=2,j=1,op="/"),
                       dict(i=0,j=1,op="+")]:
            state = h.apply_action(state, action)
        self.assertTrue(h.solved(state, 952))
        self.assertEqual(state, (F(952),))

    def test_json_is_data_only(self):
        self.assertEqual(h.parse_json_response('```json\n{"i":0,"j":1,"op":"+"}\n```')["op"], "+")
        for content in ["__import__('os').system('echo evil')", '[1,2]', '{} trailing']:
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                h.parse_json_response(content)


class BudgetTests(unittest.TestCase):
    def test_parallel_reservations_do_not_overshoot(self):
        budget = h.Budget(7, 30)
        with ThreadPoolExecutor(max_workers=30) as pool:
            accepted = list(pool.map(lambda _: budget.reserve(10), range(30)))
        self.assertEqual(sum(accepted), 3)
        self.assertEqual(budget.snapshot()["completion_tokens_reserved"], 30)
        budget.settle(10, 2)
        self.assertFalse(budget.reserve(10))
        budget.settle(10, 1)
        self.assertTrue(budget.reserve(10))

    def test_missing_usage_and_failure_are_charged(self):
        budget = h.Budget(1, 20)
        self.assertTrue(budget.reserve(20))
        budget.settle(20)
        self.assertEqual(budget.snapshot()["completion_tokens_charged"], 20)
        self.assertFalse(budget.reserve(1))


class ClientTests(unittest.TestCase):
    def test_request_body_and_actual_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            events = h.Events(path, "independent")
            budget = h.Budget(1, 20)
            client = h.Client(["http://localhost:1/v1"], "nemotron-lightning", 1, 20, 1,
                              budget, events, 7)
            payload = dict(choices=[dict(message=dict(content='{"i":0,"j":1,"op":"+"}'))],
                           usage=dict(prompt_tokens=70, completion_tokens=7, total_tokens=77))
            def transport(request, timeout):
                body = json.loads(request.data)
                self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
                self.assertEqual(body["max_tokens"], 20)
                self.assertEqual(body["model"], "nemotron-lightning")
                self.assertEqual(request.full_url, "http://localhost:1/v1/chat/completions")
                return io.BytesIO(json.dumps(payload).encode())
            try:
                with patch("urllib.request.urlopen", side_effect=transport):
                    result = client.call(0, "propose", "prompt", puzzle_id="p1", node_id="n1")
                self.assertEqual(result["op"], "+")
                self.assertEqual(budget.snapshot()["completion_tokens_charged"], 7)
                self.assertEqual(budget.snapshot()["completion_tokens_reserved"], 0)
            finally:
                events.close()
            last = json.loads(path.read_text().splitlines()[-1])
            self.assertEqual(last["usage"]["total_tokens"], 77)
            self.assertFalse(last["usage"]["estimated"])


class FakeClient:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = []

    def call(self, agent_id, stage, prompt, **context):
        with self.lock:
            self.calls.append((stage, agent_id))
        if stage == "propose":
            # 1+2=3 or 1*2=2, two distinct candidates.
            return dict(i=0, j=1, op="+" if agent_id % 2 == 0 else "*")
        choices = json.loads(prompt.split("Candidates: ", 1)[1].split(". Return only", 1)[0])
        chosen = next(c for c in choices if c["action"]["op"] == "+")
        return {"candidate_id": chosen["candidate_id"]}


class ExperimentTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(agents=4, target=3, rounds=1, allow_fractions=False, seed=1)

    def test_vote_stage_and_event_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            events = h.Events(path, "democracy")
            client = FakeClient()
            experiment = h.Experiment(self.args(), client, events)
            try:
                result = experiment.run((F(1), F(2)), "test", "democracy")
            finally:
                experiment.pool.shutdown()
                events.close()
            self.assertTrue(result["solved"])
            self.assertEqual([x[0] for x in client.calls], ["propose"] * 4 + ["vote"] * 4)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r["event_id"] for r in rows], list(range(1, len(rows) + 1)))
            nodes = {r["node_id"]: r for r in rows if r["type"] == "node"}
            for node in nodes.values():
                if node["parent_id"]:
                    self.assertIn(node["parent_id"], nodes)
                    self.assertEqual(len(node["state"]), len(nodes[node["parent_id"]]["state"]) - 1)
            self.assertEqual(sum(r["type"] == "vote" for r in rows), 4)
            self.assertEqual(sum(r.get("reason") == "duplicate_state" for r in rows), 2)
            self.assertTrue(any(r["type"] == "pruned" and r["reason"] == "vote_loser" for r in rows))

    def test_independent_agents_have_separate_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            events = h.Events(Path(directory)/"events.jsonl", "independent")
            experiment = h.Experiment(self.args(), FakeClient(), events)
            try:
                result = experiment.run((F(1), F(2)), "test", "independent")
                self.assertEqual(sum(o["solved"] for o in result["outcomes"]), 2)
            finally:
                experiment.pool.shutdown()
                events.close()

    def test_weights_use_past_binary_reward(self):
        experiment = h.Experiment(self.args(), FakeClient(), None,
                                  {"0": {"games": 8, "successes": 6}})
        try:
            self.assertEqual(experiment.weight(0), 0.7)
            self.assertEqual(experiment.weight(1), 0.5)
        finally:
            experiment.pool.shutdown()

    def test_overlapping_calibration_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"rep.json"
            path.write_text(json.dumps(dict(model="test", agents=1, scores={"0":dict(games=1,successes=1)},
                                            puzzle_fingerprints=["same"])))
            with self.assertRaisesRegex(ValueError, "overlaps"):
                h.load_reputation(path, "test", 1, "same")

    def test_failed_calibration_does_not_create_reputation(self):
        with tempfile.TemporaryDirectory() as directory:
            path, rep = Path(directory)/"events.jsonl", Path(directory)/"rep.json"
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
                with self.assertRaisesRegex(RuntimeError, "calibration incomplete"), redirect_stdout(io.StringIO()):
                    h.main(["--method", "calibrate", "--endpoint", "http://localhost:1/v1",
                            "--model", "fake", "--agents", "1", "--rounds", "1",
                            "--calibration-puzzles", "1,2:3", "--reputation", str(rep), "--events", str(path)])
            self.assertFalse(rep.exists())
            rows = [json.loads(s) for s in path.read_text().splitlines()]
            self.assertEqual(rows[-1]["status"], "failed")
            self.assertEqual(rows[-1]["budget"]["completion_tokens_reserved"], 0)
            self.assertEqual(rows[-1]["budget"]["completion_tokens_charged"], 192)

    def test_no_valid_votes_does_not_silently_choose(self):
        client = FakeClient()
        original = client.call
        client.call = lambda agent_id, stage, prompt, **kw: None if stage == "vote" else original(agent_id,stage,prompt,**kw)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"events.jsonl"
            events = h.Events(path, "democracy")
            experiment = h.Experiment(self.args(), client, events)
            try:
                result = experiment.run((F(1), F(2)), "test", "democracy")
            finally:
                experiment.pool.shutdown()
                events.close()
            self.assertFalse(result["solved"])
            rows = [json.loads(s) for s in path.read_text().splitlines()]
            self.assertTrue(any(r.get("reason") == "no_valid_votes" for r in rows))
            self.assertFalse(any(r["type"] == "chosen" for r in rows))


if __name__ == "__main__":
    unittest.main()
