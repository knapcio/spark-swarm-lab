"""Offline tests for the bugbench grader and the project/case invariants.

No model endpoint, SSH or Docker is used.  Every grade runs the trusted CHILD in
a local subprocess with the current interpreter; the Docker executor is tested
with a fake ``ssh`` that runs the same CHILD locally.
"""
import hashlib
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bugbench_grader as g  # noqa: E402

CASES = ["stockroom-b1-tier-boundary", "stockroom-b2-snapshot-alias", "stockroom-b3-rollback-order"]
PROJECT = "stockroom"
PROJECTS = ["agenda", "inkwell", "junction", "patchwork", "quarry", "relay", "stockroom", "tally", "trellis"]
ALL_CASES = {
    "agenda": ["agenda-b1-slot-grid-default", "agenda-b2-weekday-order", "agenda-b3-split-cancelled-count"],
    "inkwell": ["inkwell-b1-round-half-even", "inkwell-b2-and-or-precedence", "inkwell-b3-trim-line-drift"],
    "stockroom": CASES,
    "tally": ["tally-b1-discount-last-day", "tally-b2-vat-per-line", "tally-b3-rejected-discount-payment"],
    "quarry": ["quarry-b1-desc-tie-order", "quarry-b2-right-assoc-minus", "quarry-b3-failed-insert-keys"],
    "trellis": ["trellis-b1-caret-zero-patch", "trellis-b2-install-order-ready", "trellis-b3-backtrack-leak"],
    # fourth batch (2026-11-16)
    "relay": ["relay-b1-wait-rounds-down", "relay-b2-ready-time-tiebreak", "relay-b3-rejected-batch-tokens"],
    "patchwork": ["patchwork-b1-hunk-merge-gap", "patchwork-b2-context-newline-marker", "patchwork-b3-fuzz-trims-patch"],
    "junction": ["junction-b1-exact-transfer-time", "junction-b2-walk-time-rounding", "junction-b3-night-listing-stale"],
}


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def patched(case_id, path, old, new):
    """FILE-block patch: the buggy file of ``case_id`` with one exact edit."""
    files = g.buggy_files(g.load_case(case_id))
    return g.patch_from_files({path: replace_once(files[path], old, new)})


def run_snippet(files, source, package=PROJECT):
    """Run ad-hoc trusted probe functions through the same CHILD (used to check report numbers)."""
    names = g.probe_names(source)
    child, error = g.run_child({"mode": "probes", "package": package, "files": files, "probes": source,
                                "probe_names": names, "probe_timeout": 5.0}, 60)
    assert error is None, error
    return {name: obs.get("value", obs) for name, obs in zip(names, child["results"])}


class ProjectShapeTests(unittest.TestCase):
    def test_projects_are_bigger_than_one_prompt_but_within_design_bounds(self):
        self.assertEqual(sorted(os.listdir(g.PROJECTS)), PROJECTS)
        for name in PROJECTS:
            with self.subTest(name):
                project = g.load_project(name)
                files = g.clean_files(name)
                modules = g.editable_paths(project, files)
                lines = sum(files[path].count("\n") for path in modules)
                tokens = sum(g.approx_tokens(files[path]) for path in modules)
                self.assertTrue(4 <= len(modules) <= 10, modules)
                self.assertTrue(400 <= lines <= 1500, lines)
                self.assertGreater(tokens, 8000, "the whole package must not fit in an ~8K-token prompt")
                for path in modules:
                    self.assertLessEqual(files[path].count("\n"), 260, f"{path} too long for full-file replacement")
                self.assertIn("authorship", project)
                self.assertTrue(project["canary"].startswith("BUGBENCH-HIDDEN-CANARY"))
                self.assertIn(project["canary"], g._read(os.path.join(project["hidden"], "probes.py")))

    def test_expected_matches_current_clean_tree_and_probes(self):
        for name in PROJECTS:
            with self.subTest(name):
                project = g.load_project(name)
                expected = g.load_expected(name)
                probes = g._read(os.path.join(project["hidden"], "probes.py"))
                self.assertEqual(expected["clean_tree_sha256"], g.tree_sha256(g.clean_files(name)))
                self.assertEqual(expected["probes_sha256"], hashlib.sha256(probes.encode()).hexdigest())
                self.assertEqual(list(expected["probes"]), g.probe_names(probes))
                self.assertEqual(expected["canary"], project["canary"])

    def test_clean_reference_passes_every_probe_now(self):
        for name in PROJECTS:
            with self.subTest(name):
                child, names, error, _ = g.observe(name, g.clean_files(name))
                self.assertIsNone(error)
                self.assertIsNone(child.get("import_error"))
                passed = g.compare(g.load_expected(name), names, child)
                self.assertEqual([probe for probe, ok in passed.items() if not ok], [])
                self.assertGreaterEqual(len(names), 20)
                self.assertNotIn("timeout", [obs["kind"] for obs in g.load_expected(name)["probes"].values()])

    def test_public_tests_pass_on_clean_tree(self):
        for name in PROJECTS:
            with self.subTest(name):
                result = g.run_public_tests(name, g.clean_files(name))
                self.assertTrue(result["ok"], result)
                self.assertGreaterEqual(result["tests_run"], 13)


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
        for case_id in itertools.chain(*ALL_CASES.values()):
            with self.subTest(case_id):
                report = g.verify_case(case_id)
                self.assertTrue(report["buggy_failed_probes"])
                self.assertEqual(report["buggy_failed_probes"], report["declared_target_probes"])
                self.assertEqual(report["reference_status"], "passed")
                self.assertTrue(report["reference_gold_function_hit"])
                self.assertTrue(report["public_tests_clean"])
                self.assertTrue(report["public_tests_buggy"], "public tests must not reveal the bug")

    def test_cases_listed_and_bugs_in_distinct_functions(self):
        for name, cases in ALL_CASES.items():
            with self.subTest(name):
                self.assertEqual(g.list_cases(name), sorted(cases))
                golds = [tuple(g.load_case(case_id)["gold"]["functions"]) for case_id in cases]
                self.assertEqual(len(set(golds)), len(cases))
                found = [g.load_case(case_id) for case_id in cases]
                self.assertEqual(sorted(case["difficulty"] for case in found), ["easy", "hard", "medium"])
                self.assertEqual(len({case["bug_class"] for case in found}), 3)
                for case in found:
                    self.assertEqual(case["project"], name)
                    self.assertEqual(case["canary"], g.load_project(name)["canary"])
                    self.assertTrue(set(case["target_probes"]) <= set(g.load_expected(name)["probes"]))

    def test_reference_patch_is_minimal(self):
        for case_id in itertools.chain(*ALL_CASES.values()):
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
        for case_id in itertools.chain(*ALL_CASES.values()):
            with self.subTest(case_id):
                case = g.load_case(case_id)
                clean = g.clean_files(case["project"])
                project = g.load_project(case["project"])
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
        sandbox = g._read(os.path.join(os.path.dirname(g.ROOT), "sandbox_code.py"))
        self.assertEqual(g.IMAGE, re.search(r'IMAGE = "([^"]+)"', sandbox).group(1))
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
        table = g.load_case("inkwell-b2-and-or-precedence")
        for function in ("<module>", "PRECEDENCE", "ExpressionParser._binary"):
            self.assertEqual(g.score_localization(table, {"file": "inkwell/expr.py", "function": function}),
                             {"file_hit": True, "function_hit": True})


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



# --- the two newer projects ------------------------------------------------------------------
INK, AGENDA = ALL_CASES["inkwell"], ALL_CASES["agenda"]


class NewProjectOracleTests(unittest.TestCase):
    """Hand-computed values for target probes, independent of the reference implementations."""

    def test_inkwell_targets(self):
        expected = {name: obs.get("value") for name, obs in g.load_expected("inkwell")["probes"].items()}
        # half up: 2.345 -> 2.35, 2.5 -> 3, 0.125 -> 0.13, -2.345 -> -2.35, 0.25 -> 0.3, 1.0050 -> 1.01
        self.assertEqual(expected["probe_round_half_up_ties"][0], "2.35|3|0.13|-2.35|0.3|1.01")
        # 0.12345 * 100 = 12.345 -> 12.35 %; 0.005 * 100 = 0.5 -> 1 %; 0.00125 * 100 = 0.125 -> 0.13 %
        self.assertEqual(expected["probe_percent_half_up_ties"], ["12.35%|1%|0.13%"])
        # a or (b and c) over (a, b, c) in {0, X}^3
        self.assertEqual(expected["probe_or_and_precedence_output"], ["0", "0", "0", "C", "A", "A", "A", "A"])
        # "a\n\n{%- if x -%}\n\n{{ y }}\n{#- c -#}\n\n{% endif %}": tag on line 3, output on 5, endif on 8
        self.assertEqual(expected["probe_trim_token_lines"], [["text", 1], ["tag", 3], ["output", 5], ["tag", 8]])
        self.assertEqual(expected["probe_trim_error_in_include"][0], ["UndefinedError", 4, "item"])

    def test_agenda_targets(self):
        expected = {name: obs.get("value") for name, obs in g.load_expected("agenda")["probes"].items()}
        # planning 09:00-10:15, 30-minute slots inside 09:00-11:00 on the 15-minute grid
        self.assertEqual(expected["probe_free_slots_default_grid"][0], ["10:15", "10:30"])
        self.assertEqual(expected["probe_first_common_slot_default_grid"][0], "2026-03-03 10:15")
        # Fri 6 Mar, Mon 9, Fri 13, Mon 16
        self.assertEqual(expected["probe_weekly_unsorted_days_count"][0],
                         ["2026-03-06 18:00", "2026-03-09 18:00", "2026-03-13 18:00", "2026-03-16 18:00"])
        # 6 weekly sessions from 2 Mar, 9 Mar cancelled, split at 23 Mar: 3 generated before the split
        self.assertEqual(expected["probe_split_after_cancellation_count"],
                         [["2026-03-02 13:00", "2026-03-16 13:00"],
                          ["2026-03-23 13:00", "2026-03-30 13:00", "2026-04-06 13:00"], 3, 3])


class NewProjectFixTests(unittest.TestCase):
    def assertFixes(self, case_id, patch):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "passed", result.get("hidden"))
        return result

    def assertFailsOnly(self, case_id, patch, probes):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(sorted(result["hidden"]["failed_probes"]), sorted(probes))
        self.assertEqual(result["regression"]["broken"], [])

    def test_inkwell_alternative_and_masking_fixes(self):
        manual = patched(INK[0], "inkwell/filters.py",
                         "    result = _decimal(value).quantize(exponent, rounding=decimal.ROUND_HALF_EVEN)\n",
                         "    number = _decimal(value)\n"
                         "    steps = (number.copy_abs() / exponent + Decimal('0.5')).to_integral_value(rounding=decimal.ROUND_FLOOR)\n"
                         "    result = (steps * exponent).copy_sign(number).quantize(exponent)\n")
        self.assertFixes(INK[0], manual)
        number_only = patched(INK[0], "inkwell/filters.py", "    rounded = _quantize(value, places)\n",
                              "    rounded = _decimal(value).quantize(Decimal(1).scaleb(-_places(places)), rounding=decimal.ROUND_HALF_UP)\n"
                              "    rounded = rounded.copy_abs() if rounded.is_zero() else rounded\n")
        self.assertFailsOnly(INK[0], number_only, ["probe_round_half_up_ties"])
        lower_or = patched(INK[1], "inkwell/expr.py", '    "or": 1,\n', '    "or": 0,\n')
        self.assertFixes(INK[1], lower_or)
        offsets = patched(INK[2], "inkwell/lexer.py", '        line += text.count("\\n")\n',
                          '        line = 1 + source.count("\\n", 0, stop)\n')
        self.assertTrue(self.assertFixes(INK[2], offsets)["localization"]["gold_function_hit"])

    def test_agenda_alternative_and_masking_fixes(self):
        none_default = patched(AGENDA[0], "agenda/availability.py",
                               "def free_slots(calendar, people, day, duration, step=30, hours=None):\n",
                               "def free_slots(calendar, people, day, duration, step=None, hours=None):\n"
                               "    step = 15 if step is None else step\n")
        self.assertFixes(AGENDA[0], none_default)
        callers_only = patched(AGENDA[0], "agenda/availability.py",
                               "        slots = free_slots(calendar, people, from_day + offset * DAY, duration, hours=hours)\n",
                               "        slots = free_slots(calendar, people, from_day + offset * DAY, duration, step=15, hours=hours)\n")
        self.assertFailsOnly(AGENDA[0], callers_only, ["probe_free_command_default_grid", "probe_free_slots_default_grid"])
        sort_in_dates = patched(AGENDA[1], "agenda/recurrence.py",
                                "            days, week = self.weekdays or (first.weekday(),), monday_of(first)\n",
                                "            days, week = sorted(self.weekdays or (first.weekday(),)), monday_of(first)\n")
        self.assertFixes(AGENDA[1], sort_in_dates)
        sort_listing = patched(AGENDA[1], "agenda/calendar.py", "        return sorted(found, key=lambda item: item.start)\n",
                               "        return sorted(found, key=lambda item: (item.start, item.event_id))\n")
        result = g.grade(AGENDA[1], sort_listing)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["target"]["passed"], 0)
        tail_only = patched(AGENDA[2], "agenda/calendar.py", "        event.rule = rule.replace(count=done)\n",
                            "        event.rule = rule.replace(count=len(generated))\n")
        self.assertFailsOnly(AGENDA[2], tail_only, ["probe_split_after_cancellation_count",
                                                    "probe_split_after_cancellation_schedule"])

    def test_report_numbers_reproduce_on_clean_and_buggy(self):
        ink = """
from decimal import Decimal
INVOICE = "<h1>Invoice {{ number }}</h1>\\n<table>\\n{%- for line in lines %}\\n  <tr><td>{{ line.name }}</td><td>{{ line.qty }}</td></tr>\\n{%- endfor %}\\n</table>\\n<p>Total: {{ totl }}</p>\\n"
def probe_b1():
    from inkwell import Environment
    line = Environment().from_string("{{ name }}: {{ amount|number(2) }} PLN")
    return [line.render(name="Shipping", amount=Decimal("12.345")), line.render(name="Handling", amount=Decimal("12.355"))]
def probe_b2():
    from inkwell import Environment
    t = Environment().from_string("{% if user.is_admin or user.is_author and post.draft %}[Edit]{% endif %}{{ post.title }}")
    return [t.render(user={"is_admin": True, "is_author": False}, post={"draft": False, "title": "News"}),
            t.render(user={"is_admin": False, "is_author": True}, post={"draft": True, "title": "Draft"})]
def probe_b3():
    from inkwell import Environment, UndefinedError
    try:
        Environment({"invoice": INVOICE}, strict=True).render("invoice", number=17, lines=[{"name": "Tea", "qty": 2}], total=8)
    except UndefinedError as exc:
        return [str(exc), exc.line]
"""
        agenda = """
import datetime
def probe_b1():
    from agenda import Calendar, free_slots
    cal = Calendar()
    cal.add_event("PLAN", "Sprint planning", datetime.datetime(2026, 3, 3, 9, 0), datetime.timedelta(minutes=75), attendees=["ann"])
    return [s.strftime("%H:%M") for s in free_slots(cal, ["ann"], datetime.date(2026, 3, 3), datetime.timedelta(minutes=30))[:3]]
def probe_b2():
    from agenda import replay
    from agenda.reports import series_dates
    cal, _ = replay('event TRAIN "Training" at 2026-03-06 18:00 for 1h repeat weekly on fri,mon count 4 with ann\\n')
    return series_dates(cal, "TRAIN")[-1]
def probe_b3():
    from agenda import replay
    from agenda.reports import series_dates
    cal, _ = replay('event COURSE "Pottery course" at 2026-03-02 13:00 for 2h repeat weekly count 6 room R2 with ann\\n'
                    "cancel COURSE 2026-03-09 13:00\\nsplit COURSE at 2026-03-23 13:00 as COURSE-B room R3\\n")
    return [series_dates(cal, "COURSE"), series_dates(cal, "COURSE-B")]
"""
        expected = {
            "inkwell": ({"probe_b1": ["Shipping: 12.35 PLN", "Handling: 12.36 PLN"], "probe_b2": ["[Edit]News", "[Edit]Draft"],
                         "probe_b3": ["invoice, line 7: 'totl' is undefined", 7]},
                        {"probe_b1": ["Shipping: 12.34 PLN", "Handling: 12.36 PLN"], "probe_b2": ["News", "[Edit]Draft"],
                         "probe_b3": ["invoice, line 5: 'totl' is undefined", 5]},
                        [["12.35", "12.34", "12.36"], ["[Edit]News", "`News`"], ["line 7", "line 5"]]),
            "agenda": ({"probe_b1": ["10:15", "10:30", "10:45"], "probe_b2": "2026-03-16 18:00",
                        "probe_b3": [["2026-03-02 13:00", "2026-03-16 13:00"], ["2026-03-23 13:00", "2026-03-30 13:00", "2026-04-06 13:00"]]},
                       {"probe_b1": ["10:30", "11:00", "11:30"], "probe_b2": "2026-03-20 18:00",
                        "probe_b3": [["2026-03-02 13:00"], ["2026-03-23 13:00", "2026-03-30 13:00", "2026-04-06 13:00", "2026-04-13 13:00"]]},
                       [["10:15, 10:30, 10:45", "10:30, 11:00, 11:30"], ["2026-03-16", "2026-03-20"], ["2026-03-16", "2026-04-13"]]),
        }
        for name, source in (("inkwell", ink), ("agenda", agenda)):
            clean_values, buggy_values, quoted = expected[name]
            with self.subTest(name):
                self.assertEqual(run_snippet(g.clean_files(name), source, name), clean_values)
                cases = ALL_CASES[name]
                actual = {probe: run_snippet(g.buggy_files(g.load_case(case_id)), source, name)[probe]
                          for probe, case_id in zip(["probe_b1", "probe_b2", "probe_b3"], cases)}
                self.assertEqual(actual, buggy_values)
                for case_id, numbers in zip(cases, quoted):
                    for number in numbers:
                        self.assertIn(number, g.load_case(case_id)["report_text"])


# --- the third batch: tally, quarry, trellis -----------------------------------------------------
TALLY, QUARRY, TRELLIS = ALL_CASES["tally"], ALL_CASES["quarry"], ALL_CASES["trellis"]
THIRD_BATCH_REPORTS = {
    "tally": """
import datetime
def probe_b1():
    from tally import Books
    books = Books()
    books.add_customer("ACME", "Acme Ltd", days=30, discount="2", discount_days=10)
    books.invoice("A-1", "ACME", datetime.date(2026, 5, 4), [("Widget", "10", "10.00", "S")])
    payment = books.receive("P-1", "ACME", "120.54", datetime.date(2026, 5, 14))
    return [list(payment.allocations), books.statement("ACME")[0]]
def probe_b2():
    from tally import Books
    books = Books()
    books.add_customer("BETA", "Beta", days=14)
    invoice = books.invoice("INV-31", "BETA", datetime.date(2026, 5, 4),
                            [("Toner", "1", "189.00", "S"), ("Pens", "12", "1.15", "S"), ("Labels", "2", "12.35", "S")])
    return [invoice.tax, invoice.gross, books.vat_report(datetime.date(2026, 5, 1), datetime.date(2026, 5, 31))[0]]
def probe_b3():
    from tally import Books, PeriodClosed
    books = Books()
    books.add_customer("ACME", "Acme Ltd", days=30, discount="2", discount_days=10)
    books.invoice("A-1", "ACME", datetime.date(2026, 4, 24), [("Widget", "10", "10.00", "S")])
    books.invoice("A-2", "ACME", datetime.date(2026, 4, 28), [("Widget", "5", "10.00", "S")])
    books.close_period(datetime.date(2026, 4, 30))
    try:
        books.receive("P-1", "ACME", "180.81", datetime.date(2026, 4, 29))
    except PeriodClosed:
        pass
    payment = books.receive("P-2", "ACME", "180.81", datetime.date(2026, 5, 3))
    return [list(payment.allocations), books.statement("ACME")[-1], books.balance("1100")]
""",
    "quarry": """
def probe_b1():
    from quarry import Engine
    db = Engine()
    db.run_script("CREATE TABLE scores (player TEXT, team TEXT, points INTEGER);"
                  "INSERT INTO scores VALUES ('Ola', 'red', 90), ('Bart', 'blue', 75), ('Celina', 'red', 90), "
                  "('Dawid', 'blue', 90), ('Ewa', 'red', 60), ('Filip', 'blue', 75)")
    return [", ".join(r[0] for r in db.query("SELECT player FROM scores ORDER BY team DESC, player")),
            ", ".join(r[0] for r in db.query("SELECT player FROM scores ORDER BY points DESC"))]
def probe_b2():
    from quarry import Engine
    db = Engine()
    db.run_script("CREATE TABLE lines (no INTEGER, gross INTEGER, discount INTEGER, shipping INTEGER);"
                  "INSERT INTO lines VALUES (1, 1000, 100, 50), (2, 500, 0, 25)")
    return [str(db.query("SELECT no, gross - discount - shipping AS net FROM lines")), db.query("SELECT 12 / 2 * 3")[0][0]]
def probe_b3():
    from quarry import Engine
    db = Engine()
    db.execute("CREATE TABLE orders (no INTEGER PRIMARY KEY, product INTEGER, qty INTEGER, city TEXT)")
    out = []
    for sql in ("INSERT INTO orders VALUES (7, 10, 1, 'Lodz'), (8, 11, 2, 'Lodz'), (9, 12, 'three', 'Lodz')",
                "INSERT INTO orders VALUES (7, 10, 1, 'Lodz'), (8, 11, 2, 'Lodz'), (9, 12, 3, 'Lodz')"):
        try:
            out.append(db.execute(sql).rowcount)
        except Exception as exc:
            out.append(type(exc).__name__)
    return out + [db.query("SELECT COUNT(*) FROM orders")[0][0]]
""",
    "trellis": """
def probe_b1():
    from trellis import Constraint, Workspace
    index = "tiny 0.0.3\\ntiny 0.0.4\\ntiny 0.0.9\\nweb 1.0.0: tiny ^0.0.3\\n"
    lock = Workspace(index, '[project]\\nname = "shop"\\n[dependencies]\\nweb = "^1"\\n').install().lock
    return [lock.splitlines()[2], str(Constraint.parse("^0.0.3"))]
def probe_b2():
    from trellis import Workspace
    index = "fmt 2.0.0\\nlog 1.0.0: fmt *\\nweb 1.0.0: log *\\nauth 1.0.0: fmt *\\nzip 1.0.0\\n"
    return str(Workspace(index, '[project]\\nname = "shop"\\n[dependencies]\\nweb = "*"\\nauth = "*"\\nzip = "*"\\n').install().order)
def probe_b3():
    from trellis import ResolutionImpossible, Workspace
    index = "ui 1.1.0: theme ^2\\nui 1.0.0: theme ^1\\ntheme 1.0.0\\ntheme 1.1.0\\ntheme 1.2.0\\ntheme 2.0.0\\n"
    try:
        return Workspace(index, '[project]\\nname = "shop"\\n[dependencies]\\nui = "*"\\ntheme = "^1"\\n').install().lock.splitlines()[2:]
    except ResolutionImpossible as exc:
        return exc.lines
""",
}


class ThirdBatchOracleTests(unittest.TestCase):
    """Hand-computed values for target probes, independent of the reference implementations."""

    def values(self, project):
        return {name: obs.get("value") for name, obs in g.load_expected(project)["probes"].items()}

    def test_tally_targets(self):
        expected = self.values("tally")
        # 10 x 10.00 = 100.00 + 23 % = 123.00; 2 % discount = 2.46; paid on day 10 settles 120.54 + 2.46
        self.assertEqual(expected["probe_discount_on_last_day"][0], [["A-1", 12054, 246]])
        # net 189.00 + 13.80 + 24.70 = 227.50; 23 % = 52.325 -> 52.33 (per line: 43.47 + 3.17 + 5.68 = 52.32)
        self.assertEqual(expected["probe_vat_rounded_per_code"][0][:4], ["INV-31", 22750, 5233, 27983])
        # 2 x 10.02 at 23 %: 20.04 x 0.23 = 4.6092 -> 4.61 once per code, not 2.30 + 2.30
        self.assertEqual(expected["probe_vat_rounded_per_code"][4][0], ["S", 2004, 461])
        self.assertEqual(expected["probe_rejected_discount_payment_restores_invoice"][:4], ["PeriodClosed", 12300, 0, 0])

    def test_quarry_targets(self):
        expected = self.values("quarry")
        # 10-4-3, 12/2*3, 100/10/5, 7-2+1, 17%5*2, 7*3/2 (21/2 truncated), 2*7%4, 1-1-1-1
        self.assertEqual(expected["probe_left_to_right_arithmetic"][0], [[3, 18, 2, 6, 4, 10, 2, -2]])
        self.assertEqual(expected["probe_desc_keeps_tied_rows_in_order"][0],
                         [["Ola"], ["Celina"], ["Dawid"], ["Bart"], ["Filip"], ["Ewa"]])
        self.assertEqual(expected["probe_insert_retry_after_failed_batch"], [["error", "TypeMismatch"], [[], [], 3], [[7], [8], [9]]])

    def test_trellis_targets(self):
        expected = self.values("trellis")
        self.assertEqual(expected["probe_caret_zero_zero_patch"][0], [">=0.0.3, <0.0.4", ["0.0.3"]])
        # core first (only package without dependencies besides mid/zeta); alpha becomes ready and sorts before mid
        self.assertEqual(expected["probe_install_order_ready_alphabetical"], ["core", "alpha", "mid", "zeta"])
        self.assertEqual(expected["probe_backtrack_keeps_newest"][0], {"app-core": "1.0.0", "http": "2.2.0", "json": "2.4.0"})


class ThirdBatchFixTests(unittest.TestCase):
    def assertFixes(self, case_id, patch):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "passed", result.get("hidden"))
        return result

    def assertFailsWith(self, case_id, patch, probes, exact=False):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["regression"]["broken"], [])
        if exact:
            self.assertEqual(sorted(result["hidden"]["failed_probes"]), sorted(probes))
        else:
            self.assertTrue(set(probes) <= set(result["hidden"]["failed_probes"]), result["hidden"])
        return result

    def test_tally_alternative_masking_and_overfit(self):
        self.assertFixes(TALLY[0], patched(TALLY[0], "tally/payments.py", "                if on < invoice.discount_date:\n",
                                           "                if not on > invoice.discount_date:\n"))
        overfit = patched(TALLY[0], "tally/payments.py", "                if on < invoice.discount_date:\n",
                          "                if on < invoice.discount_date or on == datetime.date(2026, 5, 14):\n")
        self.assertLess(g.grade(TALLY[0], overfit)["target"]["passed"], 3)
        self.assertFixes(TALLY[1], patched(TALLY[1], "tally/tax.py",
                                           "        group[1] += round_cents(Decimal(line.net) * rate / HUNDRED)\n",
                                           "        group[1] = Decimal(group[0]) * rate / HUNDRED\n"))
        invoice_only = patched(TALLY[1], "tally/invoices.py", "        self.tax_lines = tax_summary(self.lines)\n",
                               "        self.tax_lines = [type(t)(t.code, t.net, round_cents(Decimal(t.net) * (t.rate or 0) / HUNDRED))\n"
                               "                          for t in tax_summary(self.lines)]\n")
        self.assertFailsWith(TALLY[1], invoice_only, ["probe_vat_rounded_per_code"], exact=True)
        post_first = patched(TALLY[2], "tally/payments.py",
                             "        done = []\n        try:\n            for invoice, take, discount in plan:\n"
                             "                invoice.settle(take, discount)\n                done.append((invoice, take, discount))\n"
                             "            return self.ledger.post(on, memo, postings, source=source)\n        except TallyError:\n"
                             "            for invoice, take, discount in reversed(done):\n                invoice.settle(-take, discount)\n"
                             "            raise\n",
                             "        entry = self.ledger.post(on, memo, postings, source=source)\n"
                             "        for invoice, take, discount in plan:\n            invoice.settle(take, discount)\n        return entry\n")
        self.assertTrue(self.assertFixes(TALLY[2], post_first)["localization"]["gold_function_hit"])
        no_once_rule = patched(TALLY[2], "tally/payments.py",
                               "            if allow_discount and invoice.discount_date is not None and invoice.discount_taken == 0:\n",
                               "            if allow_discount and invoice.discount_date is not None:\n")
        self.assertFailsWith(TALLY[2], no_once_rule, ["probe_rejected_discount_payment_restores_invoice"])

    def test_quarry_alternative_and_masking(self):
        reverse_twice = patched(QUARRY[0], "quarry/planner.py", "        records.sort(key=lambda record: sort_key(function(record)))\n",
                                "        if descending:\n            records.reverse()\n"
                                "        records.sort(key=lambda record: sort_key(function(record)))\n")
        self.assertFixes(QUARRY[0], reverse_twice)
        associative_only = patched(QUARRY[1], "quarry/parser.py", "            right = self.expression(prec)\n",
                                   '            right = self.expression(prec if op in ("AND", "OR", "||", "+", "*") else prec + 1)\n')
        result = self.assertFailsWith(QUARRY[1], associative_only, ["probe_left_to_right_canonical_text"])
        self.assertLess(result["target"]["passed"], result["target"]["total"])
        rebuild = patched(QUARRY[2], "quarry/table.py", "        checked, seen = [], set()\n",
                          "        if self.key_index is not None:\n            self._keys = {row[self.key_index] for row in self._rows}\n"
                          "        checked, seen = [], set()\n")
        self.assertTrue(self.assertFixes(QUARRY[2], rebuild)["localization"]["gold_function_hit"])

    def test_trellis_alternative_and_overfit(self):
        self.assertFixes(TRELLIS[0], patched(TRELLIS[0], "trellis/constraint.py", "    elif minor >= 0 or len(numbers) == 2:\n",
                                             "    elif minor != 0 or len(numbers) == 2:\n"))
        overfit = patched(TRELLIS[0], "trellis/constraint.py", "    elif minor >= 0 or len(numbers) == 2:\n",
                          "    elif (minor >= 0 and patch != 3) or len(numbers) == 2:\n")
        result = g.grade(TRELLIS[0], overfit)
        self.assertEqual(result["status"], "failed")
        self.assertLess(result["target"]["passed"], result["target"]["total"])
        self.assertFixes(TRELLIS[1], patched(TRELLIS[1], "trellis/graph.py", "                ready.append(dependent)\n",
                                             "                ready.append(dependent)\n                ready.sort()\n"))
        fresh_lists = patched(TRELLIS[2], "trellis/resolver.py",
                              "            state.requirements.setdefault(dep, []).append((constraint, source))\n",
                              "            state.requirements[dep] = state.requirements.get(dep, []) + [(constraint, source)]\n")
        self.assertFalse(self.assertFixes(TRELLIS[2], fresh_lists)["localization"]["gold_function_hit"])

    def test_report_numbers_reproduce_on_clean_and_buggy(self):
        expected = {
            "tally": ({"probe_b1": [[["A-1", 12054, 246]], "A-1 2026-05-04 123.00 open 0.00"],
                       "probe_b2": [5233, 27983, ["23%", "227.50", "52.33"]],
                       "probe_b3": [[["A-1", 12054, 246], ["A-2", 6027, 123]], "balance due 0.00", 0]},
                      {"probe_b1": [[["A-1", 12054, 0]], "A-1 2026-05-04 123.00 open 2.46"],
                       "probe_b2": [5232, 27982, ["23%", "227.50", "52.32"]],
                       "probe_b3": [[["A-1", 11808, 0], ["A-2", 5904, 0]], "balance due -3.69", 738]},
                      [["2.46", "open 0.00", "open 2.46"], ["52.33", "279.83", "52.32", "279.82"],
                       ["118.08", "59.04", "3.69", "7.38"]]),
            "quarry": ({"probe_b1": ["Celina, Ewa, Ola, Bart, Dawid, Filip", "Ola, Celina, Dawid, Bart, Filip, Ewa"],
                        "probe_b2": ["[(1, 850), (2, 475)]", 18], "probe_b3": ["TypeMismatch", 3, 3]},
                       {"probe_b1": ["Ola, Ewa, Celina, Filip, Dawid, Bart", "Dawid, Celina, Ola, Filip, Bart, Ewa"],
                        "probe_b2": ["[(1, 950), (2, 525)]", 2], "probe_b3": ["TypeMismatch", "DuplicateKey", 0]},
                       [["Celina, Ewa, Ola, Bart, Dawid, Filip", "Ola, Ewa, Celina, Filip, Dawid, Bart"],
                        ["[(1, 850), (2, 475)]", "[(1, 950), (2, 525)]", "returns 2 instead of 18"], ["DuplicateKey", "adds 3 rows"]]),
            "trellis": ({"probe_b1": ["tiny 0.0.3", ">=0.0.3, <0.0.4"], "probe_b2": "['fmt', 'auth', 'log', 'web', 'zip']",
                         "probe_b3": ["theme 1.2.0", "ui 1.0.0"]},
                        {"probe_b1": ["tiny 0.0.9", ">=0.0.3, <0.1.0"], "probe_b2": "['fmt', 'zip', 'auth', 'log', 'web']",
                         "probe_b3": ["no version of theme satisfies all requirements:", "  shop requires theme >=1.0.0, <2.0.0",
                                      "  ui 1.1.0 requires theme >=2.0.0, <3.0.0"]},
                        [["tiny 0.0.3", "tiny 0.0.9", "<0.0.4", "<0.1.0"],
                         ["['fmt', 'auth', 'log', 'web', 'zip']", "['fmt', 'zip', 'auth', 'log', 'web']"],
                         ["theme 1.2.0", "ui 1.1.0 requires theme >=2.0.0, <3.0.0"]]),
        }
        for name, (clean_values, buggy_values, quoted) in expected.items():
            with self.subTest(name):
                source = THIRD_BATCH_REPORTS[name]
                self.assertEqual(run_snippet(g.clean_files(name), source, name), clean_values)
                cases = ALL_CASES[name]
                actual = {probe: run_snippet(g.buggy_files(g.load_case(case_id)), source, name)[probe]
                          for probe, case_id in zip(["probe_b1", "probe_b2", "probe_b3"], cases)}
                self.assertEqual(actual, buggy_values)
                for case_id, numbers in zip(cases, quoted):
                    for number in numbers:
                        self.assertIn(number, g.load_case(case_id)["report_text"])


# === fourth batch: relay, patchwork, junction ===================================================
# --- relay: rate limiter + job queue ---------------------------------------------------------------
RELAY = ["relay-b1-wait-rounds-down", "relay-b2-ready-time-tiebreak", "relay-b3-rejected-batch-tokens"]
RELAY_REPORTS = '''
def probe_b1():
    from relay import Dispatcher, Limiter
    limiter = Limiter()
    limiter.configure("mail", "3/s", burst=1)
    dispatcher = Dispatcher(workers=3, limiter=limiter)
    for n in (1, 2, 3):
        dispatcher.submit(f"welcome-{n}", key="mail")
    dispatcher.run()
    return [[job.id, job.started_at] for job in dispatcher.jobs()]
def probe_b2():
    from relay import Dispatcher, order_of_starts
    dispatcher = Dispatcher(workers=1)
    dispatcher.submit("report", delay="600ms", takes="10ms")
    dispatcher.submit("backup", takes="1s")
    dispatcher.submit("email", delay="100ms", takes="10ms")
    dispatcher.run()
    return str(order_of_starts(dispatcher))
def probe_b3():
    from relay import replay
    _, outputs = replay("""rate api 5/s burst 2 maxwait 400ms
submit warm key api
batch a key api ; b key api ; c key api ; d key api
tokens api
submit e key api
submit f key api
""")
    return outputs
'''


class RelayTests(unittest.TestCase):
    """relay: hand-computed oracle values, alternative / masking / overfit fixes, report numbers."""

    def values(self):
        return {name: obs.get("value") for name, obs in g.load_expected("relay")["probes"].items()}

    def assertFixes(self, case_id, patch):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "passed", result.get("hidden"))
        return result

    def assertFailsOnly(self, case_id, patch, probes):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(sorted(result["hidden"]["failed_probes"]), sorted(probes))
        self.assertEqual(result["regression"]["broken"], [])
        return result

    def test_relay_targets(self):
        expected = self.values()
        # 3/s burst 1: one token = 1000 units, +3 units/ms. Debts 1000, 2000, 3000 units -> ceil(/3) = 334, 667, 1000 ms;
        # after four takes a fifth token needs 4000 units -> ceil(4000/3) = 1334 ms
        self.assertEqual(expected["probe_intake_wait_rounds_up"][:2], [[0, 334, 667, 1000], 1334])
        # 6/s burst 1, max wait 166 ms: a second token needs ceil(1000/6) = 167 ms > 166 -> rejected;
        # at 166 ms 4 units are missing -> 1 ms; at 167 ms 1002 units -> 1 token
        self.assertEqual(expected["probe_intake_wait_rounds_up"][-8:], ["RateLimited", 167, 166, 1, 0, 0, 1, [0]])
        # 9/2s burst 2: one token = 2000 units, +9/ms; debts 2000, 4000 -> ceil(222.2) = 223, ceil(444.4) = 445
        self.assertEqual(expected["probe_intake_wait_start_times"][:8],
                         [["m0", 0], ["m1", 334], ["m2", 667], ["m3", 1000], ["s0", 0], ["s1", 0], ["s2", 223], ["s3", 445]])
        # 7/s burst 2: c owes 1000 units -> ceil(142.9) = 143; d (cost 2) owes 3000 -> ceil(428.6) = 429.
        # 3/2s burst 1, max wait 667ms: w2 owes 2000 units -> ceil(666.7) = 667 (allowed), w3 1334 -> rejected
        self.assertEqual(expected["probe_intake_wait_script"][:4],
                         ["submitted a@0ms, b@0ms, c@143ms, d@429ms", "submitted w1 ready 0ms", "submitted w2 ready 667ms",
                          "error RateLimited"])
        # equal priority 2: late-ticket (ready 100) is the only priority-2 job ready at 399; at 500 early-ticket and
        # other are both ready at 400 -> ticket order; second backlog: ready 20, 20, 50 -> second, third, first
        self.assertEqual(expected["probe_ready_time_breaks_ties"],
                         ["late-ticket", ["high", "early-ticket", "other", "low"], ["second", "third", "first"]])
        # one worker busy with long until 1000: ready sync (0) < email (100) < report (600); sync fails at 1050,
        # its retry is due at 1150 (fixed 100ms) and re-enters the backlog
        self.assertEqual(expected["probe_retry_ready_order"][0],
                         ["long#1@0", "sync#1@1000", "email#1@1050", "report#1@1060", "sync#2@1150"])
        # mail 2/s burst 3 (2000 units left after one take): each rejected reservation leaves both buckets unchanged;
        # 5 more mails would owe 3000 units -> 1500 ms > 1 s; finally 2 + 1 tokens -> waits 0 and 500 ms
        self.assertEqual(expected["probe_rejected_reservation_restores"],
                         [[0], ["sms", 500], True, ["mail", 1500], True, ["mail", 1500], True, 2, 1, [0, 500]])
        # 5/s burst 2: warm leaves 1 token; the batch is rejected at d (debt 3000 units -> 600 ms > 400 ms);
        # then f takes the token (ready 0) and g owes 1000 units -> 200 ms
        self.assertEqual(expected["probe_rejected_batch_script"][:5],
                         ["submitted warm ready 0ms", "error RateLimited", "api 1", "submitted f ready 0ms",
                          "submitted g ready 200ms"])
        self.assertEqual(expected["probe_rejected_batch_then_submit"][3],
                         [["m0", 0], ["m3", 0], ["m4", 250], ["s3", 0], ["m5", 500]])

    def test_relay_alternative_masking_and_overfit(self):
        b1, b2, b3 = RELAY
        ceil_line = "        return missing // self.rate.tokens\n"
        self.assertFixes(b1, patched(b1, "relay/limiter.py", ceil_line,
                                     "        return (missing + self.rate.tokens - 1) // self.rate.tokens\n"))
        overfit = patched(b1, "relay/limiter.py", ceil_line,
                          "        return missing // self.rate.tokens + (self.rate.tokens == 3 and missing % 3 != 0)\n")
        result = g.grade(b1, overfit)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["target"]["passed"], 0)
        take_only = patched(b1, "relay/limiter.py", "        wait = self._ms_for(-after) if after < 0 else 0\n",
                            "        wait = -(after // self.rate.tokens) if after < 0 else 0\n")
        self.assertFailsOnly(b1, take_only, ["probe_intake_wait_rounds_up"])
        self.assertFixes(b2, patched(b2, "relay/backlog.py",
                                     "        job = min(ready, key=lambda job: (-job.priority, job.ticket, job.ready_at))\n",
                                     "        ready.sort(key=lambda job: (-job.priority, job.ready_at, job.ticket))\n"
                                     "        job = ready[0]\n"))
        dispatcher_only = patched(b2, "relay/dispatcher.py", "            job = self.backlog.pop_ready(moment)\n",
                                  "            ready = [j for j in self.backlog.pending() if j.ready_at <= moment]\n"
                                  "            job = min(ready, key=lambda j: (-j.priority, j.ready_at, j.ticket)) if ready else None\n"
                                  "            if job is not None:\n"
                                  "                self.backlog.withdraw(job.id)\n")
        self.assertFailsOnly(b2, dispatcher_only, ["probe_ready_time_breaks_ties"])
        result = self.assertFixes(b3, patched(b3, "relay/limiter.py", "                saved[key] = bucket.state()\n",
                                              "                if key not in saved:\n"
                                              "                    saved[key] = bucket.state()\n"))
        self.assertTrue(result["localization"]["gold_function_hit"])
        restore_in_dispatcher = patched(
            b3, "relay/dispatcher.py",
            "        waits = self.limiter.reserve([(job.key, job.cost) for job, _ in built], now)\n",
            "        buckets = {job.key: self.limiter.bucket(job.key, now) for job, _ in built}\n"
            "        states = {key: bucket.state() for key, bucket in buckets.items() if bucket is not None}\n"
            "        try:\n"
            "            waits = self.limiter.reserve([(job.key, job.cost) for job, _ in built], now)\n"
            "        except RelayError:\n"
            "            for key, state in states.items():\n"
            "                buckets[key].restore(state)\n"
            "            raise\n")
        restore_in_dispatcher = restore_in_dispatcher.replace(
            "from .errors import ClockError, DuplicateJob, InvalidJob, JobStateError, UnknownJob\n",
            "from .errors import ClockError, DuplicateJob, InvalidJob, JobStateError, RelayError, UnknownJob\n")
        self.assertFailsOnly(b3, restore_in_dispatcher, ["probe_rejected_reservation_restores"])

    def test_relay_report_numbers_reproduce_on_clean_and_buggy(self):
        clean_values = {"probe_b1": [["welcome-1", 0], ["welcome-2", 334], ["welcome-3", 667]],
                        "probe_b2": "['backup', 'email', 'report']",
                        "probe_b3": ["submitted warm ready 0ms", "error RateLimited", "api 1", "submitted e ready 0ms",
                                     "submitted f ready 200ms"]}
        buggy_values = {"probe_b1": [["welcome-1", 0], ["welcome-2", 333], ["welcome-3", 666]],
                        "probe_b2": "['backup', 'report', 'email']",
                        "probe_b3": ["submitted warm ready 0ms", "error RateLimited", "api 0", "error RateLimited",
                                     "error RateLimited"]}
        quoted = [["334 ms", "667 ms", "333 ms", "666 ms"],
                  ["['backup', 'email', 'report']", "['backup', 'report', 'email']"],
                  ["api 1", "submitted e ready 0ms", "submitted f ready 200ms", "api 0", "error RateLimited"]]
        self.assertEqual(run_snippet(g.clean_files("relay"), RELAY_REPORTS, "relay"), clean_values)
        actual = {probe: run_snippet(g.buggy_files(g.load_case(case_id)), RELAY_REPORTS, "relay")[probe]
                  for probe, case_id in zip(["probe_b1", "probe_b2", "probe_b3"], RELAY)}
        self.assertEqual(actual, buggy_values)
        for case_id, numbers in zip(RELAY, quoted):
            for number in numbers:
                self.assertIn(number, g.load_case(case_id)["report_text"])


# --- patchwork (diff/patch tool) -------------------------------------------------------------------
PATCHWORK = ["patchwork-b1-hunk-merge-gap", "patchwork-b2-context-newline-marker", "patchwork-b3-fuzz-trims-patch"]
PATCHWORK_REPORTS = """
def probe_b1():
    from patchwork import PatchSet, diff_texts, summary
    old = "".join(f"{name}\\n" for name in ["click==8.1", "flask==3.0", "jinja2==3.1", "markupsafe==2.1", "pytest==8.2",
                                              "requests==2.32", "rich==13.7", "urllib3==2.2", "werkzeug==3.0", "zipp==3.19"])
    new = old.replace("flask==3.0", "flask==3.1").replace("werkzeug==3.0", "werkzeug==3.1")
    text = diff_texts(old, new, "requirements.txt")
    return [[line for line in text.splitlines() if line.startswith("@@")], summary(PatchSet.diff({"r": old}, {"r": new}))["hunks"]]
def probe_b2():
    from patchwork import PatchSet
    patch = PatchSet.parse("--- a/.env\\n+++ b/.env\\n@@ -1,3 +1,3 @@\\n DEBUG=0\\n-WORKERS=2\\n+WORKERS=4\\n PORT=8000\\n"
                           "\\\\ No newline at end of file\\n")
    return repr(patch.apply({".env": "DEBUG=0\\nWORKERS=2\\nPORT=8000"}).tree[".env"])
def probe_b3():
    from patchwork import PatchSet
    cfg = ("[client]\\ntimeout = 30\\nretries = 2\\n[server]\\nhost = 0.0.0.0\\nport = 8080\\ntimeout = 30\\n"
           "workers = 4\\nlog = info\\ncache = on\\n")
    patch = PatchSet.parse("--- a/app.ini\\n+++ b/app.ini\\n@@ -4,7 +4,7 @@\\n [server]\\n host = 0.0.0.0\\n port = 8080\\n"
                           "-timeout = 30\\n+timeout = 60\\n workers = 4\\n log = info\\n cache = on\\n")
    first = patch.apply({"app.ini": cfg.replace("host = 0.0.0.0", "host = 10.0.0.5")})
    second = patch.apply({"app.ini": cfg})
    lines = second.tree["app.ini"].split("\\n")
    return [first.log[1].strip(), second.log[1].strip(), lines[1], lines[6]]
"""


class PatchworkTests(unittest.TestCase):
    def values(self):
        return {name: obs.get("value") for name, obs in g.load_expected("patchwork")["probes"].items()}

    def assertFixes(self, case_id, patch):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "passed", result.get("hidden"))
        return result

    def assertFailsOnly(self, case_id, patch, probes):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(sorted(result["hidden"]["failed_probes"]), sorted(probes))
        self.assertEqual(result["regression"]["broken"], [])
        return result

    def test_patchwork_targets(self):
        expected = self.values()
        gaps = expected["probe_hunk_gap_boundary"]
        # changes on lines 5 and 12, context 3: 6 unchanged lines between -> one hunk over lines 2..15
        self.assertEqual(gaps[0], [[1, 14, 1, 14]])
        # lines 5 and 13: 7 between -> two hunks, lines 2..8 and 10..16
        self.assertEqual(gaps[1], [[1, 7, 1, 7], [9, 7, 9, 7]])
        # lines 4 and 9 with context 2 (4 between) and lines 10 and 13 with context 1 (2 between) merge
        self.assertEqual(gaps[3], [[1, 10, 1, 10]])
        self.assertEqual(gaps[5], [[8, 6, 8, 6]])
        # bravo and golf with context 2: charlie..foxtrot (4 lines) between -> lines 1..9 in one hunk
        self.assertTrue(expected["probe_diff_texts_gap_boundary"][0].startswith("--- a/words.txt\n+++ b/words.txt\n@@ -1,9 +1,9 @@\n"))
        # a.txt: lines 10 and 17 (6 between) one hunk; b.txt: 10 and 18 (7 between) two hunks
        self.assertEqual(expected["probe_diffstat_gap_boundary"][0], {"files": 2, "hunks": 3, "insertions": 4, "deletions": 4})
        # marker after a context line: old and new both end without a newline
        self.assertEqual(expected["probe_marker_after_context_flags"][0], [[[0, 0, [" a", "-b", "+B", " c"], False, False]]])
        self.assertEqual(expected["probe_marker_context_apply_hunks"][2:], ["a\nb\nC\nd", "x\ny\nz"])
        self.assertEqual(expected["probe_marker_context_patchset_apply"][0],
                         {"motd": "Welcome\nto this\nserver", "notes.txt": "one\n2\nthree\nfour\nfive"})
        # trimming leaves the hunk itself alone: lines 5..11 around 8, fuzz 1 drops 5 and 11
        trimmed = expected["probe_trimmed_leaves_hunk"]
        self.assertEqual(trimmed[0], [5, 5, [" 6", " 7", "-8", "+eight", " 9", " 10"], True, True])
        self.assertEqual(trimmed[3:5], [True, True])
        # change on 12, context 9..11 / 13..15; 10 drifted -> fuzz 2 drops 9, 10 -> first line placed is 11
        self.assertEqual(expected["probe_fuzz_two_offsets"][0], [["hunk 1 applied at line 11 (fuzz 2)"], True])
        reused = expected["probe_patchset_reused_across_trees"]
        self.assertEqual([item[0][1] for item in reused[:5]], ["  hunk 1 applied at line 5"] * 2 +
                         ["  hunk 1 applied at line 7 (fuzz 2)", "  hunk 1 applied at line 5", "  hunk 1 applied at line 6 (offset +1)"])
        self.assertTrue(reused[5])

    def test_patchwork_alternative_masking_and_overfit(self):
        b1, b2, b3 = PATCHWORK
        gap = "        if groups and op[1] - groups[-1][-1][2] < 2 * context:\n"
        self.assertFixes(b1, patched(b1, "patchwork/hunks.py", gap,
                                     "        if groups and op[1] - groups[-1][-1][2] < 2 * context + 1:\n"))
        overfit = patched(b1, "patchwork/hunks.py", gap,
                          "        if groups and (op[1] - groups[-1][-1][2] < 2 * context or op[1] - groups[-1][-1][2] == 6):\n")
        result = g.grade(b1, overfit)
        self.assertEqual(result["status"], "failed")
        self.assertLess(result["target"]["passed"], result["target"]["total"])
        self.assertFixes(b2, patched(b2, "patchwork/unified.py", '            if last == "+":\n',
                                     '            if last in (" ", "+"):\n'))
        keep_target_newline = patched(b2, "patchwork/apply.py", "            newline = candidate.new_newline\n",
                                      '            newline = text.newline if candidate.lines[-1][0] == " " else candidate.new_newline\n')
        self.assertFailsOnly(b2, keep_target_newline, ["probe_marker_after_context_flags"])
        slice_copy = patched(b3, "patchwork/hunks.py", "        lines = self.lines\n        del lines[len(lines) - back:]\n        del lines[:front]\n",
                             "        lines = self.lines[front:len(self.lines) - back]\n")
        self.assertTrue(self.assertFixes(b3, slice_copy)["localization"]["gold_function_hit"])
        copy_in_apply = patched(b3, "patchwork/apply.py", "        candidate = hunk if level == 0 else hunk.trimmed(level)\n",
                                "        fresh = type(hunk)(hunk.old_start, hunk.new_start, list(hunk.lines), hunk.old_newline, hunk.new_newline)\n"
                                "        candidate = hunk if level == 0 else fresh.trimmed(level)\n")
        self.assertFailsOnly(b3, copy_in_apply, ["probe_trimmed_leaves_hunk"])
        copy_per_tree = patched(b3, "patchwork/patchset.py",
                                "            outcome = apply_hunks(base, item.hunks, fuzz=fuzz, ignore_space=ignore_space, path=item.path)\n",
                                "            hunks = [type(h)(h.old_start, h.new_start, list(h.lines), h.old_newline, h.new_newline) for h in item.hunks]\n"
                                "            outcome = apply_hunks(base, hunks, fuzz=fuzz, ignore_space=ignore_space, path=item.path)\n")
        # a fresh copy per file still over-trims inside one fuzz-2 application
        self.assertFailsOnly(b3, copy_per_tree, ["probe_fuzz_two_offsets", "probe_patchset_reused_across_trees",
                                                 "probe_trimmed_leaves_hunk"])

    def test_patchwork_report_numbers_reproduce_on_clean_and_buggy(self):
        clean_values = {"probe_b1": [["@@ -1,10 +1,10 @@"], 1], "probe_b2": "'DEBUG=0\\nWORKERS=4\\nPORT=8000'",
                        "probe_b3": ["hunk 1 applied at line 6 (fuzz 2)", "hunk 1 applied at line 4", "timeout = 30", "timeout = 60"]}
        buggy_values = {"probe_b1": [["@@ -1,5 +1,5 @@", "@@ -6,5 +6,5 @@"], 2], "probe_b2": "'DEBUG=0\\nWORKERS=4\\nPORT=8000\\n'",
                        "probe_b3": ["hunk 1 applied at line 7 (offset +1, fuzz 2)", "hunk 1 applied at line 2 (offset -2)",
                                     "timeout = 60", "timeout = 30"]}
        quoted = [["@@ -1,10 +1,10 @@", "@@ -1,5 +1,5 @@", "@@ -6,5 +6,5 @@"],
                  ["'DEBUG=0\\nWORKERS=4\\nPORT=8000'", "'DEBUG=0\\nWORKERS=4\\nPORT=8000\\n'"],
                  ["hunk 1 applied at line 6 (fuzz 2)", "hunk 1 applied at line 4", "hunk 1 applied at line 7 (offset +1, fuzz 2)",
                   "hunk 1 applied at line 2 (offset -2)", "timeout = 60", "timeout = 30"]]
        self.assertEqual(run_snippet(g.clean_files("patchwork"), PATCHWORK_REPORTS, "patchwork"), clean_values)
        actual = {probe: run_snippet(g.buggy_files(g.load_case(case_id)), PATCHWORK_REPORTS, "patchwork")[probe]
                  for probe, case_id in zip(["probe_b1", "probe_b2", "probe_b3"], PATCHWORK)}
        self.assertEqual(actual, buggy_values)
        for case_id, numbers in zip(PATCHWORK, quoted):
            for number in numbers:
                self.assertIn(number, g.load_case(case_id)["report_text"])


# --- junction: rail timetable planner ----------------------------------------------------------
JUNCTION = ["junction-b1-exact-transfer-time", "junction-b2-walk-time-rounding", "junction-b3-night-listing-stale"]
JUNCTION_REPORTS = """
def probe_b1():
    from junction import Junction
    text = ('station KRK "Krakow Glowny" zone 1 transfer 5\\nstation KRB "Krakow Bus Station" zone 1\\n'
            'station WIE "Wieliczka" zone 2\\nstation RZE "Rzeszow Glowny" zone 4\\nfootpath KRB KRK 240\\n'
            'service WK mon-fri 2026-03-02..2026-03-31\\ntrip R1 R5 WK\\n  WIE 07:45\\n  KRK 07:57\\n'
            'trip B1 B7 WK\\n  WIE 07:30\\n  KRB 07:52\\ntrip IC1 IC31 WK\\n  KRK 08:02\\n  RZE 09:30\\n')
    return Junction.from_text(text).plan("WIE", "RZE", "2026-03-02", "07:00").describe().splitlines()
def probe_b2():
    from junction import Junction
    text = ('station GLW "Gliwice" zone 1 transfer 4\\nstation KAT "Katowice" zone 2 transfer 5\\n'
            'station KTB "Katowice Bus" zone 2 transfer 2\\nstation SOS "Sosnowiec" zone 3\\nfootpath KAT KTB 250\\n'
            'service ALL daily 2026-05-01..2026-05-31\\ntrip G1 KS1 ALL\\n  GLW 07:00\\n  KAT 07:26\\n'
            'trip M1 B12 ALL\\n  KTB 07:29\\n  SOS 07:50\\ntrip M2 B12 ALL\\n  KTB 07:40\\n  SOS 08:01\\n')
    return Junction.from_text(text).plan("GLW", "SOS", "2026-05-12", "06:30").describe().splitlines()
def probe_b3():
    from junction import Junction
    text = ('station WAW "Warszawa Centralna" zone 1 transfer 6\\nstation RAD "Radom" zone 3 transfer 3\\n'
            'station KIE "Kielce" zone 5\\nservice NT daily 2026-03-01..2026-03-31\\n'
            'trip NX1 TLK8 NT\\n  WAW 23:20\\n  RAD 24:35 24:37\\n  KIE 25:40\\n')
    junction = Junction.from_text(text)
    before = junction.board("RAD", "2026-03-10", "00:00", "02:00").splitlines()
    junction.apply("delay NX1 2026-03-09 +25\\n")
    after = junction.board("RAD", "2026-03-10", "00:00", "02:00").splitlines()
    return [before, after, junction.plan("RAD", "KIE", "2026-03-10", "00:00").summary()]
"""


class JunctionTests(unittest.TestCase):
    def values(self):
        return {name: obs.get("value") for name, obs in g.load_expected("junction")["probes"].items()}

    def assertFixes(self, case_id, patch):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "passed", result.get("hidden"))
        return result

    def assertFailsWith(self, case_id, patch, probes, exact=False):
        result = g.grade(case_id, patch)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["regression"]["broken"], [])
        if exact:
            self.assertEqual(sorted(result["hidden"]["failed_probes"]), sorted(probes))
        else:
            self.assertTrue(set(probes) <= set(result["hidden"]["failed_probes"]), result["hidden"])
        return result

    def test_junction_targets(self):
        """Hand-computed values for target probes, independent of the reference implementation."""
        expected = self.values()
        # a gap equal to the transfer time is enough (ALF 0, BET 4, EPS 7); one minute less is not
        self.assertEqual(expected["probe_change_exact_transfer_time"][0], [True, True, False, True, False])
        # X1 reaches BET 09:20, transfer 4 -> X2 at 09:24 arrives 10:00 (X3 would arrive 10:10)
        self.assertEqual(expected["probe_change_exact_transfer_time"][1][0], "09:00 ALF -> 10:00 GAM, 1h 00m, 1 transfer")
        # T5 reaches KRK 07:57, transfer 5 -> T1 08:02; same arrival as T3 (07:40) but departs later
        self.assertEqual(expected["probe_change_exact_text_plan"][1][0], "07:45 WIE -> 09:30 RZE, 1h 45m, 1 transfer")
        # metres / 80 rounded up: 1, 40, 79 -> 1; 81, 120 -> 2; 200 -> 3; 250 -> 4; 360 -> 5; 440 -> 6; 2999, 3000 -> 38
        self.assertEqual(expected["probe_walking_minutes_round_up"][0], [1, 1, 1, 2, 2, 3, 4, 5, 6, 38, 38])
        # 520 m = 6.5 -> 7 min: LOD 07:03 + 7 = 07:10 misses the 07:09, so the 07:25 arrives 08:30
        self.assertEqual(expected["probe_walk_text_journey"][0][0], "06:50 LDW -> 08:30 SIE, 1h 40m, 1 transfer")
        self.assertEqual(expected["probe_walk_text_journey"][1:], [7, [0, 15], 7])
        # N2 (service day 2 Mar) leaves BCH 24:06 -> 00:06 on 3 Mar; +12 -> 00:18.  N6 23:52 +9 = 24:01 -> 00:01 on 3 Mar
        night = expected["probe_night_delay_after_board"]
        self.assertEqual(night[:3], [[[6, 6, 0, "N7", "N2", "TRN"]], [[18, 6, 12, "N7", "N2", "TRN"]], [[1, -8, 9, "N7", "N6", "BCH"]]])
        # after cancelling the night train, the next BCH -> TRN on Tuesday 3 Mar is T1 08:21 -> 08:41; +20 from KRK: 00:26 -> 00:55
        plans = expected["probe_night_cancel_feed_plan"]
        self.assertEqual([plans[0][0], plans[1][0], plans[3][0]], ["00:06 BCH -> 00:35 TRN, 29m, 0 transfers",
                                                                   "08:21 BCH -> 08:41 TRN, 20m, 0 transfers",
                                                                   "00:26 BCH -> 00:55 TRN, 29m, 0 transfers"])
        # N8 of Sat 7 Mar: DEB 24:06 -> TRN 24:40 shows as 00:40 on Sun 8 Mar once reinstated, 00:45 after +5 from TRN
        self.assertEqual([rows[0][:3] for rows in expected["probe_night_reinstate_arrivals"][1:3]], [[40, 40, 0], [45, 40, 5]])

    def test_junction_alternative_masking_and_overfit(self):
        b1, b2, b3 = JUNCTION
        self.assertFixes(b1, patched(b1, "junction/planner.py", "    return departure - arrival > network.transfer_minutes(station)\n",
                                     "    return not departure - arrival < network.transfer_minutes(station)\n"))
        overfit = patched(b1, "junction/planner.py", "    return departure - arrival > network.transfer_minutes(station)\n",
                          "    return departure - arrival > network.transfer_minutes(station) or departure - arrival == 5\n")
        result = g.grade(b1, overfit)
        self.assertEqual(result["status"], "failed")
        self.assertLess(result["target"]["passed"], result["target"]["total"])
        floor_division = patched(b2, "junction/network.py",
                                 '    return round(whole(metres, 1, MAX_FOOTPATH, "footpath length") / WALK_SPEED)\n',
                                 '    return -(-whole(metres, 1, MAX_FOOTPATH, "footpath length") // WALK_SPEED)\n')
        self.assertTrue(self.assertFixes(b2, floor_division)["localization"]["gold_function_hit"])
        text_only = patched(b2, "junction/journey.py",
                            '        return f"walk {self.minutes} min ({self.metres} m) {self.start} -> {self.end}"\n',
                            '        return f"walk {-(-self.metres // 80)} min ({self.metres} m) {self.start} -> {self.end}"\n')
        self.assertFailsWith(b2, text_only, ["probe_walk_transfer_rounding_plan", "probe_walking_minutes_round_up"])
        both_days = patched(b3, "junction/timetable.py", "        for listed in (service_day, service_day - ONE_DAY):\n",
                            "        for listed in (service_day - ONE_DAY, service_day, service_day + ONE_DAY):\n")
        self.assertTrue(self.assertFixes(b3, both_days)["localization"]["gold_function_hit"])
        forget_all = patched(b3, "junction/timetable.py", "        for listed in (service_day, service_day - ONE_DAY):\n",
                             "        for listed in list(self._listings):\n")
        self.assertFixes(b3, forget_all)
        boards_only = patched(b3, "junction/boards.py", "    for hop in timetable.connections(day):\n",
                              "    timetable._listings.clear()\n    for hop in timetable.connections(day):\n")
        self.assertFailsWith(b3, boards_only, ["probe_night_cancel_feed_plan"], exact=True)

    def test_junction_report_numbers_reproduce_on_clean_and_buggy(self):
        clean_values = {
            "probe_b1": ["07:45 WIE -> 09:30 RZE, 1h 45m, 1 transfer", "  07:45 WIE -> 07:57 KRK  R5 R1",
                         "  08:02 KRK -> 09:30 RZE  IC31 IC1"],
            "probe_b2": ["07:00 GLW -> 08:01 SOS, 1h 01m, 1 transfer", "  07:00 GLW -> 07:26 KAT  KS1 G1",
                         "  walk 4 min (250 m) KAT -> KTB", "  07:40 KTB -> 08:01 SOS  B12 M2"],
            "probe_b3": [["Radom 2026-03-10", "00:37       TLK8   Kielce"], ["Radom 2026-03-10", "01:02 +25   TLK8   Kielce"],
                         "01:02 RAD -> 02:05 KIE, 1h 03m, 0 transfers"]}
        buggy_values = {
            "probe_b1": ["07:30 WIE -> 09:30 RZE, 2h 00m, 1 transfer", "  07:30 WIE -> 07:52 KRB  B7 B1",
                         "  walk 3 min (240 m) KRB -> KRK", "  08:02 KRK -> 09:30 RZE  IC31 IC1"],
            "probe_b2": ["07:00 GLW -> 07:50 SOS, 50m, 1 transfer", "  07:00 GLW -> 07:26 KAT  KS1 G1",
                         "  walk 3 min (250 m) KAT -> KTB", "  07:29 KTB -> 07:50 SOS  B12 M1"],
            "probe_b3": [["Radom 2026-03-10", "00:37       TLK8   Kielce"], ["Radom 2026-03-10", "00:37       TLK8   Kielce"],
                         "00:37 RAD -> 01:40 KIE, 1h 03m, 0 transfers"]}
        quoted = [["07:45 WIE -> 09:30 RZE, 1h 45m, 1 transfer", "07:30 WIE -> 09:30 RZE, 2h 00m, 1 transfer", "07:57", "08:02"],
                  ["walk 4 min (250 m) KAT -> KTB", "walk 3 min (250 m) KAT -> KTB", "08:01", "07:50", "07:29", "07:40"],
                  ["01:02 +25   TLK8   Kielce", "01:02 RAD -> 02:05 KIE", "00:37 RAD -> 01:40 KIE", "+25"]]
        self.assertEqual(run_snippet(g.clean_files("junction"), JUNCTION_REPORTS, "junction"), clean_values)
        actual = {probe: run_snippet(g.buggy_files(g.load_case(case_id)), JUNCTION_REPORTS, "junction")[probe]
                  for probe, case_id in zip(["probe_b1", "probe_b2", "probe_b3"], JUNCTION)}
        self.assertEqual(actual, buggy_values)
        for case_id, numbers in zip(JUNCTION, quoted):
            for number in numbers:
                self.assertIn(number, g.load_case(case_id)["report_text"])


# --- Docker executor (fake ssh; the fake runs the real CHILD locally) --------------------------
def fake_ssh(child=True, returncode=0, stdout="", state=None, inspect_code=0, cleanup_code=0, labels=None,
             run_error=None):
    """Fake ``subprocess.run`` for: docker run -> owned inspection -> label-guarded cleanup."""
    calls, seen = [], {}

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert argv[:6] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--"], argv
        command = shlex.split(argv[-1])
        if command[:2] == ["docker", "run"]:
            seen.update(dict(command[i + 1].split("=", 1) for i, value in enumerate(command) if value == "--label"))
            if run_error is not None:
                raise run_error
            if child:
                tail = command[command.index(g.IMAGE) + 1:]
                with tempfile.TemporaryDirectory() as scratch:
                    process = subprocess.run([sys.executable] + tail, input=kwargs["input"], capture_output=True, text=True,
                                             timeout=60, cwd=scratch, env={"PATH": os.environ.get("PATH", ""), "TMPDIR": scratch})
                return SimpleNamespace(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
        if command[:2] == ["docker", "inspect"]:
            value = {"Config": {"Labels": seen if labels is None else labels},
                     "State": state or {"OOMKilled": False, "ExitCode": returncode, "Error": "", "Running": False}}
            return SimpleNamespace(returncode=inspect_code, stdout=json.dumps(value), stderr="no such container" if inspect_code else "")
        if command[:2] == ["sh", "-c"]:
            return SimpleNamespace(returncode=cleanup_code, stdout="", stderr="")
        raise AssertionError(command)
    return run, calls


class DockerExecutorTests(unittest.TestCase):
    def grade(self, run, case_id=None, patch=None, **kwargs):
        case_id = case_id or INK[2]
        patch = patch if patch is not None else g.reference_patch(g.load_case(case_id))
        return g.grade(case_id, patch, executor=g.DockerExecutor("Spark_01", run=run), **kwargs)

    def test_container_grade_matches_local_and_never_ships_expected_values(self):
        run, calls = fake_ssh()
        case = g.load_case(INK[2])
        patch = g.reference_patch(case)
        result = self.grade(run, patch=patch, timeout=40)
        local = g.grade(INK[2], patch)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual((result["failure_kind"], result["provenance"]), (None, "candidate"))
        self.assertEqual(result["hidden"], local["hidden"])
        self.assertTrue(result["execution"]["cleanup_ok"])
        self.assertEqual([shlex.split(argv[-1])[:2] for argv, _ in calls], [["docker", "run"], ["docker", "inspect"], ["sh", "-c"]])
        argv, kwargs = calls[0]
        docker = shlex.split(argv[-1])
        for flag, value in [("--network", "none"), ("--cap-drop", "ALL"), ("--memory", "256m"), ("--memory-swap", "256m"),
                            ("--pids-limit", "64"), ("--user", "65534:65534"), ("--cpus", "1"), ("--runtime", "runc"),
                            ("--security-opt", "no-new-privileges"), ("--entrypoint", "python3"), ("--pull", "never")]:
            self.assertEqual(docker[docker.index(flag) + 1], value)
        self.assertIn("--read-only", docker)
        self.assertNotIn("--rm", docker)
        self.assertFalse(set(docker) & {"--gpus", "--device", "--privileged", "-v", "--volume", "--mount"})
        self.assertIn("/tmp:rw,noexec,nosuid,nodev,size=16m", docker)
        self.assertEqual(docker[-5:], [g.IMAGE, "-I", "-S", "-c", g.CHILD])
        self.assertEqual(kwargs["timeout"], 40 + g.CONTAINER_STARTUP_SLACK)
        lexer = g.parse_patch(patch)["inkwell/lexer.py"]
        self.assertNotIn(lexer, argv[-1])
        wire = json.loads(kwargs["input"])
        self.assertEqual(set(wire), {"mode", "package", "files", "probes", "probe_names", "probe_timeout"})
        self.assertEqual(wire["files"]["inkwell/lexer.py"], lexer)
        expected = g.load_expected("inkwell")["probes"]
        for name in case["target_probes"]:
            self.assertNotIn(json.dumps(expected[name]["value"]), kwargs["input"])
        labels = dict(docker[i + 1].split("=", 1) for i, value in enumerate(docker) if value == "--label")
        task = labels[g.LABEL_TASK]
        self.assertEqual(labels[g.LABEL_OWNER], g.OWNER)
        self.assertEqual(docker[docker.index("--name") + 1], "swarm-bugbench-" + task)
        cleanup = calls[2][0][-1]
        for needle in (g.OWNER, task, "docker rm -f swarm-bugbench-" + task):
            self.assertIn(needle, cleanup)

    def test_buggy_tree_fails_in_container_like_locally(self):
        run, _ = fake_ssh()
        case = g.load_case(AGENDA[1])
        path = case["gold"]["files"][0]
        result = self.grade(run, AGENDA[1], g.patch_from_files({path: g.buggy_files(case)[path]}))
        self.assertEqual((result["status"], result["failure_kind"]), ("failed", "candidate_probe_failure"))
        self.assertEqual(sorted(result["hidden"]["failed_probes"]), sorted(case["target_probes"]))

    def test_timeout_is_candidate_only_with_container_evidence(self):
        running = {"OOMKilled": False, "ExitCode": 0, "Error": "", "Running": True}
        run, calls = fake_ssh(run_error=subprocess.TimeoutExpired("ssh", 75), state=running)
        result = self.grade(run)
        self.assertEqual((result["status"], result["failure_kind"], result["provenance"]), ("timeout", "candidate_timeout", "candidate"))
        self.assertEqual(shlex.split(calls[-1][0][-1])[:2], ["sh", "-c"])
        run, _ = fake_ssh(run_error=subprocess.TimeoutExpired("ssh", 75), inspect_code=1)
        result = self.grade(run)
        self.assertEqual((result["status"], result["failure_kind"], result["provenance"]), ("error", "ssh_infrastructure", "infrastructure"))

    def test_oom_kill_and_signals_are_candidate_failures(self):
        run, _ = fake_ssh(child=False, returncode=137, state={"OOMKilled": True, "ExitCode": 137, "Error": "", "Running": False})
        result = self.grade(run)
        self.assertEqual((result["status"], result["failure_kind"], result["provenance"]), ("failed", "candidate_oom", "candidate"))
        self.assertNotIn("hidden", result)
        run, _ = fake_ssh(child=False, returncode=137, state={"OOMKilled": False, "ExitCode": 137, "Error": "", "Running": False})
        self.assertEqual(self.grade(run)["failure_kind"], "candidate_signal")
        run, _ = fake_ssh(child=False, returncode=1)
        self.assertEqual(self.grade(run)["failure_kind"], "candidate_runtime")

    def test_cleanup_failure_is_infrastructure_even_after_a_good_run(self):
        run, _ = fake_ssh(cleanup_code=1)
        result = self.grade(run)
        self.assertEqual((result["status"], result["failure_kind"], result["provenance"]),
                         ("error", "cleanup_infrastructure", "infrastructure"))
        self.assertIsNone(result["execution"]["original_failure_kind"])
        self.assertFalse(result["execution"]["cleanup_ok"])
        self.assertNotIn("hidden", result)
        run, _ = fake_ssh(child=False, returncode=137, cleanup_code=1,
                          state={"OOMKilled": True, "ExitCode": 137, "Error": "", "Running": False})
        result = self.grade(run)
        self.assertEqual((result["failure_kind"], result["execution"]["original_failure_kind"]),
                         ("cleanup_infrastructure", "candidate_oom"))

    def test_malformed_output_is_a_candidate_protocol_failure(self):
        for stdout in ("not json", "[1, 2]", '{"version": 2}', '{"version": 1, "results": []}',
                       '{"version": 1, "results": [1, 2, 3]}', "x" * (g.MAX_CHILD_OUTPUT + 1)):
            with self.subTest(stdout=stdout[:30]):
                run, _ = fake_ssh(child=False, stdout=stdout)
                result = self.grade(run)
                self.assertEqual((result["status"], result["failure_kind"], result["provenance"]),
                                 ("failed", "candidate_protocol", "candidate"))

    def test_transport_docker_and_inspection_failures_are_infrastructure(self):
        broken = {"OOMKilled": False, "ExitCode": 128, "Error": "OCI runtime create failed", "Running": False}
        for kwargs, kind in [(dict(child=False, returncode=255), "ssh_infrastructure"),
                             (dict(child=False, returncode=125), "docker_infrastructure"),
                             (dict(child=False, returncode=1, state=broken), "docker_infrastructure"),
                             (dict(run_error=OSError("ssh missing")), "ssh_infrastructure"),
                             (dict(inspect_code=1), "inspection_infrastructure"),
                             (dict(labels={g.LABEL_OWNER: "someone-else", g.LABEL_TASK: "x"}), "inspection_infrastructure")]:
            with self.subTest(kind=kind, kwargs=list(kwargs)):
                run, _ = fake_ssh(**kwargs)
                result = self.grade(run)
                self.assertEqual((result["status"], result["failure_kind"], result["provenance"]), ("error", kind, "infrastructure"))

    def test_bad_hosts_never_reach_ssh(self):
        for host in ("", "-oProxyCommand=id", "spark 01", "a;b", "user@", None):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    g.DockerExecutor(host, run=lambda *a, **k: self.fail("ssh called"))

    def test_public_tests_through_container(self):
        run, calls = fake_ssh()
        case = g.load_case(AGENDA[0])
        result = g.run_public_tests("agenda", g.buggy_files(case), executor=g.DockerExecutor("user@spark-02", run=run))
        self.assertTrue(result["ok"], result)
        self.assertEqual(json.loads(calls[0][1]["input"])["mode"], "public_tests")
        run, _ = fake_ssh(child=False, returncode=255)
        result = g.run_public_tests("agenda", g.buggy_files(case), executor=g.DockerExecutor("spark-02", run=run))
        self.assertEqual((result["ok"], result["provenance"]), (False, "infrastructure"))


class MutantToolTests(unittest.TestCase):
    def test_operator_mutants_skip_docs_and_strings(self):
        source = 'def f(a, b):\n    """a < b and done."""\n    # x < y\n    if a < b and a:\n        raise ValueError(f"not {a} < {b}")\n    return a\n'
        mutants = g.operator_mutants({"m.py": source}, ["m.py"])
        self.assertEqual(sorted((m["line"], m["old"]) for m in mutants), [(4, " < "), (4, " and ")])

    def test_mutation_score_runs_on_a_sample(self):
        report = g.mutation_score("agenda", paths=["agenda/timeutil.py"], limit=6, workers=3)
        self.assertEqual(report["mutants"], 6)
        self.assertEqual(report["killed"] + len(report["survivors"]), 6)
        self.assertGreater(report["killed"], 0)


if __name__ == "__main__":
    unittest.main()


class DockerRetryTests(unittest.TestCase):
    """Transport-only: SSH connection-setup failures are retried; candidate outcomes never are."""

    def fake(self, outcomes):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            remote = argv[-1]
            kind = outcomes[0] if ' run ' in f' {remote} ' and 'docker run' in remote else 'meta'
            if 'docker run' in remote:
                outcomes.pop(0)
                if kind == 'banner':
                    return subprocess.CompletedProcess(argv, 255, '', 'Connection timed out during banner exchange')
                return subprocess.CompletedProcess(argv, 0, json.dumps({'ok': True}), '')
            if remote.startswith('sh -c'):  # guarded cleanup: nothing of ours exists
                return subprocess.CompletedProcess(argv, 0, '', '')
            if 'docker inspect' in remote:
                return subprocess.CompletedProcess(argv, 1, '', 'No such object')
            return subprocess.CompletedProcess(argv, 0, '', '')
        return run, calls

    def test_banner_timeout_is_retried_on_next_host(self):
        import bugbench_grader as g
        run, calls = self.fake(['banner', 'ok'])
        executor = g.DockerExecutor('Spark_01,Spark_02', run=run, backoff=(0,))
        executor._once = executor._once  # real path
        result, error, meta = executor({'x': 1}, 5)
        hosts = [c[c.index('--') + 1] for c in calls if 'docker run' in c[-1]]
        self.assertEqual(hosts, ['Spark_01', 'Spark_02'])
        self.assertEqual(len(meta.get('connection_retries', [])), 1)

    def test_retry_budget_exhausts_as_infrastructure(self):
        import bugbench_grader as g
        run, calls = self.fake(['banner'] * 4)
        result, error, meta = g.DockerExecutor('Spark_01', run=run, retries=3, backoff=(0,))({'x': 1}, 5)
        self.assertEqual(meta['provenance'], 'infrastructure')
        self.assertEqual(sum('docker run' in c[-1] for c in calls), 4)
