"""Offline synthetic tests; never opens real evaluation cohorts or model endpoints."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import aggregate_evaluation as ag


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, name="one", seeds=(1, 2, 3)):
        path = self.root/name; path.mkdir()
        rows = [dict(task_id=task, arm=arm, seed=seed, split="evaluation", solved=task == "t1" or arm == "b",
                     calls=1, prompt_tokens=10, completion_tokens=20, wall_seconds=15,
                     time_to_verified_solution_seconds=10 if task == "t1" or arm == "b" else None,
                     unfinished_calls=0, server_cost_known=False, server_prompt_tokens=None, server_completion_tokens=None,
                     infrastructure_failures=0, returncode=0)
                for task in ("t1", "t2") for arm in ("a", "b") for seed in seeds]
        meta = dict(split="evaluation", dataset_sha256="dataset", source_hashes={"harness.py":"frozen"},
                    final_source_hashes={"harness.py":"frozen"}, source_changed_during_run=False,
                    cases=[{k:r[k] for k in ("task_id", "arm", "seed")} for r in rows],
                    completed_cases=len(rows), completed_utc="2026-11-15T00:00:00Z", batch_wall_seconds=30,
                    incomplete=False, missing_cases=[], slot_failures=[], git_revision="source")
        self.save(path, meta, rows)
        return path, meta, rows

    def save(self, path, meta, rows):
        (path/"metadata.json").write_text(json.dumps(meta)); (path/"summary.json").write_text(json.dumps(rows))

    def load(self, paths):
        return ag.load_cohorts(paths, "arithmetic", expected_tasks=2)

    def test_cluster_bootstrap_retains_correlated_seeds(self):
        path, _, _ = self.fixture(); rows, cohorts, dataset = self.load([path])
        report = ag.report_for(rows, cohorts, dataset, "arithmetic", 5000)
        a, b = report["arms"]
        self.assertEqual((a["tasks"], a["cases"], a["accuracy"]), (2, 6, .5))
        self.assertEqual((a["cluster95_low"], a["cluster95_high"]), (0, 1))
        self.assertEqual((b["cluster95_low"], b["cluster95_high"]), (1, 1))
        self.assertEqual(ag.cluster_ci([0, .5, 1], 500), ag.cluster_ci([0, .5, 1], 500))

    def test_paired_deltas_match_same_task_seeds(self):
        path, _, _ = self.fixture(); rows, cohorts, dataset = self.load([path])
        delta = ag.report_for(list(reversed(rows)), cohorts, dataset, "arithmetic")["paired_deltas"][0]
        self.assertEqual((delta["arm_a"], delta["arm_b"], delta["matched_task_seed_pairs"]), ("a", "b", 6))
        self.assertEqual((delta["accuracy_delta"], delta["cluster95_low"], delta["cluster95_high"]), (-.5, -1, 0))

    def test_multiple_seed_directories_and_duplicate_rejection(self):
        paths = [self.fixture(str(s), (s,))[0] for s in (1,2,3)]
        self.assertEqual(len(self.load(paths)[0]), 12)
        with self.assertRaisesRegex(ValueError, "duplicate"): self.load(paths+[paths[0]])
        path, meta, rows = self.fixture("duplicate")
        rows.append(copy.deepcopy(rows[0])); self.save(path, meta, rows)
        with self.assertRaisesRegex(ValueError, "unique"): self.load([path])

    def test_incomplete_changed_and_dataset_split_rejected(self):
        for kind in ("missing", "incomplete", "changed", "unverified", "dataset", "split", "unbalanced"):
            with self.subTest(kind=kind):
                path, meta, rows = self.fixture(kind)
                if kind == "missing": rows.pop()
                elif kind == "incomplete": meta["incomplete"] = True
                elif kind == "changed": meta["final_source_hashes"] = {"harness.py":"changed"}
                elif kind == "unverified": meta.pop("source_changed_during_run")
                elif kind == "split": rows[0]["split"] = "development"
                elif kind == "unbalanced":
                    rows = [r for r in rows if not(r["task_id"]=="t2" and r["arm"]=="b")]
                    meta["cases"] = [{k:r[k] for k in ("task_id","arm","seed")} for r in rows]; meta["completed_cases"] = len(rows)
                else: meta["dataset_sha256"] = "other"
                self.save(path, meta, rows)
                paths = [path]
                if kind == "dataset": paths.append(self.fixture("original", (4,))[0])
                with self.assertRaises(ValueError): self.load(paths)

    def test_unknown_stale_cost_and_client_lower_bound(self):
        path, _, rows = self.fixture(); loaded, cohorts, dataset = self.load([path])
        selected = [r for r in loaded if r["arm"]=="a"]
        selected[0].update(server_cost_known=True, server_prompt_tokens=10, server_completion_tokens=25)
        selected[1].update(server_cost_known=True, server_prompt_tokens=9, server_completion_tokens=25)
        selected[2]["unfinished_calls"] = 1
        report = ag.report_for(loaded, cohorts, dataset, "arithmetic")
        a, b = report["arms"]
        self.assertEqual((a["server_cost_known_cases"],a["server_cost_unknown_cases"],a["server_completion_tokens_known"]),(1,5,25))
        self.assertTrue(a["client_cost_is_lower_bound"])
        self.assertIsNone(b["server_completion_tokens_known"])

    def test_time_curves_include_failures_and_missing_proof(self):
        path, _, _ = self.fixture(); rows, cohorts, dataset = self.load([path])
        next(r for r in rows if r["arm"]=="a" and r["solved"])["time_to_verified_solution_seconds"] = None
        report = ag.report_for(rows, cohorts, dataset, "arithmetic")
        curve = next(r for r in report["success_by_time"] if r["arm"]=="a" and r["seconds"]==10)
        self.assertEqual((curve["solved_by_time"],curve["cases"],curve["fraction"],curve["missing_solved_proof_times"]),(2,6,1/3,1))
        self.assertEqual(report["arms"][0]["median_occupied_case_wall_seconds"],15)

    def test_explicit_supplementary_label_preserves_source_variant(self):
        first, _, _ = self.fixture("primary")
        second, meta, rows = self.fixture("supplement")
        meta["git_revision"] = "supplement-source"; self.save(second, meta, rows)
        loaded, cohorts, dataset = ag.load_cohorts([first,second], "arithmetic", {str(second.resolve()):"supplement"}, 2)
        report = ag.report_for(loaded, cohorts, dataset, "arithmetic", 500)
        self.assertEqual({r["arm"] for r in report["arms"]},{"a","b","supplement/a","supplement/b"})
        self.assertEqual(len(report["paired_cases"]),6)
        self.assertEqual(report["source_cohorts"][1]["source_commit"],"supplement-source")

    def test_expected_kill_is_not_process_error(self):
        path, _, _ = self.fixture(); rows, cohorts, dataset = self.load([path])
        rows[0].update(returncode=-15, controller_stop=True)
        row = ag.report_for(rows, cohorts, dataset, "arithmetic", 500)["arms"][0]
        self.assertEqual(row["unexpected_process_error_cases"],0)

    def test_ledger_rejects_original_coding_and_accepts_uniform_fixed_name(self):
        original, meta, rows = self.fixture("evaluation-v1-coding-s1", (1,))
        meta.update(domain="coding", seed=1); self.save(original, meta, rows)
        fixed, fixed_meta, fixed_rows = self.fixture("evaluation-v1-coding-fixed-s1", (1,))
        fixed_meta.update(domain="coding", seed=1); self.save(fixed, fixed_meta, fixed_rows)
        common = dict(domain="coding", seed=1, returncode=0, incomplete=False, source_changed=False,
                      completed_utc="done", completed_cases=len(rows), source_revision="source")
        ledger = [dict(common, name=original.name, review_annotation={"primary_aggregation":"Excluded pending uniform instrumentation rerun"}),
                  dict(common, name=fixed.name, valid_for_aggregation=True)]
        with self.assertRaisesRegex(ValueError,"excludes"):
            ag.load_cohorts([original],"coding",expected_tasks=2,expected_seeds=1,ledger=ledger)
        loaded, cohorts, _ = ag.load_cohorts([fixed],"coding",expected_tasks=2,expected_seeds=1,ledger=ledger)
        self.assertEqual(len(loaded),4)
        self.assertEqual(cohorts[0]["ledger_verification"]["entry"]["name"],fixed.name)
        # Curated aliases must retain the original identity through their export manifest.
        curated = self.root/"coding-s1"; curated.mkdir(); self.save(curated,fixed_meta,fixed_rows)
        (curated/"manifest.json").write_text(json.dumps(dict(source_directory=str(fixed))))
        self.assertEqual(ag.load_cohorts([curated],"coding",expected_tasks=2,expected_seeds=1,ledger=ledger)[1][0]["ledger_verification"]["identity_manifest_sha256"],ag.sha(curated/"manifest.json"))
        for key,value in [("valid_for_aggregation",False),("returncode",1),("incomplete",True),("source_changed",True),("source_revision","other"),("seed",2)]:
            bad = copy.deepcopy(ledger); bad[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                ag.load_cohorts([fixed],"coding",expected_tasks=2,expected_seeds=1,ledger=bad)


if __name__ == "__main__": unittest.main()
