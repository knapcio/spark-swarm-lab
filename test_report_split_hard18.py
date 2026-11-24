"""Offline tests for inkling/report_split_hard18.py on synthetic run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_split_hard18 as rep  # noqa: E402

STUDY = 'swarm-split-hard18-v1'
TASKS = [dict(id=f't{i}', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822) for i in range(3)]


def agent(slot, verdict=None, solved=False):
    return dict(slot=slot, plan={'moves': [1]} if verdict is not None else None, verdict=verdict, verifier_solved=solved,
                started=True, cancelled=False, tokens=10)


def row(task, policy, slot=None, solved=True, wrong=False, infra=0, esc=0, agents=None):
    answered = slot is not None
    return dict(task_id=task, seed=1, policy=policy, answered=answered, solved=answered and solved,
                wrong=answered and wrong, infra=infra, selected_slot=slot, escalated_agents=esc,
                agents=agents if agents is not None else ([agent(slot, True, solved)] if answered else [agent(0)]))


def acct(tokens, wh=1.0, **changes):
    snaps = {k: dict(nodes={n: dict(generation_tokens=float(i)) for n in ('01', '02', '03', '04')})
             for i, k in enumerate(('before', 'after'))}
    per_node = {n: dict(generation_tokens=tokens / 4, decode_tokens=tokens / 4, requests=3) for n in ('01', '02', '03', '04')}
    rec = dict(protocol='swarm-arm-accounting-v1', **snaps, runner_wall_seconds=100, runner_exit=0, idle_after=True,
               server=dict(total=dict(generation_tokens=tokens), per_node=per_node), energy=dict(total_wh=wh))
    rec.update(changes)
    return rec


def write_run(path, plan, policy, rows, tokens, wh=1.0, resume_of=None):
    path.mkdir(parents=True)
    meta = dict(protocol=plan, policies=[policy], resume=dict(resumed_from=str(resume_of)) if resume_of else None)
    (path / 'metadata.json').write_text(json.dumps(meta))
    (path / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (path / 'arm_accounting.json').write_text(json.dumps(acct(tokens, wh)))


def study(root, split_rows=None, with_split=True, with_resume=True):
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS)))
    plan = dict(study=STUDY, dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=3, seeds=[1],
                policies=list(rep.ARMS), agent_variant='xl_forced_original',
                seed_offsets=dict(roll12strategy=18400, roll12split=18400),
                decision_rule='roll12split becomes the arithmetic default if ...')
    (root / rep.PLAN).write_text(json.dumps(plan) + '\n')
    runs = root / 'runs'
    write_run(runs / f'{STUDY}-roll12strategy', plan, 'roll12strategy',
              [row('t0', 'roll12strategy', 0), row('t1', 'roll12strategy', 5, esc=2), row('t2', 'roll12strategy', esc=8)],
              1200, wh=3.0)
    if not with_split:
        return
    split = runs / f'{STUDY}-roll12split'
    rows = split_rows or [row('t0', 'roll12split', 1), row('t1', 'roll12split', 4, esc=1),
                          row('t2', 'roll12split', infra=1, esc=4)]
    write_run(split, plan, 'roll12split', rows, 1000, wh=2.0)
    if with_resume:
        # t2 rerun after the infra stop: answered by escalation slot 6; slot 9 was accepted too but wrong (verifier)
        t2 = row('t2', 'roll12split', 6, esc=3, agents=[agent(0), agent(6, True, True), agent(9, True, False)])
        write_run(runs / f'{STUDY}-roll12split-resume1', plan, 'roll12split', [t2], 400, wh=1.0, resume_of=split)


class SplitReportTests(unittest.TestCase):
    def build(self, root):
        return rep.build(root, dict(roll12strategy=f'runs/{STUDY}-roll12strategy', roll12split=f'runs/{STUDY}-roll12split'))

    def test_full_study(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
        A, B = s['arms']['roll12strategy'], s['arms']['roll12split']
        self.assertEqual((A['status'], A['solved'], A['wrong'], A['abstain'], A['server_tokens_per_case']), ('complete', 2, 0, 1, 400))
        self.assertEqual((A['wh_per_solved'], A['escalation_answered'], A['escalated_cases']), (1.5, 1, 2))
        self.assertEqual((B['status'], B['solved'], B['abstain'], B['server_tokens'], B['wh'], B['wall_seconds']),
                         ('complete', 3, 0, 1400, 3.0, 200))
        self.assertEqual(B['wh_per_solved'], 1.0)
        self.assertEqual(len(B['segments']), 2)
        self.assertEqual((B['escalation_answered'], B['escalation_solved'], B['escalation_wrong']), (2, 2, 0))
        pos = B['accepted_escalation_by_hint_position']
        self.assertEqual([(pos[p]['accepted'], pos[p]['correct']) for p in range(4)], [(1, 1), (1, 0), (1, 1), (0, 0)])
        self.assertEqual(s['paired'], dict(cases=3, split_only=1, strategy_only=0, sign_test_p=1.0))
        self.assertEqual(s['decision'], dict(zero_wrong=True, solved_at_least_default=True,
                                             escalation_answers_at_least_default=True, adopt_roll12split=True))
        self.assertTrue(s['frozen_rule'].startswith('roll12split becomes'))
        self.assertIn('flush_caches ignores the ssh exit status', s['disclosure'])
        self.assertIn('| roll12split | complete | 3 |', md)
        self.assertIn('## Disclosures', md)

    def test_rule_on_unrounded_values_and_failures(self):
        s = dict(arms=dict(roll12strategy=dict(status='complete', solved=30, escalation_answered=5),
                           roll12split=dict(status='complete', solved=30, wrong=0, wrong_all_attempts=0, escalation_answered=5)))
        self.assertTrue(rep.decision(s)['adopt_roll12split'])
        s['arms']['roll12split'].update(wrong_all_attempts=1)
        self.assertFalse(rep.decision(s)['adopt_roll12split'])
        s['arms']['roll12split'].update(wrong_all_attempts=0, solved=29)
        self.assertFalse(rep.decision(s)['solved_at_least_default'])
        s['arms']['roll12split'].update(solved=30, escalation_answered=4)
        self.assertFalse(rep.decision(s)['escalation_answers_at_least_default'])

    def test_wrong_answer_blocks_adoption(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, split_rows=[row('t0', 'roll12split', 1), row('t1', 'roll12split', 4, solved=False, wrong=True),
                                    row('t2', 'roll12split', 6)], with_resume=False)
            s = self.build(root)
        self.assertEqual(s['arms']['roll12split']['wrong'], 1)
        self.assertFalse(s['decision']['adopt_roll12split'])

    def test_superseded_wrong_attempt_blocks_adoption(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # t2 first attempt: answered WRONG in an infra-faulted run; the resume answers it correctly
            study(root, split_rows=[row('t0', 'roll12split', 1), row('t1', 'roll12split', 4, esc=1),
                                    row('t2', 'roll12split', 0, solved=False, wrong=True, infra=1)])
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
        B = s['arms']['roll12split']
        self.assertEqual((B['status'], B['wrong'], B['wrong_all_attempts']), ('complete', 0, 1))
        self.assertFalse(s['decision']['zero_wrong'])
        self.assertFalse(s['decision']['adopt_roll12split'])
        self.assertEqual([(w['dir'], w['server_tokens'], w['superseded_cases']) for w in B['wasted_work']],
                         [(f'{STUDY}-roll12split', 1000, [['t2', 1]])])
        self.assertIn('wasted segment', md)
        self.assertIn('escalation agent runs on the node of the agent whose end freed its slot', md)

    def test_caseless_segment_is_wasted_work_and_needs_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            seg = root / 'runs' / f'{STUDY}-roll12split-resume2'  # a failed start: accounting, no case rows
            seg.mkdir()
            plan = json.loads((root / rep.PLAN).read_text())
            (seg / 'metadata.json').write_text(json.dumps(dict(protocol=plan, policies=['roll12split'],
                                                               resume=dict(resumed_from='x'))))
            (seg / 'arm_accounting.json').write_text(json.dumps(acct(40, wh=0.2)))
            s = self.build(root)
            B = s['arms']['roll12split']
            self.assertEqual((B['status'], B['server_tokens']), ('complete', 1440))
            self.assertEqual([(w['dir'], w['server_tokens'], w['no_case_rows'], w['superseded_cases']) for w in B['wasted_work']],
                             [(f'{STUDY}-roll12split', 1000, False, [['t2', 1]]),
                              (f'{STUDY}-roll12split-resume2', 40, True, [])])
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            self.assertIn('resume2: server tokens 40', (root / 'results' / STUDY / 'REPORT.md').read_text())
            (seg / 'metadata.json').unlink()
            s = self.build(root)
        self.assertEqual(s['arms']['roll12split']['status'], 'incomplete')
        self.assertIn('resume2: no metadata.json with the embedded plan', ' '.join(s['arms']['roll12split']['reasons']))
        self.assertTrue(s['decision'].startswith('incomplete'))

    def test_both_arms_must_embed_the_frozen_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            meta = root / 'runs' / f'{STUDY}-roll12strategy' / 'metadata.json'
            m = json.loads(meta.read_text())
            m['protocol']['seed_offsets']['roll12strategy'] = 1
            meta.write_text(json.dumps(m))
            s = self.build(root)
        self.assertEqual(s['arms']['roll12strategy']['status'], 'incomplete')
        self.assertIn('embedded plan differs', ' '.join(s['arms']['roll12strategy']['reasons']))
        self.assertEqual(s['arms']['roll12split']['status'], 'complete')
        self.assertTrue(s['decision'].startswith('incomplete'))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            (root / rep.PLAN).unlink()
            self.assertTrue(self.build(root)['decision'].startswith('incomplete'))

    def test_missing_unresolved_and_invalid_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, with_split=False)
            s = self.build(root)
        self.assertEqual(s['arms']['roll12split']['status'], 'not run')
        self.assertTrue(s['decision'].startswith('incomplete'))
        self.assertNotIn('paired', s)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, with_resume=False)  # t2 still infra
            s = self.build(root)
        self.assertEqual(s['arms']['roll12split']['status'], 'incomplete')
        self.assertIn('unresolved', ' '.join(s['arms']['roll12split']['reasons']))
        self.assertTrue(s['decision'].startswith('incomplete'))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            f = root / 'runs' / f'{STUDY}-roll12split-resume1' / 'arm_accounting.json'
            rec = json.loads(f.read_text())
            rec['server']['per_node']['03'] = dict(generation_tokens=0, decode_tokens=50, requests=2)
            f.write_text(json.dumps(rec))
            s = self.build(root)
        self.assertEqual(s['arms']['roll12split']['status'], 'incomplete')
        self.assertIsNone(s['arms']['roll12split']['server_tokens'])
        self.assertTrue(s['decision'].startswith('incomplete'))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            (root / 'runs' / f'{STUDY}-roll12strategy' / 'arm_accounting.json').unlink()
            s = self.build(root)
        self.assertEqual(s['arms']['roll12strategy']['status'], 'incomplete')
        self.assertIn('no arm_accounting.json', ' '.join(s['arms']['roll12strategy']['reasons']))


if __name__ == '__main__':
    unittest.main()
