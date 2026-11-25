"""Offline tests for inkling/report_aot_coding.py on synthetic coding run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_aot_coding as rep  # noqa: E402
from test_report_relay_swarm import acct  # noqa: E402

STUDY = rep.STUDY
TASKS = [dict(id=f't{i}', split='evaluation') for i in range(4)] + [dict(id='x', split='train')]
SEEDS = [1, 2]
CASES = [(f't{i}', s) for s in SEEDS for i in range(4)]  # 8 cases


def plan(variant, **over):
    p = dict(protocol='coding-agents-v1', status='FROZEN', source_revision='abc', source_path='.runtime/src',
             limits=dict(per_agent_completion_tokens=32768), scheduling=dict(concurrent_agents_per_node=20),
             runner='run_coding_earlystop.py', study=f'{STUDY}-{variant}', agent_variants=[variant] * 8,
             agent_seed_offset=8700, matrix=dict(tasks='corpus.json', split='evaluation', tasks_count=4, seeds=SEEDS),
             serving=dict(model='m'), early_stop='first_feedback_pass_in_time', rolling=dict(width=2),
             decision_rule='AoT adopted if ...')
    p.update(over)
    return p


def agent_row(d, task, seed, agent, feedback, holdout, aot=None):
    events = d / f'{task}-s{seed}-a{agent}.jsonl'
    end = dict(type='puzzle_end', feedback_pass=feedback, holdout_pass=holdout)
    if aot is not None:
        end['aot'] = aot
    events.write_text(json.dumps(dict(type='request_end')) + '\n' + json.dumps(end) + '\n')
    return dict(task_id=task, seed=seed, agent=agent, events=f'/elsewhere/{events.name}', controller_error=None,
                malformed_lines=0, infrastructure_failures=0, returncode=0, controller_stop=False, deadline=False, calls=1,
                unfinished_calls=0, status='complete', feedback_pass=feedback, holdout_pass=holdout, cancelled=False,
                completion_tokens=100)


def write_arm(root, k, p, outcomes, tokens, aot=False):
    """outcomes: {case: 'solved' | 'wrong' | 'none'} for every case written (missing -> not in the run)."""
    d = root / rep.ARMS[k]['dir']
    d.mkdir(parents=True)
    (root / rep.ARMS[k]['plan']).write_text(json.dumps(p))
    summary, cases = [], []
    for (task, seed), out in outcomes.items():
        summary.append(agent_row(d, task, seed, 0, out != 'none', out == 'solved',
                                 dict(rounds=[dict(round=1, solved=2, contracted=True)], facts=2, contracted=True)
                                 if aot and out == 'solved' else dict(rounds=[dict(round=1, stop='unparsed')], facts=0,
                                                                      contracted=False) if aot else None))
        cases.append(dict(task_id=task, seed=seed, answered=out != 'none', solved=out == 'solved',
                          winner_agent=0 if out != 'none' else None))
    (d / 'summary.json').write_text(json.dumps(summary))
    (d / 'cases.json').write_text(json.dumps(cases))
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=p, completed_utc='2026-11-26T01:00:00+00:00', errors=[],
                                                     source_changed_during_run=False)))
    (d / 'arm_accounting.json').write_text(json.dumps(acct(tokens, prompt=10000, prefill=3000)))
    return d


def study(root, p_out=None, a_out=None, p_tokens=1000, a_tokens=1100, a_plan=None):
    (root / 'corpus.json').write_text(json.dumps(dict(tasks=TASKS)))
    p_out = p_out or {c: ('solved' if i < 3 else 'wrong' if i == 3 else 'none') for i, c in enumerate(CASES)}
    a_out = a_out or {c: ('solved' if i < 6 else 'wrong' if i == 6 else 'none') for i, c in enumerate(CASES)}
    write_arm(root, 'P', plan('code_xl'), p_out, p_tokens)
    write_arm(root, 'A', a_plan or plan('code_aot'), a_out, a_tokens, aot=True)


class CodingAotReportTests(unittest.TestCase):
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
        P, A = s['arms']['P'], s['arms']['A']
        self.assertEqual((P['status'], A['status']), ('complete', 'complete'), (P.get('reasons'), A.get('reasons')))
        self.assertEqual((P['solved'], P['wrong'], A['solved'], A['wrong']), (3, 1, 6, 1))
        self.assertEqual(s['decision'], dict(solved_at_least_plain_plus_3=True, wrong_at_most_plain=True,
                                             tokens_at_most_110pct=True, AoT_adopted=True))
        self.assertEqual(s['paired'], dict(cases=8, aot_only=3, plain_only=0, sign_test_p=0.25))
        m = s['mechanism']
        self.assertEqual((m['agents'], m['with_facts'], m['facts'], m['winners_with_facts'], m['round1_unparsed']),
                         (8, 6, 12, 6, 2))
        self.assertEqual(A['transport_retries'], dict(retries=0, retries_not_sent=0))
        self.assertIn('no completion retry in either variant', md)

    def test_rules_are_exact_and_strict(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, a_tokens=1101)
            self.assertFalse(self.build(root)['decision']['tokens_at_most_110pct'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # +2 only
            study(root, a_out={c: ('solved' if i < 5 else 'wrong' if i == 5 else 'none') for i, c in enumerate(CASES)})
            self.assertFalse(self.build(root)['decision']['solved_at_least_plain_plus_3'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # +3 solved but 2 wrong vs 1
            study(root, a_out={c: ('solved' if i < 6 else 'wrong') for i, c in enumerate(CASES)})
            s = self.build(root)
            self.assertEqual((s['decision']['wrong_at_most_plain'], s['decision']['AoT_adopted']), (False, False))

    def test_pairing_must_be_complete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # A ran another seed set to completion: each arm complete, pairing not
            seeds = [1, 3]
            a_cases = [(f't{i}', s) for s in seeds for i in range(4)]
            study(root, a_out={c: 'solved' for c in a_cases},
                  a_plan=plan('code_aot', matrix=dict(tasks='corpus.json', split='evaluation', tasks_count=4, seeds=seeds)))
            s = self.build(root)
        self.assertEqual((s['arms']['P']['status'], s['arms']['A']['status']), ('complete', 'complete'))
        self.assertTrue(s['decision'].startswith('incomplete'))
        self.assertIn("frozen plans differ in ['matrix']", s['decision'])
        self.assertIn('case sets differ', s['decision'])
        empty = dict(plan=plan('code_xl'), cases={})
        self.assertIn('no paired cases', rep.pairing(dict(P=empty, A=dict(empty, plan=plan('code_aot')))))

    def test_arm_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # a missing case
            study(root, a_out={c: 'solved' for c in CASES[:-1]})
            s = self.build(root)
            self.assertIn('1 missing', ' '.join(s['arms']['A']['reasons']))
            self.assertTrue(s['decision'].startswith('incomplete'))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # A embeds the wrong plan / not R2 / mixed variants
            study(root)
            (root / rep.ARMS['A']['plan']).write_text(json.dumps(plan('code_aot', rolling=dict(width=1))))
            reasons = ' '.join(self.build(root)['arms']['A']['reasons'])
            self.assertIn('embedded plan differs', reasons)
            self.assertIn('not R2', reasons)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, a_plan=plan('code_aot', agent_variants=['code_aot'] * 7 + ['code_xl']))
            self.assertIn('expected only code_aot', ' '.join(self.build(root)['arms']['A']['reasons']))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # an operational fault, a retry event, a dirty accounting record
            study(root)
            a_dir = root / rep.ARMS['A']['dir']
            rows = json.loads((a_dir / 'summary.json').read_text())
            rows[0]['infrastructure_failures'] = 1
            (a_dir / 'summary.json').write_text(json.dumps(rows))
            with open(a_dir / 't1-s1-a0.jsonl', 'a') as f:
                f.write(json.dumps(dict(type='request_retry', lost_completion_tokens=3)) + '\n')
            record = json.loads((a_dir / 'arm_accounting.json').read_text())
            record.update(runner_exit=1, idle_after=False)
            (a_dir / 'arm_accounting.json').write_text(json.dumps(record))
            reasons = ' '.join(self.build(root)['arms']['A']['reasons'])
            for text in ('operational fault', 'transport retry events found', 'runner exit 1', 'idle_after'):
                self.assertIn(text, reasons)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            (root / rep.ARMS['P']['dir'] / 'metadata.json').write_text(json.dumps(dict(protocol=plan('code_xl'))))
            self.assertIn('not completed cleanly', ' '.join(self.build(root)['arms']['P']['reasons']))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            s = self.build(root)
            self.assertEqual(s['arms']['P']['status'], 'not run')
            self.assertTrue(s['decision'].startswith('incomplete'))


if __name__ == '__main__':
    unittest.main()
