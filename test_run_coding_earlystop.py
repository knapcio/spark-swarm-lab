"""Offline tests for the early-stop coding runner (fake workers, no model, no sandbox)."""
import contextlib
import hashlib
import io
import json
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
    def run_main(self, fast_pass, holdout):
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
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps(plan))
            adm = root / 'adm.json'
            adm.write_text(json.dumps(dict(verified=True, verified_utc=datetime.now(timezone.utc).isoformat())))
            started = []

            def execute(job, deadline, cancel):
                started.append((job['task_id'], job['agent']))
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

            def outcome(events):
                agent = int(Path(events).name.split('-a')[1].split('-')[0])
                return dict(parsed=True, feedback_pass=agent in fast_pass, holdout_pass=agent in holdout, budget_forced=False)
            with patch.object(r, 'execute_cancellable', execute), patch.object(r, 'agent_outcome', outcome), \
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

    def test_cancelled_row_is_not_an_operational_fault(self):
        row = dict(cancelled=True, controller_error=None, malformed_lines=0)
        self.assertIsNone(r.fault(row))


if __name__ == '__main__':
    unittest.main()
