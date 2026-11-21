"""Offline orchestration tests for swarm variants (no model)."""
import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import run_variants as v

PLAN = dict(agent_variant='long_forced_original', agent_wall_deadline_seconds=3600,
            seed_offsets=dict(deep4=1400, strategy4=1500, repair4=1600, board2x2=1700))
TASK = dict(id='t', numbers=[1, 2, 3, 4], target=10)


class VariantTests(unittest.TestCase):
    def run_policy(self, policy, verdicts, plans=True):
        seen = []

        def execute(job, deadline_seconds):
            c = job['command']
            seen.append(Path(c[c.index('--extra-file') + 1]).read_text() if '--extra-file' in c else '')
            return dict(deadline=False)

        def plan_of(path):
            return dict(plan={'moves': [1]} if plans else None, verifier_solved=False, tokens=1, infra=0)

        calls = iter(verdicts)

        def judge(cand, endpoint, events_path, seed):
            return dict(verdict=next(calls), reason='move 2 uses index 5', infra=0, tokens=1)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute', execute), patch.object(v, 'plan_of', plan_of), \
                patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            (out / 'agents').mkdir(); (out / 'extra').mkdir(); (out / 'judges').mkdir()
            rec = v.run_policy(PLAN, Path('/src'), out, TASK, 1, 0, policy, v.Slots(8))
        return rec, seen

    def test_strategy_hints_are_distinct(self):
        rec, seen = self.run_policy('strategy4', [False] * 4)
        self.assertEqual(sorted(seen), sorted(v.STRATEGIES))

    def test_repair_feeds_critique_and_stops_on_accept(self):
        rec, seen = self.run_policy('repair4', [False, True])
        self.assertEqual(rec['calls'], 2)
        self.assertEqual(seen[0], '')
        self.assertIn('move 2 uses index 5', seen[1])
        self.assertTrue(rec['answered'])

    def test_board_round_two_sees_round_one(self):
        rec, seen = self.run_policy('board2x2', [False, False, False, False])
        self.assertEqual(rec['calls'], 4)
        self.assertTrue(all('Shared board' in s for s in seen[2:]))
        self.assertEqual(seen[:2], ['', ''])

    def test_board_skips_round_two_when_accepted(self):
        rec, _ = self.run_policy('board2x2', [True, False])
        self.assertEqual(rec['calls'], 2)


class CancelPolicyTests(unittest.TestCase):
    """deep4cancel / waves2cancel with a fake worker that runs until cancelled unless it is a 'fast' slot."""
    def run_policy(self, policy, fast, accept):
        import threading, time
        started = []

        def execute(job, deadline_seconds, cancel=None):
            slot = int(job['events'].rsplit('-a', 1)[1].split('.')[0])
            started.append(slot)
            if slot in fast:
                return dict(deadline=False, cancelled=False, returncode=0)
            for _ in range(200):  # slow agent: runs until the controller cancels it
                if cancel is not None and cancel.is_set():
                    return dict(deadline=False, cancelled=True, returncode=-15)
                time.sleep(.01)
            return dict(deadline=False, cancelled=False, returncode=0)

        def plan_of(path):
            return dict(plan={'moves': [1]}, verifier_solved=True, tokens=5, infra=0)

        def judge(cand, endpoint, events_path, seed):
            slot = int(str(events_path).rsplit('-a', 1)[1].split('.')[0])
            return dict(verdict=slot in accept, reason='', infra=0, tokens=1)
        plan = dict(PLAN, seed_offsets=dict(PLAN['seed_offsets'], deep4cancel=1400, waves2cancel=1400, roll8cancel=1400))
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute', execute), patch.object(v, 'plan_of', plan_of), \
                patch.object(v, 'execute_cancellable', execute), patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            (out / 'agents').mkdir(); (out / 'extra').mkdir(); (out / 'judges').mkdir()
            rec = v.run_policy(plan, Path('/src'), out, TASK, 1, 0, policy, v.Slots(8))
        return rec, started

    def test_first_accept_cancels_the_rest(self):
        rec, started = self.run_policy('deep4cancel', fast={2}, accept={2})
        self.assertIn(2, started)
        self.assertEqual(rec['selected_slot'], 2)
        self.assertTrue(rec['solved'] and rec['answered'])
        # every other agent is either terminated or never started (it may reach its slot after the accept)
        self.assertEqual(rec['cancelled_agents'] + rec['unstarted_agents'], 3)
        self.assertEqual(rec['calls'], 4)
        self.assertEqual(rec['infra'], 0)
        self.assertLess(rec['case_seconds'], 1.5)
        self.assertIsNotNone(rec['answer_seconds'])

    def test_rejected_fast_plan_does_not_cancel(self):
        rec, _ = self.run_policy('deep4cancel', fast={0, 1, 2, 3}, accept=set())
        self.assertFalse(rec['answered'])
        self.assertEqual(rec['cancelled_agents'], 0)
        self.assertIsNone(rec['selected_slot'])
        self.assertEqual(rec['calls'], 4)

    def test_waves_skip_second_wave_when_first_accepted(self):
        rec, started = self.run_policy('waves2cancel', fast={1}, accept={1})
        self.assertLessEqual(set(started), {0, 1})
        self.assertEqual(rec['selected_slot'], 1)
        self.assertEqual(rec['cancelled_agents'] + rec['unstarted_agents'], 3)

    def test_waves_run_second_wave_after_rejections(self):
        rec, started = self.run_policy('waves2cancel', fast={0, 1, 3}, accept={3})
        self.assertEqual(sorted(started), [0, 1, 2, 3])
        self.assertEqual(rec['selected_slot'], 3)
        self.assertEqual(rec['cancelled_agents'], 1)

    def test_roll_replaces_failures_until_accept(self):
        # slots 0-3 end fast and are rejected; replacements 4,5 fast rejected, 6 accepted; 7 may start and is cancelled
        rec, started = self.run_policy('roll8cancel', fast={0, 1, 2, 3, 4, 5, 6}, accept={6})
        self.assertEqual(rec['selected_slot'], 6)
        self.assertTrue(rec['answered'])
        self.assertLessEqual(set(started), set(range(8)))
        self.assertIn(6, started)
        self.assertGreaterEqual(rec['escalated_agents'], 3)

    def test_roll_caps_at_eight_agents(self):
        rec, started = self.run_policy('roll8cancel', fast=set(range(8)), accept=set())
        self.assertEqual(sorted(started), list(range(8)))
        self.assertFalse(rec['answered'])
        self.assertEqual(rec['escalated_agents'], 4)

    def test_roll_without_failures_is_deep4cancel(self):
        rec, started = self.run_policy('roll8cancel', fast={1}, accept={1})
        self.assertEqual(rec['selected_slot'], 1)
        self.assertEqual(rec['escalated_agents'], 0)
        self.assertLessEqual(set(started), {0, 1, 2, 3})

    def test_deep4_keeps_slot_order_selection(self):
        rec, started = self.run_policy('deep4', fast={0, 1, 2, 3}, accept={1, 3})
        self.assertEqual(rec['selected_slot'], 1)
        self.assertNotIn('cancelled_agents', rec)


class ExecuteCancellableTests(unittest.TestCase):
    """The real process-group executor with a fake worker process (no model)."""
    def case(self, root, sleep):
        import json, sys
        trace = root / 'a.jsonl'
        rec = json.dumps(dict(event_id=1, run_id='r', method='m', type='request_start', request_id='x'))
        code = f"import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(sys.argv[2]); time.sleep({sleep})"
        return dict(arm='deep4cancel', events=str(trace), stdout=str(root / 'o.log'), stderr=str(root / 'e.log'),
                    command=[sys.executable, '-c', code, str(trace), rec + '\n'])

    def test_cancel_terminates_process_group(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            root, cancel = Path(d), threading.Event()
            threading.Timer(.3, cancel.set).start()
            row = v.execute_cancellable(self.case(root, 30), 60, cancel)
            last = v.read_trace(root / 'a.jsonl')[0][-1]
        self.assertTrue(row['cancelled'])
        self.assertEqual(row['status'], 'cancelled')
        self.assertFalse(row['deadline'])
        self.assertLess(row['returncode'], 0)
        self.assertLess(row['wall_seconds'], 5)
        self.assertEqual((last['type'], last['status']), ('controller_stop', 'cancelled'))

    def test_unset_cancel_lets_worker_finish(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            row = v.execute_cancellable(self.case(Path(d), .2), 60, threading.Event())
        self.assertFalse(row['cancelled'] or row['deadline'] or row['controller_stop'])
        self.assertEqual(row['returncode'], 0)

    def test_deadline_still_applies(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            row = v.execute_cancellable(self.case(Path(d), 30), .3, threading.Event())
        self.assertTrue(row['deadline'])
        self.assertFalse(row['cancelled'])


if __name__ == '__main__':
    unittest.main()
