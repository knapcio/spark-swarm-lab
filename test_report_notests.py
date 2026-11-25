"""Offline tests for inkling/report_notests.py (synthetic run directories)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_notests as rn  # noqa: E402

PLAN = dict(matrix=dict(tasks='t.json', seeds=[1]), agent_variants=['code_xl'] * 4, agent_seed_offset=7,
            rolling=dict(width=2), source_revision='abc', limits=dict(x=1), scheduling=dict(concurrent_agents_per_node=20),
            serving=dict(container='swarm-recipe', image_id='sha256:e', mem_fraction='0.88'))


def make_arm(root, name, acceptance, outcomes, wh=10.0, server=1000, plan_extra=None, judge_tokens=0):
    """outcomes: {task: (answered, solved, [(accepted, feedback, holdout, extra), ...])} for one seed."""
    d = root / name
    d.mkdir()
    plan = dict(PLAN, **({'acceptance': acceptance} if acceptance else {}), **(plan_extra or {}))
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=plan, errors=[], batch_wall_seconds=50)))
    cases, rows = [], []
    for task, (answered, solved, agents) in outcomes.items():
        cases.append(dict(task_id=task, seed=1, answered=answered, solved=solved, winner_agent=0 if answered else None,
                          started=len(agents), cancelled=0, never_started=4 - len(agents), completion_tokens=100,
                          stop_seconds=30.0 if answered else None, agents=4))
        for i, (accepted, feedback, holdout, extra) in enumerate(agents):
            events = f'/elsewhere/{task}-s1-a{i}-code_xl.jsonl'
            records = [dict(type='request_end', stage='code_propose', usage=dict(completion_tokens=50))]
            if acceptance == 'judge':
                records.append(dict(type='request_end', stage='judge', usage=dict(completion_tokens=judge_tokens)))
            records.append(dict(type='puzzle_end', parsed=True, accepted=accepted, feedback_pass=feedback,
                                holdout_pass=holdout, **extra))
            (d / Path(events).name).write_text('\n'.join(json.dumps(r) for r in records) + '\n')
            rows.append(dict(events=events, cancelled=False, task_id=task, seed=1, agent=i))
    (d / 'cases.json').write_text(json.dumps(cases))
    (d / 'summary.json').write_text(json.dumps(rows))
    (d / 'arm_accounting.json').write_text(json.dumps(dict(server=dict(total=dict(generation_tokens=server)),
                                                           runner_wall_seconds=100.0, runner_exit=0,
                                                           energy=dict(total_wh=wh))))
    return d


class ReportNoTestsTests(unittest.TestCase):
    def build(self, root, judge_plan=None):
        ok = (True, True, False, {})
        make_arm(root, 'pub', None, {'a': (True, True, [ok]), 'b': (True, False, [(False, True, False, {})]),
                                     'c': (False, False, [(False, False, False, {})] * 2)})
        make_arm(root, 'self', 'self_tests', {'a': (True, True, [ok]), 'b': (True, True, [ok]),
                                              'c': (True, True, [(False, True, True, dict(self_tests_error='bad')), ok])},
                 wh=6.0, server=600)
        make_arm(root, 'jud', 'judge', {'a': (False, False, [(False, True, True, dict(judge_verdict=None))] * 2),
                                        'b': (True, False, [(True, False, True, dict(judge_verdict=True))]),
                                        'c': (False, False, [(False, False, False, dict(judge_verdict=False))])},
                 plan_extra=judge_plan, judge_tokens=30)

    def run_report(self, root):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rn.main(['--public', 'pub', '--self-tests', 'self', '--judge', 'jud', '--runs-dir', str(root),
                     '--out', str(root / 'out')])
        return json.loads((root / 'out' / 'report.json').read_text()), out.getvalue()

    def test_three_arm_report(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root)
            res, md = self.run_report(root)
        pub, own, jud = res['arms']['public'], res['arms']['self_tests'], res['arms']['judge']
        self.assertEqual((pub['solved'], pub['wrong'], pub['unanswered']), (1, 1, 1))
        self.assertEqual((own['solved'], own['wrong'], own['unanswered']), (3, 0, 0))
        self.assertEqual((jud['solved'], jud['wrong'], jud['unanswered']), (0, 1, 2))
        self.assertEqual((pub['wh_per_solved'], own['wh_per_solved'], jud['wh_per_solved']), (10.0, 2.0, None))
        self.assertEqual((own['server_tokens_per_case'], own['client_tokens_per_case']), (200, 100))
        self.assertEqual(jud['judge_tokens_per_case'], 40)  # 4 judged agents x 30 tokens / 3 cases
        self.assertEqual(res['paired']['self_tests'], dict(cases=3, wins=2, losses=0, p=0.5, answered_wins=1,
                                                           answered_losses=0, answered_p=1.0))
        self.assertEqual((res['paired']['judge']['wins'], res['paired']['judge']['losses']), (0, 1))
        q = own['acceptance_quality']
        self.assertEqual((q['accepted'], q['accepted_correct'], q['rejected_correct'], q['self_tests_invalid']),
                         (3, 0, 1, 1))  # 'ok' agents pass the feedback cases but fail the holdout
        self.assertEqual(jud['acceptance_quality']['judge_unparsed'], 2)
        self.assertEqual(pub['acceptance_quality']['accepted_wrong'], 2)  # public: accepted = feedback pass
        self.assertEqual(res['consistency'], [])
        self.assertIn('R2, no tests: own tests vs public tests', md)

    def test_plan_differences_are_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root, judge_plan=dict(agent_seed_offset=8))
            res, md = self.run_report(root)
        self.assertTrue(any(x.startswith('agent_seed_offset differs') for x in res['consistency']))
        self.assertIn('Plan differences', md)

    def test_missing_public_arm(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                rn.main(['--public', 'none', '--runs-dir', d, '--out', str(Path(d) / 'out')])


if __name__ == '__main__':
    unittest.main()
