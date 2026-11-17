"""Offline control-flow tests for the arbiter-free swarm (no model, no subprocess)."""
import unittest
from pathlib import Path
from unittest.mock import patch
import run_arbiterfree as r

PLAN = dict(stage_a_variant='forced_explicit', stage_a_seed_offset=1100, stage_b_variant='long_forced_original',
            stage_b_seed_offset=1200, agent_wall_deadline_seconds=3600)
TASK = dict(id='t', numbers=[1, 2, 3, 4], target=10)


def fake(stage_plans, verdicts, truth):
    calls = {'judge': [], 'jobs': []}

    def execute(job, deadline_seconds):
        calls['jobs'].append(job['command'][job['command'].index('--variant') + 1])
        return dict(deadline=False, controller_error=None)

    def plan_of(path):
        name = Path(path).stem  # t-s1-A0-variant
        key = name.split('-')[2]
        return dict(plan=stage_plans.get(key), verifier_solved=truth.get(key, False), tokens=10, infra=0)

    def judge(candidate, mode, endpoint, events_path, seed):
        key = f"{candidate['run']}{candidate['agent']}"
        assert candidate['truth'] is None and mode == 'think'
        calls['judge'].append(key)
        return dict(verdict=verdicts.get(key), infra=0, tokens=5)
    return calls, execute, plan_of, judge


class ArbiterFreeTests(unittest.TestCase):
    def run_case(self, stage_plans, verdicts, truth):
        calls, ex, po, ju = fake(stage_plans, verdicts, truth)
        with patch.object(r, 'execute', ex), patch.object(r, 'plan_of', po), patch.object(r.run_judge, 'judge', ju):
            rec = r.run_case(PLAN, Path('/src'), Path('/out'), TASK, 1, 0, r.Slots(4))
        return calls, rec

    def test_stage_a_accept_stops_without_escalation(self):
        plans = {'A0': {'moves': [1]}, 'A1': {'moves': [1]}}
        calls, rec = self.run_case(plans, {'A0': False, 'A1': True}, {'A1': True})
        self.assertFalse(rec['escalated'])
        self.assertEqual(rec['selected'], dict(stage='A', agent=1))
        self.assertTrue(rec['solved'])
        self.assertEqual(calls['jobs'].count('long_forced_original'), 0)

    def test_escalates_when_nothing_accepted_and_selection_ignores_truth(self):
        plans = {'A0': {'moves': [1]}, 'B2': {'moves': [1]}, 'B3': {'moves': [1]}}
        calls, rec = self.run_case(plans, {'A0': False, 'B2': True, 'B3': True}, {'A0': True, 'B3': True})
        self.assertTrue(rec['escalated'])
        self.assertEqual(rec['selected'], dict(stage='B', agent=2))  # first accepted, although B3 was the true one
        self.assertTrue(rec['wrong_answer'] and rec['oracle_any'])
        self.assertEqual(calls['jobs'].count('long_forced_original'), 4)

    def test_unparsed_plans_are_not_judged_and_no_answer_possible(self):
        calls, rec = self.run_case({}, {}, {})
        self.assertEqual(calls['judge'], [])
        self.assertFalse(rec['answered'] or rec['solved'])


if __name__ == '__main__':
    unittest.main()
