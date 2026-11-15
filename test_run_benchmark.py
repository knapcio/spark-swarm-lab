"""Offline controller tests. Synthetic children and mocked metrics; no model API."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_benchmark as runner


class ControllerTests(unittest.TestCase):
    def test_only_producer_verifier_events_are_proof(self):
        for record in ({"type": "request_end", "response": '{"solved": true}'},
                       {"type": "proposal", "solved": True},
                       {"type": "controller_stop", "source": "controller", "solved": True},
                       {"type": "reward", "solved": "true"}):
            self.assertFalse(runner.verified([record]))
        for kind in ("reward", "puzzle_end", "run_end"):
            self.assertTrue(runner.verified([{"type": kind, "solved": 1}]))

    def test_proof_counts_even_with_deadline(self):
        row = runner.metrics([{"type": "reward", "agent_id": 0, "solved": True}], deadline=True)
        self.assertTrue(row["solved"])
        self.assertEqual(row["successful_paths"], 1)
        self.assertEqual(row["status"], "deadline")

    def test_stale_server_cost_is_unknown_not_zero(self):
        before = dict(prompt=100, completion=40, running=0, waiting=0)
        after = dict(prompt=120, completion=46, running=0, waiting=0)
        result = runner.server_cost(before, after, True, dict(prompt_tokens=20, completion_tokens=7))
        self.assertFalse(result["server_cost_known"])
        self.assertEqual(result["server_cost_reason"], "server_delta_below_completed_client_usage")
        self.assertIsNone(result["server_prompt_tokens"])
        self.assertIsNone(result["server_completion_tokens"])
        self.assertEqual(after["completion"], 46)

    def test_server_cost_accepts_complete_client_floor(self):
        result = runner.server_cost(dict(prompt=100, completion=40, running=0, waiting=0),
                                    dict(prompt=120, completion=47), True,
                                    dict(prompt_tokens=20, completion_tokens=7))
        self.assertTrue(result["server_cost_known"])
        self.assertEqual(result["server_completion_tokens"], 7)

    def test_drain_requires_two_separated_zero_observations(self):
        clock, samples = [0.0], []
        def sample(*args):
            samples.append(clock[0])
            return dict(running=0, waiting=0)
        with patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(runner.time, "sleep", side_effect=lambda n: clock.__setitem__(0, clock[0] + n)), \
             patch.object(runner, "server_metrics", side_effect=sample):
            _, idle, elapsed = runner.drain("http://offline.invalid/v1")
        self.assertTrue(idle)
        self.assertEqual(len(samples), 2)
        self.assertGreaterEqual(samples[1] - samples[0], .2)
        self.assertGreaterEqual(elapsed, .2)

    def test_busy_sample_resets_idle_confirmation(self):
        clock = [0.0]
        snapshots = [dict(running=0, waiting=0), dict(running=1, waiting=0),
                     dict(running=0, waiting=0), dict(running=0, waiting=0)]
        with patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(runner.time, "sleep", side_effect=lambda n: clock.__setitem__(0, clock[0] + n)), \
             patch.object(runner, "server_metrics", side_effect=snapshots):
            _, idle, elapsed = runner.drain("http://offline.invalid/v1")
        self.assertTrue(idle)
        self.assertGreaterEqual(elapsed, .6)

    def synthetic_case(self, root, proof=True, stop=True):
        records = [{"event_id": 1, "run_id": "offline-run", "method": "independent",
                    "type": "request_start", "request_id": "pending"}]
        if proof:
            records.append({"event_id": 2, "run_id": "offline-run", "method": "independent",
                            "type": "reward", "agent_id": 0, "solved": True})
        code = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(sys.argv[2]); time.sleep(5)"
        trace = root / "events.jsonl"
        return dict(task_id="dev-fake", split="development", arm="independent8", seed=1,
                    endpoint="http://offline.invalid/v1", events=str(trace), stdout=str(root / "out.log"),
                    stderr=str(root / "err.log"), server_metrics=True, stop_on_solution=stop,
                    command=[sys.executable, "-c", code, str(trace),
                             "\n".join(map(json.dumps, records)) + "\n"])

    def run_child(self, proof, stop):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(runner, "server_metrics", return_value=dict(prompt=0, completion=0, running=0, waiting=0)), \
                 patch.object(runner, "drain", return_value=(dict(prompt=0, completion=0, running=0, waiting=0), True, .2)):
                row = runner.execute(self.synthetic_case(root, proof, stop), deadline_seconds=.25)
            records, malformed = runner.read_trace(root / "events.jsonl")
        self.assertEqual(malformed, 0)
        self.assertEqual(records[-1]["type"], "controller_stop")
        self.assertEqual(records[-1]["source"], "controller")
        self.assertEqual(records[-1]["run_id"], "offline-run")
        self.assertEqual(records[-1]["event_id"], len(records))
        self.assertFalse(any(r["type"] == "run_end" for r in records))
        self.assertLess(row["returncode"], 0)
        self.assertEqual(row["unfinished_calls"], 1)
        return row

    def test_success_early_has_explicit_controller_terminal_event(self):
        row = self.run_child(True, True)
        self.assertEqual(row["status"], "success_early")
        self.assertTrue(row["solved"])
        self.assertIsNone(row["controller_error"])

    def test_deadline_preserves_existing_verifier_proof(self):
        row = self.run_child(True, False)
        self.assertTrue(row["deadline"])
        self.assertTrue(row["solved"])

    def test_deadline_without_proof_is_unsolved(self):
        self.assertFalse(self.run_child(False, False)["solved"])

    def test_append_preserves_partial_tail_and_does_not_self_prove(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace.jsonl"
            original = b'{"event_id":1,"run_id":"r","method":"m","type":"request_start"}\n{"event_id":2'
            path.write_bytes(original)
            records, _ = runner.read_trace(path)
            row = {k: None for k in runner.FIELDS}
            row.update(solved=False, status="deadline", deadline=True, unfinished_calls=1,
                       server_cost_known=False, server_cost_reason="metrics_unavailable")
            runner.append_controller_stop(path, records, row, {"arm": "independent8"})
            self.assertTrue(path.read_bytes().startswith(original + b"\n"))
            final, malformed = runner.read_trace(path)
            self.assertEqual(malformed, 1)
            self.assertEqual(final[-1]["event_id"], 2)
            self.assertFalse(runner.verified(final))

    def test_expected_negative_early_kill_is_not_controller_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = dict(protocol="synthetic-countdown-v1", tasks=[
                dict(id=f"{split}-{i}", split=split, numbers=[2, 3, 25, 50], target=53+i)
                for split, n in (("development", 8), ("evaluation", 24)) for i in range(n)])
            path = root / "tasks.json"
            path.write_text(json.dumps(dataset))
            def fake(case):
                row = {k: None for k in runner.FIELDS}
                row.update({k: case[k] for k in ("task_id", "split", "arm", "seed", "endpoint", "events")})
                row.update(status="success_early", solved=True, controller_stop=True, server_idle_after=True,
                           returncode=-15, controller_error=None, calls=1, wall_seconds=.1)
                return row
            with patch.object(runner, "execute", side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
                code = runner.main(["--dataset", str(path), "--split", "development", "--arms", "direct_off",
                                    "--jobs", "1", "--output", str(root / "run"), "--run", "--stop-on-solution"])
            self.assertEqual(code, 0)
            metadata = json.loads((root / "run/metadata.json").read_text())
            self.assertFalse(metadata["incomplete"])


if __name__ == "__main__":
    unittest.main()
