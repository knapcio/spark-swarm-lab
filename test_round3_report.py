"""Offline tests for inkling/round3_gate.py and inkling/report_round3_hard17.py on synthetic run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_round3_hard17 as rep  # noqa: E402
import round3_gate as gate  # noqa: E402

STUDY = 'swarm-round3-hard17-v1'
TASKS = [dict(id=f't{i}', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822) for i in range(4)]
REASONING = 'Target 822 restated.\nTry 55*15=825 hmm\n825-3 = 822 done\nmore thinking here\n'
RESPONSE = '{"moves": [1, 2, 3, 4]}'


def agent(slot, verdict=None, plan=None, solved=False):
    return dict(slot=slot, plan=plan, verdict=verdict, verifier_solved=solved, started=True, cancelled=False, tokens=10)


def row(task, policy, answered=False, solved=False, wrong=False, slot=None, agents=(), infra=0, seed=1):
    return dict(task_id=task, seed=seed, policy=policy, answered=answered, solved=solved, wrong=wrong, infra=infra,
                selected_slot=slot, agents=list(agents) or [agent(0)])


def write_run(path, plan, rows, tokens, resume_of=None, wh=1.0):
    path.mkdir(parents=True)
    (path / 'agents').mkdir()
    meta = dict(protocol=plan, policies=plan['policies'], resume=dict(resumed_from=str(resume_of)) if resume_of else None)
    (path / 'metadata.json').write_text(json.dumps(meta))
    (path / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (path / 'arm_accounting.json').write_text(json.dumps(dict(
        protocol='swarm-arm-accounting-v1', runner_wall_seconds=10, server=dict(total=dict(generation_tokens=tokens)),
        energy=dict(total_wh=wh))))


def trace(path, reasoning=REASONING, response=RESPONSE, tokens=100):
    path.write_text(json.dumps(dict(type='request_end', reasoning=reasoning, response=response,
                                    usage=dict(completion_tokens=tokens))) + '\n')


class Study:
    """A synthetic study tree under a temporary root."""
    def __init__(self, root, with_addons=True):
        self.root = root
        (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS)))
        base = dict(dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=4, seeds=[1],
                    agent_variant='xl_forced_original', seed_offsets=dict(roll12strategy=17400, esc_extra=17400))
        self.d_plan = dict(base, study=f'{STUDY}-d', policies=['roll12strategy'])
        runs = root / 'runs'
        d = runs / f'{STUDY}-d-roll12strategy'
        win = agent(0, True, {'moves': [{}] * 4}, True)  # 4 moves on 6 numbers: one number left over
        write_run(d, self.d_plan, [row('t0', 'roll12strategy', True, True, slot=0, agents=[win]),
                                   row('t1', 'roll12strategy'), row('t2', 'roll12strategy', infra=1),
                                   row('t3', 'roll12strategy', True, False, True, slot=1)], 1000)
        trace(d / 'agents' / 't0-s1-roll12strategy-a0.jsonl')
        write_run(runs / f'{STUDY}-d-roll12strategy-resume1', self.d_plan, [row('t2', 'roll12strategy')], 200,
                  resume_of=d)
        l_plan = dict(self.d_plan, study=f'{STUDY}-l', agent_variant='xl_forced_leftover')
        lwin = agent(0, True, {'moves': [{}] * 5}, True)  # uses every number: not a leftover winner
        write_run(runs / f'{STUDY}-l-roll12strategy', l_plan,
                  [row('t0', 'roll12strategy', True, True, slot=0, agents=[lwin]),
                   row('t1', 'roll12strategy', True, True, slot=0, agents=[lwin]), row('t2', 'roll12strategy'),
                   row('t3', 'roll12strategy')], 900)
        if not with_addons:
            return
        self.abst = root / 'results' / STUDY / 'd_abstentions.json'
        with contextlib.redirect_stdout(io.StringIO()):
            gate.main(['abstentions', '--run', str(d), '--output', str(self.abst), '--root', str(root)])
        x_plan = dict(base, study=f'{STUDY}-x', policies=['esc_extra'], case_list=str(self.abst))
        write_run(runs / f'{STUDY}-x-esc_extra', x_plan,
                  [row('t1', 'esc_extra', True, True, slot=13), row('t2', 'esc_extra')], 300)
        c = runs / f'{STUDY}-c'
        c.mkdir()
        (c / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (
            dict(run='d', task_id='t1', seed=1, closers=[{}], rescue=True, solved=True, wrong=False, infra=0),
            dict(run='d', task_id='t2', seed=1, closers=[{}], rescue=True, solved=False, wrong=True, infra=0))))
        (c / 'arm_accounting.json').write_text(json.dumps(dict(runner_wall_seconds=5, server=dict(total=dict(generation_tokens=50)),
                                                               energy=dict(total_wh=0.1))))
        (runs / f'{STUDY}-r.cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (
            recall_row('t1', 'none'), recall_row('t2', 'case_rescue', accepted=1, solved=1))))
        (runs / f'{STUDY}-r').mkdir()
        (runs / f'{STUDY}-r' / 'arm_accounting.json').write_text(json.dumps(dict(
            runner_wall_seconds=5, server=dict(total=dict(generation_tokens=80)), energy=dict(total_wh=0.1))))


def recall_row(task, outcome, accepted=0, solved=0, wrong=0, answered=False, errors=0):
    return dict(run='d', task_id=task, seed=1, recorded_answered=answered, recorded_solved=False, replays=2,
                replay_errors=errors, replay_plans=1, judge_accepted=accepted, judge_accepted_verifier_solved=solved,
                judge_accepted_wrong=wrong, outcome=outcome, accepted_stems=[], tokens_generated=10)


def closer_row(task, solved=False, wrong=False):
    return dict(run='d', task_id=task, seed=1, closers=[{}], rescue=solved or wrong, solved=solved, wrong=wrong, infra=0)


class GateTests(unittest.TestCase):
    def screen(self, rows, name='cases.jsonl', as_dir=True):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / name
            f.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gate.main(['screen', d if as_dir else str(f)])
            return code, json.loads(buf.getvalue())

    def test_closer_screen_pass_and_fail(self):
        rows = [closer_row(f't{i}', solved=True) for i in range(4)] + [closer_row('t9')]
        code, out = self.screen(rows)
        self.assertEqual((code, out['kind'], out['cases'], out['rescued'], out['wrong'], out['pass']), (0, 'closer', 5, 4, 0, True))
        code, out = self.screen(rows + [closer_row('t8', wrong=True)])
        self.assertEqual((code, out['wrong'], out['pass']), (10, 1, False))
        code, out = self.screen(rows[1:])
        self.assertEqual((code, out['rescued']), (10, 3))

    def test_recall_screen_counts_any_wrong_accept_and_skips_answered_cases(self):
        rows = [recall_row(f't{i}', 'case_rescue', accepted=1, solved=1) for i in range(4)]
        rows.append(recall_row('a', 'agent_accept', accepted=1, solved=0, wrong=1, answered=True))  # not counted
        code, out = self.screen(rows, 'x.cases.jsonl')
        self.assertEqual((code, out['kind'], out['cases'], out['rescued'], out['wrong']), (0, 'recall', 4, 4, 0))
        mixed = recall_row('t5', 'case_rescue', accepted=2, solved=1, wrong=1)  # one right, one wrong accept
        code, out = self.screen(rows + [mixed], 'x.cases.jsonl', as_dir=False)
        self.assertEqual((code, out['rescued'], out['wrong'], out['pass']), (10, 4, 1, False))

    def test_abstentions_follow_the_resume_rule(self):
        with tempfile.TemporaryDirectory() as d:
            study = Study(Path(d))
            data = json.loads(study.abst.read_text())
            self.assertEqual(data['cases'], [['t1', 1], ['t2', 1]])  # t2 from -resume1; t0/t3 answered
            self.assertEqual(data['segments'], [f'{STUDY}-d-roll12strategy', f'{STUDY}-d-roll12strategy-resume1'])
            with self.assertRaisesRegex(SystemExit, 'exists'):
                gate.main(['abstentions', '--run', str(Path(d) / 'runs' / f'{STUDY}-d-roll12strategy'),
                           '--output', str(study.abst), '--root', d])

    def test_abstentions_refuse_unresolved_infra(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            Study(root, with_addons=False)
            import shutil
            shutil.rmtree(root / 'runs' / f'{STUDY}-d-roll12strategy-resume1')
            with self.assertRaisesRegex(SystemExit, 'unresolved'):
                gate.main(['abstentions', '--run', str(root / 'runs' / f'{STUDY}-d-roll12strategy'),
                           '--output', str(root / 'a.json'), '--root', d])


class ReportTests(unittest.TestCase):
    def build(self, root):
        return rep.build(root, dict(rep.DEFAULTS))

    def test_full_study(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            Study(root)
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
            js = json.loads((root / 'results' / STUDY / 'report.json').read_text())
        D, L = s['arms']['D'], s['arms']['L']
        self.assertEqual((D['cases'], D['solved'], D['wrong'], D['abstain'], D['server_tokens']), (4, 1, 1, 2, 1200))
        self.assertEqual((D['server_tokens_per_case'], D['server_tokens_per_solved'], D['wh']), (300, 1200, 2.0))
        self.assertEqual(len(D['segments']), 2)
        self.assertEqual((L['solved'], L['abstain'], L['server_tokens_per_solved']), (2, 2, 450))
        self.assertEqual(s['paired_L_vs_D'], dict(cases=4, l_only=1, d_only=0, sign_test_p=1.0))
        pos = REASONING.index('822 done\n') + len('822 done\n')
        expected = round(100 * (1 - pos / (len(REASONING) + len(RESPONSE))))
        self.assertEqual(s['mechanism']['D'], dict(leftover_winners=1, measured=1, target_statement_not_found=0,
                                                   median=expected, p90=expected))
        self.assertEqual(s['mechanism']['L']['leftover_winners'], 0)
        X, C, R = (s['addons'][k] for k in 'XCR')
        self.assertEqual((X['rescued'], X['wrong'], X['rescue_slots'], X['share_of_d_tokens']), (1, 0, [13], 0.25))
        self.assertEqual((C['rescued'], C['wrong'], C['server_tokens']), (1, 1, 50))
        self.assertEqual((R['rescued'], R['wrong'], R['share_of_d_tokens']), (1, 0, round(80 / 1200, 4)))
        self.assertEqual(s['overlap']['pairwise'], {'C&R': 0, 'C&X': 1, 'R&X': 0})
        self.assertEqual(s['overlap']['union'], 2)
        dec = s['decisions']
        self.assertEqual(dec['L'], dict(zero_wrong=True, solved_within_noise=True, cheaper_per_solved=True,
                                        adopt_sentence=True, rejected_pending_review=False))
        self.assertEqual(dec['X']['outcome'], 'no change')
        self.assertFalse(dec['C']['adopt'])
        self.assertEqual(dec['R'], dict(zero_wrong=True, rescued_at_least_2=False, tokens_at_most_10pct_of_d=True, adopt=False))
        self.assertIn('flush_caches ignores the ssh exit status', s['disclosure'])
        self.assertIn('| D | complete |', md)
        self.assertIn('Accounting disclosure', md)
        self.assertEqual(js['arms']['D']['solved'], 1)

    def test_missing_and_incomplete_arms(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            Study(root, with_addons=False)
            lines = (root / 'runs' / f'{STUDY}-l-roll12strategy' / 'cases.jsonl').read_text().splitlines()
            (root / 'runs' / f'{STUDY}-l-roll12strategy' / 'cases.jsonl').write_text('\n'.join(lines[:2]) + '\n')
            s = self.build(root)
        self.assertEqual(s['arms']['D']['status'], 'complete')
        self.assertEqual(s['arms']['L']['status'], 'incomplete')
        self.assertEqual({k: v['status'] for k, v in s['addons'].items()}, dict(X='not run', C='not run', R='not run'))
        self.assertEqual(s['screens'], dict(closer='not run', recall='not run'))
        self.assertIn('not evaluable', s['decisions']['L'])
        self.assertEqual(s['plans']['D'], 'plan not written')

    def test_x_rule_cap16_and_both_addons_pass(self):
        s = dict(arms=dict(D=dict(solved=10, server_tokens_per_solved=5), L=dict(solved=7, wrong=0, server_tokens_per_solved=4)),
                 addons=dict(X=dict(rescued=2, wrong=0, rescue_slots=[12, 15]),
                             C=dict(rescued=3, wrong=0, share_of_d_tokens=0.05, server_tokens=10),
                             R=dict(rescued=3, wrong=0, share_of_d_tokens=0.04, server_tokens=8)))
        dec = rep.decisions(s)
        self.assertEqual(dec['X']['outcome'], 'cap 16')
        self.assertTrue(dec['L']['rejected_pending_review'])
        self.assertIn('adopt R first', dec['C_and_R'])
        s['addons']['X']['rescue_slots'] = [12, 18]
        self.assertEqual(rep.decisions(s)['X']['outcome'], 'cap 20')


if __name__ == '__main__':
    unittest.main()
