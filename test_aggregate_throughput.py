"""Synthetic queues only: no study outcomes, model endpoints, or SSH."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import aggregate_throughput as a


class ThroughputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, name="one", known=True):
        path = self.root / name; path.mkdir()
        rows = [dict(task_id=task, seed=seed, arm="a", split="development", solved=task == "t1",
                     infrastructure_failures=0, controller_error=None, returncode=0, controller_stop=False,
                     queue_wait_seconds=seed, service_wall_seconds=10 + seed, total_latency_seconds=10 + 2 * seed,
                     end_to_end_first_proof_seconds=10 if task == "t1" else None)
                for task in ("t1", "t2") for seed in (1, 2, 3, 4)]
        nodes = [dict(endpoint=str(index), idle_after=True, server_cost_known=known,
                      completed_client_floor=dict(prompt_tokens=10, completion_tokens=20),
                      server_prompt_tokens=10 if known else None, server_completion_tokens=20 if known else None) for index in range(4)]
        common = dict(arm="a", split="development", seeds=[1, 2, 3, 4], unique_tasks=2, attempts=8, completed_cases=8, batch_wall_seconds=30)
        meta = dict(common, mode="run", status="complete", incomplete=False, source_changed_during_run=False,
                    source_hashes={"harness.py": "pin"}, final_source_hashes={"harness.py": "pin"}, cases=rows,
                    jobs_per_node=1, git_revision="source", dataset_sha256="data", nodes=nodes)
        cohort = dict(common, fully_drained=True, throughput_scope_valid=True, controller_errors=0,
                      known_infrastructure_failures=0, verified_successes=4, successes_per_minute=8,
                      server_cost_known=known, server_prompt_tokens=40 if known else None, server_completion_tokens=80 if known else None)
        self.save(path, meta, cohort, rows)
        return path, meta, cohort, rows

    @staticmethod
    def save(path, meta, cohort, rows):
        for filename, value in (("metadata.json", meta), ("cohort.json", cohort), ("summary.json", rows)):
            (path / filename).write_text(json.dumps(value))

    def test_actual_batch_wall_global_cost_and_clustered_seeds(self):
        row = a.load_cohort(self.fixture()[0], repetitions=500)
        self.assertEqual(row["successes_per_minute"], 8)  # Not sum of overlapping service times.
        self.assertEqual(row["server_completion_tokens"], 80)
        self.assertEqual(row["task_cluster_success_fraction_ci95"], [0, 1])
        self.assertEqual(row["queue_wait_seconds"]["median"], 2.5)
        self.assertIn("No rate CI", row["rate_uncertainty"])

    def test_unknown_global_cost_stays_unknown_and_false_coverage_rejected(self):
        row = a.load_cohort(self.fixture(known=False)[0])
        self.assertFalse(row["server_cost_known"]); self.assertIsNone(row["server_completion_tokens"])
        path, meta, cohort, rows = self.fixture("false-claim")
        meta["nodes"][0]["server_completion_tokens"] = 19
        self.save(path, meta, cohort, rows)
        with self.assertRaisesRegex(ValueError, "coverage"): a.load_cohort(path)

    def test_incomplete_changed_not_drained_infra_and_task_matrix_rejected(self):
        for kind in ("incomplete", "changed", "drain", "infra", "duplicate", "rate"):
            path, meta, cohort, rows = self.fixture(kind)
            if kind == "incomplete": meta["incomplete"] = True
            if kind == "changed": meta["final_source_hashes"]["harness.py"] = "changed"
            if kind == "drain": cohort["fully_drained"] = False
            if kind == "infra": rows[0]["infrastructure_failures"] = 1
            if kind == "duplicate": rows[1] = copy.deepcopy(rows[0])
            if kind == "rate": cohort["successes_per_minute"] = 999
            self.save(path, meta, cohort, rows)
            with self.subTest(kind=kind), self.assertRaises(ValueError): a.load_cohort(path)

    def grid(self):
        base = a.load_cohort(self.fixture()[0], repetitions=0)
        return [dict(base, jobs_per_node=jobs, cohort="j" + str(jobs), successes_per_minute=rate)
                for jobs, rate in ((1, 9.91), (2, 10), (4, 9), (8, 8))]

    def test_selection_within_one_percent_prefers_smaller_and_requires_full_grid(self):
        rows = self.grid()
        self.assertEqual(a.select_development(rows, ["a"])["selections"][0]["jobs_per_node"], 1)
        rows[0]["successes_per_minute"] = 9.89
        self.assertEqual(a.select_development(rows)["selections"][0]["jobs_per_node"], 2)
        with self.assertRaisesRegex(ValueError, "grid"): a.select_development(rows[:-1])

    def test_evaluation_tuning_and_duplicate_grid_rejected(self):
        rows = self.grid()
        with self.assertRaisesRegex(ValueError, "grid"): a.select_development(rows + [rows[0]])
        rows[0]["split"] = "evaluation"
        with self.assertRaisesRegex(ValueError, "development inputs ONLY"): a.select_development(rows)

    def test_controlled_stop_null_infra_requires_trace_transport_audit(self):
        path, meta, cohort, rows = self.fixture()
        rows[0].update(infrastructure_failures=None, controller_stop=True, returncode=-15, events="/old/source/case.jsonl")
        trace = path / "case.jsonl"
        trace.write_text(json.dumps(dict(type="request_end", error="JSONDecodeError: invalid candidate JSON", response="bad", finish_reason="stop")) + "\n")
        self.save(path, meta, cohort, rows)
        self.assertEqual(a.load_cohort(path)["verified_successes"], 4)
        for error, response in (("URLError: connection failed", None), ("JSONDecodeError: invalid HTTP body", None)):
            trace.write_text(json.dumps(dict(type="request_end", error=error, response=response)) + "\n")
            with self.assertRaisesRegex(ValueError, "infrastructure"): a.load_cohort(path)
        trace.unlink()
        with self.assertRaisesRegex(ValueError, "infrastructure"): a.load_cohort(path)


if __name__ == "__main__":
    unittest.main()
