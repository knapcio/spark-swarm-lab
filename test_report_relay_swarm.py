"""Offline tests for inkling/report_relay_swarm.py on synthetic run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_relay_swarm as rep  # noqa: E402

STUDY = 'swarm-relay-hard19-v1'
TASKS = [dict(id=f't{i}', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822) for i in range(3)]


def agent(slot, verdict=None, solved=False, **extra):
    return dict(dict(slot=slot, plan={'moves': [1]} if verdict is not None else None, verdict=verdict,
                     verifier_solved=solved, started=True, cancelled=False, tokens=10), **extra)


def row(task, policy, slot=None, solved=True, wrong=False, relay_source=None, infra=0):
    answered = slot is not None
    agents = [agent(slot, True, solved, relay_source_slot=relay_source)] if answered else [agent(0)]
    return dict(task_id=task, seed=1, policy=policy, answered=answered, solved=answered and solved,
                wrong=answered and wrong, infra=infra, selected_slot=slot, agents=agents)


def acct(tokens, prompt=None, prefill=None, wall=100, wh=1.0):
    nodes = ('01', '02', '03', '04')
    start = datetime(2026, 11, 24, tzinfo=timezone.utc)
    total = dict(generation_tokens=tokens)
    if prompt is not None:
        total['prompt_tokens'] = prompt
    if prefill is not None:
        total['prefill_compute_tokens'] = prefill
    return dict(protocol='swarm-arm-accounting-v1', runner_wall_seconds=round(wall, 1), runner_exit=0, idle_after=True,
                before=dict(utc=start.isoformat(), nodes={n: dict(generation_tokens=0.0) for n in nodes}),
                after=dict(utc=(start + timedelta(seconds=wall)).isoformat(), nodes={n: dict(generation_tokens=1.0) for n in nodes}),
                server=dict(total=total, per_node={n: dict(generation_tokens=tokens / 4, decode_tokens=tokens / 4, requests=3,
                                                           prompt_tokens=(prompt or 0) / 4, prefill_compute_tokens=(prefill or 0) / 4)
                                                   for n in nodes}),
                energy=dict(total_wh=wh) if wh is not None else dict(error='ssh down'))


def write_run(path, plan, policy, rows, record):
    path.mkdir(parents=True)
    (path / 'metadata.json').write_text(json.dumps(dict(protocol=plan, policies=[policy], resume=None)))
    (path / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (path / 'arm_accounting.json').write_text(json.dumps(record))


def study(root, rl_rows=None, rl_record=None):
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS)))
    plan = dict(study=STUDY, dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=3, seeds=[1],
                policies=list(rep.ARMS.values()), agent_variant='xl_forced_original',
                seed_offsets={p: 19400 for p in rep.ARMS.values()}, relay=dict(max_chars=12000),
                decision_rule='RL replaces G if ...')
    (root / rep.PLAN).write_text(json.dumps(plan))
    runs = root / 'runs'
    write_run(runs / f'{STUDY}-roll12cancel', plan, 'roll12cancel',
              [row('t0', 'roll12cancel', 0), row('t1', 'roll12cancel', 5), row('t2', 'roll12cancel')],
              acct(1200, prompt=30000, prefill=9000))
    write_run(runs / f'{STUDY}-roll12relay', plan, 'roll12relay',
              rl_rows or [row('t0', 'roll12relay', 0), row('t1', 'roll12relay', 6, relay_source=2),
                          row('t2', 'roll12relay', 9, relay_source=4)],
              rl_record or acct(1500, prompt=60000, prefill=21000, wall=110, wh=1.5))


class RelaySwarmReportTests(unittest.TestCase):
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
        G, RL = s['arms']['G'], s['arms']['RL']
        self.assertEqual([(a['status'], a['solved'], a['abstain']) for a in (G, RL)], [('complete', 2, 1), ('complete', 3, 0)])
        self.assertEqual((RL['generated_tokens'], RL['prompt_tokens'], RL['prefill_compute_tokens'], RL['total_compute_tokens']),
                         (1500, 60000, 21000, 22500))
        self.assertEqual((RL['total_compute_per_case'], RL['wh_per_solved'], RL['wall_seconds']), (7500, 0.5, 110))
        self.assertEqual((G['escalation_answered'], G['relayed_answered']), (1, 0))
        self.assertEqual((RL['escalation_answered'], RL['relayed_answered'], RL['relayed_solved']), (2, 2, 2))
        self.assertEqual(s['paired'], dict(cases=3, rl_only=1, g_only=0, sign_test_p=1.0))
        self.assertEqual(s['decision'], dict(zero_wrong=True, solved_at_least_G=True, escalation_answers_at_least_G=True,
                                             RL_replaces_G=True))
        self.assertIn('total compute/case', md)
        self.assertIn('never by content', md)
        self.assertIn('flush_caches ignores the ssh exit status', md)

    def test_rule_failures(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, rl_rows=[row('t0', 'roll12relay', 0), row('t1', 'roll12relay', 6, solved=False, wrong=True, relay_source=1),
                                 row('t2', 'roll12relay')])
            s = self.build(root)
        self.assertEqual(s['decision']['zero_wrong'], False)
        self.assertFalse(s['decision']['RL_replaces_G'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, rl_rows=[row('t0', 'roll12relay', 0), row('t1', 'roll12relay', 2), row('t2', 'roll12relay')])
            s = self.build(root)
        self.assertFalse(s['decision']['escalation_answers_at_least_G'])

    def test_missing_input_counter_makes_the_arm_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, rl_record=acct(1500, prompt=60000, prefill=None))
            s = self.build(root)
        self.assertEqual(s['arms']['RL']['status'], 'incomplete')
        self.assertIn('prefill_compute_tokens missing', ' '.join(s['arms']['RL']['reasons']))
        self.assertIsNone(s['arms']['RL']['total_compute_tokens'])
        self.assertTrue(s['decision'].startswith('incomplete'))

    def test_zero_input_counter_on_an_active_node_and_missing_wh(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec = acct(1500, prompt=60000, prefill=21000)
            rec['server']['per_node']['03']['prefill_compute_tokens'] = 0
            study(root, rl_record=rec)
            s = self.build(root)
        self.assertEqual(s['arms']['RL']['status'], 'incomplete')
        self.assertIn('node 03 shows activity but prompt/prefill tokens are 0', ' '.join(s['arms']['RL']['reasons']))
        self.assertTrue(s['decision'].startswith('incomplete'))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, rl_record=acct(1500, prompt=60000, prefill=21000, wh=None))
            s = self.build(root)
        self.assertEqual(s['arms']['RL']['status'], 'incomplete')
        self.assertIn('Wh', ' '.join(s['arms']['RL']['reasons']))

    def test_missing_arm(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            import shutil
            shutil.rmtree(root / 'runs' / f'{STUDY}-roll12relay')
            s = self.build(root)
        self.assertEqual(s['arms']['RL']['status'], 'not run')
        self.assertNotIn('paired', s)
        self.assertTrue(s['decision'].startswith('incomplete'))


if __name__ == '__main__':
    unittest.main()
