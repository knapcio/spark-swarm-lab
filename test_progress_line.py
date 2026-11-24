"""Offline tests for inkling/progress_line.py on synthetic run directories."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import progress_line as pl  # noqa: E402


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def jsonl(path, rows, partial=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows) + ('{"half' if partial else ''))


class ProgressLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self.tmp.name) / 'runs'
        self.runs.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_arithmetic_arm_with_plan_total_resume_and_partial_line(self):
        d = self.runs / 'arm'
        write(d / 'metadata.json', dict(protocol=dict(tasks=48, seeds=[1, 2])))
        jsonl(d / 'cases.jsonl', [dict(policy='roll12cancel', solved=True, wrong=False, cancelled_agents=3, escalated_agents=0),
                                  dict(policy='roll12cancel', solved=False, wrong=True, escalated_agents=8),
                                  dict(policy='roll12cancel', solved=False, wrong=False, infra=1)], partial=True)
        (self.runs / 'arm-resume1').mkdir()
        self.assertEqual(pl.line('arm', self.runs), 'progress arm: cases 3/96, solved 1, wrong 1, abstain 1, infra 1, '
                                                    'cancelled agents 3, escalation agents 8, resume segments 1')

    def test_case_list_total(self):
        d = self.runs / 'esc'
        write(self.runs.parent / 'cl.json', dict(cases=[['t0', 1], ['t1', 1]]))
        write(d / 'metadata.json', dict(protocol=dict(tasks=48, seeds=[1, 2], case_list='cl.json')))
        jsonl(d / 'cases.jsonl', [dict(policy='esc_extra', solved=True, wrong=False)])
        self.assertIn('cases 1/2,', pl.line('esc', self.runs))

    def test_relay_screen_running_and_done_under_account_cmd(self):
        d = self.runs / 'screen-relay'
        write(d / 'metadata.json', dict(protocol='swarm-relay-replay-v1', arm='relay', cohort=dict(cases=[[1], [2], [3]])))
        self.assertEqual(pl.line('screen-relay', self.runs), 'progress screen-relay: relay cases 0/3, rescued 0, wrong 0, faults 0')
        jsonl(d / 'cases.jsonl', [dict(rescued=True, wrong=False, faults=0), dict(rescued=False, wrong=True, faults=0),
                                  dict(rescued=False, wrong=False, faults=1)])
        write(d / 'arm_accounting.json', dict(command=['python3', 'relay_replay.py'], runner_exit=0, energy_error='energy missing'))
        self.assertEqual(pl.line('screen-relay', self.runs), 'progress screen-relay: relay cases 3/3, rescued 1, wrong 1, '
                                                             'faults 1; account_cmd done (runner exit 0, energy missing)')

    def test_closer_replay(self):
        jsonl(self.runs / 'closers' / 'cases.jsonl', [dict(closers=[{}], solved=True, wrong=False, infra=0)])
        self.assertEqual(pl.line('closers', self.runs), 'progress closers: closer cases 1, rescued 1, wrong 0, infra 0')

    def test_coding_arm(self):
        write(self.runs / 'code' / 'cases.json', [dict(answered=True, solved=True), dict(answered=True, solved=False),
                                                  dict(answered=False, solved=False)])
        self.assertEqual(pl.line('code', self.runs), 'progress code: coding cases 3, solved 1, wrong 1, unanswered 1')

    def test_log_only_and_not_started(self):
        (self.runs / 'x.log').write_text('starting\n{"done": 1, "total": 9}\n{"done": 2, "total": 9}\n')
        self.assertEqual(pl.line('x', self.runs), 'progress x: items 2/9')
        (self.runs / 'y.log').write_text('admission ok\n')
        self.assertEqual(pl.line('y', self.runs), 'progress y: started, no finished item yet')
        self.assertEqual(pl.line('z', self.runs), 'progress z: not started')


if __name__ == '__main__':
    unittest.main()
