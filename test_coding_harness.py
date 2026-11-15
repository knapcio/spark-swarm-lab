"""No model/SSH/Docker calls; fake client and grader exercise selection boundaries."""
import argparse
import json
import threading
import unittest
from unittest.mock import patch

import coding_harness as c
import harness as h


class Events:
    def __init__(self):
        self.rows, self.lock = [], threading.Lock()

    def emit(self, kind, **fields):
        with self.lock:
            self.rows.append(dict(type=kind, **fields))


class Client:
    def __init__(self, budget=None):
        self.budget = budget or h.Budget(100, 10000)
        self.infra_failures = self.budget_failures = 0
        self.calls, self.lock = [], threading.Lock()

    def call(self, agent, stage, prompt, **context):
        with self.lock:
            self.calls.append(dict(agent=agent, stage=stage, prompt=prompt, **context))
        if not self.budget.reserve(10):
            self.budget_failures += 1
            return None
        self.budget.settle(10, 2)
        if stage == "code_vote":
            return {"candidate_id": json.loads(prompt.split("Candidates:\n", 1)[1])[0]["candidate_id"]}
        return {"code": f"def f(x): return x  # agent={agent},round={context['round']}"}


class CodingTests(unittest.TestCase):
    task = dict(id="dev-f", function_name="f", spec="Return an integer.", examples=[dict(args=[1], expected=2), dict(args=[2], expected=3)])
    private = dict(feedback_tests=[dict(args=[3], expected=4), dict(args=[4], expected=5)],
                   holdout_tests=[dict(args=[999], expected="HOLDOUT_SENTINEL")],
                   trusted_reference_source="REFERENCE_SENTINEL")

    def execute(self, method, grader, agents=2, rounds=3, client=None, code_format="json"):
        args = argparse.Namespace(method=method, agents=1 if method in ("direct", "iterative") else agents,
                                  rounds=rounds, host="Spark_02", code_format=code_format)
        events, client = Events(), client or Client()
        main_thread = threading.get_ident()
        grades = []
        def evaluate(code, function, tests, host):
            self.assertEqual(threading.get_ident(), main_thread)
            phase = "holdout" if tests is self.private["holdout_tests"] else "feedback"
            grades.append((phase, code))
            return grader(phase, code, tests)
        result = c.run_experiment(args, self.task, self.private, client, events, evaluate)
        for call in client.calls:
            self.assertNotIn("HOLDOUT_SENTINEL", call["prompt"])
            self.assertNotIn("REFERENCE_SENTINEL", call["prompt"])
        self.assertEqual(sum(phase == "holdout" for phase, _ in grades), 1)
        self.assertEqual(grades[-1][0], "holdout")
        return result, events.rows, client.calls, grades

    def test_all_policies_freeze_before_one_holdout_with_no_holdout_repair(self):
        def grade(phase, code, tests):
            return dict(status="passed" if phase == "feedback" else "failed", passed=len(tests) if phase == "feedback" else 0,
                        total=len(tests), first_failure=None if phase == "feedback" else {"expected": "HOLDOUT_SENTINEL"})
        for method in ("direct", "iterative", "independent", "shared", "democracy"):
            with self.subTest(method=method):
                result, rows, calls, _ = self.execute(method, grade)
                self.assertFalse(result["solved"])
                self.assertEqual(result["selection_basis"], "democracy_review_vote" if method == "democracy" else "first_feedback_pass")
                self.assertEqual(sum(call["stage"] == "code_vote" for call in calls), 2 if method == "democracy" else 0)
                self.assertTrue(all(call["round"] == 0 for call in calls))
                selected = next(i for i, row in enumerate(rows) if row["type"] == "candidate_selected")
                held = next(i for i, row in enumerate(rows) if row["type"] == "evaluation_start" and row["phase"] == "holdout")
                complete = next(i for i, row in enumerate(rows) if row["type"] == "selection_complete")
                self.assertLess(selected, held)
                self.assertLess(held, complete)

    def test_shared_feedback_bounded_and_independent_tracks_do_not_share(self):
        def grade(phase, code, tests):
            return dict(status="failed", passed=1, total=len(tests),
                        first_failure=dict(input={"args": [3], "kwargs": {}}, expected=4, actual=0))
        for method in ("independent", "shared", "democracy"):
            result, rows, calls, _ = self.execute(method, grade)
            self.assertEqual(result["selection_basis"], "democracy_review_vote" if method == "democracy" else "best_feedback_score_then_code_hash")
            self.assertEqual([call["round"] for call in calls if call["stage"] == "code_propose"], [0, 0, 1, 1, 2, 2])
            snapshots = [row for row in rows if row["type"] == "memory_snapshot"]
            self.assertTrue(all(len(row["facts"]) <= 4 for row in snapshots))
            if method == "independent":
                self.assertEqual(snapshots, [])
                for call in (row for row in calls if row["round"] > 0):
                    self.assertIn(f"agent={call['agent']}", call["prompt"])
                    self.assertNotIn(f"agent={1-call['agent']}", call["prompt"])
            if method == "democracy":
                self.assertEqual(sum(call["stage"] == "code_vote" for call in calls), 6)

    def test_final_selection_uses_feedback_score_then_hash_not_holdout_best_of_n(self):
        def grade(phase, code, tests):
            return dict(status="failed", passed=(1 if "agent=1" in code and phase == "feedback" else 0), total=len(tests), first_failure=None)
        result, _, _, grades = self.execute("independent", grade)
        self.assertIn("agent=1", grades[-1][1])
        self.assertEqual(result["feedback"]["passed"], 1)

    def test_infrastructure_failure_is_not_a_valid_candidate_quality_grade(self):
        def grade(phase, code, tests):
            if "agent=0" in code and phase == "feedback":
                return dict(status="error", error="SSH failed", exit_code=255, cleanup_ok=False)
            return dict(status="failed", passed=0, total=len(tests), first_failure=None)
        result, _, _, grades = self.execute("independent", grade, rounds=1)
        self.assertIn("agent=1", grades[-1][1])
        self.assertEqual(result["infrastructure_failures"], 1)

    def test_resource_failures_with_successful_cleanup_can_be_repaired(self):
        def grade(phase, code, tests):
            if phase == "feedback" and "round=0" in code:
                return dict(status="error", passed=0, total=len(tests), error="candidate OOM", exit_code=137,
                            container_state=dict(OOMKilled=True, ExitCode=137), cleanup_ok=True,
                            failure_kind="candidate_oom", provenance="candidate")
            return dict(status="passed", passed=len(tests), total=len(tests))
        result, rows, calls, _ = self.execute("iterative", grade)
        self.assertTrue(result["solved"])
        self.assertEqual(result["infrastructure_failures"], 0)
        self.assertIn("Previous implementation", calls[1]["prompt"])
        self.assertIn("candidate OOM", calls[1]["prompt"])
        for kind in ("candidate_oom", "candidate_signal", "candidate_runtime", "candidate_timeout"):
            self.assertFalse(c.infrastructure(dict(status="error", exit_code=137, cleanup_ok=True, failure_kind=kind)))
        self.assertTrue(c.infrastructure(dict(status="error", failure_kind="candidate_oom", cleanup_ok=False)))
        self.assertTrue(c.infrastructure(dict(status="error", failure_kind="ssh_infrastructure", cleanup_ok=True)))

    def test_all_invalid_model_outputs_finish_without_a_holdout_or_extra_calls(self):
        client, events = Client(), Events()
        args = argparse.Namespace(method="shared", agents=2, rounds=3, host="Spark_02")
        with patch.object(client, "call", return_value=None), patch.object(c, "evaluate_code") as grade:
            result = c.run_experiment(args, self.task, self.private, client, events, evaluator=grade)
        grade.assert_not_called()
        self.assertIsNone(result["candidate_id"])
        self.assertFalse(result["solved"])
        self.assertTrue(any(row["type"] == "selection_complete" for row in events.rows))

    def test_feedback_holdout_overlap_is_rejected_before_any_call(self):
        args = argparse.Namespace(method="direct", agents=1, rounds=1, host="Spark_02")
        client = Client()
        with self.assertRaises(ValueError):
            c.run_experiment(args, self.task, dict(feedback_tests=[dict(args=[1], expected=2)],
                holdout_tests=[dict(args=[1], expected=99)]), client, Events(), evaluator=lambda *args: None)
        self.assertEqual(client.calls, [])

    def test_cli_mode_can_finalize_failed_holdout_before_pending_http_finishes(self):
        started, release = threading.Event(), threading.Event()
        class PendingClient(Client):
            def call(self, agent, stage, prompt, **context):
                if agent != 1:
                    return super().call(agent, stage, prompt, **context)
                self.budget.reserve(10)
                started.set()
                release.wait(3)
                self.budget.settle(10, 2)
                return {"code": "def f(x): return x"}
        client, events = PendingClient(), Events()
        args = argparse.Namespace(method="independent", agents=2, rounds=3, host="Spark_02")
        def grade(code, function, cases, host):
            self.assertTrue(started.wait(2))
            return dict(status="passed" if cases is self.private["feedback_tests"] else "failed",
                        passed=len(cases) if cases is self.private["feedback_tests"] else 0, total=len(cases))
        try:
            result = c.run_experiment(args, self.task, self.private, client, events, grade, wait_for_pending=False)
            self.assertFalse(result["solved"])
            self.assertFalse(result["usage_complete"])
            self.assertEqual(result["pending_tasks_aborted_on_cli_exit"], 1)
            self.assertEqual(result["completion_tokens_upper_bound_at_selection"], 12)
            self.assertTrue(any(row["type"] == "selection_complete" for row in events.rows))
        finally:
            release.set()

    def test_private_overlap_with_examples_is_rejected(self):
        args = argparse.Namespace(method="direct", agents=1, rounds=1, host="Spark_02")
        with self.assertRaises(ValueError):
            c.run_experiment(args, self.task, dict(feedback_tests=[dict(args=[1], expected=2)],
                holdout_tests=[dict(args=[999], expected=0)]), Client(), Events(), evaluator=lambda *a: None)

    def test_democracy_reviews_complete_passing_batch_before_private_grade_once(self):
        def grade(phase, code, tests):
            return dict(status="passed", passed=len(tests), total=len(tests))
        result, rows, calls, grades = self.execute("democracy", grade, agents=3)
        self.assertTrue(result["solved"])
        self.assertEqual([phase for phase, _ in grades], ["feedback"] * 3 + ["holdout"])
        self.assertEqual(sum(call["stage"] == "code_vote" for call in calls), 3)
        last_feedback = max(i for i, row in enumerate(rows) if row["type"] == "evaluation_end" and row["phase"] == "feedback")
        first_vote = min(i for i, row in enumerate(rows) if row["type"] == "vote")
        holdout = next(i for i, row in enumerate(rows) if row["type"] == "evaluation_start" and row["phase"] == "holdout")
        self.assertLess(last_feedback, first_vote)
        self.assertLess(first_vote, holdout)
        shortlist = json.loads(next(call["prompt"] for call in calls if call["stage"] == "code_vote").split("Candidates:\n", 1)[1])
        self.assertEqual(len(shortlist), 3)
        self.assertTrue(all(row["feedback"]["status"] == "passed" for row in shortlist))

    def test_duplicate_code_uses_common_exact_feedback_cache_but_separate_holdout(self):
        client, events, grades = Client(), Events(), []
        args = argparse.Namespace(method="independent", agents=3, rounds=2, host="Spark_02")
        def grade(code, function, cases, host):
            grades.append(cases)
            return dict(status="failed", passed=0, total=len(cases), first_failure=None)
        with patch.object(client, "call", return_value={"code": "def f(x): return x"}):
            c.run_experiment(args, self.task, self.private, client, events, grade)
        self.assertEqual(grades, [self.private["feedback_tests"], self.private["holdout_tests"]])
        actual = [row for row in events.rows if row["type"] == "evaluation_end"]
        reused = [row for row in events.rows if row["type"] == "evaluation_reused"]
        self.assertEqual(len(actual), 2)
        self.assertEqual(len(reused), 5)
        self.assertTrue(all(row["source_evaluation_id"] == actual[0]["evaluation_id"] for row in reused))

    def test_infrastructure_and_timeout_reports_are_not_cached(self):
        for report in [dict(status="error", exit_code=255, cleanup_ok=False),
                       dict(status="timeout", error="Execution deadline exceeded")]:
            with self.subTest(report=report):
                client, events, grades = Client(), Events(), []
                args = argparse.Namespace(method="independent", agents=3, rounds=1, host="Spark_02")
                def grade(code, function, cases, host):
                    grades.append(cases)
                    return dict(report)
                with patch.object(client, "call", return_value={"code": "def f(x): return x"}):
                    c.run_experiment(args, self.task, self.private, client, events, grade)
                self.assertEqual(sum(cases is self.private["feedback_tests"] for cases in grades), 3)
                self.assertFalse(any(row["type"] == "evaluation_reused" for row in events.rows))

    def test_syntax_error_is_cached_as_model_quality_failure(self):
        client, events, grades = Client(), Events(), []
        args = argparse.Namespace(method="independent", agents=2, rounds=1, host="Spark_02")
        def grade(code, function, cases, host):
            grades.append(cases)
            return dict(status="error", error="SyntaxError: invalid code", passed=0, total=len(cases))
        with patch.object(client, "call", return_value={"code": "invalid code"}):
            result = c.run_experiment(args, self.task, self.private, client, events, grade)
        self.assertEqual(len(grades), 2)  # Feedback once, then the separately frozen holdout once.
        self.assertEqual(result["infrastructure_failures"], 0)
        self.assertEqual(sum(row["type"] == "evaluation_reused" for row in events.rows), 1)

    def test_democracy_holdout_grades_the_review_winner_not_first_feedback_pass(self):
        class LastVoteClient(Client):
            def call(self, agent, stage, prompt, **context):
                result = super().call(agent, stage, prompt, **context)
                if stage == "code_vote":
                    return {"candidate_id": json.loads(prompt.split("Candidates:\n", 1)[1])[-1]["candidate_id"]}
                return result
        def grade(phase, code, tests):
            return dict(status="passed", passed=len(tests), total=len(tests))
        result, _, calls, grades = self.execute("democracy", grade, agents=3, client=LastVoteClient())
        shortlist = json.loads(next(call["prompt"] for call in calls if call["stage"] == "code_vote").split("Candidates:\n", 1)[1])
        self.assertEqual(result["candidate_id"], shortlist[-1]["candidate_id"])
        self.assertEqual(c.hashlib.sha256(grades[-1][1].encode()).hexdigest(), result["candidate_id"])

    def test_python_source_plain_and_fenced_preserves_intentional_backslashes(self):
        source = 'import re\ndef f(text):\n    return re.sub(r"\\\\n", r"\\t", text)'
        self.assertEqual(c.parse_python_response(source, "code_propose"), {"code": source})
        self.assertEqual(c.parse_python_response('```python\n' + source + '\n```', "code_propose"), {"code": source})
        literal_newline_escape = r'def f(x):\n    return x'
        self.assertEqual(c.parse_python_response(literal_newline_escape, "code_propose")["code"], literal_newline_escape)
        with self.assertRaises(ValueError):
            c.parse_python_response('```python\ndef f(): pass', "code_propose")

    def test_python_format_votes_still_use_json_and_default_prompt_is_legacy_json(self):
        self.assertEqual(c.parse_python_response('{"candidate_id":"abc"}', "code_vote"), {"candidate_id": "abc"})
        with self.assertRaises(ValueError):
            c.parse_python_response('candidate_id = "abc"', "code_vote")
        def grade(phase, code, tests):
            return dict(status="passed", passed=len(tests), total=len(tests))
        _, _, calls, _ = self.execute("direct", grade)
        self.assertTrue(calls[0]["prompt"].endswith('Return exactly a JSON object with one key "code", containing the complete implementation.'))
        _, _, calls, _ = self.execute("democracy", grade, code_format="python")
        self.assertTrue(all('Return complete Python function source only.' in call["prompt"]
                            for call in calls if call["stage"] == "code_propose"))
        self.assertTrue(all('Return JSON {"candidate_id":"id"}' in call["prompt"]
                            for call in calls if call["stage"] == "code_vote"))


if __name__ == "__main__":
    unittest.main()
