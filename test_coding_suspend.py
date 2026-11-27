"""Idea #5 live validation, runner side (run_coding_earlystop.py suspend_siblings = hold_dispatch): one judge per case
(ownership file), held siblings and held starts, unchanged winner rule, the frozen wall deadline, shutdown on a signal.
Fake and tiny real workers; no model, no network, no fleet."""
import contextlib
import hashlib
import io
import json
import os
import signal
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
import json, os, sys, time
path, accepted, owner, me, takes = sys.argv[1], sys.argv[4], sys.argv[6], sys.argv[7], sys.argv[8] == '1'
judge_after, decide_after, linger = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[5])
def emit(kind, **f):
    with open(path, 'a') as s:
        s.write(json.dumps(dict(type=kind, **f)) + chr(10))
emit('request_start')
time.sleep(judge_after)
emit('request_end', usage=dict(completion_tokens=5))
emit('judge_start')
t_wait = time.monotonic()
while takes:  # the worker's first judge call takes the case's judge ownership (DispatchHold.acquire)
    try:
        fd = os.open(owner, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, me.encode()); os.close(fd); break
    except FileExistsError:
        if time.monotonic() - t_wait > 4:
            sys.exit(3)  # bounded: a runner that never releases the ownership makes the test fail, not hang
        time.sleep(0.01)
if takes:
    emit('judge_owner', owner=int(me), t=time.monotonic())
time.sleep(decide_after)
if accepted != 'none':
    emit('acceptance', accepted=accepted == '1', decided_monotonic=time.monotonic())
time.sleep(linger)
emit('puzzle_end', accepted=accepted == '1', feedback_pass=True, holdout_pass=True)
emit('run_end', status='complete', infrastructure_failures=0)
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owner(path):
    return Path(path).read_text().strip() if Path(path).exists() else None


class Guarded(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('no network in tests'))
        guard.start()
        self.addCleanup(guard.stop)
        abort = getattr(r, 'ABORT', [])
        del abort[:]
        self.addCleanup(lambda: abort.__delitem__(slice(None)))


class HoldBoardTests(Guarded):
    def test_ownership_file_intervals_and_close(self):
        now = [0.0]
        with tempfile.TemporaryDirectory() as d:
            board = r.HoldBoard(Path(d) / 'holds', clock=lambda: now[0])
            path = board.path(KEY)
            self.assertTrue(path.name.endswith('.owner'))
            path.write_text('0')  # agent 0's worker took the ownership
            board.pend(KEY, 0)
            self.assertTrue(board.held(KEY))
            now[0] = 2.0
            board.release(KEY, 1)  # not the owner: nothing is removed
            self.assertEqual(owner(path), '0')
            board.release(KEY, 0)  # a rejection of the owner
            self.assertFalse(board.held(KEY))
            path.write_text('1')
            board.pend(KEY, 1)
            now[0] = 5.0
            board.close(KEY)  # the accepted case's siblings are shut down
            self.assertFalse(board.held(KEY))
            self.assertEqual(board.summary(), dict(cases=1, pending_windows=2, pending_seconds=5.0))


class ExecuteWithHoldsTests(Guarded):
    def job(self, root, board, agent, judge_after, decide_after, accepted, linger=0.0, takes=True):
        events = root / f'a{agent}.jsonl'
        return dict(task_id=KEY[0], seed=KEY[1], agent=agent, arm='code_xl', events=str(events),
                    command=[sys.executable, '-c', SCRIPT, str(events), str(judge_after), str(decide_after), accepted,
                             str(linger), str(board.path(KEY)), str(agent), '1' if takes else '0'],
                    stdout=str(root / f'a{agent}.out'), stderr=str(root / f'a{agent}.err'))

    def run_one(self, root, board, arbiter, agent, *args, deadline=30, **kw):
        box = {}

        def go():
            box['row'] = r.execute_accepting(self.job(root, board, agent, *args, **kw), deadline, arbiter, poll=.02,
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
            self.assertEqual(owner(board.path(KEY)), '0')  # judge owned: pending
            self.assertIsNone(arbiter.winner(KEY))  # a pending verdict is never an acceptance
            t.join()
            self.assertIsNone(owner(board.path(KEY)))  # released on the rejection
            self.assertFalse(box['row']['accepted'] or box['row']['won'])

    def test_an_acceptance_keeps_the_ownership_and_wins(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            board, arbiter = r.HoldBoard(root / 'holds'), r.Arbiter({KEY: threading.Event()})
            t, box = self.run_one(root, board, arbiter, 0, .05, .2, '1')
            t.join()
            self.assertTrue(box['row']['won'])
            self.assertEqual(owner(board.path(KEY)), '0')  # kept until the siblings are shut down

    def test_a_worker_ending_without_a_decision_releases(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            board, arbiter = r.HoldBoard(root / 'holds'), r.Arbiter({KEY: threading.Event()})
            t, box = self.run_one(root, board, arbiter, 0, .05, .2, 'none')
            t.join()
            self.assertIsNone(owner(board.path(KEY)))

    def test_review_two_judges_take_turns(self):
        """Two agents reach their judge together: one owns the case's judge, the other waits for its rejection."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            board, arbiter = r.HoldBoard(root / 'holds'), r.Arbiter({KEY: threading.Event()})
            t0, b0 = self.run_one(root, board, arbiter, 0, .05, .4, '0')
            t1, b1 = self.run_one(root, board, arbiter, 1, .2, .4, '1')  # reaches its judge while agent 0 owns
            t0.join()
            t1.join()
            spans = {}
            for agent in (0, 1):
                rows = [json.loads(line) for line in (root / f'a{agent}.jsonl').read_text().splitlines()]
                own = next(row['t'] for row in rows if row['type'] == 'judge_owner')
                end = next(row['decided_monotonic'] for row in rows if row['type'] == 'acceptance')
                spans[agent] = (own, end)
            (a0, a1), (c0, c1) = spans[0], spans[1]
            self.assertTrue(a1 <= c0 or c1 <= a0)  # the two verdicts never overlap
            self.assertTrue(b1['row']['won'])
            self.assertEqual(board.summary()['pending_windows'], 2)

    def test_the_winner_rule_is_unchanged(self):
        """Same recorded decisions with and without holds: the earliest recorded in-time acceptance wins."""
        winners = []
        for holds in (False, True):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                board = r.HoldBoard(root / 'holds')
                arbiter = r.Arbiter({KEY: threading.Event()})

                def go(agent, judge_after, decide_after, poll):
                    job = self.job(root, board, agent, judge_after, decide_after, '1', .3)
                    r.execute_accepting(job, 30, arbiter, poll=poll, holds=board if holds else None)
                threads = [threading.Thread(target=go, args=(1, .05, .15, 1.0)),
                           threading.Thread(target=go, args=(0, .1, .45, .02))]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                winners.append(arbiter.winner(KEY))
        self.assertEqual(winners, [1, 1])

    def test_review_the_frozen_wall_deadline_has_no_hold_credit(self):
        """sol review blocker 2: a decision after the agent's wall deadline is late in BOTH arms, however long other
        agents of its case were pending."""
        outcomes = []
        for holds in (False, True):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                board = r.HoldBoard(root / 'holds')
                arbiter = r.Arbiter({KEY: threading.Event()})
                rows = {}

                def go(agent, judge_after, decide_after, accepted, deadline, takes):
                    job = self.job(root, board, agent, judge_after, decide_after, accepted, takes=takes)
                    rows[agent] = r.execute_accepting(job, deadline, arbiter, poll=.02, holds=board if holds else None)
                # agent 0 is pending ~0.6 s (then rejected) while agent 1 generates; agent 1 decides ~0.75 s after its
                # start (the decision protocol itself is not under test here), past its 0.6 s wall deadline
                a = threading.Thread(target=go, args=(0, 0.0, 0.6, '0', 30, True))
                b = threading.Thread(target=go, args=(1, 0.65, 0.1, '1', 0.6, False))
                a.start()
                time.sleep(.1)
                b.start()
                a.join()
                b.join()
                outcomes.append((rows[1]['accepted'], rows[1]['deadline']))
        self.assertEqual(outcomes, [(False, True), (False, True)])

    def test_review_a_latched_abort_terminates_and_reaps_the_worker(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            board, arbiter = r.HoldBoard(root / 'holds'), r.Arbiter({KEY: threading.Event()})
            t, box = self.run_one(root, board, arbiter, 0, 5.0, 5.0, '1')
            time.sleep(.3)
            r.on_signal(signal.SIGTERM, None)  # latch only
            t.join(5)
            self.assertFalse(t.is_alive())
            self.assertTrue(box['row']['aborted'])
            self.assertIsNotNone(box['row']['returncode'])  # the worker process was reaped


class MainWithHoldsTests(Guarded):
    def run_main(self, scripts, plan_extra, agents=3, width=2, admission_extra=None, abort_after=None):
        """scripts[(task, agent)] = (own_seconds, accepted) for a fake executor that takes the ownership at once
        (holds), waits, then decides; records each start time."""
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
            receipt = dict(verified=True, verified_utc=datetime.now(timezone.utc).isoformat(), allow_busy=False,
                           plan_sha256=sha(plan_path), source_revision='x')
            receipt.update(admission_extra or {})
            adm.write_text(json.dumps(receipt))
            starts, commands, t0 = {}, [], time.monotonic()
            real_sleep = time.sleep

            def execute_accepting(job, deadline, arbiter, holds=None):
                key, me = (job['task_id'], job['seed']), job['agent']
                starts[(job['task_id'], me)] = time.monotonic() - t0
                commands.append(job['command'])
                arbiter.register(key, me, job['events'], time.monotonic(), deadline)
                own, accepted = scripts.get((job['task_id'], me), (0.0, False))
                base = dict(deadline=False, controller_error=None, controller_stop=False, calls=1, unfinished_calls=0,
                            infrastructure_failures=0, completion_tokens=10, scoring_timeout=False, late_decision=False,
                            aborted=False)
                if holds is not None and own:
                    holds.path(key).write_text(str(me))
                    holds.pend(key, me)
                if abort_after is not None and me == 0:
                    real_sleep(abort_after)
                    r.on_signal(signal.SIGTERM, None)
                    return dict(base, cancelled=False, returncode=-15, status='aborted', accepted=False, won=False,
                                aborted=True)
                real_sleep(own)
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
            with patch.object(r, 'execute_accepting', execute_accepting), patch.object(r, 'agent_outcome', outcome), \
                    patch.object(r, 'validate_source', lambda *a: None), patch.object(r, 'hashes', lambda s: {}), \
                    patch.object(r, 'server_metrics', lambda *a, **k: {}), \
                    patch.object(r.time, 'sleep', lambda s: real_sleep(min(s, .05))), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = r.main(['--plan', str(plan_path), '--output', str(root / 'out'), '--source', str(root),
                               '--admission', str(adm), '--run'])
            meta = json.loads((root / 'out' / 'metadata.json').read_text())
            holds_left = sorted(p.name for p in (root / 'out' / 'holds').glob('*')) \
                if (root / 'out' / 'holds').exists() else []
        return starts, commands, meta, code, holds_left

    def test_no_new_agent_of_a_held_case_starts_and_other_cases_go_on(self):
        # t1: agent 0 owns the judge 0.6 s then is rejected; agent 1 fails at once -> replacement agent 2 is due but
        # its case is held until agent 0's verdict; t2 is never held.
        scripts = {('t1', 0): (0.6, False), ('t1', 1): (0.0, False), ('t1', 2): (0.0, True), ('t2', 0): (0.0, True)}
        starts, commands, meta, _, _ = self.run_main(scripts, dict(suspend_siblings='hold_dispatch'))
        self.assertGreaterEqual(starts[('t1', 2)], 0.55)  # not before agent 0's rejection
        self.assertLess(starts[('t2', 0)], 0.3)
        self.assertTrue(all('--hold-file' in c and '--agent-index' in c for c in commands))
        self.assertTrue(all(c[c.index('--hold-file') + 1].endswith('.owner') for c in commands))
        self.assertIn('holds', meta)
        starts, commands, meta, _, _ = self.run_main(scripts, {})
        self.assertLess(starts[('t1', 2)], 0.3)  # without the flag the replacement starts at once
        self.assertFalse(any('--hold-file' in c for c in commands))
        self.assertNotIn('holds', meta)

    def test_should_accepted_ownership_closes_when_the_case_shuts_down(self):
        scripts = {('t1', 0): (0.2, True), ('t2', 0): (0.2, True)}
        _, _, meta, _, left = self.run_main(scripts, dict(suspend_siblings='hold_dispatch'))
        self.assertEqual(left, [])  # closed once every started agent of each answered case ended
        self.assertEqual(meta['holds']['pending_windows'], 2)

    def test_review_a_signal_stops_admissions(self):
        scripts = {('t1', 1): (0.5, False), ('t2', 0): (0.5, False), ('t2', 1): (0.5, False)}
        starts, _, meta, code, _ = self.run_main(scripts, dict(suspend_siblings='hold_dispatch'), abort_after=0.1)
        self.assertNotEqual(code, 0)
        self.assertTrue(any(e.get('reason') == 'signal' for e in meta['errors']))
        self.assertEqual([k for k in starts if k[1] >= 2], [])  # the replacements due after the latch never start

    def test_should_ab_plans_need_a_receipt_bound_to_the_plan(self):
        plan = dict(suspend_siblings='hold_dispatch', ab_arm='hold')
        with self.assertRaisesRegex(ValueError, 'Admission not bound to this plan'):
            self.run_main({}, plan, admission_extra=dict(plan_sha256='0' * 64))
        self.run_main({}, plan)  # bound: runs

    def test_plan_checks(self):
        with self.assertRaisesRegex(ValueError, 'suspend_siblings needs judge acceptance'):
            self.run_main({}, dict(suspend_siblings='pause_streams'))
        with self.assertRaisesRegex(ValueError, 'suspend_siblings needs judge acceptance'):
            self.run_main({}, dict(suspend_siblings='hold_dispatch', acceptance='self_tests'))


if __name__ == '__main__':
    unittest.main()
