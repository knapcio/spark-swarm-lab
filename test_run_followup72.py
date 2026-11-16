import json
from collections import Counter
from pathlib import Path
import unittest

from run_followup72 import DATASET, make_cases, operational_fault


class FollowupMatrixTests(unittest.TestCase):
    def test_balanced_complete_development_matrix(self):
        endpoints = [f'http://127.0.0.1:{p}/v1' for p in range(18081, 18085)]
        dataset = json.loads(DATASET.read_text())
        rows = make_cases(dataset, Path('/unused-plan-output'), endpoints)
        self.assertEqual(len(rows), 168)
        self.assertEqual(len({r['events'] for r in rows}), 168)
        self.assertEqual(set(Counter(r['block'] for r in rows).values()), {7})
        self.assertEqual(Counter(r['slot'] for r in rows), {i: 42 for i in range(4)})
        self.assertEqual(set(Counter((r['seed'], r['arm'], r['slot']) for r in rows).values()), {2})
        evaluation = {t['id'] for t in dataset['tasks'] if t['split'] == 'evaluation'}
        self.assertFalse(evaluation & {r['task_id'] for r in rows})
        for row in rows:
            self.assertEqual(row['endpoint'], endpoints[row['slot']])
            self.assertIn('--run', row['command'])
            self.assertEqual(row['command'][row['command'].index('--timeout') + 1], '210')
            self.assertFalse(row['stop_on_solution'])
            self.assertTrue(row['server_metrics'])

    def test_duplicate_endpoint_cannot_be_treated_as_four_nodes(self):
        with self.assertRaisesRegex(ValueError, 'distinct endpoints'):
            make_cases(json.loads(DATASET.read_text()), Path('/unused'), ['http://same/v1'] * 4)


class FaultClassificationTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(controller_error=None, malformed_lines=0, infrastructure_failures=0,
                   returncode=0, controller_stop=False, calls=1, completed_calls=1,
                   unfinished_calls=0, deadline=False, status='complete',
                   server_idle_after=True, server_cost_known=True)
        row.update(changes)
        return row

    def test_controlled_deadline_keeps_task_outcome_and_unknown_client_usage(self):
        self.assertIsNone(operational_fault(self.row(deadline=True, controller_stop=True,
                          returncode=-15, completed_calls=0, unfinished_calls=1,
                          infrastructure_failures=None, status='deadline')))

    def test_budget_denial_is_not_itself_infrastructure(self):
        self.assertIsNone(operational_fault(self.row(status='budget_limited', budget_denials=1)))

    def test_no_dispatch_and_missing_final_record_are_not_valid_cases(self):
        self.assertEqual(operational_fault(self.row(calls=0, completed_calls=0)),
                         'missing_or_inconsistent_request_lifecycle')
        self.assertEqual(operational_fault(self.row(status='missing_run_end', infrastructure_failures=None)),
                         'unexpected_completion_state')

    def test_transport_fault_and_unconfirmed_server_cost_halt_next_block(self):
        self.assertEqual(operational_fault(self.row(infrastructure_failures=1)),
                         'controller_or_transport_failure')
        self.assertEqual(operational_fault(self.row(server_cost_known=False)),
                         'endpoint_drain_or_counter_accounting_unknown')


if __name__ == '__main__':
    unittest.main()
