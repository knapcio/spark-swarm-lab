"""Offline tests for the bugbench grader and the stockroom prototype invariants.

No model endpoint, SSH or Docker is used.  Every grade runs the trusted CHILD in
a local subprocess with the current interpreter.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bugbench_grader as g  # noqa: E402

CASES = ["stockroom-b1-tier-boundary", "stockroom-b2-snapshot-alias", "stockroom-b3-rollback-order"]
PROJECT = "stockroom"


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def patched(case_id, path, old, new):
    """FILE-block patch: the buggy file of ``case_id`` with one exact edit."""
    files = g.buggy_files(g.load_case(case_id))
    return g.patch_from_files({path: replace_once(files[path], old, new)})


def run_snippet(files, source):
    """Run ad-hoc trusted probe functions through the same CHILD (used to check report numbers)."""
    names = g.probe_names(source)
    child, error = g.run_child({"mode": "probes", "package": PROJECT, "files": files, "probes": source,
                                "probe_names": names, "probe_timeout": 5.0}, 60)
    assert error is None, error
    return {name: obs.get("value", obs) for name, obs in zip(names, child["results"])}


class ProjectShapeTests(unittest.TestCase):
    def test_project_is_bigger_than_one_prompt_but_within_design_bounds(self):
        project = g.load_project(PROJECT)
        files = g.clean_files(PROJECT)
        modules = g.editable_paths(project, files)
        lines = sum(files[path].count("\n") for path in modules)
        tokens = sum(g.approx_tokens(files[path]) for path in modules)
        self.assertTrue(4 <= len(modules) <= 10, modules)
        self.assertTrue(400 <= lines <= 1500, lines)
        self.assertGreater(tokens, 8000, "the whole package must not fit in an ~8K-token prompt")
        for path in modules:
            self.assertLessEqual(files[path].count("\n"), 260, f"{path} too long for full-file replacement")

    def test_expected_matches_current_clean_tree_and_probes(self):
        project = g.load_project(PROJECT)
        expected = g.load_expected(PROJECT)
        probes = g._read(os.path.join(project["hidden"], "probes.py"))
        self.assertEqual(expected["clean_tree_sha256"], g.tree_sha256(g.clean_files(PROJECT)))
        self.assertEqual(expected["probes_sha256"], hashlib.sha256(probes.encode()).hexdigest())
        self.assertEqual(list(expected["probes"]), g.probe_names(probes))

    def test_clean_reference_passes_every_probe_now(self):
        child, names, error, _ = g.observe(PROJECT, g.clean_files(PROJECT))
        self.assertIsNone(error)
        self.assertIsNone(child.get("import_error"))
        passed = g.compare(g.load_expected(PROJECT), names, child)
        self.assertEqual([name for name, ok in passed.items() if not ok], [])
        self.assertGreaterEqual(len(names), 20)

    def test_public_tests_pass_on_clean_tree(self):
        result = g.run_public_tests(PROJECT, g.clean_files(PROJECT))
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(result["tests_run"], 15)


class OracleCrossCheckTests(unittest.TestCase):
    """Hand-computed values for target probes, independent of the reference implementation."""

    def setUp(self):
        self.expected = {name: obs.get("value") for name, obs in g.load_expected(PROJECT)["probes"].items()}

    def test_tier_boundaries(self):
        self.assertEqual(self.expected["probe_tier_exact_boundaries"], [[10, "2.30 PLN"], [50, "2.10 PLN"]])
        # 24 cups at the 24+ tier: 24 * 6.00 = 144.00, VAT 23 % = 33.12
        self.assertEqual(self.expected["probe_tier_boundary_via_journal"], "177.12 PLN")
        # 12 pens at 0.80 EUR = 9.60, VAT 2.208 -> 2.21 half-up
        self.assertEqual(self.expected["probe_tier_boundary_other_product"][2], "11.81 EUR")

    def test_snapshot_values(self):
        # 10 widgets at 1.00 + 4 books at 12.50 at snapshot time; 4 widgets left now.
        self.assertEqual(self.expected["probe_snapshot_after_shipment"][-3:], [14, "60.00 PLN", "4.00 PLN"])
        self.assertEqual(self.expected["probe_snapshot_after_writeoff"], [3, 3, 1])
        self.assertEqual(self.expected["probe_snapshot_survives_direct_issue"], [[["FOO-004#1", 4], ["FOO-004#2", 4]], 8, 2])

    def test_rollback_fifo_values(self):
        self.assertEqual(self.expected["probe_failed_shipment_then_cogs"][1:], ["5.00 PLN", ["WID-001#1"]])
        # 3 x 1.00 + 3 x 1.10 + 2 x 1.20
        self.assertEqual(self.expected["probe_failed_shipment_three_lots"][0], "8.70 PLN")
        self.assertEqual(self.expected["probe_failed_shipment_via_journal"], [9, "InsufficientStock", "20.00 PLN", 4])


class CaseInvariantTests(unittest.TestCase):
    def test_each_case_fails_exactly_its_targets_and_reference_restores(self):
        for case_id in CASES:
            with self.subTest(case_id):
                report = g.verify_case(case_id)
                self.assertTrue(report["buggy_failed_probes"])
                self.assertEqual(report["buggy_failed_probes"], report["declared_target_probes"])
                self.assertEqual(report["reference_status"], "passed")
                self.assertTrue(report["reference_gold_function_hit"])
                self.assertTrue(report["public_tests_clean"])
                self.assertTrue(report["public_tests_buggy"], "public tests must not reveal the bug")

    def test_cases_listed_and_bugs_in_distinct_functions(self):
        self.assertEqual(g.list_cases(PROJECT), sorted(CASES))
        golds = [tuple(g.load_case(case_id)["gold"]["functions"]) for case_id in CASES]
        self.assertEqual(len(set(golds)), len(CASES))

    def test_reference_patch_is_minimal(self):
        for case_id in CASES:
            with self.subTest(case_id):
                result = g.grade(case_id, g.reference_patch(g.load_case(case_id)))
                self.assertEqual(result["status"], "passed")
                self.assertLessEqual(result["patch"]["added_lines"] + result["patch"]["removed_lines"], 4)
                self.assertEqual(result["localization"]["functions_touched"], g.load_case(case_id)["gold"]["functions"])

    def test_report_numbers_reproduce_on_clean_and_buggy(self):
        source = '''
import datetime
def _replay(text, store=None):
    from stockroom import replay
    return replay(text, store)
def probe_b1():
    store, results = _replay('product WID-001 "Widget" 2.50 tiers 10=2.30 50=2.10\\nreceive WID-001 100 @ 1.20 on 2026-03-01\\norder O-1 on 2026-03-02 : WID-001 x 10\\nconfirm O-1\\n')
    return results[-1]["total"]
def probe_b2():
    store, _ = _replay('product LMP-100 "Desk lamp" 89.00\\nproduct BLB-101 "LED bulb" 12.00\\nreceive LMP-100 6 @ 41.00 on 2026-10-01\\nreceive BLB-101 40 @ 3.20 on 2026-10-01\\norder S-501 on 2026-10-30 : LMP-100 x 2, BLB-101 x 10\\nconfirm S-501\\nsnapshot october-close\\n')
    before = store.valuation("october-close")
    _replay("ship S-501 on 2026-11-02\\n", store)
    after = store.valuation("october-close")
    return [before["quantity"], str(before["value"]), after["quantity"], str(after["value"])]
def probe_b3():
    store, _ = _replay('product LMP-100 "Desk lamp" 89.00\\nproduct BLB-101 "LED bulb" 12.00\\nreceive LMP-100 5 @ 40.00 on 2026-10-01\\nreceive LMP-100 5 @ 46.00 on 2026-10-15\\nreceive BLB-101 4 @ 3.20 on 2026-10-01\\norder S-610 on 2026-11-03 : LMP-100 x 5, BLB-101 x 4\\nconfirm S-610\\nwriteoff BLB-101 1 on 2026-11-03 reason broken\\n')
    try:
        store.ship("S-610", datetime.date(2026, 11, 4))
        error = None
    except Exception as exc:
        error = type(exc).__name__
    on_hand = store.inventory.on_hand("LMP-100")
    _, results = _replay("cancel S-610 on 2026-11-04\\norder S-611 on 2026-11-05 : LMP-100 x 2\\nconfirm S-611\\nship S-611 on 2026-11-06\\n", store)
    return [error, on_hand, results[-1]["cogs"]]
'''
        clean = run_snippet(g.clean_files(PROJECT), source)
        self.assertEqual(clean, {"probe_b1": "28.29 PLN", "probe_b2": [46, "374.00 PLN", 46, "374.00 PLN"],
                                 "probe_b3": ["InsufficientStock", 10, "80.00 PLN"]})
        actual = {name: run_snippet(g.buggy_files(g.load_case(case_id)), source)[name]
                  for name, case_id in zip(["probe_b1", "probe_b2", "probe_b3"], CASES)}
        self.assertEqual(actual, {"probe_b1": "30.75 PLN", "probe_b2": [46, "374.00 PLN", 34, "260.00 PLN"],
                                  "probe_b3": ["InsufficientStock", 10, "92.00 PLN"]})
        reports = {case_id: g.load_case(case_id)["report_text"] for case_id in CASES}
        for case_id, numbers in zip(CASES, [["28.29", "30.75"], ["374.00", "260.00"], ["80.00", "92.00"]]):
            for number in numbers:
                self.assertIn(number, reports[case_id])


class LeakageTests(unittest.TestCase):
    def test_agent_bundle_contains_no_hidden_material(self):
        clean = g.clean_files(PROJECT)
        project = g.load_project(PROJECT)
        for case_id in CASES:
            with self.subTest(case_id):
                case = g.load_case(case_id)
                bundle = g.agent_bundle(case_id)
                self.assertEqual(set(bundle["files"]), set(clean))
                changed = [path for path in clean if clean[path] != bundle["files"][path]]
                self.assertEqual(changed, sorted({m["file"] for m in case["mutations"]}))
                visible = json.dumps(bundle)
                for secret in (project["canary"], "probe_", "expected.json", "case.json", "gold", "mutation"):
                    self.assertNotIn(secret, visible)
                for path in case["gold"]["files"]:
                    self.assertNotIn(os.path.basename(path), bundle["report"])

    def test_child_never_receives_expected_values(self):
        seen = {}
        real = g.run_child

        def capture(payload, timeout, python=None):
            seen.update(payload)
            return real(payload, timeout, python)
        with mock.patch.object(g, "run_child", side_effect=capture):
            g.grade(CASES[2], g.reference_patch(g.load_case(CASES[2])))
        self.assertEqual(set(seen), {"mode", "package", "files", "probes", "probe_names", "probe_timeout"})
        wire = json.dumps(seen)
        expected = g.load_expected(PROJECT)["probes"]
        for name in g.load_case(CASES[2])["target_probes"]:
            self.assertNotIn(json.dumps(expected[name]), wire)

    def test_container_argv_mirrors_existing_isolation(self):
        argv = g.container_argv("abc123")
        source = g._read(os.path.join(os.path.dirname(g.ROOT), "independent_code_grader.py"))
        image = re.search(r"IMAGE = '([^']+)'", source).group(1)
        self.assertEqual(g.IMAGE, image)
        for flag in (["--network", "none"], ["--read-only"], ["--cap-drop", "ALL"], ["--pids-limit", "64"],
                     ["--memory", "256m"], ["--memory-swap", "256m"], ["--cpus", "1"], ["--user", "65534:65534"],
                     ["--runtime", "runc"], ["--pull", "never"]):
            index = argv.index(flag[0])
            self.assertEqual(argv[index:index + len(flag)], flag)
        self.assertEqual(argv[-4:-1], ["-I", "-S", "-c"])
        self.assertIs(argv[-1], g.CHILD)


class PatchParsingTests(unittest.TestCase):
    def test_blocks_with_fences_and_prose(self):
        text = ("I think the bug is here.\n=== FILE: ./stockroom/a.py ===\n```python\nx = 1\n```\n=== END FILE ===\n"
                "and also\n=== FILE: stockroom/b.py ===\n\ny = 2\n\n=== END FILE ===\nthanks")
        self.assertEqual(g.parse_patch(text), {"stockroom/a.py": "x = 1\n", "stockroom/b.py": "y = 2\n"})

    def test_malformed_patches(self):
        bad = ["no blocks here",
               "=== FILE: stockroom/a.py ===\nx = 1\n",
               "=== END FILE ===\n",
               "=== FILE: stockroom/a.py ===\n=== FILE: stockroom/b.py ===\n=== END FILE ===\n",
               "=== FILE: a.py ===\n1\n=== END FILE ===\n=== FILE: a.py ===\n2\n=== END FILE ===\n",
               "=== FILE: ../a.py ===\n1\n=== END FILE ===\n",
               "=== FILE: /etc/passwd ===\n1\n=== END FILE ===\n",
               "=== FILE: stockroom\\a.py ===\n1\n=== END FILE ===\n"]
        for text in bad:
            with self.subTest(text=text[:40]):
                with self.assertRaises(g.PatchError):
                    g.parse_patch(text)

    def test_validation_rules(self):
        case = g.load_case(CASES[0])
        files, project = g.buggy_files(case), g.load_project(PROJECT)
        for patch in ({"stockroom/new.py": "x\n"}, {"tests/test_public.py": "x\n"}, {"README.md": "x\n"},
                      {"stockroom/money.py": "x\0\n"}, {"stockroom/money.py": "#" * 70000},
                      {p: "x\n" for p in ["stockroom/money.py", "stockroom/catalog.py", "stockroom/orders.py", "stockroom/store.py"]},
                      {}):
            with self.subTest(patch=list(patch)[:2]):
                with self.assertRaises(g.PatchError):
                    g.validate_patch(patch, files, project)
        result = g.grade(CASES[0], "=== FILE: tests/test_public.py ===\npass\n=== END FILE ===\n")
        self.assertEqual(result["status"], "invalid_patch")
        self.assertNotIn("hidden", result)

    def test_round_trip(self):
        files = {"stockroom/a.py": "x = 1\n", "stockroom/b.py": "y = 2"}
        self.assertEqual(g.parse_patch(g.patch_from_files(files)), {"stockroom/a.py": "x = 1\n", "stockroom/b.py": "y = 2\n"})


class GradingBehaviourTests(unittest.TestCase):
    def test_no_op_patch_fails_targets_only(self):
        case = g.load_case(CASES[0])
        path = case["gold"]["files"][0]
        result = g.grade(CASES[0], g.patch_from_files({path: g.buggy_files(case)[path]}))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["patch"]["no_op"])
        self.assertEqual(result["target"]["passed"], 0)
        self.assertEqual(result["regression"]["broken"], [])
        self.assertFalse(result["localization"]["gold_function_hit"])

    def test_overfit_fix_for_the_report_example_fails(self):
        patch = patched(CASES[0], "stockroom/pricing.py", "if quantity > tier.min_quantity:",
                        "if quantity > tier.min_quantity or quantity == 10:")
        result = g.grade(CASES[0], patch)
        self.assertEqual(result["status"], "failed")
        self.assertLess(result["target"]["passed"], result["target"]["total"])
        self.assertTrue(result["localization"]["gold_function_hit"])

    def test_fix_that_breaks_something_else_is_rejected(self):
        files = g.buggy_files(g.load_case(CASES[0]))
        text = replace_once(files["stockroom/pricing.py"], "if quantity > tier.min_quantity:", "if quantity >= tier.min_quantity:")
        text = replace_once(text, "discount > best_discount:", "discount >= best_discount:")
        result = g.grade(CASES[0], g.patch_from_files({"stockroom/pricing.py": text}))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["target"]["passed"], result["target"]["total"])
        self.assertIn("probe_promotion_tie_and_bundle", result["regression"]["broken"])

    def test_alternative_valid_fixes_count(self):
        cow = patched(CASES[1], "stockroom/inventory.py", "            lot = lots[0]\n",
                      "            lot = lots[0] = lots[0].copy()\n")
        result = g.grade(CASES[1], cow)
        self.assertEqual(result["status"], "passed", result.get("hidden"))
        self.assertFalse(result["localization"]["gold_function_hit"])
        resort = patched(CASES[2], "stockroom/inventory.py", "                self._lots.setdefault(item.sku, []).append(lot)\n",
                         "                self._lots.setdefault(item.sku, []).append(lot)\n"
                         "                self._lots[item.sku].sort(key=Lot.sort_key)\n")
        result = g.grade(CASES[2], resort)
        self.assertEqual(result["status"], "passed", result.get("hidden"))
        self.assertTrue(result["localization"]["gold_function_hit"])

    def test_symptom_masking_fixes_fail(self):
        store_only = patched(CASES[1], "stockroom/store.py", "        snapshot = self.inventory.snapshot(label)\n",
                             "        snapshot = self.inventory.snapshot(label)\n"
                             "        snapshot = type(snapshot)(label, {s: [l.copy() for l in ls] for s, ls in snapshot.lots.items()},\n"
                             "                                  snapshot.reservations)\n")
        result = g.grade(CASES[1], store_only)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["hidden"]["failed_probes"], ["probe_snapshot_survives_direct_issue"])
        sort_in_take = patched(CASES[2], "stockroom/inventory.py", "        lots = self._lots[sku]\n",
                               "        lots = self._lots[sku]\n        lots.sort(key=Lot.sort_key)\n")
        result = g.grade(CASES[2], sort_in_take)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["hidden"]["failed_probes"], ["probe_failed_shipment_restores_lot_order"])

    def test_syntax_error_and_elision(self):
        broken = patched(CASES[0], "stockroom/pricing.py", "if quantity > tier.min_quantity:", "if quantity >= tier.min_quantity")
        result = g.grade(CASES[0], broken)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["import_error"].startswith("SyntaxError"))
        self.assertEqual(result["hidden"]["passed"], 0)
        self.assertEqual(result["localization"]["functions_touched"], ["stockroom/pricing.py::<syntax-error>"])
        lazy = "=== FILE: stockroom/pricing.py ===\nfrom .money import Money\n# ... rest unchanged\n=== END FILE ===\n"
        result = g.grade(CASES[0], lazy)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["patch"]["suspected_elision"])

    def test_infinite_loop_is_bounded_per_probe(self):
        hang = patched(CASES[0], "stockroom/pricing.py", "        price = product.list_price\n",
                       "        price = product.list_price\n        while True:\n            pass\n")
        result = g.grade(CASES[0], hang, probe_timeout=0.3, timeout=60)
        self.assertEqual(result["status"], "failed")
        self.assertIn("probe_tier_exact_boundaries", result["timed_out_probes"])
        self.assertIn("probe_money_allocate", g.probe_names(g._read(os.path.join(g.load_project(PROJECT)["hidden"], "probes.py"))))
        self.assertNotIn("probe_money_allocate", result["hidden"]["failed_probes"])

    def test_controller_timeout_is_reported(self):
        result = g.grade(CASES[0], g.reference_patch(g.load_case(CASES[0])), timeout=0.01)
        self.assertEqual(result["status"], "timeout")

    def test_selfcheck_exposes_only_public_tests(self):
        case = g.load_case(CASES[0])
        files = g.buggy_files(case)
        self.assertTrue(g.run_public_tests(PROJECT, files)["ok"])
        files["stockroom/pricing.py"] = replace_once(files["stockroom/pricing.py"], "price = tier.unit_price", "pass")
        result = g.run_public_tests(PROJECT, files)
        self.assertFalse(result["ok"])
        self.assertIn("test_large_order_gets_tier_price", result["output"])

    def test_localization_claim_scoring(self):
        case = g.load_case(CASES[2])
        self.assertEqual(g.score_localization(case, {"file": "stockroom/inventory.py", "function": "Inventory.restore"}),
                         {"file_hit": True, "function_hit": True})
        self.assertEqual(g.score_localization(case, {"file": "stockroom/orders.py", "function": "OrderBook.ship"}),
                         {"file_hit": False, "function_hit": False})


class CliTests(unittest.TestCase):
    def test_materialize_and_grade_reference(self):
        script = os.path.join(g.ROOT, "bugbench_grader.py")
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "case")
            subprocess.run([sys.executable, script, "materialize", CASES[1], target], check=True, capture_output=True)
            self.assertTrue(os.path.isfile(os.path.join(target, "REPORT.md")))
            self.assertIn("Inventory.snapshot", g._read(os.path.join(target, "REPO_MAP.txt")))
            again = subprocess.run([sys.executable, script, "materialize", CASES[1], target], capture_output=True)
            self.assertNotEqual(again.returncode, 0)
            patch = os.path.join(directory, "fix.txt")
            with open(patch, "w") as handle:
                handle.write(subprocess.run([sys.executable, script, "reference-patch", CASES[1]], check=True,
                                            capture_output=True, text=True).stdout)
            graded = subprocess.run([sys.executable, script, "grade", CASES[1], patch], capture_output=True, text=True)
            self.assertEqual(graded.returncode, 0, graded.stdout + graded.stderr)
            self.assertEqual(json.loads(graded.stdout)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
