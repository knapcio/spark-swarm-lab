"""Offline tests for inkling/report_aot.py on synthetic run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_aot as rep  # noqa: E402
from test_report_relay_swarm import acct, write_run  # noqa: E402

STUDY = rep.STUDY
TASKS = [dict(id=f't{i}', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822) for i in range(5)]


def row(task, slot=None, solved=True, wrong=False):
    answered = slot is not None
    agent = dict(slot=slot if answered else 0, plan=None, verdict=True if answered else None, verifier_solved=solved,
                 started=True, cancelled=False, tokens=10)
    return dict(task_id=task, seed=1, policy='roll12wide', answered=answered, solved=answered and solved,
                wrong=answered and wrong, infra=0, selected_slot=slot, agents=[agent])


def study(root, a_rows=None, p_tokens=1000, a_tokens=1100, a_tasks=5):
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS)))
    (root / 'data_a.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS[:a_tasks])))
    plans = {}
    for k, variant in (('P', 'xl_forced_original'), ('A', 'xl_aot')):
        data = 'data_a.json' if k == 'A' and a_tasks != 5 else 'data.json'
        plans[k] = dict(study=f'{STUDY}-{k.lower()}', dataset=str(root / data), dataset_protocol='p',
                        split='evaluation', tasks=a_tasks if k == 'A' else 5, seeds=[1], policies=['roll12wide'], agent_variant=variant,
                        seed_offsets=dict(roll12wide=21400), decision_rule='AoT adopted if ...')
        (root / rep.ARMS[k]['plan']).write_text(json.dumps(plans[k]))
    write_run(root / rep.ARMS['P']['dir'], plans['P'], 'roll12wide',
              [row('t0', 0), row('t1', 2), row('t2'), row('t3'), row('t4')], acct(p_tokens, prompt=10000, prefill=3000))
    a_dir = root / rep.ARMS['A']['dir']
    write_run(a_dir, plans['A'], 'roll12wide',
              a_rows or [row('t0', 0), row('t1', 2), row('t2', 1), row('t3', 5), row('t4', 3)],
              acct(a_tokens, prompt=40000, prefill=12000))
    (a_dir / 'agents').mkdir(exist_ok=True)
    for i, (slot, facts) in enumerate(((0, 2), (2, 0), (1, 3))):
        summary = dict(rounds=[dict(round=1, solved=facts, contracted=True)] if facts else [dict(round=1, stop='unparsed')],
                       facts=facts, contracted=bool(facts))
        (a_dir / 'agents' / f't{i}-s1-roll12wide-a{slot}.jsonl').write_text(json.dumps(dict(type='puzzle_end', aot=summary)) + '\n')


class AotReportTests(unittest.TestCase):
    def build(self, root):
        return rep.build(root, {k: v['dir'] for k, v in rep.ARMS.items()})

    def test_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
        self.assertEqual((s['arms']['P']['solved'], s['arms']['A']['solved']), (2, 5))
        self.assertEqual(s['decision'], dict(zero_wrong=True, solved_at_least_plain_plus_3=True,
                                             tokens_at_most_110pct=True, AoT_adopted=True))
        self.assertEqual(s['paired'], dict(cases=5, aot_only=3, plain_only=0, sign_test_p=0.25))
        m = s['mechanism']
        self.assertEqual((m['agents'], m['with_facts'], m['facts'], m['round1_unparsed'], m['no_summary']), (3, 2, 5, 1, 2))
        self.assertIn('qixucen/atom', md)

    def test_rules_are_exact_and_strict(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, a_tokens=1101)  # 1.101 x plain
            s = self.build(root)
        self.assertFalse(s['decision']['tokens_at_most_110pct'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, a_rows=[row('t0', 0), row('t1', 2), row('t2', 1), row('t3', 5), row('t4')])  # +2 only
            self.assertFalse(self.build(root)['decision']['solved_at_least_plain_plus_3'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, a_rows=[row('t0', 0), row('t1', 2), row('t2', 1), row('t3', 5), row('t4', 3, solved=False, wrong=True)])
            self.assertFalse(self.build(root)['decision']['AoT_adopted'])

    def test_pairing_must_be_complete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # A ran a smaller corpus to completion: both arms complete, pairing is not
            study(root, a_tasks=4, a_rows=[row('t0', 0), row('t1', 2), row('t2', 1), row('t3', 5)])
            s = self.build(root)
        self.assertEqual((s['arms']['P']['status'], s['arms']['A']['status']), ('complete', 'complete'))
        self.assertTrue(s['decision'].startswith('incomplete'), s['decision'])
        self.assertIn('pairing: frozen plans differ', s['decision'])
        self.assertIn('case sets differ', s['decision'])
        empty = dict(rows={}, arm=dict(latest={}))
        self.assertIn('no paired cases', rep.pairing(Path('/nonexistent'), dict(P=empty, A=empty)))
        self.assertTrue(rep.decision(dict(P=dict(status='complete'), A=dict(status='complete')),
                                     ['no paired cases']).startswith('incomplete'))

    def test_transport_retries_are_listed_per_arm(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            trace = root / rep.ARMS['A']['dir'] / 'agents' / 't3-s1-roll12wide-a5.jsonl'
            trace.write_text(''.join(json.dumps(e) + '\n' for e in (
                dict(type='request_retry', lost_completion_tokens=40), dict(type='request_retry_aborted'),
                dict(type='request_retry', lost_completion_tokens=2))))
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
        self.assertEqual(s['arms']['A']['transport_retries'], dict(retries=2, lost_completion_tokens=42, retries_not_sent=1))
        self.assertEqual(s['arms']['P']['transport_retries'], dict(retries=0, lost_completion_tokens=0, retries_not_sent=0))
        self.assertIn('Transport retries per arm', md)
        self.assertIn('Asymmetry', md)

    def test_each_arm_must_embed_its_own_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            (root / rep.ARMS['A']['plan']).write_text((root / rep.ARMS['P']['plan']).read_text())
            s = self.build(root)
        self.assertEqual(s['arms']['A']['status'], 'incomplete')
        self.assertTrue(s['decision'].startswith('incomplete'))


if __name__ == '__main__':
    unittest.main()
