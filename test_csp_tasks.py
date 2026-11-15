import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import csp_tasks as c


class CSPTasksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public, cls.private = c.generate()

    def test_deterministic_design_and_independent_witness_check(self):
        self.assertEqual((self.public, self.private), c.generate())
        rows = self.public["tasks"]
        self.assertEqual(len(rows), 16)
        self.assertEqual(len({row["id"] for row in rows}), 16)
        self.assertEqual(sum(row["split"] == "development" for row in rows), 4)
        design = set()
        for row in rows:
            reference = self.private["witnesses"][row["id"]]
            labels = reference["assignment"]
            # Independent exact check: no call to producer verifier.
            self.assertEqual(len(labels), row["vertex_count"])
            self.assertTrue(all(type(v) is int and 0 <= v < row["color_count"] for v in labels))
            self.assertTrue(all(labels[u] != labels[v] for u, v in row["edges"]))
            self.assertTrue(c.connected(row["vertex_count"], row["edges"]))
            self.assertEqual(len(row["edges"]), reference["edge_count"])
            self.assertEqual(reference["graph_sha256"], c.graph_digest(row))
            if row["split"] == "evaluation":
                design.add((row["vertex_count"], row["color_count"], reference["eligible_pair_density_percent"]))
        self.assertEqual(design, set(itertools.product((24, 40, 64), (3, 4), (20, 40))))

    def test_frozen_files_match_generator(self):
        base = Path(__file__).parent / "datasets" / "csp-v1"
        self.assertEqual(json.loads((base / "tasks.json").read_text()), self.public)
        self.assertEqual(json.loads((base / "reference-witnesses.json").read_text()), self.private)

    def test_every_planted_witness_and_conflicting_mutation(self):
        for row in self.public["tasks"]:
            labels = self.private["witnesses"][row["id"]]["assignment"]
            self.assertTrue(c.verify_assignment(row, {"assignment": labels})["solved"])
            broken = list(labels)
            u, v = row["edges"][0]
            broken[v] = broken[u]
            report = c.verify_assignment(row, {"assignment": broken})
            self.assertFalse(report["solved"])
            self.assertIn(0, report["violating_edges"])
            self.assertGreaterEqual(report["conflicts"], 1)

    def test_exact_verifier_exhaustive_small_graph(self):
        task = dict(id="tiny", vertex_count=4, color_count=3, edges=[[0, 1], [1, 2], [2, 3], [0, 3]])
        for assignment in itertools.product(range(3), repeat=4):
            report = c.verify_assignment(task, {"assignment": list(assignment)})
            expected = sum(assignment[u] == assignment[v] for u, v in task["edges"])
            self.assertEqual(report["conflicts"], expected)
            self.assertEqual(report["solved"], expected == 0)
            self.assertEqual(report["fitness"], [1, -expected])

    def test_schema_domain_and_vertex_mutations_rejected(self):
        row = self.public["tasks"][0]
        labels = self.private["witnesses"][row["id"]]["assignment"]
        bad = [None, labels, {}, {"assignment": labels, "explanation": "ok"},
               {"assignment": labels[:-1]}, {"assignment": labels + [0]},
               {"assignment": {str(i): v for i, v in enumerate(labels)}}]
        for value in (-1, row["color_count"], True, False, 0.0, "0", None):
            modified = list(labels)
            modified[0] = value
            bad.append({"assignment": modified})
        for candidate in bad:
            with self.subTest(candidate=candidate):
                report = c.verify_assignment(row, candidate)
                self.assertFalse(report["solved"])
                self.assertFalse(report["valid_schema"])
                self.assertIsNone(report["conflicts"])

    def test_task_mutations_rejected(self):
        original = self.public["tasks"][0]
        bad_edges = [[[0, 0]], [[1, 0]], [[-1, 2]], [[0, original["vertex_count"]]],
                     [[False, 1]], [[0.0, 1]], [[0, 1, 2]], [[0, 1], [0, 1]]]
        for edges in bad_edges:
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                c.validate_graph(dict(original, edges=edges))
        for changes in ({"witness": []}, {"color_count": True}, {"vertex_count": 2.0}, {"split": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                c.validate_graph(dict(original, **changes))

    def test_worker_loader_reads_only_public_path_and_strips_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            path.write_text(json.dumps(self.public))
            (Path(directory) / "reference-witnesses.json").write_text("FORBIDDEN INVALID JSON")
            original_open, opened = Path.open, []
            def recording_open(target, *args, **kwargs):
                opened.append(target)
                return original_open(target, *args, **kwargs)
            with patch.object(Path, "open", recording_open):
                rows = c.load_tasks(path, "evaluation")
            self.assertEqual(opened, [path])
            self.assertEqual(len(rows), 12)
            self.assertTrue(all(set(row) == c.WORKER_KEYS for row in rows))
            self.assertNotIn("assignment", json.dumps(rows))

    def test_loader_rejects_reference_file_and_contaminated_public_task(self):
        contaminated = copy.deepcopy(self.public)
        contaminated["tasks"][0]["assignment"] = [0]
        duplicate = copy.deepcopy(self.public)
        duplicate["tasks"].append(duplicate["tasks"][0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for document in (self.private, contaminated, duplicate):
                path.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    c.load_tasks(path)


if __name__ == "__main__":
    unittest.main()
