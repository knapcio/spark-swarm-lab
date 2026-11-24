"""Offline tests for inkling/report_generic_hard18.py on synthetic run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_generic_hard18 as rep  # noqa: E402

STUDY = 'swarm-generic-hard18-v1'
TASKS = [dict(id=f't{i}', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822) for i in range(3)]


def agent(slot, verdict=None, solved=False, **extra):
    return dict(dict(slot=slot, plan={'moves': [1]} if verdict is not None else None, verdict=verdict,
                     verifier_solved=solved, started=True, cancelled=False, tokens=10), **extra)


def row(task, policy, slot=None, solved=True, wrong=False, infra=0, agents=None, **extra):
    answered = slot is not None
    return dict(dict(task_id=task, seed=1, policy=policy, answered=answered, solved=answered and solved,
                     wrong=answered and wrong, infra=infra, selected_slot=slot,
                     agents=agents if agents is not None else ([agent(slot, True, solved)] if answered else [agent(0)])),
                **extra)


def acct(tokens, wall=100, wh=1.0):
    nodes = ('01', '02', '03', '04')
    return dict(protocol='swarm-arm-accounting-v1', runner_wall_seconds=wall, runner_exit=0, idle_after=True,
                before=dict(nodes={n: dict(generation_tokens=0.0) for n in nodes}),
                after=dict(nodes={n: dict(generation_tokens=tokens / 4) for n in nodes}),
                server=dict(total=dict(generation_tokens=tokens),
                            per_node={n: dict(generation_tokens=tokens / 4, decode_tokens=tokens / 4, requests=3) for n in nodes}),
                energy=dict(total_wh=wh))


def write_run(path, plan, policy, rows, tokens, wall=100, wh=1.0):
    path.mkdir(parents=True)
    (path / 'metadata.json').write_text(json.dumps(dict(protocol=plan, policies=[policy], resume=None)))
    (path / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (path / 'arm_accounting.json').write_text(json.dumps(acct(tokens, wall, wh)))


def study(root, gi_wall=105, with_gi=True, gi_rows=None):
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS)))
    plan = dict(study=STUDY, dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=3, seeds=[1],
                policies=list(rep.ARMS.values()), agent_variant='xl_forced_original',
                seed_offsets={p: 18400 for p in rep.ARMS.values()}, decision_rule='G replaces S if ...; GI replaces G if ...')
    (root / rep.PLAN).write_text(json.dumps(plan))
    runs = root / 'runs'
    write_run(runs / f'{STUDY}-roll12strategy', plan, 'roll12strategy',
              [row('t0', 'roll12strategy', 0), row('t1', 'roll12strategy', 5), row('t2', 'roll12strategy')], 1200)
    write_run(runs / f'{STUDY}-roll12cancel', plan, 'roll12cancel',
              [row('t0', 'roll12cancel', 0), row('t1', 'roll12cancel'), row('t2', 'roll12cancel', 6)], 1100)
    if not with_gi:
        return
    t1 = row('t1', 'roll12idle', 14, idle_phase=True, extra_agents=3,
             agents=[agent(s) for s in range(12)] + [agent(12, idle_occupancy_at_start=3), agent(13, idle_occupancy_at_start=5),
                                                     agent(14, True, True, idle_occupancy_at_start=4)])
    rows = gi_rows or [row('t0', 'roll12idle', 0, idle_phase=False, extra_agents=0), t1,
                       row('t2', 'roll12idle', 6, idle_phase=False, extra_agents=0)]
    write_run(runs / f'{STUDY}-roll12idle', plan, 'roll12idle', rows, 1500, wall=gi_wall, wh=1.5)


class GenericReportTests(unittest.TestCase):
    def build(self, root):
        return rep.build(root, {k: f'runs/{STUDY}-{p}' for k, p in rep.ARMS.items()})

    def test_full_study(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
        S, G, GI = (s['arms'][k] for k in ('S', 'G', 'GI'))
        self.assertEqual([(a['status'], a['solved'], a['abstain']) for a in (S, G, GI)],
                         [('complete', 2, 1), ('complete', 2, 1), ('complete', 3, 0)])
        self.assertEqual((GI['server_tokens_per_case'], GI['wh_per_solved']), (500, 0.5))
        self.assertEqual((GI['idle_phase_cases'], GI['extra_agents_total'], GI['extra_agents_per_idle_case']), (1, 3, [3]))
        self.assertEqual((GI['answered_by_extra'], GI['solved_by_extra'], GI['wrong_by_extra']), (1, 1, 0))
        self.assertEqual(GI['occupancy_at_start'], dict(n=3, median=4, max=5, histogram={'3': 1, '4': 1, '5': 1}))
        self.assertNotIn('extra_agents_total', G)
        self.assertEqual(s['paired']['G_vs_S'], dict(cases=3, first_only=1, second_only=1, sign_test_p=1.0))
        self.assertEqual(s['paired']['GI_vs_G'], dict(cases=3, first_only=1, second_only=0, sign_test_p=1.0))
        self.assertEqual(s['decisions']['G'], dict(zero_wrong=True, solved_within_noise=True, G_replaces_S=True))
        self.assertEqual(s['decisions']['GI'], dict(zero_wrong=True, solved_at_least_G=True, answered_by_extra_slot=True,
                                                    wall_at_most_110pct_of_G=True, GI_replaces_G=True))
        self.assertIn('| GI | roll12idle | complete | 3 | 3 |', md)
        self.assertIn('GI idle-capacity escalation', md)
        self.assertIn('never on elapsed time', md)
        self.assertIn('flush_caches ignores the ssh exit status', md)

    def test_wall_limit_is_unrounded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, gi_wall=110.0001)  # 1.100001 x G
            s = self.build(root)
        self.assertFalse(s['decisions']['GI']['wall_at_most_110pct_of_G'])
        self.assertFalse(s['decisions']['GI']['GI_replaces_G'])

    def test_gi_needs_an_extra_slot_answer_and_no_wrong(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, gi_rows=[row('t0', 'roll12idle', 0), row('t1', 'roll12idle', 9), row('t2', 'roll12idle', 6)])
            s = self.build(root)
        self.assertFalse(s['decisions']['GI']['answered_by_extra_slot'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, gi_rows=[row('t0', 'roll12idle', 0), row('t1', 'roll12idle', 14, solved=False, wrong=True),
                                 row('t2', 'roll12idle', 6)])
            s = self.build(root)
        self.assertEqual(s['arms']['GI']['wrong_all_attempts'], 1)
        self.assertFalse(s['decisions']['GI']['zero_wrong'])

    def test_rules_on_synthetic_values(self):
        arms = dict(S=dict(status='complete', solved=30), G=dict(status='complete', solved=28, wrong_all_attempts=0,
                                                                 wall_seconds=1000.0),
                    GI=dict(status='complete', solved=28, wrong_all_attempts=0, answered_by_extra=1, wall_seconds=1100.0))
        dec = rep.decisions(arms)
        self.assertTrue(dec['G']['G_replaces_S'] and dec['GI']['GI_replaces_G'])
        arms['G']['solved'] = 27
        self.assertFalse(rep.decisions(arms)['G']['G_replaces_S'])
        arms['GI']['wall_seconds'] = 1100.1  # 1.1001 x G
        self.assertFalse(rep.decisions(arms)['GI']['wall_at_most_110pct_of_G'])
        arms['GI'].update(wall_seconds=1000.0, solved=26)
        self.assertFalse(rep.decisions(arms)['GI']['solved_at_least_G'])

    def test_missing_or_incomplete_arms_block_only_their_rules(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, with_gi=False)
            s = self.build(root)
        self.assertEqual(s['arms']['GI']['status'], 'not run')
        self.assertTrue(s['decisions']['GI'].startswith('incomplete'))
        self.assertTrue(s['decisions']['G']['G_replaces_S'])
        self.assertNotIn('GI_vs_G', s['paired'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            f = root / rep.PLAN
            f.write_text(json.dumps(dict(json.loads(f.read_text()), note='amended')))
            s = self.build(root)
        self.assertTrue(all(s['arms'][k]['status'] == 'incomplete' for k in rep.ARMS))
        self.assertTrue(all(v.startswith('incomplete') for v in s['decisions'].values()))


if __name__ == '__main__':
    unittest.main()
