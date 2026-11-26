"""Offline tests for inkling/report_collab_screen.py and inkling/collab_plans.py on synthetic runs (no model calls)."""
import hashlib
import json
import re
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import collab_plans as cp  # noqa: E402
import report_collab_screen as rep  # noqa: E402

ARMS = ["D'", "C'", "C'div"]
PROSE = 'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau'


def s1_plan(n=6):
    cases = [dict(case_id=f'k{i}', cohort='primary' if i < n else 'extension', puzzle_key=f'p{i % n}')
             for i in range(n + 2)]
    return dict(screen='s1', study='collab-s1-test', arm_order=ARMS,
                arms={"D'": dict(protocol=False), "C'": dict(protocol=True), "C'div": dict(protocol=True)},
                protocol_constants=dict(marks=[8192, 16384, 24576]), cases=cases)


def agent(text, t0=0.0, t1=10.0, prefix='', notes=(), submissions=()):
    return dict(prefix_text=prefix, segments=[dict(think_before=8192, tokens=8192, text=text, t0=t0, t_first=t0,
                                                   t1=t1)],
                notes=list(notes), reads=[], submissions=list(submissions))


def write_s1(d, plan, rows, records=None):
    d.mkdir(parents=True)
    (d / 'metadata.json').write_text(json.dumps(dict(plan=plan)))
    (d / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    recs = records or [dict(agent(PROSE + f' {r["case_id"]} {r["arm"]} {i}'), case_id=r['case_id'], arm=r['arm'],
                            slot=i) for r in rows for i in range(4)]
    (d / 'records.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in recs))


def row(case, arm, rescued=False, wrong=0, accepted=None, status='complete', puzzle=None):
    return dict(case_id=case, arm=arm, puzzle=puzzle or 'p' + case[1:], status=status, rescued=rescued,
                answered=rescued or wrong > 0, wrong=wrong, accepted_agents=accepted if accepted is not None else int(rescued),
                generated_tokens=100, wall_s=1.0, checkpoints=3, winner_where='segment' if rescued else None)


class S1ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, c_rescued, d_rescued, div_rescued=0, c_wrong=0, n=6):
        out = []
        for i in range(n):
            out += [row(f'k{i}', "D'", rescued=i < d_rescued), row(f'k{i}', "C'", rescued=i < c_rescued,
                                                                    wrong=c_wrong if i == n - 1 else 0),
                    row(f'k{i}', "C'div", rescued=i < div_rescued)]
        return out

    def test_pass_grey_stop(self):
        plan = s1_plan()
        write_s1(self.root / 'pass', plan, self.rows(5, 1))
        r = rep.build(plan, [self.root / 'pass'])
        self.assertEqual(r['decision'], 'PASS')
        self.assertEqual(r['verdicts']["C'"]['verdict'], 'PASS')
        self.assertEqual(r['verdicts']["C'div"]['verdict'], 'STOP')
        self.assertEqual(r['verdicts']["C'"]['paired_puzzles']['protocol_only'], 4)
        write_s1(self.root / 'grey', plan, self.rows(3, 1))
        self.assertEqual(rep.build(plan, [self.root / 'grey'])['decision'], 'GREY')
        write_s1(self.root / 'wrong', plan, self.rows(5, 1, c_wrong=1))
        r = rep.build(plan, [self.root / 'wrong'])
        self.assertEqual(r['decision'], 'STOP')
        self.assertFalse(r['verdicts']["C'"]['rules']['zero_wrong'])

    def test_incomplete_missing_job_plan_mismatch_and_rerun_merge(self):
        plan = s1_plan()
        rows = self.rows(5, 1)
        rows[1]['status'] = 'infrastructure'
        write_s1(self.root / 'a', plan, rows)
        r = rep.build(plan, [self.root / 'a'])
        self.assertEqual(r['status'], 'incomplete')
        write_s1(self.root / 'b', plan, [row('k0', "C'", rescued=True)])
        self.assertEqual(rep.build(plan, [self.root / 'a', self.root / 'b'])['decision'], 'PASS')
        other = dict(plan, study='changed')
        write_s1(self.root / 'c', other, self.rows(5, 1))
        self.assertIn('embedded plan differs', rep.build(plan, [self.root / 'c'])['decision'])
        write_s1(self.root / 'd', plan, self.rows(5, 1)[:-1])
        self.assertIn('missing', rep.build(plan, [self.root / 'd'])['decision'])

    def test_pooled_extension_rule(self):
        plan = s1_plan(n=6)
        rows = self.rows(3, 1)
        rows += [row('k6', a, rescued=a == "C'", puzzle='p0') for a in ARMS]
        rows += [row('k7', a, rescued=a == "C'", puzzle='p5') for a in ARMS]
        write_s1(self.root / 'x', plan, rows)
        r = rep.build(plan, [self.root / 'x'])
        self.assertTrue(r['pooled'])
        self.assertEqual(r['verdicts']["C'"]['required_lead'], 6)
        self.assertEqual(r['arms']["C'"]['rescued_puzzles'], 4)  # p0 counted once, p5 rescued by its second case
        self.assertEqual(r['decision'], 'STOP')

    def test_novelty_sees_copied_peer_text_and_time(self):
        a = agent('one two three four five six seven eight', t0=0, t1=10)
        b = agent('one two three four five six seven eight', t0=20, t1=30)  # written after a finished
        c = agent('zz yy xx ww vv uu tt ss', t0=0, t1=10)
        values = rep.novelty([a, b, c], [8192, 16384, 24576])
        self.assertEqual(values, [Fraction(1), Fraction(0), Fraction(1)])
        early = agent('one two three four five six seven eight', t0=-5, t1=1)
        self.assertEqual(rep.novelty([a, early], [])[1], Fraction(1))  # nothing of a was written when early started
        prefix = agent('q w e r t y', prefix='q w e r t y u')
        self.assertEqual(rep.novelty([prefix, agent('q w e r t y')], [])[1], Fraction(0))  # peers' prefixes count
        noted = agent('m n o p q r s', notes=[dict(text='m n o p q r s', t=-1.0)])
        self.assertEqual(rep.novelty([noted, agent('m n o p q r s')], [])[1], Fraction(0))  # peers' notes count

    def test_split_segment_at_marks(self):
        seg = dict(think_before=8192, tokens=16384, text='a' * 100 + 'b' * 100, t0=0.0, t_first=0.0, t1=20.0)
        pieces = rep.split_segment(seg, [8192, 16384, 24576])
        self.assertEqual([p['text'] for p in pieces], ['a' * 100, 'b' * 100])
        self.assertEqual([p['t_start'] for p in pieces], [0.0, 10.0])


class S0ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return dict(screen='s0', study='collab-s0-test', checks=cp.S0_CHECKS, answer_at_once_tokens=512,
                    groups=[dict(group_id='g', members=[dict(slot=0), dict(slot=1)])])

    def rec(self, slot, focus, result, cont_text, closed_at=None, kind='note', tokens=100):
        return dict(group_id='g', slot=slot, family='arith', status='complete', prefix_identical=True,
                    continuation_prefix_identical=True, accepted=False,
                    note=dict(kind=kind, tokens=tokens, ttft_s=0.5, latency_s=4.0,
                              note=dict(focus=focus, results=[result], dead_ends=[], reviews=[]) if kind == 'note' else None),
                    continuation=dict(ttft_s=0.4, closed=closed_at is not None, closed_at_token=closed_at,
                                      thinking_text=cont_text),
                    prefix_text=PROSE, recorded_continuation_text='new words here only for the record now ok',
                    submissions=[])

    def write(self, plan, recs, prompt=1000, prefill=20):
        d = self.root / 'run'
        d.mkdir()
        (d / 'metadata.json').write_text(json.dumps(dict(plan=plan)))
        (d / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
        total = dict(prompt_tokens=prompt, prefill_compute_tokens=prefill, generation_tokens=1, requests=1)
        (d / 'summary.json').write_text(json.dumps(dict(phases=dict(board=dict(total=total)))))
        return d

    def test_pass_and_failures(self):
        plan = self.plan()
        recs = [self.rec(0, 'work backward from the target', '6*7=42 from the two largest', 'brand new thinking words '
                         'that never appeared anywhere before at all'),
                self.rec(1, 'try products of large numbers first', '12+30=42', 'other fresh words entirely new to '
                         'this stream and unseen')]
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertEqual(r['decision'], 'PASS', r)
        checks = {c['id']: c for c in r['checks']}
        self.assertEqual(checks['cached_share']['exact'], '49/50')
        self.assertEqual(checks['checkpoint_latency']['value'], 0.9)

    def test_stop_on_wrong_results_and_same_focus(self):
        plan = self.plan()
        recs = [self.rec(0, 'same focus line', '6*7=43', 'x y z w v u'), self.rec(1, 'same focus line', '2+2=5',
                                                                                  'x y z w v u')]
        r = rep.build(plan, [self.write(plan, recs, prompt=100, prefill=50)])
        self.assertEqual(r['decision'], 'STOP')
        self.assertIn('arith_results_correct', r['failed'])
        self.assertIn('focus_distinct', r['failed'])
        self.assertIn('cached_share', r['failed'])

    def test_fix_only_and_incomplete(self):
        plan = self.plan()
        recs = [self.rec(0, 'a b c', '1+1=2', 'p q r s t u v', kind='neither'),
                self.rec(1, 'd e f', '2+2=4', 'g h i j k l m', closed_at=10, tokens=900)]
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertIn('reply_parse', r['failed'])
        recs[0]['status'] = 'infrastructure'
        d = self.root / 'run'
        (d / 'records.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in recs))
        self.assertEqual(rep.build(plan, [d])['status'], 'incomplete')


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def trace(self, path, ids, variant='xl_forced_original', puzzle='2,3,7,9:5', extra=''):
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [dict(type='run_start', config=dict(puzzle=puzzle, variant=variant, seed=11)),
                dict(type='extra_prompt', text=extra),
                dict(type='request_start', stage='plan', request_id='r', prompt_ids_sha256='ps'),
                dict(type='request_end', stage='plan', request_id='r', token_ids=ids,
                     usage=dict(completion_tokens=len(ids)), finish_reason='length')]
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))

    def arm(self, name, cases):
        d = self.root / 'runs' / name
        rows = []
        for task, seed, spec in cases:
            agents = []
            for slot in range(4):
                kind = spec[slot] if slot < len(spec) else 'long'
                ids = [1] * (cp.CUT + 5) if kind != 'short' else [1] * 10
                if kind == 'closed':
                    ids[5] = cp.INKLING_CONTENT_TEXT
                self.trace(d / 'agents' / f'{task}-s{seed}-roll12cancel-a{slot}.jsonl', ids)
                agents.append(dict(slot=slot, verdict=kind == 'accepted', cancelled=kind == 'cancelled'))
            rows.append(dict(task_id=task, seed=seed, policy='roll12cancel', agents=agents, answered=False,
                             solved=False))
        d.mkdir(parents=True, exist_ok=True)
        (d / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))

    def test_s1_cohort_selection(self):
        a, b = cp.S1_ARMS[2], cp.S1_ARMS[3]  # the two hard-v20 arms share a corpus
        self.arm(a, [('t1', 2, ''), ('t1', 1, ''), ('t2', 1, ['accepted']), ('t3', 1, ['short']),
                     ('t4', 1, ['closed']), ('t5', 1, ['cancelled'])])
        self.arm(b, [('t1', 1, ''), ('t6', 2, '')])
        cases, skipped = cp.s1_cohort(self.root, arms=[a, b])
        got = [(k['run'], k['task_id'], k['seed'], k['cohort']) for k in cases]
        # primary: lowest seed per puzzle, ties to the arm listed first; then puzzle, seed, run order
        self.assertEqual(got, [(a, 't1', 1, 'primary'), (b, 't6', 2, 'primary'), (b, 't1', 1, 'extension'),
                               (a, 't1', 2, 'extension')])
        self.assertEqual(skipped, {'10 tokens <= cut': 1, 'thinking closed before the cut': 1})
        k = cases[0]
        self.assertEqual(k['case_id'], 'h20g-t1-s1')
        self.assertEqual(k['agents'][2]['agent_seed'], 1000 + cp.S1_SEED_OFFSET + 2)
        self.assertEqual(k['agents'][0]['prefix_ids_sha256'],
                         hashlib.sha256(json.dumps([1] * cp.CUT).encode()).hexdigest())
        self.assertEqual(k['agents'][0]['trace'], f'runs/{a}/agents/t1-s1-roll12cancel-a0.jsonl')

    def test_variant_and_extra_text_exclude(self):
        a = cp.S1_ARMS[0]
        self.arm(a, [('t1', 1, '')])
        self.trace(self.root / 'runs' / a / 'agents' / 't1-s1-roll12cancel-a3.jsonl', [1] * (cp.CUT + 5),
                   extra='Strategy hint: x')
        self.assertEqual(cp.s1_cohort(self.root, arms=[a])[1], {'extra prompt text': 1})

    def test_inkling_content_text_matches_the_shim(self):
        shim = (Path(__file__).resolve().parent / 'inkling' / 'shim.py').read_text()
        m = re.search(r'END_MESSAGE, MESSAGE_MODEL, CONTENT_TEXT = (\d+), (\d+), (\d+)', shim)
        self.assertEqual(int(m.group(3)), cp.INKLING_CONTENT_TEXT)

    def test_s0_coding_grouping(self):
        for run in cp.CODING_RUNS:
            d = self.root / 'runs' / run
            d.mkdir(parents=True)
            (d / 'metadata.json').write_text(json.dumps(dict(protocol=dict(matrix=dict(tasks='T', tests='H')))))
        specs = [('coding-v29-r2-v1', 'eva-a', 19, 6), ('coding-v29-r2-v1', 'eva-b', 19, 1),
                 ('coding-aot-v1-p', 'eva-c', 25, 2), ('coding-v29-r2-v1', 'eva-d', 20, 1)]
        for run, task, seed, n in specs:
            for agent in range(n):
                p = self.root / 'runs' / run / f'{task}-s{seed}-a{agent}-code_xl.jsonl'
                rows = [dict(type='run_start', config=dict(seed=5, variant='code_xl')),
                        dict(type='request_start', stage='code_propose', request_id='r', prompt_ids_sha256='x'),
                        dict(type='request_end', stage='code_propose', request_id='r', token_ids=[1] * 17000,
                             usage=dict(completion_tokens=17000))]
                p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        groups = cp.coding_streams(self.root)
        order = sorted(groups, key=lambda k: (-len(groups[k]), k[0], k[2], k[3]))
        self.assertEqual([(k[2], len(groups[k])) for k in order], [('eva-a', 6), ('eva-c', 2), ('eva-b', 1),
                                                                    ('eva-d', 1)])


if __name__ == '__main__':
    unittest.main()
