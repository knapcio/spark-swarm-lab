"""Offline checks for coding-hard-v1. No model, SSH or Docker calls."""
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import re
import unittest

import coding_harness
import coding_hard_second_refs as second
import make_coding_hard as m
from sandbox_code import _run_cases

HERE = Path(__file__).resolve().parent
DATA = HERE / "datasets" / "coding-hard-v1"
# Frozen corpus bytes. Regenerating the corpus intentionally requires updating these pins.
PINNED_SHA256 = {
    "tasks.json": "01cb39b1b18d7e6565576fa8b96a30681b3fe2a31796399bfd8f0f6761033da0",
    "hidden-tests.json": "57cf4420c5db07ae2afab10b86c93f07fc24da6318386856cd10399b11effa13",
}
PRIVATE_KEYS = {"feedback_tests", "holdout_tests", "trusted_reference_source", "trusted_reference_sha256"}


def load(name):
    return json.loads((DATA / name).read_text())


class CorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public = load("tasks.json")
        cls.private = load("hidden-tests.json")
        cls.tasks = cls.public["tasks"]
        cls.refs = cls.private["references"]

    def test_schema_matches_coding_v1_shape(self):
        old_public = json.loads((HERE / "datasets/coding-v1/tasks.json").read_text())
        old_private = json.loads((HERE / "datasets/coding-v1/hidden-tests.json").read_text())
        self.assertEqual(self.public["protocol"], old_public["protocol"])
        self.assertEqual(self.private["protocol"], self.public["protocol"])
        self.assertEqual(self.public["corpus"], "coding-hard-v1")
        self.assertNotIn("references", self.public)
        self.assertEqual(set(old_public["tasks"][0]), set(self.tasks[0]))
        self.assertEqual(set(next(iter(old_private["references"].values()))), PRIVATE_KEYS)
        self.assertEqual(Counter(t["split"] for t in self.tasks), {"development": 8, "evaluation": 24})
        self.assertEqual(len({t["id"] for t in self.tasks}), 32)
        self.assertEqual(len({t["function_name"] for t in self.tasks}), 32)
        self.assertEqual({t["id"] for t in self.tasks}, set(self.refs))
        for task in self.tasks:
            self.assertEqual(set(task), set(old_public["tasks"][0]))
            self.assertRegex(task["id"], r"^[A-Za-z0-9_-]+$")
            self.assertTrue(task["function_name"].isidentifier())
            self.assertTrue(task["id"].startswith(task["split"][:3] + "-"))
            self.assertEqual(len(task["examples"]), 2)
            self.assertLessEqual(len(task["spec"].split()), 250, task["id"])
            ref = self.refs[task["id"]]
            self.assertEqual(set(ref), PRIVATE_KEYS)
            for phase in ("feedback_tests", "holdout_tests"):
                cases = ref[phase]
                self.assertGreaterEqual(len(cases), 10, (task["id"], phase))
                self.assertLessEqual(len(cases), 128)
                payload = json.dumps(dict(code="", function_name=task["function_name"], tests=cases, timeout=10), allow_nan=False)
                self.assertLess(len(payload.encode()), 1_000_000)
                for case in cases:
                    self.assertEqual(set(case), {"args", "expected", "check_input_unchanged", "ordered_dict"})
                    self.assertIsInstance(case["args"], list)
                    self.assertIs(case["check_input_unchanged"], True)
                    self.assertIs(case["ordered_dict"], False)

    def test_inputs_disjoint_with_harness_digest(self):
        digest = lambda cases: {coding_harness.digest([c["args"], c.get("kwargs", {})]) for c in cases}
        for task in self.tasks:
            ref = self.refs[task["id"]]
            parts = [digest(task["examples"]), digest(ref["feedback_tests"]), digest(ref["holdout_tests"])]
            self.assertEqual(len(parts[1]), len(ref["feedback_tests"]))
            self.assertEqual(len(parts[2]), len(ref["holdout_tests"]))
            for i in range(3):
                for j in range(i):
                    self.assertFalse(parts[i] & parts[j], task["id"])

    def test_both_references_pass_every_case(self):
        for task in self.tasks:
            ref = self.refs[task["id"]]
            namespace = {}
            exec(compile(ref["trusted_reference_source"], "<reference-a>", "exec"), namespace)  # trusted corpus source
            reference_a = namespace[task["function_name"]]
            reference_b = getattr(second, task["function_name"])
            self.assertEqual(hashlib.sha256(ref["trusted_reference_source"].encode()).hexdigest(), ref["trusted_reference_sha256"])
            self.assertEqual(ref["trusted_reference_source"], inspect.getsource(getattr(m, task["function_name"])))
            for cases in (task["examples"], ref["feedback_tests"], ref["holdout_tests"]):
                for reference in (reference_a, reference_b):
                    report = _run_cases(reference, cases)
                    self.assertEqual(report["status"], "passed", (task["id"], reference.__module__, report["first_failure"]))

    def test_build_is_deterministic_and_matches_disk(self):
        first = {name: m.serialize(doc) for name, doc in m.documents().items()}
        again = {name: m.serialize(doc) for name, doc in m.documents().items()}
        self.assertEqual(first, again)
        for name, text in first.items():
            self.assertEqual((DATA / name).read_text(), text, name + " is stale; regenerate the corpus")
        other_seed = m.serialize(m.documents(m.DEFAULT_SEED + 1)["hidden-tests.json"])
        self.assertNotEqual(other_seed, first["hidden-tests.json"])

    def test_hash_stability(self):
        self.assertEqual(self.public["generator_sha256"], hashlib.sha256((HERE / "make_coding_hard.py").read_bytes()).hexdigest())
        self.assertEqual(self.private["validation"]["second_reference_sha256"],
                         hashlib.sha256((HERE / "coding_hard_second_refs.py").read_bytes()).hexdigest())
        for name, pinned in PINNED_SHA256.items():
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), pinned, name)

    def test_disagreement_is_reported(self):
        class Broken:
            def __getattr__(self, name):
                original = getattr(second, name)
                return lambda *args: ["broken"] if name == "csv_parse" else original(*args)
        _, _, disagreements = m.build(second=Broken())
        self.assertTrue(disagreements)
        self.assertEqual({d["task"] for d in disagreements}, {"eva-csv_parse"})
        with self.assertRaises(AssertionError):
            m.documents(second=Broken())

    def test_references_do_not_mutate_and_are_self_contained(self):
        for fn, *_ in m.TASKS:
            source = inspect.getsource(fn)
            self.assertTrue(source.startswith("def " + fn.__name__ + "("), fn.__name__)
        # m.run_reference asserts no input mutation on every generated case during build().
        public, private, disagreements = m.build()
        self.assertEqual(disagreements, [])


if __name__ == "__main__":
    unittest.main()
