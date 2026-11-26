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
PROSE = ' '.join(f'w{i}' for i in range(40))
MARGINS = dict(primary_margin=4, grey_band=[2, 3], pooled_margin=6)


def s1_plan(n=6):
    cases = [dict(case_id=f'k{i}', cohort='primary' if i < n else 'extension', puzzle_key=f'p{i % n}',
                  agents=[dict(slot=s) for s in range(4)]) for i in range(n + 2)]
    return dict(screen='s1', study='collab-s1-test', arm_order=ARMS,
                arms={"D'": dict(protocol=False), "C'": dict(protocol=True), "C'div": dict(protocol=True)},
                decision_rule=dict(margins=MARGINS), cases=cases)


def seg(text, t0=0.0, t1=10.0, think_before=8192, tokens=8192, progress=None):
    return dict(think_before=think_before, tokens=tokens, thinking_tokens=tokens, text=text, t0=t0, t_first=t0,
                t1=t1, progress=progress if progress is not None else [(t1, tokens, len(text))])


def agent(text, t0=0.0, t1=10.0, prefix='', notes=(), submissions=()):
    return dict(prefix_text=prefix, segments=[seg(text, t0, t1)], notes=list(notes), reads=[],
                submissions=list(submissions))


def write_s1(d, plan, rows, records=None, cohort='primary', bypass=None):
    d.mkdir(parents=True)
    (d / 'metadata.json').write_text(json.dumps(dict(plan=plan, cohort=cohort, bypass=bypass or [])))
    (d / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    recs = records if records is not None else [
        dict(agent(PROSE + f' {r["case_id"]} {r["arm"]} {i}'), case_id=r['case_id'], arm=r['arm'], slot=i,
             status='complete') for r in rows for i in range(4)]
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

    def test_pass_grey_stop_with_plan_margins(self):
        plan = s1_plan()
        write_s1(self.root / 'pass', plan, self.rows(5, 1))
        r = rep.build(plan, [self.root / 'pass'])
        self.assertEqual(r['decision'], 'PASS')
        self.assertEqual((r['verdicts']["C'"]['verdict'], r['verdicts']["C'div"]['verdict']), ('PASS', 'STOP'))
        self.assertEqual(r['passing_arms'], ["C'"])
        self.assertEqual(r['verdicts']["C'"]['paired_puzzles']['protocol_only'], 4)
        write_s1(self.root / 'grey', plan, self.rows(3, 1))
        self.assertEqual(rep.build(plan, [self.root / 'grey'])['decision'], 'GREY')
        write_s1(self.root / 'wrong', plan, self.rows(5, 1, c_wrong=1))
        r = rep.build(plan, [self.root / 'wrong'])
        self.assertEqual(r['decision'], 'STOP')
        self.assertFalse(r['verdicts']["C'"]['rules']['zero_wrong'])
        strict = dict(plan, decision_rule=dict(margins=dict(primary_margin=5, grey_band=[3, 4], pooled_margin=7)))
        write_s1(self.root / 'strict', strict, self.rows(5, 1))
        self.assertEqual(rep.build(strict, [self.root / 'strict'])['decision'], 'GREY')

    def test_jobs_are_validated_as_units_and_reruns_merge_only_incomplete_jobs(self):
        plan = s1_plan()
        rows = self.rows(5, 1)
        rows[1]['status'] = 'infrastructure'
        write_s1(self.root / 'a', plan, rows)
        self.assertEqual(rep.build(plan, [self.root / 'a'])['status'], 'incomplete')
        write_s1(self.root / 'b', plan, [row('k0', "C'", rescued=True)])
        self.assertEqual(rep.build(plan, [self.root / 'a', self.root / 'b'])['decision'], 'PASS')
        write_s1(self.root / 'dup', plan, [row('k1', "D'")])  # k1:D' was already complete in a
        self.assertIn('complete in two', rep.build(plan, [self.root / 'a', self.root / 'b', self.root / 'dup'])['decision'])
        recs = [dict(agent(PROSE), case_id=r['case_id'], arm=r['arm'], slot=i, status='complete')
                for r in self.rows(5, 1) for i in range(4)][:-1]  # one agent record missing
        write_s1(self.root / 'units', plan, self.rows(5, 1), records=recs)
        self.assertIn('not complete as a unit', rep.build(plan, [self.root / 'units'])['decision'])
        write_s1(self.root / 'c', dict(plan, study='changed'), self.rows(5, 1))
        self.assertIn('embedded plan differs', rep.build(plan, [self.root / 'c'])['decision'])
        write_s1(self.root / 'd', plan, self.rows(5, 1)[:-1])
        self.assertIn('missing', rep.build(plan, [self.root / 'd'])['decision'])
        write_s1(self.root / 'bypass', plan, self.rows(5, 1), bypass=['no-source-check'])
        self.assertIn('bypassed', rep.build(plan, [self.root / 'bypass'])['decision'])

    def test_torn_lines_are_skipped_and_listed(self):
        plan = s1_plan()
        write_s1(self.root / 't', plan, self.rows(5, 1))
        with (self.root / 't' / 'records.jsonl').open('a') as f:
            f.write('{"torn": ')
        r = rep.build(plan, [self.root / 't'])
        self.assertEqual(r['decision'], 'PASS')
        self.assertEqual(len(r['torn_lines']), 1)

    def test_pooled_look_only_for_primary_grey_arms(self):
        plan = s1_plan(n=6)
        write_s1(self.root / 'p', plan, self.rows(3, 1, div_rescued=5))
        ext = [row('k6', a, rescued=a in ("C'", "C'div"), puzzle='p4') for a in ARMS]
        ext += [row('k7', a, rescued=a in ("C'", "C'div"), puzzle='p5') for a in ARMS]
        write_s1(self.root / 'e', plan, ext, cohort='extension')
        r = rep.build(plan, [self.root / 'p', self.root / 'e'])
        self.assertIn('--primary-verdicts', r['decision'])
        r = rep.build(plan, [self.root / 'p', self.root / 'e'], {"C'": 'GREY: run', "C'div": 'PASS'})
        self.assertTrue(r['pooled'])
        self.assertEqual(r['verdicts']["C'"]['required_lead'], 6)
        self.assertEqual(r['arms']["C'"]['rescued_puzzles'], 5)  # p4, p5 rescued by their extension cases
        self.assertEqual(r['verdicts']["C'"]['verdict'], 'STOP')
        self.assertTrue(r['verdicts']["C'div"]['verdict'].startswith('NOT ELIGIBLE'))

    def test_novelty_by_time_progress_and_peer_texts(self):
        a = agent(PROSE, t0=0, t1=10)
        b = agent(PROSE, t0=20, t1=30)  # written after a finished
        c = agent(' '.join(f'z{i}' for i in range(40)), t0=0, t1=10)
        self.assertEqual([v for v, _ in rep.novelty([a, b, c])], [Fraction(1), Fraction(0), Fraction(1)])
        early = agent(PROSE, t0=-5, t1=1)
        self.assertEqual([v for v, _ in rep.novelty([a, early])][1], Fraction(1))  # nothing of a written yet
        prefix = agent(PROSE, prefix=PROSE)
        self.assertEqual([v for v, _ in rep.novelty([prefix, agent(PROSE)])][1], Fraction(0))  # peers' prefixes
        noted = agent(PROSE, notes=[dict(text=PROSE, t=-1.0)])
        self.assertEqual([v for v, _ in rep.novelty([noted, agent(PROSE, t0=0)])][1], Fraction(0))  # peers' notes
        short = agent('a b c d e f')  # fewer than MIN_GRAMS distinct 5-grams: not counted
        self.assertEqual(rep.novelty([short, c]), [(Fraction(1), 8192)])

    def test_pieces_at_common_thinking_token_boundaries(self):
        text = 'a' * 100 + 'b' * 300
        s = seg(text, 0.0, 20.0, think_before=8192, tokens=16384,
                progress=[(5.0, 8192, 100), (20.0, 16384, 400)])  # uneven characters per token
        ps = rep.pieces(s)
        self.assertEqual([p['text'] for p in ps], ['a' * 100, 'b' * 300])
        self.assertEqual([p['t_start'] for p in ps], [0.0, 5.0])
        closed = dict(s, thinking_tokens=8192)  # a segment that closed: only its thinking tokens split
        self.assertEqual(len(rep.pieces(closed)), 1)


class S0ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return dict(screen='s0', study='collab-s0-test', checks=cp.S0_CHECKS, answer_at_once_tokens=512,
                    groups=[dict(group_id='g', members=[dict(slot=0), dict(slot=1)])])

    def rec(self, slot, focus, result, cont_text, closed_at=None, kind='note', tokens=100, located=True):
        return dict(group_id='g', slot=slot, family='arith', status='complete', prefix_identical=True,
                    continuation_prefix_identical=True, accepted=False, group_size=2,
                    note=dict(kind=kind, tokens=tokens, t0=10.0, t_first=10.5, t=14.0, finish_reason='stop',
                              note=dict(focus=focus, results=[result], dead_ends=[], reviews=[]) if kind == 'note' else None),
                    joins=[dict(terminated=True, terminator_overlap=2)],
                    continuation=dict(t0=20.0, t_first=20.4, closed=closed_at is not None or not located,
                                      closed_at_token=closed_at, close_located=located, thinking_text=cont_text),
                    prefix_text=PROSE, recorded_continuation_text='new words here only for the record now ok',
                    submissions=[])

    def write(self, plan, recs, per_node=None, preflight_ok=True, name='run'):
        d = self.root / name
        d.mkdir()
        (d / 'metadata.json').write_text(json.dumps(dict(plan=plan, bypass=[])))
        (d / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
        per_node = per_node or {'n0': dict(prompt_tokens=1000, prefill_compute_tokens=20, generation_tokens=1,
                                           requests=1),
                                'n1': dict(prompt_tokens=1000, prefill_compute_tokens=40, generation_tokens=1,
                                           requests=1)}
        (d / 'summary.json').write_text(json.dumps(dict(preflight=dict(arith=dict(ok=preflight_ok)),
                                                        phases=dict(board=dict(per_node=per_node)))))
        return d

    def good(self):
        return [self.rec(0, 'work backward from the target', '6*7=42 from the two largest', 'brand new thinking words '
                         'that never appeared anywhere before at all'),
                self.rec(1, 'try products of large numbers first', '12+30=42', 'other fresh words entirely new to '
                         'this stream and unseen')]

    def test_pass_with_raw_timing_and_lowest_node_cache(self):
        plan = self.plan()
        r = rep.build(plan, [self.write(plan, self.good())])
        self.assertEqual(r['decision'], 'PASS', r)
        checks = {c['id']: c for c in r['checks']}
        self.assertEqual(checks['cached_share']['exact'], '24/25')  # the lowest node, not the pool
        self.assertAlmostEqual(checks['checkpoint_latency']['value'], 0.9)

    def test_missing_counters_and_failed_preflight_are_not_met(self):
        plan = self.plan()
        d = self.write(plan, self.good(), per_node={'n0': dict(error='missing counters: [prefill]')},
                       preflight_ok=False)
        r = rep.build(plan, [d])
        self.assertIn('cached_share', r['failed'])
        self.assertIn('turn_boundaries', r['failed'])

    def test_stop_on_wrong_checkable_results_and_same_focus(self):
        plan = self.plan()
        recs = [self.rec(0, 'same focus line', '6*7=43 and no more', 'x y z w v u'),
                self.rec(1, 'same focus line', 'a sentence with no equation', 'x y z w v u')]
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertEqual(r['decision'], 'STOP')
        checks = {c['id']: c for c in r['checks']}
        self.assertEqual(checks['arith_results_correct']['exact'], '0')  # only the checkable sentence counts
        self.assertEqual(r['result_sentences_checkable'], 1)
        self.assertIn('focus_distinct', r['failed'])

    def test_unlocated_closes_need_coverage(self):
        plan = self.plan()
        recs = self.good()
        recs[0]['continuation'].update(closed=True, close_located=False, closed_at_token=None)
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertIn('answer_at_once', r['failed'])  # 1 of 2 closes located < 90 %

    def test_one_intact_attempt_and_complete_checkpoints(self):
        plan = self.plan()
        recs = self.good()
        d = self.write(plan, recs)
        self.assertIn('exactly one', rep.build(plan, [d, d])['decision'])
        recs[0]['status'] = 'infrastructure'
        d2 = self.write(plan, recs, name='run2')
        self.assertEqual(rep.build(plan, [d2])['status'], 'incomplete')


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
        # primary: lowest seed per puzzle, ties to the arm listed first; extension: the lowest OTHER seed; the
        # same puzzle and seed in another policy is not planned
        self.assertEqual(got, [(a, 't1', 1, 'primary'), (b, 't6', 2, 'primary'), (a, 't1', 2, 'extension')])
        self.assertEqual(skipped, {'10 tokens <= cut': 1, 'thinking closed before the cut': 1,
                                   "same seed as the puzzle's primary or extension case (not planned)": 1})
        k = cases[0]
        self.assertEqual(k['case_id'], 'h20g-t1-s1')
        self.assertEqual(k['agents'][2]['agent_seed'], 1000 + cp.S1_SEED_OFFSET + 2)
        self.assertEqual(k['agents'][0]['prefix_ids_sha256'],
                         hashlib.sha256(json.dumps([1] * cp.CUT).encode()).hexdigest())
        self.assertEqual(k['agents'][0]['trace'], f'runs/{a}/agents/t1-s1-roll12cancel-a0.jsonl')

    def test_calibration_bounds_the_familywise_false_pass(self):
        m = cp.calibrate(41, 29)
        self.assertLessEqual(m['familywise_false_pass_max'], cp.ALPHA)
        self.assertEqual(m['grey_band'], [m['primary_margin'] - 2, m['primary_margin'] - 1])
        looser = cp.familywise(41, 29, 9 / 41, m['primary_margin'] - 1, m['pooled_margin'])
        self.assertGreater(looser, m['familywise_false_pass_by_null_rescues']['9'])
        one = cp.familywise(41, 29, 7 / 41, 4, 6, arms=1)
        two = cp.familywise(41, 29, 7 / 41, 4, 6, arms=2)
        self.assertGreater(two, one)
        dist = cp.arm_distribution(5, 2, 0.3)
        self.assertAlmostEqual(sum(dist.values()), 1.0)
        self.assertTrue(all(b >= x for x, b in dist))

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
