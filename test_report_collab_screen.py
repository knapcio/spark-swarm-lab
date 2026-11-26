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
    return dict(screen='s1', study='collab-s1-test', arm_order=ARMS, per_node=20,
                arms={"D'": dict(protocol=False), "C'": dict(protocol=True), "C'div": dict(protocol=True)},
                decision_rule=dict(margins=MARGINS), cases=cases)


def seg(text, t0=0.0, t1=10.0, think_before=8192, tokens=8192, progress=None):
    return dict(think_before=think_before, tokens=tokens, thinking_tokens=tokens, text=text, t0=t0, t_first=t0,
                t1=t1, progress=progress if progress is not None else [(t1, tokens, len(text))])


def agent(text, t0=0.0, t1=10.0, prefix='', notes=(), submissions=()):
    return dict(prefix_text=prefix, segments=[seg(text, t0, t1)], notes=list(notes), reads=[],
                submissions=list(submissions))


def write_s1(d, plan, rows, records=None, cohort='primary', bypass=None, drained=True):
    d.mkdir(parents=True)
    (d / 'metadata.json').write_text(json.dumps(dict(plan=plan, cohort=cohort, bypass=bypass or [], per_node=20)))
    (d / 'summary.json').write_text(json.dumps(dict(screen='s1', drain_confirmed=drained)))
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
        self.assertEqual(r['arms']["C'"]['verifier_prompt_tokens'], 0)  # checker compute is an arm total
        rows = self.rows(5, 1)
        for x in rows:
            if x['arm'] == "C'":
                x.update(verifier_calls=2, verifier_prompt_tokens=50, verifier_completion_tokens=3)
        write_s1(self.root / 'checker', plan, rows)
        arms = rep.build(plan, [self.root / 'checker'])['arms']
        self.assertEqual((arms["C'"]['verifier_calls'], arms["C'"]['verifier_prompt_tokens']),
                         (2 * sum(x['arm'] == "C'" for x in rows), 50 * sum(x['arm'] == "C'" for x in rows)))
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

    def test_pooled_look_only_for_primary_grey_arms_and_primary_pass_is_kept(self):
        plan = s1_plan(n=6)
        # primary: C' leads by 2 (GREY), C'div leads by 4 (PASS)
        write_s1(self.root / 'p', plan, self.rows(3, 1, div_rescued=5))
        ext = [row('k6', a, rescued=a in ("C'", "C'div"), puzzle='p4') for a in ARMS]
        ext += [row('k7', a, rescued=a in ("C'", "C'div"), puzzle='p5') for a in ARMS]
        write_s1(self.root / 'e', plan, ext, cohort='extension')
        r = rep.build(plan, [self.root / 'p', self.root / 'e'])
        self.assertTrue(r['pooled'])
        self.assertEqual(r['primary']['verdicts']["C'div"]['verdict'], 'PASS')
        self.assertTrue(r['primary']['verdicts']["C'"]['verdict'].startswith('GREY'))
        self.assertEqual(r['pooled_look']['arms']["C'"]['rescued_puzzles'], 5)  # p4, p5 rescued by their extensions
        self.assertEqual(r['final_verdicts'], {"C'": 'STOP', "C'div": 'PASS'})  # lead 4 < pooled 6; PASS kept
        self.assertEqual((r['decision'], r['passing_arms']), ('PASS', ["C'div"]))
        plan8 = s1_plan(n=6)
        plan8['decision_rule'] = dict(margins=dict(MARGINS, pooled_margin=5))
        plan8['cases'] = [k for k in plan8['cases'] if k['cohort'] == 'primary'] + [
            dict(case_id=f'k{i}', cohort='extension', puzzle_key=f'p{i - 6}', agents=[dict(slot=x) for x in range(4)])
            for i in (9, 10, 11)]
        write_s1(self.root / 'p8', plan8, self.rows(3, 1))
        ext2 = [row(f'k{i}', a, rescued=a == "C'", puzzle=f'p{i - 6}') for i in (9, 10, 11) for a in ARMS]
        write_s1(self.root / 'e8', plan8, ext2, cohort='extension')
        r = rep.build(plan8, [self.root / 'p8', self.root / 'e8'])
        self.assertEqual(r['final_verdicts']["C'"], 'PASS (pooled)')  # GREY at primary, pooled lead 5
        self.assertTrue(r['pooled_look']['verdicts']["C'div"]['verdict'].startswith('NOT ELIGIBLE'))

    def test_wrong_acceptances_count_from_every_attempt_in_any_order(self):
        plan = s1_plan()
        wrong_sub = [dict(where='segment', accepted=True, verifier_solved=False)]
        rows = self.rows(5, 1)
        bad = next(x for x in rows if (x['case_id'], x['arm']) == ('k2', "C'"))
        bad.update(status='infrastructure', wrong=1)
        recs = [dict(agent(PROSE + f' {r["case_id"]} {r["arm"]} {i}'), case_id=r['case_id'], arm=r['arm'], slot=i,
                     status='complete', submissions=wrong_sub if (r is bad and i == 0) else [])
                for r in rows for i in range(4)]
        write_s1(self.root / 'a', plan, rows, records=recs)
        write_s1(self.root / 'b', plan, [row('k2', "C'", rescued=True)])
        for order in ([self.root / 'a', self.root / 'b'], [self.root / 'b', self.root / 'a']):
            r = rep.build(plan, order)
            self.assertEqual(r['arms']["C'"]['wrong'], 1, order)  # the rerun listed first erases nothing
            self.assertEqual(r['decision'], 'STOP')
        # the faulted attempt left its agent record but no case row: the wrong acceptance still counts
        rows_no_row = [x for x in rows if x is not bad]
        write_s1(self.root / 'c', plan, rows_no_row, records=recs)
        r = rep.build(plan, [self.root / 'c', self.root / 'b'])
        self.assertEqual(r['arms']["C'"]['wrong'], 1)

    def test_runs_without_confirmed_drain_are_rejected(self):
        plan = s1_plan()
        write_s1(self.root / 'nd', plan, self.rows(5, 1), drained=False)
        self.assertIn('drain was not confirmed', rep.build(plan, [self.root / 'nd'])['decision'])

    def test_markdown_shows_final_verdicts(self):
        plan = s1_plan()
        write_s1(self.root / 'md', plan, self.rows(5, 1))
        text = rep.markdown(rep.build(plan, [self.root / 'md']))
        self.assertIn("- C': **PASS**", text)

    def test_non_utf8_torn_line_is_skipped_and_listed(self):
        plan = s1_plan()
        write_s1(self.root / 'u', plan, self.rows(5, 1))
        with (self.root / 'u' / 'records.jsonl').open('ab') as f:
            f.write(b'{"slot": "\xff\xfe torn')
        r = rep.build(plan, [self.root / 'u'])
        self.assertEqual(r['decision'], 'PASS')
        self.assertEqual(len(r['torn_lines']), 1)

    def test_other_load_settings_are_rejected(self):
        plan = s1_plan()
        write_s1(self.root / 'l', plan, self.rows(5, 1))
        meta = json.loads((self.root / 'l' / 'metadata.json').read_text())
        (self.root / 'l' / 'metadata.json').write_text(json.dumps(dict(meta, per_node=24)))
        self.assertIn('per_node 24', rep.build(plan, [self.root / 'l'])['decision'])

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

    def test_novelty_combines_pieces_of_one_bin_across_request_breaks(self):
        first = seg(' '.join(f'a{i}' for i in range(30)), 0.0, 5.0, think_before=8192, tokens=3000)
        second = seg(' '.join(f'b{i}' for i in range(30)), 20.0, 25.0, think_before=11192, tokens=3000)
        broken = dict(prefix_text='', segments=[first, second], notes=[], reads=[], submissions=[])
        peer = agent(' '.join(f'b{i}' for i in range(30)), t0=6.0, t1=7.0)  # wrote the b-words between the parts
        values = rep.novelty([broken, peer])
        own = values[0]
        self.assertEqual(own[1], 6000)  # one combined bin, not two pieces
        self.assertEqual(own[0], Fraction(26, 52))  # the a-grams are new, the b-grams were written by the peer first
        cancelled = dict(seg('x y z w v u t s r q p o n m l k j i h g f e d c b a', 0, 1), thinking_tokens=None)
        self.assertEqual(len(rep.pieces(cancelled)), 1)  # unlocated end of thinking: its streamed thinking, one piece

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
    EPS = ['http://n0/v1', 'http://n1/v1']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return dict(screen='s0', study='collab-s0-test', checks=cp.S0_CHECKS, answer_at_once_tokens=512, nodes=2,
                    per_node=20, groups=[dict(group_id='g', members=[dict(slot=0), dict(slot=1)])])

    def rec(self, slot, focus, result, cont_text, closed_at=None, kind='note', tokens=100, closed=None):
        return dict(group_id='g', slot=slot, family='arith', status='complete', prefix_identical=True,
                    continuation_prefix_identical=True, accepted=False, group_size=2, endpoint=self.EPS[slot],
                    note=dict(kind=kind, tokens=tokens, t0=10.0, t_first=10.5, t=14.0, finish_reason='stop',
                              note=dict(focus=focus, results=[result], dead_ends=[], reviews=[]) if kind == 'note' else None),
                    joins=[dict(terminated=True, terminator_overlap=2)],
                    continuation=dict(t0=20.0, t_first=20.4, attempts=1,
                                      closed=closed if closed is not None else closed_at is not None,
                                      closed_at_token=closed_at, thinking_text=cont_text),
                    prefix_text=PROSE, recorded_continuation_text='new words here only for the record now ok',
                    submissions=[])

    def write(self, plan, recs, per_node=None, preflight_ok=True, name='run', used=20):
        d = self.root / name
        d.mkdir()
        (d / 'metadata.json').write_text(json.dumps(dict(plan=plan, bypass=[], per_node=used)))
        (d / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
        per_node = per_node or {self.EPS[0]: dict(prompt_tokens=1000, prefill_compute_tokens=20, generation_tokens=1,
                                                  requests=1),
                                self.EPS[1]: dict(prompt_tokens=1000, prefill_compute_tokens=40, generation_tokens=1,
                                                  requests=1)}
        pre = {e: dict(arith=dict(ok=preflight_ok)) for e in self.EPS}
        (d / 'summary.json').write_text(json.dumps(dict(preflight=pre, phases=dict(board=dict(per_node=per_node)),
                                                        drain_confirmed=True)))
        return d

    def good(self):
        return [self.rec(0, 'work backward from the target', '6*7=42 from the two largest', 'brand new thinking words '
                         'that never appeared anywhere before at all'),
                self.rec(1, 'try products of large numbers first', '12+30=42', 'other fresh words entirely new to '
                         'this stream and unseen')]

    def checks(self, report):
        return {c['id']: c for c in report['checks']}

    def test_pass_with_raw_timing_and_lowest_node_cache(self):
        plan = self.plan()
        r = rep.build(plan, [self.write(plan, self.good())])
        self.assertEqual(r['decision'], 'PASS', r)
        self.assertEqual(self.checks(r)['cached_share']['exact'], '24/25')  # the lowest node, not the pool
        self.assertAlmostEqual(self.checks(r)['checkpoint_latency']['value'], 0.9)

    def test_counters_must_reconcile_and_never_reset(self):
        plan = self.plan()
        extra = {self.EPS[0]: dict(prompt_tokens=1000, prefill_compute_tokens=20, generation_tokens=1, requests=3),
                 self.EPS[1]: dict(prompt_tokens=1000, prefill_compute_tokens=40, generation_tokens=1, requests=1)}
        r = rep.build(plan, [self.write(plan, self.good(), per_node=extra, name='more')])
        self.assertIn('cached_share', r['failed'])  # 3 requests on n0 but 1 continuation sent there
        reset = dict(extra, **{self.EPS[0]: dict(prompt_tokens=-5, prefill_compute_tokens=0, generation_tokens=1,
                                                 requests=1)})
        r = rep.build(plan, [self.write(plan, self.good(), per_node=reset, name='reset')])
        self.assertIn('cached_share', r['failed'])
        missing = {self.EPS[0]: dict(error='missing counters')}
        r = rep.build(plan, [self.write(plan, self.good(), per_node=missing, name='missing', preflight_ok=False)])
        self.assertIn('cached_share', r['failed'])
        self.assertIn('turn_boundaries', r['failed'])

    def test_timing_coverage_and_close_coverage_among_closes(self):
        plan = self.plan()
        recs = self.good()
        recs[0]['continuation']['t_first'] = None
        r = rep.build(plan, [self.write(plan, recs, name='timing')])
        self.assertIn('checkpoint_latency', r['failed'])  # one continued checkpoint has no first-token time
        recs = self.good()
        recs[0]['continuation'].update(closed=True, closed_at_token=None)  # the only close is not located
        r = rep.build(plan, [self.write(plan, recs, name='close')])
        self.assertIn('answer_at_once', r['failed'])  # open streams do not make up the 90 %
        self.assertEqual((r['closes'], r['closes_located']), (1, 0))

    def test_stop_on_wrong_checkable_results_and_same_focus(self):
        plan = self.plan()
        recs = [self.rec(0, 'same focus line', '6*7=43 and no more', 'x y z w v u'),
                self.rec(1, 'same focus line', 'a sentence with no equation', 'x y z w v u')]
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertEqual(r['decision'], 'STOP')
        self.assertEqual(self.checks(r)['arith_results_correct']['exact'], '0')  # only the checkable sentence counts
        self.assertEqual(r['result_sentences_checkable'], 1)
        self.assertIn('focus_distinct', r['failed'])

    # collab-s0-v1 result sentences the old a-op-b=c regex flagged (records.jsonl lines 5, 16, 24, 30, 31, 48, 53,
    # 56, 66, 70, 71, 75): correct when read whole; and record 42's real false equality the regex missed
    V1_CORRECT = [
        "75+4*2=83 is a clean way to build 83 using 75,4,2.",
        "(25-5-1)+3-1 = 21 uses 25,5,1,3,1 and leaves 50; then need 19 somehow but only 50 remains, so not complete.",
        "Initial values: 1, 50, 75, 4, 2, 9; 916=4*229=2*458, so multiplication and division endpoints are promising.",
        "800=50*16=50*(4+10+2) is exact, leaving 33 to be made from 100 and 5, which is impossible (only 105,95,500,20).",
        "Other factorization to test: 833=119*7, with 100+10+5+4=119, leaving 2 and50 which do not yield 7.",
        "The subset {75,1,5,2} reduces to 75+1+5+2=83, but leaves {4,25} unusable for 8, so that partition fails.",
        "Pair results: 25-5-1=19 and 50*19=950, but the remaining 3,1 cannot make 21.",
        "A promising route is 50*19+21=971, requiring disjoint subsets for 19 and 21 from {3,25,1,5,1}; triple {25,1,5} "
        "can make both 19 and 21, but leaves an unusable\u2026",
        "Factoring shows 972=9*108=2*486=4*243; direct final division is not integer for 75,50,10.",
        "Factorization 833=7^2*17=49*17=7*119, useful for final multiplication.",
        "Preliminary check: 100+10+5+4=119, but the remaining 2 and 50 cannot make 7, so 119*7 is not achievable with "
        "that split.",
        "I found a promising subtree: 6-4=2, 25+2=27, 5*27=135, 100+135=235, and 4*235-1=939, but it needs a 1 that "
        "cannot be made from the remaining single 4."]
    V1_FALSE = "17 = 3 + (25-5): triple {5,25,3}; operations 25-5=20 then 20-3=17? Actually 20-3=17, so 5+? no; use " \
               "3+(5+9) for safety."

    def test_v1_checker_artifacts_count_correct_and_the_real_error_counts_wrong(self):
        plan = self.plan()
        plan['groups'][0]['members'] = [dict(slot=i) for i in range(len(self.V1_CORRECT) + 1)]
        recs = []
        for i, text in enumerate(self.V1_CORRECT + [self.V1_FALSE]):
            r = self.rec(0, f'focus number {i} ' + 'abcdefghijklmnopqrstuvwxyz'[i], text, 'x y z w v u')
            r.update(slot=i, endpoint=self.EPS[0])
            recs.append(r)
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertEqual(self.checks(r)['arith_results_correct']['exact'], '12/13')
        self.assertEqual(r['result_sentences_false'], 1)
        for text in self.V1_CORRECT:
            self.assertEqual(rep.exact_claims.check_claim(text)[0], rep.exact_claims.TRUE, text)

    def test_facts_notes_count_only_posted_statements(self):
        plan = self.plan()
        recs = self.good()
        for r, claims in zip(recs, ([dict(kind='computed', text='6*7=42', tag='VERIFIED'),
                                     dict(kind='tried', text='approach: 2+2=5 tried', tag='drop', mechanical='false equation')],
                                    [dict(kind='computed', text='x = 4*y', tag='UNVERIFIED'),
                                     dict(kind='tried', text='approach: a; observed: b', tag='agent-checked',
                                          checker=dict(verdict='SUPPORTED'))])):
            r['note']['claims'] = claims
        recs[0]['verifications'] = [dict(prompt_tokens=1500, completion_tokens=2, t0=1.0, t1=2.5)]
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertEqual(self.checks(r)['arith_results_correct']['exact'], '1')  # the dropped false one never posted
        self.assertEqual(r['result_sentences_unsupported'], 1)
        c = r['claims']
        self.assertEqual((c['claims_made'], c['claims_dropped'], c['claims_unverified'], c['claims_agent_checked'],
                          c['claims_verified']), (4, 1, 1, 1, 1))
        self.assertEqual((c['verifier_prompt_tokens'], c['verifier_latency_median_s']), (1500, 1.5))

    def test_review_blocker_4_coverage_gate(self):
        # one true post and every other statement dropped: arith_results_correct alone would be 100 %
        plan = self.plan()
        plan['groups'][0]['members'] = [dict(slot=i) for i in range(5)]
        recs = []
        for i in range(5):
            r = self.rec(0, f'distinct focus {i} ' + 'abcde'[i], 'x', 'x y z w v u')
            r.update(slot=i)
            r['note']['claims'] = ([dict(kind='computed', text='6*7=42', tag='VERIFIED')] if i == 0 else
                                   [dict(kind='computed', text='6*7=43', tag='drop', mechanical='false equation')])
            recs.append(r)
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertEqual(self.checks(r)['arith_results_correct']['exact'], '1')
        self.assertEqual(self.checks(r)['arith_coverage']['exact'], '1/5')
        self.assertIn('arith_coverage', r['failed'])
        c = r['claims']['by_family']['arith']
        self.assertEqual((c['claims_made'], c['claims_dropped'], c['drop_rate'], c['prefilter_accuracy']),
                         (5, 4, 0.8, 0.2))

    def test_review_blocker_7_dev_is_refused_before_any_screen_branch(self):
        s1 = dict(screen='s1', study='x', dev=True, cases=[], arms={}, per_node=20)
        self.assertIn('dev plans are S0 only', rep.build(s1, [])['decision'])
        plan = self.plan()
        d = self.write(plan, self.good(), name='devrun')
        meta = json.loads((d / 'metadata.json').read_text())
        (d / 'metadata.json').write_text(json.dumps(dict(meta, bypass=['dev'])))
        r = rep.build(plan, [d])
        self.assertIn('under a non-dev plan', r['decision'])
        self.assertEqual(r['status'], 'incomplete')

    def test_dev_plans_never_decide_and_the_checker_is_pinned(self):
        plan = dict(self.plan(), dev=True)
        d = self.write(plan, self.good())
        meta = json.loads((d / 'metadata.json').read_text())
        (d / 'metadata.json').write_text(json.dumps(dict(meta, bypass=['dev'])))
        r = rep.build(plan, [d])
        self.assertEqual(r['status'], 'dev')
        self.assertTrue(r['decision'].startswith('DEV RUN, not for decisions'))
        r = rep.build(self.plan(), [self.write(self.plan(), self.good(), name='nodev')])
        self.assertEqual(r['status'], 'complete')
        pinned = dict(self.plan(), exact_claims_sha256='0' * 64, source_revision='0' * 40)
        r = rep.build(pinned, [self.write(pinned, self.good(), name='pin')])
        self.assertIn('differs from the plan pin', r['decision'])

    def test_board_miss_splits_new_text_from_eviction(self):
        plan = self.plan()
        recs = self.good()
        for r in recs:
            r['board_new_tokens'] = 15
        r = rep.build(plan, [self.write(plan, recs)])
        self.assertEqual(r['board_miss_by_node'][self.EPS[1]]['eviction_tokens'], 25)
        self.assertEqual(r['board_miss_by_node'][self.EPS[0]]['eviction_tokens'], 5)

    def test_one_intact_attempt_unique_rows_and_frozen_load(self):
        plan = self.plan()
        recs = self.good()
        d = self.write(plan, recs)
        self.assertIn('exactly one', rep.build(plan, [d, d])['decision'])
        self.assertIn('more than once', rep.build(plan, [self.write(plan, recs + [recs[0]], name='dup')])['decision'])
        self.assertIn('per_node 25', rep.build(plan, [self.write(plan, recs, name='load', used=25)])['decision'])
        recs[0]['status'] = 'infrastructure'
        self.assertEqual(rep.build(plan, [self.write(plan, recs, name='run2')])['status'], 'incomplete')


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

    def test_judge_pins_cover_every_module_the_judge_loads(self):
        files = cp.judge_files(cp.ROOT)
        for name in ('run_variants.py', 'run_judge.py', 'run_agents72.py', 'run_nemotron72_known.py',
                     'run_benchmark.py', 'inkling/admit.py', 'inkling/fleet_lease.py'):
            self.assertIn(name, files)
        plan = cp.base_plan('s0', 'x', '0' * 40)
        self.assertEqual(set(plan['judge_code_sha256']), set(files))
        self.assertEqual((plan['fleet'], plan['per_node']), (cp.FLEET, 20))
        self.assertEqual(plan['fleet']['endpoints'][0], 'http://127.0.0.1:18081/v1')

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


class S0V2PlanTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent
    V1_LIMITS = [('prefix_identical', '== 1.0', 'fix'), ('turn_boundaries', '== 1.0', 'fix'),
                 ('cached_share', '>= 0.95', 'fix or fallback B'), ('checkpoint_latency', '<= 5.0 s', 'fix or fallback B'),
                 ('reply_parse', '>= 0.90', 'fix the note prompt once, then fallback B'),
                 ('note_within_256', '>= 0.90', 'fix the note prompt once, then fallback B'),
                 ('arith_results_correct', '>= 0.90', 'stop'), ('focus_distinct', '>= 0.75', 'stop: nothing to divide'),
                 ('answer_at_once', '<= 0.20', 'stop, or fallback B'), ('own_repeat', '<= +0.10', 'stop, or fallback B')]

    def test_thresholds_are_not_loosened(self):
        got = [(c['id'], c['limit'], c['on_fail']) for c in cp.S0_CHECKS]
        self.assertEqual([x for x in got if x[0] != 'arith_coverage'], self.V1_LIMITS)  # v1 gates unchanged
        self.assertIn(('arith_coverage', '>= 0.75', 'fix the note prompt once, then fallback B'), got)  # one added

    def test_committed_plans(self):
        s0 = json.loads((self.ROOT / 'COLLAB_S0_PLAN.json').read_text())
        s1 = json.loads((self.ROOT / 'COLLAB_S1_PLAN.json').read_text())
        dev = json.loads((self.ROOT / 'COLLAB_S0_DEV_PLAN.json').read_text())
        self.assertEqual((s0['study'], s0['per_node'], s0['wave_groups'], s0['nodes']), ('collab-s0-v3', 20, 20, 4))
        self.assertTrue(s0['warm_barrier'])
        self.assertIn('warm-ups of a wave complete before its notes', ' '.join(s0['amendments']))
        self.assertEqual(s0['protocol_constants']['note_max_tokens'], 200)
        self.assertLessEqual(s0['protocol_constants']['note_max_tokens'], 256)  # note_within_256 by construction
        self.assertEqual(s0['protocol_constants']['board_share'], 0.03)
        self.assertEqual(s0['exact_claims_sha256'], rep.exact_claims_sha256())
        self.assertEqual(s0['source_revision'], 'e0576ea71704b6394fae7f054cd08a0c458506f4')  # S0 v3 as frozen
        worker_sha = rep.worker_exact_claims_sha256(s0['source_revision'])
        if worker_sha is not None:  # the worker revision lives on a local research branch; absent in a CI clone
            self.assertEqual(worker_sha, s0['exact_claims_sha256'])
        self.assertEqual(s0['s1_plan_cases'], sorted(s0['s1_plan_cases']) and s0['s1_plan_cases'])
        self.assertEqual((s1['study'], s1['arm_order']), ('collab-s1-v2', ["D'", "C'div"]))  # plain C' dropped
        self.assertIn('collab-s1-v2 RETEST', ' '.join(s1['amendments']))
        for arm in ("C'div",):
            self.assertEqual((s1['arms'][arm]['note_max_tokens'], s1['arms'][arm]['board_share'],
                              s1['arms'][arm]['verify_async']), (200, 0.03, True))
        s1dev = json.loads((self.ROOT / 'COLLAB_S1_DEV_PLAN.json').read_text())
        self.assertEqual((s1dev['study'], s1dev['dev'], s1dev['dev_fleet_mode']), ('collab-s1-v2-dev', True,
                                                                                    'decision-nodes'))
        self.assertEqual({k: v for k, v in s1dev.items() if k not in ('study', 'dev', 'dev_fleet_mode', 'execution')},
                         {k: v for k, v in s1.items() if k not in ('study', 'execution')})
        self.assertEqual((s1['cohort_counts']['primary'], s1['cohort_counts']['extension']), (41, 29))
        self.assertIn('S1 abort confirmation', ' '.join(s1['amendments']))
        self.assertEqual(s1['decision_rule']['margins']['primary_margin'], 7)
        self.assertTrue(dev['dev'] and dev['nodes'] == 2 and dev['study'].endswith('-dev'))
        self.assertEqual(dev['groups'], s0['groups'])


if __name__ == '__main__':
    unittest.main()
