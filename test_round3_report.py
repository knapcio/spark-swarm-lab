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
    (path / 'arm_accounting.json').write_text(json.dumps(acct(tokens, wh=wh)))


def acct(tokens, wh=1.0, wrapper=False, **changes):
    snaps = {k: dict(nodes={n: dict(generation_tokens=float(i)) for n in ('01', '02', '03', '04')})
             for i, k in enumerate(('before', 'after'))}
    rec = dict(protocol='swarm-arm-accounting-v1', **snaps, runner_wall_seconds=10, runner_exit=0, idle_after=True,
               server=dict(total=dict(generation_tokens=tokens), per_node={'01': dict(generation_tokens=tokens)}),
               energy=dict(total_wh=wh))
    if wrapper:
        rec['command'] = ['python3', 'x.py']
    rec.update(changes)
    return rec


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
        (root / 'SWARM_ROUND3_HARD17_D_PLAN.json').write_text(json.dumps(self.d_plan))
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
        (root / 'SWARM_ROUND3_HARD17_L_PLAN.json').write_text(json.dumps(l_plan))
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
        (root / 'SWARM_ROUND3_HARD17_X_PLAN.json').write_text(json.dumps(x_plan))
        write_run(runs / f'{STUDY}-x-esc_extra', x_plan,
                  [row('t1', 'esc_extra', True, True, slot=13), row('t2', 'esc_extra')], 300)
        c = runs / f'{STUDY}-c'
        c.mkdir()
        (c / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (
            dict(run='d', task_id='t1', seed=1, closers=[{}], rescue=True, solved=True, wrong=False, infra=0),
            dict(run='d', task_id='t2', seed=1, closers=[{}], rescue=True, solved=False, wrong=True, infra=0))))
        (c / 'arm_accounting.json').write_text(json.dumps(acct(50, wh=0.1, wrapper=True)))
        (runs / f'{STUDY}-r.cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (
            recall_row('t1', 'none'), recall_row('t2', 'case_rescue', accepted=1, solved=1))))
        (runs / f'{STUDY}-r.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (
            replay_record('t1'), replay_record('t2', verdict=True))))
        (runs / f'{STUDY}-r').mkdir()
        (runs / f'{STUDY}-r' / 'arm_accounting.json').write_text(json.dumps(acct(80, wh=0.1, wrapper=True)))
        for name, rows in (('closer_screen', [closer_row(f's{i}', solved=True) for i in range(4)]),
                           ('recall_screen', [recall_row(f's{i}', 'case_rescue', accepted=1, solved=1) for i in range(4)])):
            (root / '.runtime' / name).mkdir(parents=True)
            fname = 'cases.jsonl' if name == 'closer_screen' else 'recall.cases.jsonl'
            (root / '.runtime' / name / fname).write_text(''.join(json.dumps(r) + '\n' for r in rows))


def recall_row(task, outcome, accepted=0, solved=0, wrong=0, answered=False, errors=0):
    return dict(run='d', task_id=task, seed=1, recorded_answered=answered, recorded_solved=False, replays=2,
                replay_errors=errors, replay_plans=1, judge_accepted=accepted, judge_accepted_verifier_solved=solved,
                judge_accepted_wrong=wrong, outcome=outcome, accepted_stems=[], tokens_generated=10)


def replay_record(task, verdict=None, **changes):
    return dict(dict(run='d', task_id=task, seed=1, stem=f'{task}-a0', error=None, verdict=verdict, judge_error=None,
                     judge_infra=0, verifier_solved=bool(verdict)), **changes)


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

    def test_recall_screen_counts_judge_faults_from_the_records(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [recall_row(f't{i}', 'case_rescue', accepted=1, solved=1) for i in range(4)]
            (Path(d) / 'x.cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            out = gate.screen(Path(d) / 'x.cases.jsonl')
            self.assertEqual(out['faults'], 4)  # no records file: judge outcomes unverifiable
            (Path(d) / 'x.jsonl').write_text(''.join(json.dumps(replay_record(f't{i}', verdict=True,
                                                                              judge_error='boom' if i == 2 else None)) + '\n'
                                                     for i in range(4)))
            out = gate.screen(Path(d) / 'x.cases.jsonl')
            self.assertEqual((out['faults'], out['rescued'], out['pass']), (1, 4, True))

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
        self.assertEqual((D['server_tokens_per_case'], D['server_tokens_per_solved'], D['wh'], D['status']), (300, 1200, 2.0, 'complete'))
        self.assertEqual(len(D['segments']), 2)
        self.assertEqual((L['solved'], L['abstain'], L['server_tokens_per_solved']), (2, 2, 450))
        self.assertEqual(s['paired_L_vs_D'], dict(cases=4, l_only=1, d_only=0, sign_test_p=1.0))
        pos = REASONING.index('822 done\n') + len('822 done\n')
        expected = 100 * (1 - pos / (len(REASONING) + len(RESPONSE)))  # unrounded
        self.assertEqual(s['mechanism']['D'], dict(leftover_winners=1, measured=1, target_statement_not_found=0,
                                                   median=expected, p90=expected))
        self.assertEqual(s['mechanism']['L']['leftover_winners'], 0)
        X, C, R = (s['addons'][k] for k in 'XCR')
        self.assertEqual((X['rescued'], X['wrong'], X['rescue_slots'], X['share_of_d_tokens']), (1, 0, [13], 0.25))
        self.assertEqual((C['status'], C['rescued'], C['wrong'], C['server_tokens']), ('complete', 1, 1, 50))
        self.assertEqual((R['status'], R['rescued'], R['wrong'], R['share_of_d_tokens']), ('complete', 1, 0, 80 / 1200))
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
        self.assertTrue(s['decisions']['L'].startswith('incomplete'))
        self.assertTrue(all(s['decisions'][k].startswith('incomplete') for k in 'XCR'))
        self.assertEqual(s['plans']['C'], 'plan not written')

    @staticmethod
    def complete(**kw):
        return dict(status='complete', reasons=[], **kw)

    def synthetic(self):
        return dict(arms=dict(D=self.complete(solved=10, server_tokens_per_solved=5.0),
                              L=self.complete(solved=7, wrong=0, wrong_all_attempts=0, server_tokens_per_solved=4.0)),
                    addons=dict(X=self.complete(rescued=2, wrong=0, wrong_all_attempts=0, rescue_slots=[12, 15]),
                                C=self.complete(rescued=3, wrong=0, share_of_d_tokens=0.05, server_tokens=10),
                                R=self.complete(rescued=3, wrong=0, share_of_d_tokens=0.04, server_tokens=8)))

    def test_x_rule_cap16_and_both_addons_pass(self):
        s = self.synthetic()
        dec = rep.decisions(s)
        self.assertEqual(dec['X']['outcome'], 'cap 16')
        self.assertTrue(dec['L']['rejected_pending_review'])
        self.assertIn('adopt R first', dec['C_and_R'])
        s['addons']['X']['rescue_slots'] = [12, 18]
        self.assertEqual(rep.decisions(s)['X']['outcome'], 'cap 20')

    def test_decisions_use_unrounded_values(self):
        s = self.synthetic()
        s['arms']['D'].update(solved=3, server_tokens_per_solved=1000 / 3)  # 333.33
        s['arms']['L'].update(solved=4, server_tokens_per_solved=1332 / 4)  # 333.0: equal when rounded, cheaper unrounded
        self.assertTrue(rep.decisions(s)['L']['cheaper_per_solved'])
        s['addons']['C']['share_of_d_tokens'] = 0.1000001  # rounds to 0.1 but is above the 10 % ceiling
        self.assertFalse(rep.decisions(s)['C']['tokens_at_most_10pct_of_d'])

    def test_no_decision_without_complete_inputs(self):
        for arm, part in (('D', 'arms'), ('L', 'arms'), ('X', 'addons'), ('C', 'addons')):
            s = self.synthetic()
            s[part][arm] = dict(status='incomplete', reasons=['why'])
            dec = rep.decisions(s)
            blocked = {'D': 'LXCR', 'L': 'L', 'X': 'X', 'C': 'C'}[arm]
            for k in 'LXCR':
                self.assertEqual(isinstance(dec[k], str) and dec[k].startswith('incomplete'), k in blocked, (arm, k))

    def study_status(self, mutate):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            Study(root)
            mutate(root)
            return self.build(root)

    def test_incomplete_inputs_are_reported_with_reasons(self):
        runs = lambda root: root / 'runs'

        def drop_counter(root):
            f = runs(root) / f'{STUDY}-d-roll12strategy-resume1' / 'arm_accounting.json'
            rec = json.loads(f.read_text())
            del rec['server']['total']['generation_tokens']
            f.write_text(json.dumps(rec))
        s = self.study_status(drop_counter)
        self.assertEqual(s['arms']['D']['status'], 'incomplete')
        self.assertIsNone(s['arms']['D']['server_tokens'])  # never a partial total
        self.assertTrue(all(isinstance(s['decisions'][k], str) for k in 'LXCR'))

        def negative_delta(root):
            (runs(root) / f'{STUDY}-l-roll12strategy' / 'arm_accounting.json').write_text(json.dumps(
                acct(900, server=dict(total=dict(generation_tokens=900), per_node={'01': dict(generation_tokens=-5)}))))
        s = self.study_status(negative_delta)
        self.assertIn('negative', ' '.join(s['arms']['L']['reasons']))

        def no_screen(root):
            import shutil
            shutil.rmtree(root / '.runtime' / 'closer_screen')
        s = self.study_status(no_screen)
        self.assertEqual(s['addons']['C']['status'], 'incomplete')
        self.assertIn('dev-screen gate', ' '.join(s['addons']['C']['reasons']))
        self.assertEqual(s['addons']['R']['status'], 'complete')

        def dirty_wrapper(root):
            (runs(root) / f'{STUDY}-r' / 'arm_accounting.json').write_text(json.dumps(
                acct(80, wrapper=True, energy_error='energy samples missing on nodes [02]')))
        s = self.study_status(dirty_wrapper)
        self.assertEqual(s['addons']['R']['status'], 'incomplete')

        def faulted_row(root):
            with (runs(root) / f'{STUDY}-r.cases.jsonl').open('a') as f:
                f.write(json.dumps(recall_row('t3', 'none', errors=1)) + '\n')
        s = self.study_status(faulted_row)
        self.assertIn('faulted', ' '.join(s['addons']['R']['reasons']))

    def test_replay_cohort_and_judge_faults(self):
        runs = lambda root: root / 'runs'

        def judge_fault(root):
            (runs(root) / f'{STUDY}-r.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (
                replay_record('t1', judge_infra=1), replay_record('t2', verdict=True))))
        s = self.study_status(judge_fault)
        self.assertEqual(s['addons']['R']['status'], 'incomplete')
        self.assertIn('faulted', ' '.join(s['addons']['R']['reasons']))

        def no_records(root):
            (runs(root) / f'{STUDY}-r.jsonl').unlink()
        self.assertEqual(self.study_status(no_records)['addons']['R']['status'], 'incomplete')

        def partial_cohort(root):
            f = runs(root) / f'{STUDY}-c' / 'cases.jsonl'
            f.write_text(f.read_text().splitlines()[0] + '\n')
        s = self.study_status(partial_cohort)
        self.assertEqual(s['addons']['C']['status'], 'incomplete')
        self.assertIn("cohort differs from D's clean abstentions (0 extra, 1 missing)", ' '.join(s['addons']['C']['reasons']))
        self.assertTrue(s['decisions']['C'].startswith('incomplete'))

        def extra_case(root):
            with (runs(root) / f'{STUDY}-r.cases.jsonl').open('a') as f:
                f.write(json.dumps(recall_row('t3', 'none')) + '\n')
            with (runs(root) / f'{STUDY}-r.jsonl').open('a') as f:
                f.write(json.dumps(replay_record('t3')) + '\n')
        self.assertIn('1 extra', ' '.join(self.study_status(extra_case)['addons']['R']['reasons']))

    def test_zero_node_delta_and_every_segment_counts(self):
        runs = lambda root: root / 'runs'

        def zero_node(root):
            (runs(root) / f'{STUDY}-l-roll12strategy' / 'arm_accounting.json').write_text(json.dumps(acct(
                900, server=dict(total=dict(generation_tokens=900),
                                 per_node={'01': dict(generation_tokens=900), '02': dict(generation_tokens=0)}))))
        s = self.study_status(zero_node)
        self.assertEqual(s['arms']['L']['status'], 'incomplete')
        self.assertIn("delta 0 on node(s) ['02']", ' '.join(s['arms']['L']['reasons']))

        def caseless_segment(root):  # a resume that crashed before writing any case still cost server tokens
            seg = runs(root) / f'{STUDY}-d-roll12strategy-resume2'
            seg.mkdir()
            (seg / 'arm_accounting.json').write_text(json.dumps(acct(
                55, server=dict(total=dict(generation_tokens=55), per_node={'01': dict(generation_tokens=0)}))))
        s = self.study_status(caseless_segment)
        self.assertEqual((s['arms']['D']['status'], s['arms']['D']['server_tokens']), ('complete', 1255))
        self.assertEqual(len(s['arms']['D']['segments']), 3)

        def caseless_without_accounting(root):
            (runs(root) / f'{STUDY}-d-roll12strategy-resume2').mkdir()
        s = self.study_status(caseless_without_accounting)
        self.assertEqual(s['arms']['D']['status'], 'incomplete')
        self.assertIsNone(s['arms']['D']['server_tokens'])

    def test_zero_generation_with_activity_in_a_caseless_segment(self):
        # L-flip: a case-less L resume segment whose node 02 lost its generation counter (written as 0 by arms.py) while
        # decode and request deltas show work; summing it would undercount L's tokens and could flip the L decision
        def flip(root):
            seg = root / 'runs' / f'{STUDY}-l-roll12strategy-resume1'
            seg.mkdir()
            per_node = {'01': dict(generation_tokens=100, decode_tokens=100, requests=3),
                        '02': dict(generation_tokens=0, decode_tokens=5000, requests=12)}
            (seg / 'arm_accounting.json').write_text(json.dumps(acct(
                100, server=dict(total=dict(generation_tokens=100), per_node=per_node))))
        s = self.study_status(flip)
        self.assertEqual(s['arms']['L']['status'], 'incomplete')
        self.assertIn("node(s) ['02'] report generation_tokens 0", ' '.join(s['arms']['L']['reasons']))
        self.assertIsNone(s['arms']['L']['server_tokens'])
        self.assertTrue(s['decisions']['L'].startswith('incomplete'))

    def test_inconsistent_node_rule(self):
        self.assertTrue(rep.inconsistent_node(dict(generation_tokens=0, decode_tokens=5, requests=1)))
        self.assertTrue(rep.inconsistent_node(dict(generation_tokens=7, decode_tokens=0, requests=0)))
        self.assertTrue(rep.inconsistent_node(dict(generation_tokens=0, decode_tokens=0, requests=2)))
        self.assertFalse(rep.inconsistent_node(dict(generation_tokens=0, decode_tokens=0, requests=0)))
        self.assertFalse(rep.inconsistent_node(dict(generation_tokens=7, decode_tokens=7, requests=1)))
        self.assertFalse(rep.inconsistent_node(dict(generation_tokens=7)))

    def test_superseded_wrong_attempt_counts_and_wasted_work(self):
        def wrong_then_resumed(root):
            # L: t2 first attempt answered WRONG in an infra-faulted run; the resume answers it correctly
            base = root / 'runs' / f'{STUDY}-l-roll12strategy'
            rows = [json.loads(line) for line in (base / 'cases.jsonl').read_text().splitlines()]
            rows[2].update(answered=True, wrong=True, infra=1, selected_slot=0)
            (base / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            plan = json.loads((root / 'SWARM_ROUND3_HARD17_L_PLAN.json').read_text())
            write_run(root / 'runs' / f'{STUDY}-l-roll12strategy-resume1', plan,
                      [row('t2', 'roll12strategy', True, True, slot=0)], 50, resume_of=base)
        s = self.study_status(wrong_then_resumed)
        L = s['arms']['L']
        self.assertEqual((L['status'], L['wrong'], L['wrong_all_attempts']), ('complete', 0, 1))
        self.assertEqual(L['wrong_attempts'], [dict(task_id='t2', seed=1, segment=f'{STUDY}-l-roll12strategy',
                                                    superseded=True, infra=True)])
        self.assertFalse(s['decisions']['L']['zero_wrong'])
        self.assertFalse(s['decisions']['L']['adopt_sentence'])
        self.assertEqual([(w['dir'], w['server_tokens'], w['superseded_cases']) for w in L['wasted_work']],
                         [(f'{STUDY}-l-roll12strategy', 900, [['t2', 1]])])

    def test_plan_equality_idle_and_snapshots_required(self):
        def other_plan(root):
            f = root / 'SWARM_ROUND3_HARD17_L_PLAN.json'
            f.write_text(json.dumps(dict(json.loads(f.read_text()), note='amended')))
        s = self.study_status(other_plan)
        self.assertEqual(s['arms']['L']['status'], 'incomplete')
        self.assertIn('embedded plan differs', ' '.join(s['arms']['L']['reasons']))

        def no_idle_flag(root):
            f = root / 'runs' / f'{STUDY}-l-roll12strategy' / 'arm_accounting.json'
            rec = json.loads(f.read_text())
            del rec['idle_after']
            f.write_text(json.dumps(rec))
        self.assertIn('idle_after is not true', ' '.join(self.study_status(no_idle_flag)['arms']['L']['reasons']))

        def missing_snapshot_node(root):
            f = root / 'runs' / f'{STUDY}-l-roll12strategy' / 'arm_accounting.json'
            rec = json.loads(f.read_text())
            del rec['after']['nodes']['03']['generation_tokens']
            f.write_text(json.dumps(rec))
        self.assertIn("after snapshot lacks generation_tokens for node(s) ['03']",
                      ' '.join(self.study_status(missing_snapshot_node)['arms']['L']['reasons']))

    def test_unresolved_infra_blocks_the_arm(self):
        def unresolved(root):
            f = root / 'runs' / f'{STUDY}-l-roll12strategy' / 'cases.jsonl'
            rows = [json.loads(line) for line in f.read_text().splitlines()]
            rows[2]['infra'] = 1
            f.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        s = self.study_status(unresolved)
        self.assertEqual(s['arms']['L']['status'], 'incomplete')
        self.assertTrue(s['decisions']['L'].startswith('incomplete'))


class MechanismTests(unittest.TestCase):
    def test_discovery_needs_a_true_equation_in_the_accepted_stream(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'a.jsonl'
            failed = dict(type='request_end', request_id='r1', error='ConnectionError: stream ended without finish_reason',
                          reasoning='first try\n825-3 = 822 found early\n', response=None, usage=dict(completion_tokens=500))
            plan = dict(type='request_end', request_id='r2', error=None, finish_reason='length',
                        reasoning='2+3 = 822 is false\nTry 55*15=825\n(825-3) = 822 yes\ncheck again\n', response=None,
                        usage=dict(completion_tokens=100))
            forced = dict(type='request_end', request_id='r3', parent_request_id='r2', error=None, reasoning='',
                          response=RESPONSE, usage=dict(completion_tokens=20))
            f.write_text(''.join(json.dumps(e) + '\n' for e in (failed, plan, forced)))
            after = rep.tokens_after_target(f, 822)
        text = plan['reasoning']
        pos = text.index('yes\n') + len('yes\n')
        self.assertAlmostEqual(after, 100 * (1 - pos / len(text)) + 20)  # failed attempt r1 not counted

    def test_lost_attempt_tokens_are_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'a.jsonl'
            text = 'Try 55*15=825\n825-3 = 822 yes\nmore\n'
            # transport-retried request: usage charges lost 400 + delivered 100; only the delivered 100 count
            plan = dict(type='request_end', request_id='r1', error=None, reasoning=text, response=RESPONSE,
                        usage=dict(completion_tokens=500, lost_attempt_completion_tokens=400), attempts=2,
                        attempt_completion_tokens=[400, 100], token_ids=[0] * 100)
            f.write_text(json.dumps(dict(type='request_retry', request_id='r1', lost_completion_tokens=400)) + '\n' +
                         json.dumps(plan) + '\n')
            after = rep.tokens_after_target(f, 822)
        pos = text.index('yes\n') + len('yes\n')
        self.assertAlmostEqual(after, 100 * (1 - pos / (len(text) + len(RESPONSE))))

    def test_evaluate(self):
        self.assertEqual(rep.evaluate(['(', '25', '*', '4', '-', '2', ')', '*', '8']), 784)
        self.assertEqual(rep.evaluate(['7', '/', '2']), rep.Fraction(7, 2))
        self.assertIsNone(rep.evaluate(['1', '/', '0']))
        self.assertIsNone(rep.evaluate(['1', '+']))


if __name__ == '__main__':
    unittest.main()
