"""Pure offline checks for early outcomes and honest server-cost accounting."""
import unittest

import analysis


class AnalysisTests(unittest.TestCase):
    def test_expected_negative_early_kill_is_success(self):
        self.assertEqual(analysis.outcome(dict(solved=True, controller_stop=True, returncode=-15)), "solved_early")

    def test_deadline_with_verified_success_is_preserved(self):
        self.assertEqual(analysis.outcome(dict(deadline=True, solved=True)), "solved_with_deadline")

    def test_unknown_or_stale_server_cost_is_not_zero(self):
        row = dict(solved=True, wall_seconds=1, prompt_tokens=20, completion_tokens=7,
                   server_cost_known=False, server_prompt_tokens=0, server_completion_tokens=0)
        summary = analysis.aggregate("direct_off", [row], 1)
        self.assertIsNone(summary["server_prompt_tokens_known"])
        self.assertIsNone(summary["server_completion_tokens_known"])
        row["server_cost_known"] = True
        self.assertFalse(analysis.valid_server_cost(row))
        self.assertEqual(analysis.aggregate("direct_off", [row], 1)["server_counter_floor_failures"], 1)

    def test_server_cost_and_unfinished_client_cost_are_distinct(self):
        row = dict(solved=True, wall_seconds=1, unfinished_calls=1, prompt_tokens=20, completion_tokens=7,
                   server_cost_known=True, server_prompt_tokens=30, server_completion_tokens=11,
                   controller_stop=True, returncode=-15, status="success_early")
        summary = analysis.aggregate("independent8", [row], 1)
        self.assertTrue(summary["observed_cost_is_lower_bound"])
        self.assertEqual(summary["server_completion_tokens_known"], 11)
        self.assertEqual(summary["unexpected_process_error_cases"], 0)

    def test_empty_arm_has_unknown_server_cost(self):
        summary = analysis.aggregate("independent8", [], 8)
        self.assertIsNone(summary["success_rate"])
        self.assertIsNone(summary["server_completion_tokens_known"])
        self.assertTrue(summary["observed_cost_is_lower_bound"])

    def test_no_candidate_stays_unsolved_in_denominator_and_has_unknown_holdout_totals(self):
        missing = dict(solved=False, wall_seconds=2, returncode=0, holdout_status=None,
                       holdout_eval_count=0, holdout_passed=None, holdout_total=None,
                       feedback_final_status=None, feedback_eval_count=0)
        passed = dict(solved=True, wall_seconds=1, returncode=0, holdout_status="passed",
                      holdout_eval_count=1, holdout_passed=6, holdout_total=6,
                      feedback_final_status="passed", feedback_eval_count=1)
        summary = analysis.aggregate("direct_thinking", [passed, missing], 2)
        self.assertEqual((summary["observed_cases"], summary["solved"], summary["success_rate"]), (2, 1, .5))
        self.assertEqual((summary["holdout_eval_count"], summary["cases_with_holdout_grade"], summary["cases_without_holdout_grade"]), (1, 1, 1))
        self.assertEqual((summary["holdout_passed"], summary["holdout_total"], summary["holdout_test_totals_known_cases"], summary["holdout_test_totals_unknown_cases"]), (6, 6, 1, 1))
        ungraded = analysis.aggregate("direct_thinking", [missing], 1)
        self.assertEqual((ungraded["observed_cases"], ungraded["solved"], ungraded["success_rate"]), (1, 0, 0))
        self.assertIsNone(ungraded["holdout_passed"])
        self.assertIsNone(ungraded["holdout_total"])
        self.assertEqual((ungraded["cases_without_holdout_grade"], ungraded["holdout_test_totals_known_cases"]), (1, 0))
        self.assertIsNone(missing["holdout_total"])


if __name__ == "__main__":
    unittest.main()
