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
PROJECTS = ["agenda", "inkwell", "stockroom"]
ALL_CASES = {
    "agenda": ["agenda-b1-slot-grid-default", "agenda-b2-weekday-order", "agenda-b3-split-cancelled-count"],
    "inkwell": ["inkwell-b1-round-half-even", "inkwell-b2-and-or-precedence", "inkwell-b3-trim-line-drift"],
    "stockroom": CASES,
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
