"""Idea #5 live validation, runner side (run_coding_earlystop.py suspend_siblings = hold_dispatch): pending verdicts,
held siblings and held starts, unchanged winner rule, deadline extension. Fake and tiny real workers; no model, no
network, no fleet."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import run_coding_earlystop as r

KEY = ('t1', 4)
SCRIPT = r"""
import json, sys, time
path, accepted = sys.argv[1], sys.argv[4]
judge_after, decide_after, linger = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[5])
def emit(kind, **f):
    with open(path, 'a') as s:
        s.write(json.dumps(dict(type=kind, **f)) + chr(10))
emit('request_start')
time.sleep(judge_after)
emit('request_end', usage=dict(completion_tokens=5))
emit('judge_start')
time.sleep(decide_after)
if accepted != 'none':
    emit('acceptance', accepted=accepted == '1', decided_monotonic=time.monotonic())
time.sleep(linger)
emit('puzzle_end', accepted=accepted == '1', feedback_pass=True, holdout_pass=True)
emit('run_end', status='complete', infrastructure_failures=0)
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pending(path):
    return json.loads(Path(path).read_text())['pending'] if Path(path).exists() else None


class Guarded(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('no network in tests'))
        guard.start()
        self.addCleanup(guard.stop)


class HoldBoardTests(Guarded):
    def test_mirror_and_held_seconds(self):
        now = [0.0]
        with tempfile.TemporaryDirectory() as d:
            board = r.HoldBoard(Path(d) / 'holds', clock=lambda: now[0])
            path = board.path(KEY)
            board.pend(KEY, 0)
            self.assertEqual((pending(path), board.held(KEY)), ([0], True))
            now[0] = 2.0
            board.pend(KEY, 1)
            now[0] = 3.0
            board.release(KEY, 0)
            self.assertEqual(pending(path), [1])
            now[0] = 5.0
            board.release(KEY, 1)
            self.assertEqual((pending(path), board.held(KEY)), ([], False))
            self.assertAlmostEqual(board.held_seconds(KEY, 2, 0, 10), 5.0)  # union of [0, 3] and [2, 5]
            self.assertAlmostEqual(board.held_seconds(KEY, 1, 0, 10), 3.0)  # its own window is not a hold
            self.assertAlmostEqual(board.held_seconds(KEY, 2, 1, 2.5), 1.5)
            self.assertEqual(board.summary()['pending_windows'], 2)


class ExecuteWithHoldsTests(Guarded):
    def job(self, root, agent, judge_after, decide_after, accepted, linger=0.0):
        events = root / f'a{agent}.jsonl'
        return dict(task_id=KEY[0], seed=KEY[1], agent=agent, arm='code_xl', events=str(events),
                    command=[sys.executable, '-c', SCRIPT, str(events), str(judge_after), str(decide_after), accepted,
                             str(linger)], stdout=str(root / f'a{agent}.out'), stderr=str(root / f'a{agent}.err'))

    def run_one(self, root, board, arbiter, agent, *args, deadline=30, **kw):
        box = {}

        def go():
            box['row'] = r.execute_accepting(self.job(root, agent, *args, **kw), deadline, arbiter, poll=.02,
                                             holds=board)
        t = threading.Thread(target=go)
        t.start()
        return t, box

    def test_pending_is_never_an_acceptance_and_a_rejection_releases(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            board, arbiter = r.HoldBoard(root / 'holds'), r.Arbiter({KEY: threading.Event()})
            t, box = self.run_one(root, board, arbiter, 0, .05, .6, '0')
            time.sleep(.35)
            self.assertEqual(pending(board.path(KEY)), [0])  # judge started: pending
            self.assertIsNone(arbiter.winner(KEY))  # a pending verdict is never an acceptance
            t.join()
            self.assertEqual(pending(board.path(KEY)), [])
            self.assertFalse(box['row']['accepted'] or box['row']['won'])

    def test_an_acceptance_keeps_the_siblings_held_and_wins(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            board, arbiter = r.HoldBoard(root / 'holds'), r.Arbiter({KEY: threading.Event()})
            t, box = self.run_one(root, board, arbiter, 0, .05, .2, '1')
            t.join()
            self.assertTrue(box['row']['won'])
            self.assertEqual(pending(board.path(KEY)), [0])  # held until the siblings are terminated

    def test_a_worker_ending_without_a_decision_releases(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            board, arbiter = r.HoldBoard(root / 'holds'), r.Arbiter({KEY: threading.Event()})
            t, box = self.run_one(root, board, arbiter, 0, .05, .2, 'none')
            t.join()
            self.assertEqual(pending(board.path(KEY)), [])

    def test_the_winner_rule_is_unchanged(self):
        """Same recorded decisions with and without holds: the earliest recorded in-time acceptance wins."""
        winners = []
        for holds in (False, True):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                board = r.HoldBoard(root / 'holds') if holds else None
                arbiter = r.Arbiter({KEY: threading.Event()})
                rows = {}

                def go(agent, judge_after, decide_after, poll):
                    rows[agent] = r.execute_accepting(self.job(root, agent, judge_after, decide_after, '1', .3), 30,
                                                      arbiter, poll=poll, holds=board)
                threads = [threading.Thread(target=go, args=(1, .05, .15, 1.0)),
                           threading.Thread(target=go, args=(0, .05, .45, .02))]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                winners.append(arbiter.winner(KEY))
        self.assertEqual(winners, [1, 1])

    def test_the_deadline_is_extended_by_other_agents_pending_time(self):
        outcomes = []
        for holds in (False, True):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                board = r.HoldBoard(root / 'holds') if holds else None
                arbiter = r.Arbiter({KEY: threading.Event()})
                rows = {}

                def go(agent, judge_after, decide_after, accepted, deadline):
                    job = self.job(root, agent, judge_after, decide_after, accepted)
                    rows[agent] = r.execute_accepting(job, deadline, arbiter, poll=.02, holds=board)
                a = threading.Thread(target=go, args=(0, 0.0, 1.2, '0', 30))  # pending for ~1.2 s, then rejected
                b = threading.Thread(target=go, args=(1, 0.8, 0.1, '1', 0.6))  # decides at ~0.9 s, deadline 0.6 s
                a.start()
                time.sleep(.1)
                b.start()
                a.join()
                b.join()
                outcomes.append((rows[1]['accepted'], rows[1]['deadline']))
        self.assertEqual(outcomes[0], (False, True))  # no holds: terminated at its 0.6 s deadline
        self.assertEqual(outcomes[1], (True, False))  # holds: the agent's deadline grew by the time it was held


class MainWithHoldsTests(Guarded):
    def run_main(self, scripts, plan_extra, agents=3, width=2):
        """scripts[(task, agent)] = (pend_seconds, accepted) for a fake executor that pends at once (holds), waits,
        then decides; records each start time."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tasks = root / 'tasks.json'
            tasks.write_text(json.dumps(dict(tasks=[dict(id=t, split='evaluation') for t in ('t1', 't2')])))
            tests = root / 'tests.json'
            tests.write_text('{}')
            plan = dict(protocol=r.PROTOCOL, early_stop='first_accepted_in_time', status='FROZEN', source_revision='x',
                        acceptance='judge', agent_variants=['code_xl'] * agents, agent_seed_offset=700,
                        rolling=dict(width=width),
                        matrix=dict(tasks=str(tasks), tests=str(tests), tasks_sha256=sha(tasks),
                                    tests_sha256=sha(tests), split='evaluation', tasks_count=2, seeds=[4]),
                        scheduling=dict(concurrent_agents_per_node=4), limits=dict(agent_wall_deadline_seconds=60))
            plan.update(plan_extra)
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps(plan))
            adm = root / 'adm.json'
            adm.write_text(json.dumps(dict(verified=True, verified_utc=datetime.now(timezone.utc).isoformat())))
            starts, commands, t0 = {}, [], time.monotonic()

            def execute_accepting(job, deadline, arbiter, holds=None):
                key, me = (job['task_id'], job['seed']), job['agent']
                starts[(job['task_id'], me)] = time.monotonic() - t0
                commands.append(job['command'])
                arbiter.register(key, me, job['events'], time.monotonic(), deadline)
                pend, accepted = scripts.get((job['task_id'], me), (0.0, False))
                base = dict(deadline=False, controller_error=None, controller_stop=False, calls=1, unfinished_calls=0,
                            infrastructure_failures=0, completion_tokens=10, scoring_timeout=False, late_decision=False)
                if holds is not None and pend:
                    holds.pend(key, me)
                real_sleep(pend)
                Path(job['events']).write_text(json.dumps(dict(type='acceptance', accepted=accepted,
                                                               decided_monotonic=time.monotonic())) + '\n')
                if accepted:
                    arbiter.decide(key)
                elif holds is not None:
                    holds.release(key, me)
                return dict(base, cancelled=False, returncode=0, status='complete', accepted=accepted,
                            won=arbiter.winner(key) == me)
            def outcome(events):
                return dict(parsed=True, feedback_pass=True, holdout_pass=True, budget_forced=False)
            real_sleep = time.sleep
            with patch.object(r, 'execute_accepting', execute_accepting), patch.object(r, 'agent_outcome', outcome), \
                    patch.object(r, 'validate_source', lambda *a: None), patch.object(r, 'hashes', lambda s: {}), \
                    patch.object(r, 'server_metrics', lambda *a, **k: {}), \
                    patch.object(r.time, 'sleep', lambda s: real_sleep(min(s, .05))), \
                    contextlib.redirect_stdout(io.StringIO()):
                r.main(['--plan', str(plan_path), '--output', str(root / 'out'), '--source', str(root),
                        '--admission', str(adm), '--run'])
            meta = json.loads((root / 'out' / 'metadata.json').read_text())
        return starts, commands, meta

    def test_no_new_agent_of_a_held_case_starts_and_other_cases_go_on(self):
        # t1: agent 0 pends 0.6 s then is rejected; agent 1 fails at once -> replacement agent 2 is due but its case is
        # held until agent 0's verdict; t2 is never held.
        scripts = {('t1', 0): (0.6, False), ('t1', 1): (0.0, False), ('t1', 2): (0.0, True), ('t2', 0): (0.0, True)}
        starts, commands, meta = self.run_main(scripts, dict(suspend_siblings='hold_dispatch'))
        self.assertGreaterEqual(starts[('t1', 2)], 0.55)  # not before agent 0's rejection
        self.assertLess(starts[('t2', 0)], 0.3)
        self.assertTrue(all('--hold-file' in c and '--agent-index' in c for c in commands))
        self.assertIn('holds', meta)
        starts, commands, meta = self.run_main(scripts, {})
        self.assertLess(starts[('t1', 2)], 0.3)  # without the flag the replacement starts at once
        self.assertFalse(any('--hold-file' in c for c in commands))
        self.assertNotIn('holds', meta)

    def test_plan_checks(self):
        with self.assertRaisesRegex(ValueError, 'suspend_siblings needs judge acceptance'):
            self.run_main({}, dict(suspend_siblings='pause_streams'))
        with self.assertRaisesRegex(ValueError, 'suspend_siblings needs judge acceptance'):
            self.run_main({}, dict(suspend_siblings='hold_dispatch', acceptance='self_tests'))


if __name__ == '__main__':
    unittest.main()
