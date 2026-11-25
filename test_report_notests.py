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

TASKS = json.dumps(dict(tasks=[dict(id=t, split='evaluation') for t in 'abc'] + [dict(id='z', split='development')]))
PLAN = dict(matrix=dict(tasks='t.json', seeds=[1], split='evaluation', tasks_count=3,
                        tasks_sha256=__import__('hashlib').sha256(TASKS.encode()).hexdigest()), agent_variants=['code_xl'] * 4, agent_seed_offset=7,
            rolling=dict(width=2), source_revision='abc', limits=dict(x=1), scheduling=dict(concurrent_agents_per_node=20),
            serving=dict(container='swarm-recipe', image_id='sha256:e', mem_fraction='0.88'))


def make_arm(root, name, acceptance, outcomes, wh=10.0, server=1000, plan_extra=None, judge_tokens=0, exit_code=0,
             errors=()):
    """outcomes: {task: (answered, solved, [(accepted, feedback, holdout, extra), ...])} for one seed."""
    d = root / name
    d.mkdir()
    plan = dict(PLAN, **({'acceptance': acceptance} if acceptance else {}), **(plan_extra or {}))
    (root / 't.json').write_text(TASKS)
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=plan, errors=list(errors), batch_wall_seconds=50,
                                                     completed_utc='2026-11-25T00:00:00+00:00')))
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
                records.append(dict(type='judge_end', judge_forced=bool(extra.get('_forced'))))
            if not extra.get('_cancelled'):
                records.append(dict(type='puzzle_end', parsed=True, accepted=accepted, feedback_pass=feedback,
                                    holdout_pass=holdout, **extra))
            (d / Path(events).name).write_text('\n'.join(json.dumps(r) for r in records) + '\n')
            rows.append(dict(events=events, cancelled=bool(extra.get('_cancelled')), task_id=task, seed=1, agent=i,
                             late_decision=bool(extra.get('_late'))))
    (d / 'cases.json').write_text(json.dumps(cases))
    (d / 'summary.json').write_text(json.dumps(rows))
    (d / 'arm_accounting.json').write_text(json.dumps(dict(server=dict(total=dict(generation_tokens=server)),
                                                           runner_wall_seconds=100.0, runner_exit=exit_code,
                                                           energy=dict(total_wh=wh))))
    return d


class ReportNoTestsTests(unittest.TestCase):
    def build(self, root, judge_plan=None, judge_exit=0, drop_judge_case=False, skip_judge=False, cancelled_judge=False,
              forced_judge=False):
        ok = (True, True, False, {})
        make_arm(root, 'pub', None, {'a': (True, True, [ok]), 'b': (True, False, [(False, True, False, {})]),
                                     'c': (False, False, [(False, False, False, {})] * 2)})
        make_arm(root, 'self', 'self_tests', {'a': (True, True, [ok]), 'b': (True, True, [ok]),
                                              'c': (True, True, [(False, True, True, dict(self_tests_error='bad')), ok])},
                 wh=6.0, server=600)
        judge = {'a': (False, False, [(False, True, True, dict(judge_verdict=None))] * 2),
                 'b': (True, False, [(True, False, True, dict(judge_verdict=True))]),
                 'c': (False, False, [(False, False, False, dict(judge_verdict=False))])}
        if forced_judge:
            judge['b'] = (True, False, [(True, False, True, dict(judge_verdict=True, _forced=True))])
        if cancelled_judge:  # a cancelled agent whose judge call completed before the cancel
            judge['c'] = (False, False, judge['c'][2] + [(False, False, False, dict(_cancelled=True))])
        if drop_judge_case:
            del judge['c']
        if not skip_judge:
            make_arm(root, 'jud', 'judge', judge, plan_extra=judge_plan, judge_tokens=30, exit_code=judge_exit)

    def run_report(self, root):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rn.main(['--public', 'pub', '--self-tests', 'self', '--judge', 'jud', '--runs-dir', str(root),
                            '--out', str(root / 'out'), '--root', str(root)])
        res = json.loads((root / 'out' / 'report.json').read_text())
        self.assertEqual(code, 0 if res['status'] == 'complete' else 1)
        return res, out.getvalue()

    def assert_incomplete(self, res, md, text):
        self.assertEqual(res['status'], 'incomplete')
        self.assertEqual(res['paired'], {})
        self.assertTrue(any(text in x for x in res['problems']), res['problems'])
        self.assertIn('INCOMPLETE', md)

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
        self.assertEqual(jud['solver_tokens_per_case'], 60)  # client 100 per case minus judge
        self.assertEqual(res['status'], 'complete')
        self.assertIn('up to 2 judge calls and up to 8,192 completion tokens (6,144 thinking + 2,048 for a forced', md)
        self.assertEqual(res['disclosure'], rn.DISCLOSURE)
        self.assertEqual(res['paired']['self_tests'], dict(cases=3, wins=2, losses=0, p=0.5, answered_wins=1,
                                                           answered_losses=0, answered_p=1.0))
        self.assertEqual((res['paired']['judge']['wins'], res['paired']['judge']['losses']), (0, 1))
        q = own['acceptance_quality']
        self.assertEqual((q['accepted'], q['accepted_correct'], q['rejected_correct'], q['self_tests_invalid']),
                         (3, 0, 1, 1))  # 'ok' agents pass the feedback cases but fail the holdout
        self.assertEqual(jud['acceptance_quality']['judge_unparsed'], 2)
        self.assertEqual(pub['acceptance_quality']['accepted_wrong'], 2)  # public: accepted = feedback pass
        self.assertEqual(res['problems'], [])
        self.assertIn('R2, no tests: own tests vs public tests', md)

    def test_cancelled_agents_judge_tokens_are_judge_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root, cancelled_judge=True)
            res, md = self.run_report(root)
        jud = res['arms']['judge']
        self.assertEqual(jud['judge_tokens_per_case'], 50)  # 5 judge calls x 30 tokens / 3 cases
        self.assertEqual(jud['solver_tokens_per_case'], 50)  # client 100 per case minus judge
        self.assertEqual(jud['acceptance_quality']['finished'], 4)  # the cancelled agent is not a finished agent

    def test_late_decisions_excluded_from_acceptance_quality(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_arm(root, 'pub', None, {'a': (True, True, [(True, True, True, {})]), 'b': (False, False, []),
                                         'c': (False, False, [])})
            make_arm(root, 'self', 'self_tests', {'a': (True, True, [(True, True, True, {})]),
                                                  'b': (False, False, [(True, True, True, dict(_late=True))]),
                                                  'c': (False, False, [])})
            make_arm(root, 'jud', 'judge', {'a': (False, False, []), 'b': (False, False, []), 'c': (False, False, [])})
            res, md = self.run_report(root)
        q = res['arms']['self_tests']['acceptance_quality']
        self.assertEqual((q['finished'], q['accepted'], q['accepted_correct'], q['late_decisions']), (1, 1, 1, 1))
        self.assertIn('Late decisions (excluded)', md)

    def test_forced_verdict_share_and_budget_disclosure(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root, judge_plan=dict(judge=dict(thinking_tokens=16384)), forced_judge=True)
            res, md = self.run_report(root)
        j = res['arms']['judge']['judge']
        self.assertEqual((j['verdicts'], j['forced'], j['forced_share']), (4, 1, .25))
        self.assertEqual(j['budget'], dict(thinking_tokens=16384, answer_tokens=2048, max_calls=2))
        self.assertIsNone(res['arms']['self_tests']['judge'])
        self.assertIn('up to 18,432 completion tokens (16,384 thinking + 2,048 for a forced verdict)', md)
        self.assertIn('forced after the thinking cap: 1 (25.0 %)', md)
        # judge plan differences are not a cross-arm inconsistency (only the judge arm has a judge budget)
        self.assertEqual(res['status'], 'complete', res['problems'])

    def test_decision_timing_disclosed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root)
            res, md = self.run_report(root)
        self.assertIn('the public-tests arm is the unchanged default path', md)
        self.assertIn('decide BEFORE hidden grading', md)
        self.assertEqual(res['decision_timing'], rn.DECISION_TIMING)

    def test_plan_differences_make_it_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root, judge_plan=dict(agent_seed_offset=8))
            res, md = self.run_report(root)
        self.assert_incomplete(res, md, 'agent_seed_offset differs')

    def test_missing_arm_is_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root, skip_judge=True)
            res, md = self.run_report(root)
        self.assert_incomplete(res, md, 'judge: arm jud missing')

    def test_failed_run_is_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root, judge_exit=1)
            res, md = self.run_report(root)
        self.assert_incomplete(res, md, 'judge: runner exit 1')

    def test_case_set_must_equal_the_frozen_set(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root, drop_judge_case=True)
            res, md = self.run_report(root)
        self.assert_incomplete(res, md, 'judge: task/seed set is not the frozen 3 (1 missing, 0 extra)')

    def test_tasks_file_hash_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.build(root)
            (root / 't.json').write_text(TASKS + ' ')
            res, md = self.run_report(root)
        self.assert_incomplete(res, md, 'does not match the plan hash')

    def test_paired_refuses_unequal_sets(self):
        with self.assertRaises(ValueError):
            rn.paired({('a', 1): {}}, {})


if __name__ == '__main__':
    unittest.main()
