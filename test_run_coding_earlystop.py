"""Offline tests for the early-stop coding runner (fake workers, no model, no sandbox)."""
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class EarlyStopTests(unittest.TestCase):
    def run_main(self, fast_pass, holdout, stagger=None, rolling=None, acceptance=None, feedback=None, plan_extra=None):
        """acceptance: no-provided-tests mode; fast_pass then means 'accepted', feedback = agents passing the hidden
        feedback cases (default: every agent)."""
        """fast_pass: agents that end at once with feedback pass; every other agent runs until cancelled."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tasks = root / 'tasks.json'
            tasks.write_text(json.dumps(dict(tasks=[dict(id='t1', split='evaluation'), dict(id='t2', split='evaluation')])))
            tests = root / 'tests.json'
            tests.write_text('{}')
            plan = dict(protocol=r.PROTOCOL, early_stop='first_feedback_pass_in_time', status='FROZEN', source_revision='x',
                        agent_variants=['code_xl'] * 4, agent_seed_offset=700,
                        matrix=dict(tasks=str(tasks), tests=str(tests), tasks_sha256=sha(tasks), tests_sha256=sha(tests),
                                    split='evaluation', tasks_count=2, seeds=[4]),
                        scheduling=dict(concurrent_agents_per_node=2), limits=dict(agent_wall_deadline_seconds=60))
            if stagger:
                plan['stagger'] = stagger
            if rolling:
                plan['rolling'] = rolling
            if acceptance:
                plan.update(acceptance=acceptance, early_stop='first_accepted_in_time')
            plan.update(plan_extra or {})
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps(plan))
            adm = root / 'adm.json'
            adm.write_text(json.dumps(dict(verified=True, verified_utc=datetime.now(timezone.utc).isoformat())))
            started, self.commands = [], []

            def execute(job, deadline, cancel):
                started.append((job['task_id'], job['agent']))
                self.commands.append(job['command'])
                if job['agent'] in fast_pass:
                    return dict(cancelled=False, deadline=False, controller_error=None, returncode=0, controller_stop=False,
                                status='complete', calls=1, unfinished_calls=0, infrastructure_failures=0, completion_tokens=10)
                for _ in range(300):
                    if cancel.is_set():
                        return dict(cancelled=True, deadline=False, controller_error=None, returncode=-15, controller_stop=True,
                                    status='cancelled', calls=1, unfinished_calls=1, infrastructure_failures=None,
                                    completion_tokens=0)
                    time.sleep(.01)
                return dict(cancelled=False, deadline=False, controller_error=None, returncode=0, controller_stop=False,
                            status='complete', calls=1, unfinished_calls=0, infrastructure_failures=0, completion_tokens=10)

            def agent_of(events):
                return int(Path(events).name.split('-a')[1].split('-')[0])

            def outcome(events):
                agent = agent_of(events)
                fb = agent in fast_pass if not acceptance else (feedback is None or agent in feedback)
                return dict(parsed=True, feedback_pass=fb, holdout_pass=agent in holdout, budget_forced=False)

            def execute_accepting(job, deadline, arbiter):
                """Fast agents record an accepted decision at once (a real trace event) and ask the arbiter; the rest
                wait until another agent is the winner."""
                key, me = (job['task_id'], job['seed']), job['agent']
                started.append((job['task_id'], job['agent']))
                self.commands.append(job['command'])
                arbiter.register(key, me, job['events'], time.monotonic(), deadline)
                base = dict(deadline=False, controller_error=None, controller_stop=False, calls=1, unfinished_calls=0,
                            infrastructure_failures=0, completion_tokens=10, scoring_timeout=False, late_decision=False)
                if me in fast_pass:
                    Path(job['events']).write_text(json.dumps(dict(type='acceptance', accepted=True,
                                                                   decided_monotonic=time.monotonic())) + '\n')
                    arbiter.decide(key)
                    return dict(base, cancelled=False, returncode=0, status='complete', accepted=True,
                                won=arbiter.winner(key) == me)
                for _ in range(300):
                    if arbiter.winner(key) not in (None, me):
                        return dict(base, cancelled=True, returncode=-15, controller_stop=True, status='cancelled',
                                    unfinished_calls=1, infrastructure_failures=None, completion_tokens=0,
                                    accepted=False, won=False)
                    time.sleep(.01)
                return dict(base, cancelled=False, returncode=0, status='complete', accepted=False, won=False)
            with patch.object(r, 'execute_cancellable', execute), patch.object(r, 'agent_outcome', outcome), \
                    patch.object(r, 'execute_accepting', execute_accepting), \
                    patch.object(r, 'validate_source', lambda *a: None), patch.object(r, 'hashes', lambda s: {}), \
                    patch.object(r, 'server_metrics', lambda *a, **k: {}), contextlib.redirect_stdout(io.StringIO()):
                code = r.main(['--plan', str(plan_path), '--output', str(root / 'out'), '--source', str(root),
                               '--admission', str(adm), '--run'])
            cases = json.loads((root / 'out' / 'cases.json').read_text())
        return code, cases, started

    def test_first_feedback_pass_stops_the_case(self):
        code, cases, started = self.run_main(fast_pass={2}, holdout={2})
        self.assertEqual(code, 0)
        self.assertEqual(len(cases), 2)
        for c in cases:
            self.assertTrue(c['answered'] and c['solved'])
            self.assertEqual(c['winner_agent'], 2)
            self.assertEqual(c['cancelled'] + c['never_started'], 3)

    def test_holdout_failure_of_winner_is_unsolved(self):
        code, cases, _ = self.run_main(fast_pass={1}, holdout={0, 2, 3})
        self.assertTrue(all(c['answered'] and not c['solved'] for c in cases))

    def test_no_feedback_pass_runs_everyone_to_the_end(self):
        code, cases, started = self.run_main(fast_pass=set(), holdout=set())
        self.assertEqual(code, 0)
        self.assertEqual(len(started), 8)
        self.assertTrue(all(not c['answered'] and c['cancelled'] == 0 for c in cases))

    def test_stagger_skips_later_agents_when_first_wave_passes(self):
        code, cases, started = self.run_main(fast_pass={1}, holdout={1}, stagger=dict(first=2, after_seconds=30))
        self.assertEqual(code, 0)
        self.assertTrue(all(c['solved'] for c in cases))
        self.assertTrue(all(agent < 2 for _, agent in started))
        self.assertTrue(all(c['never_started'] == 2 for c in cases))

    def test_stagger_starts_later_agents_after_first_wave_fails(self):
        # first wave (0,1) ends fast without a pass -> later agents start at once (not after 30 s); agent 3 passes
        code, cases, started = self.run_main(fast_pass={3}, holdout={3}, stagger=dict(first=2, after_seconds=30))
        self.assertEqual(code, 0)
        self.assertTrue(all(c['solved'] and c['winner_agent'] == 3 for c in cases))

    def test_rolling_replaces_failures_one_by_one(self):
        # width 2: agents 0 and 1 start; slow agents run ~3 s and fail; agent 3 passes once started
        code, cases, started = self.run_main(fast_pass={3}, holdout={3}, rolling=dict(width=2))
        self.assertEqual(code, 0)
        self.assertTrue(all(c['solved'] and c['winner_agent'] == 3 for c in cases))

    def test_rolling_no_extra_agents_when_first_passes(self):
        code, cases, started = self.run_main(fast_pass={0}, holdout={0}, rolling=dict(width=2))
        self.assertTrue(all(agent < 2 for _, agent in started))
        self.assertTrue(all(c['never_started'] >= 2 for c in cases))

    def test_default_commands_have_no_acceptance_flag(self):
        self.run_main(fast_pass={0}, holdout={0}, rolling=dict(width=2))
        self.assertTrue(self.commands and all('--acceptance' not in c for c in self.commands))

    def test_acceptance_stops_on_first_accepted_not_on_feedback(self):
        # every agent passes the hidden feedback cases, but only agent 3 is accepted (own tests / judge)
        for mode in ('self_tests', 'judge'):
            code, cases, started = self.run_main(fast_pass={3}, holdout={3}, rolling=dict(width=2), acceptance=mode)
            self.assertEqual(code, 0)
            self.assertTrue(all(c['answered'] and c['solved'] and c['winner_agent'] == 3 for c in cases))
            self.assertTrue(all(c[-2:] == ['--acceptance', mode] for c in self.commands))

    def test_acceptance_solved_needs_every_hidden_case(self):
        # accepted agent 0 passes the holdout but not the hidden feedback cases: answered, wrong
        code, cases, _ = self.run_main(fast_pass={0}, holdout={0}, rolling=dict(width=2), acceptance='judge',
                                       feedback={1, 2, 3})
        self.assertTrue(all(c['answered'] and not c['solved'] for c in cases))

    def test_acceptance_no_accept_leaves_case_unanswered(self):
        code, cases, started = self.run_main(fast_pass=set(), holdout={0, 1, 2, 3}, rolling=dict(width=2),
                                             acceptance='self_tests')
        self.assertEqual(code, 0)
        self.assertEqual(len(started), 8)
        self.assertTrue(all(not c['answered'] and not c['solved'] for c in cases))

    def test_acceptance_plan_checks(self):
        for bad in (dict(acceptance='self_tests'), dict(acceptance='feedback', early_stop='first_accepted_in_time'),
                    dict(early_stop='first_accepted_in_time')):
            with self.assertRaises(ValueError):
                self.run_main(fast_pass={0}, holdout={0}, plan_extra=bad)

    def test_cancelled_row_is_not_an_operational_fault(self):
        row = dict(cancelled=True, controller_error=None, malformed_lines=0)
        self.assertIsNone(r.fault(row))


SCRIPT = r"""
import json, sys, time
path, decide_after, accepted, score_seconds = sys.argv[1], float(sys.argv[2]), sys.argv[3] == '1', float(sys.argv[4])
def emit(kind, **f):
    with open(path, 'a') as s:
        s.write(json.dumps(dict(type=kind, **f)) + chr(10))
emit('request_start')
time.sleep(decide_after)
emit('request_end', usage=dict(completion_tokens=5))
emit('acceptance', accepted=accepted, decided_monotonic=time.monotonic())
time.sleep(score_seconds)  # hidden grading, scoring only
emit('puzzle_end', accepted=accepted, feedback_pass=True, holdout_pass=True)
emit('run_end', status='complete', infrastructure_failures=0)
"""
KEY = ('t1', 4)


class ExecuteAcceptingTests(unittest.TestCase):
    """execute_accepting against real worker processes (a tiny script writing the trace protocol)."""
    def job(self, root, agent, decide_after, accepted, score_seconds):
        events = root / f'a{agent}.jsonl'
        return dict(task_id=KEY[0], seed=KEY[1], agent=agent, arm='code_xl', events=str(events),
                    command=[sys.executable, '-c', SCRIPT, str(events), str(decide_after), '1' if accepted else '0',
                             str(score_seconds)], stdout=str(root / f'a{agent}.out'), stderr=str(root / f'a{agent}.err'))

    def arbiter(self):
        return r.Arbiter({KEY: threading.Event()})

    def test_winner_at_decision_and_scoring_not_cut_by_deadline(self):
        arbiter = self.arbiter()
        with tempfile.TemporaryDirectory() as d:
            t0 = time.monotonic()
            row = r.execute_accepting(self.job(Path(d), 0, .2, True, 1.5), 1.0, arbiter, poll=.02)
        self.assertTrue(row['accepted'] and row['won'])
        self.assertFalse(row['cancelled'] or row['deadline'] or row['scoring_timeout'] or row['late_decision'])
        self.assertLess(arbiter.decided(KEY) - t0, 1.0)  # the recorded decision time, before the 1.5 s of scoring
        self.assertTrue(arbiter.cancels[KEY].is_set())
        self.assertGreater(row['wall_seconds'], 1.5)  # scoring ran past the 1 s agent deadline
        self.assertEqual(row['status'], 'complete')

    def test_earliest_recorded_decision_wins_not_poll_order(self):
        # agent 1 records its acceptance first (0.2 s) but its executor polls every 1.5 s; agent 0 records at 0.5 s and
        # polls fast, so agent 0's executor observes first; the arbiter still picks agent 1
        arbiter, rows = self.arbiter(), {}
        with tempfile.TemporaryDirectory() as d:
            def run(agent, decide_after, poll):
                rows[agent] = r.execute_accepting(self.job(Path(d), agent, decide_after, True, .3), 30, arbiter, poll=poll)
            threads = [threading.Thread(target=run, args=(1, .2, 1.5)), threading.Thread(target=run, args=(0, .5, .02))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(arbiter.winner(KEY), 1)
        self.assertTrue(rows[1]['won'] and rows[1]['accepted'])
        self.assertFalse(rows[0]['won'])

    def test_decision_recorded_after_the_deadline_is_not_an_acceptance(self):
        arbiter = self.arbiter()
        with tempfile.TemporaryDirectory() as d:  # observed only at the 2 s poll: recorded at 0.8 s > deadline 0.5 s
            row = r.execute_accepting(self.job(Path(d), 0, .8, True, 0), .5, arbiter, poll=2.0)
        self.assertTrue(row['deadline'] and row['late_decision'])
        self.assertFalse(row['accepted'] or row['won'])
        self.assertIsNone(arbiter.winner(KEY))

    def test_rejected_decision_never_wins(self):
        arbiter = self.arbiter()
        with tempfile.TemporaryDirectory() as d:
            row = r.execute_accepting(self.job(Path(d), 0, .1, False, .1), 30, arbiter, poll=.02)
        self.assertFalse(row['accepted'] or row['won'] or row['cancelled'])
        self.assertIsNone(arbiter.winner(KEY))

    def test_deadline_applies_until_the_decision(self):
        with tempfile.TemporaryDirectory() as d:
            row = r.execute_accepting(self.job(Path(d), 0, 5, True, 0), .5, self.arbiter(), poll=.02)
        self.assertTrue(row['deadline'])
        self.assertFalse(row['accepted'] or row['scoring_timeout'])

    def test_scoring_grace_bounds_hidden_grading(self):
        with tempfile.TemporaryDirectory() as d:
            row = r.execute_accepting(self.job(Path(d), 0, .1, True, 10), 30, self.arbiter(), grace_seconds=.5, poll=.02)
        self.assertTrue(row['won'] and row['scoring_timeout'] and row['deadline'])

    def test_arbiter_ignores_rejected_late_and_untimed_decisions(self):
        arbiter = self.arbiter()
        with tempfile.TemporaryDirectory() as d:
            def trace(agent, **event):
                path = Path(d) / f'{agent}.jsonl'
                path.write_text(json.dumps(dict(type='acceptance', **event)) + '\n')
                return str(path)
            arbiter.register(KEY, 0, trace(0, accepted=True, decided_monotonic=100.0), 90.0, 5)    # late (10 s > 5)
            arbiter.register(KEY, 1, trace(1, accepted=False, decided_monotonic=91.0), 90.0, 50)   # rejected
            arbiter.register(KEY, 2, trace(2, accepted=True), 90.0, 50)                            # no timestamp
            arbiter.register(KEY, 3, trace(3, accepted=True, decided_monotonic=120.0), 90.0, 50)   # in time
            arbiter.register(KEY, 4, trace(4, accepted=True, decided_monotonic=110.0), 90.0, 50)   # in time, earliest
            arbiter.register(KEY, 5, str(Path(d) / 'none.jsonl'), 90.0, 50)                       # no decision yet
            self.assertEqual(arbiter.decide(KEY), 4)
            self.assertEqual(arbiter.decided(KEY), 110.0)
            arbiter.register(KEY, 6, trace(6, accepted=True, decided_monotonic=95.0), 90.0, 50)
            self.assertEqual(arbiter.decide(KEY), 4)  # a winner is final


if __name__ == '__main__':
    unittest.main()
