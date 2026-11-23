"""Offline tests for the lead relay (closers.py, closer_replay.py): no model, no network."""
import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import closer_replay
import closers
import run_variants as v


class StatementTests(unittest.TestCase):
    def lines(self, text):
        return [line for line, _ in closers.statements(text)]

    def test_plain_and_spaced(self):
        self.assertEqual(self.lines('so 55*15=825 then'), ['55 * 15 = 825'])
        self.assertEqual(self.lines('Try 55 * 15 = 825, minus 3'), ['55 * 15 = 825'])

    def test_unicode_and_latex_symbols(self):
        self.assertEqual(self.lines('55 × 15 = 825'), ['55 * 15 = 825'])
        self.assertEqual(self.lines('83·12 = 996'), ['83 * 12 = 996'])
        self.assertEqual(self.lines('100 ÷ 4 = 25 and 30 − 4 = 26'), ['100 / 4 = 25', '30 - 4 = 26'])
        self.assertEqual(self.lines(r'$55 \times 15 = 825$'), ['55 * 15 = 825'])
        self.assertEqual(self.lines('55 x 15 = 825'), ['55 * 15 = 825'])

    def test_parenthesised_expressions(self):
        self.assertEqual(self.lines('(25*4-2)*8=784'), ['(25 * 4 - 2) * 8 = 784'])
        self.assertEqual(self.lines('check ((25*4-2)*8 = 784)'), ['(25 * 4 - 2) * 8 = 784'])

    def test_chains_yield_each_link(self):
        self.assertEqual(self.lines('55*15 = 825; 825-3 = 822'), ['55 * 15 = 825', '825 - 3 = 822'])
        # '= 825 - 3' is not a value of the left side; the next link is read on its own
        self.assertEqual(self.lines('55*15-3 = 825 - 3 = 822'), ['825 - 3 = 822'])

    def test_false_matches_rejected(self):
        for text in ('825/2 = 412.5', 'x = 825', 'if a <= 825', 'a >= 3+4', '7 = 7', '825 = 825',
                     'so 2**3 = 8', '1650/4 = 412,5', '100/8 = 25/2', 'a != 3*5', 'n == 3*5', '3*5 = -15'):
            self.assertEqual(self.lines(text), [], text)

    def test_fraction_right_side_rejected_but_fraction_left_ok(self):
        self.assertEqual(self.lines('825/2 = 412 1/2'), [])
        self.assertEqual(self.lines('3/4*8 = 6'), ['3 / 4 * 8 = 6'])

    def test_adjacent_numbers_cut_to_expression(self):
        self.assertEqual(self.lines('numbers 6 25*4 = 100'), ['25 * 4 = 100'])
        self.assertEqual(self.lines('Step 2: 25*4 = 100'), ['25 * 4 = 100'])
        self.assertEqual(self.lines('3. 25*4 = 100'), ['25 * 4 = 100'])

    def test_thousands_separator(self):
        self.assertEqual(closers.statements('822*75 = 61,650'), [('822 * 75 = 61650', 61650)])

    def test_leads_tiers_dedup_and_limit(self):
        text = ('Hmm 55*15=825. Also 55 * 15 = 825 again. target? 800+22 = 822. 83*12=996 no. '
                '(25*4-2)*8=784 meh. 822/2 = 411')
        res = closers.leads(text, wanted={825, 819, 411, 2466}, target=822)
        self.assertEqual(res['tier1'], ['55 * 15 = 825', '822 / 2 = 411'])
        self.assertEqual(res['tier2'], ['800 + 22 = 822'])
        self.assertEqual(res['lines'], ['55 * 15 = 825', '822 / 2 = 411', '800 + 22 = 822'])
        self.assertEqual(closers.leads(text, {825, 411}, 822, limit=2)['truncated'], 1)
        self.assertEqual(closers.leads('nothing here', {825}, 822)['lines'], [])

    def test_extra_text(self):
        extra = closers.closer_extra(['55 * 15 = 825'])
        self.assertTrue(extra.startswith('Another solver computed these lines:\n55 * 15 = 825\n'))
        self.assertTrue(extra.endswith('otherwise answer with no moves.'))


class WantedTests(unittest.TestCase):
    def test_parse_model_lines(self):
        text = '822+3 = 825\n822-3 = 819\n822*3 = 2466\n822/3 = 274\n- 822 + 75 = 897\n822/75 = none\n' \
               '822*75 = 61,650\n3+822 = 825\n822+9 = 830\n100+3 = 103\nSure! 822-8 = 814'
        lines, values = closers.parse_wanted(text, [3, 75], 822)
        # the model's values are taken as written (822+9 is not a given number; 830 would be the model's own value)
        self.assertEqual(lines, ['822+3 = 825', '822-3 = 819', '822*3 = 2466', '822/3 = 274', '822+75 = 897',
                                 '822*75 = 61650', '3+822 = 825'])
        self.assertEqual(values, [825, 819, 2466, 274, 897, 61650])

    def test_model_mistakes_are_not_corrected(self):
        lines, values = closers.parse_wanted('822+3 = 826', [3], 822)
        self.assertEqual(values, [826])

    def test_prompt_mentions_every_form(self):
        prompt = closers.wanted_prompt([3, 75], 822)
        for part in ('822+x', '822-x', '822*x', '822/x', '3, 75'):
            self.assertIn(part, prompt)

    def test_reference_values(self):
        self.assertEqual(closers.reference_wanted_values([3, 1000], 822), {825, 819, 2466, 274, 1822, 822000})


def fake_events(path, reasonings):
    with open(path, 'w') as f:
        f.write(json.dumps(dict(type='run_start')) + '\n')
        for r in reasonings:
            f.write(json.dumps(dict(type='request_end', reasoning=r, response=None)) + '\n')


class RunCaseTests(unittest.TestCase):
    TASK = dict(id='t', numbers=[3, 15, 55, 7, 2, 9], target=822)

    def run_case(self, rows, fast, accept, solved=()):
        launched, extras = [], {}

        def execute(job, deadline_seconds, cancel=None):
            slot = int(job['events'].rsplit('-a', 1)[1].split('.')[0])
            launched.append(slot)
            c = job['command']
            extras[slot] = Path(c[c.index('--extra-file') + 1]).read_text()
            self.assertEqual(c[c.index('--variant') + 1], 'forced_original')
            self.assertEqual(int(c[c.index('--seed') + 1]), 1000 * 2 + closers.CLOSER_SEED_OFFSET + slot)
            if slot in fast:
                return dict(deadline=False, cancelled=False, returncode=0)
            for _ in range(200):
                if cancel.is_set():
                    return dict(deadline=False, cancelled=True, returncode=-15)
                time.sleep(.01)
            return dict(deadline=False, cancelled=False, returncode=0)

        def plan_of(path):
            slot = int(str(path).rsplit('-a', 1)[1].split('.')[0])
            return dict(plan={'moves': [1]}, verifier_solved=slot in solved, tokens=10, infra=0)

        def judge(cand, endpoint, events_path, seed):
            slot = int(str(events_path).rsplit('-a', 1)[1].split('.')[0])
            return dict(verdict=slot in accept, reason='', infra=0, tokens=3)
        wanted_calls = []

        def wanted(endpoint, path, seed, numbers, target):
            wanted_calls.append((endpoint, seed))
            return dict(lines=['822+3 = 825'], values=[825], infra=0, error=None, tokens=50, retry=False)
        seen_values = []

        def leads_fn(values):
            seen_values.append(values)
            return rows
        plan = dict(agent_variant='forced_original', agent_wall_deadline_seconds=60)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute_cancellable', execute), \
                patch.object(v, 'plan_of', plan_of), patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            for sub in ('agents', 'judges', 'extra', 'wanted'):
                (out / sub).mkdir()
            rec = closers.run_case(plan, Path('/src'), out, self.TASK, 2, 5, leads_fn, closers.EndpointSlots(v.ENDPOINTS, 8),
                                   v.ENDPOINTS, wanted_fn=wanted)
        self.assertEqual(seen_values, [[825]])
        self.assertEqual(len(wanted_calls), 1)
        return rec, launched, extras

    @staticmethod
    def row(slot, tier1=(), tier2=()):
        return dict(slot=slot, missing=False, tier1=list(tier1), tier2=list(tier2), lines=list(tier1) + list(tier2), truncated=0)

    def test_closers_only_for_agents_with_leads(self):
        rows = [self.row(0, ['55 * 15 = 825']), self.row(1), self.row(2, tier2=['800 + 22 = 822']), self.row(3)]
        rec, launched, extras = self.run_case(rows, fast={100, 102}, accept=set())
        self.assertEqual(sorted(launched), [100, 102])
        self.assertIn('55 * 15 = 825', extras[100])
        self.assertIn('800 + 22 = 822', extras[102])
        self.assertTrue(all(e.endswith(closers.CLOSER_TAIL) for e in extras.values()))
        self.assertEqual([(c['source_slot'], c['tier1'], c['tier2']) for c in rec['closers']], [(0, 1, 0), (2, 0, 1)])
        self.assertFalse(rec['rescue'])
        self.assertEqual((rec['failed_agents'], rec['agents_tier1'], rec['agents_tier2']), (4, 1, 1))
        self.assertEqual(rec['tokens'], 50 + 2 * (10 + 3))
        self.assertEqual(rec['calls'], 3)

    def test_ranking_and_cap(self):
        rows = [self.row(0, tier2=['a', 'b', 'c']), self.row(1, ['x'], ['a']), self.row(2, ['x', 'y']), self.row(3),
                self.row(4, ['x'], ['a']), self.row(5, ['x'], ['a', 'b']), self.row(6, tier2=['a', 'b', 'c'])]
        chosen, skipped = closers.select_closers(rows, 4)
        self.assertEqual([r['slot'] for r in chosen], [2, 5, 1, 4])
        self.assertEqual(skipped, [0, 6])
        self.assertEqual([r['slot'] for r in closers.select_closers(rows, 10)[0]], [2, 5, 1, 4, 0, 6])
        self.assertEqual(closers.select_closers(rows, 10)[1], [])

    def test_case_starts_only_top_n_and_records_skipped(self):
        rows = [self.row(s, ['55 * 15 = 825'] * (s % 3), ['800 + 22 = 822']) for s in range(7)]
        rec, launched, _ = self.run_case(rows, fast=set(range(100, 107)), accept=set())
        # tier-1 counts by slot: 0,1,2,0,1,2,0 -> ranked 2,5,1,4 | 0,3,6
        self.assertEqual(sorted(launched), [101, 102, 104, 105])
        self.assertEqual([c['source_slot'] for c in rec['closers']], [2, 5, 1, 4])
        self.assertEqual((rec['max_closers'], rec['skipped_closers'], rec['skipped_slots']), (4, 3, [0, 3, 6]))
        self.assertEqual(rec['calls'], 5)

    def test_no_leads_no_closers(self):
        rec, launched, _ = self.run_case([self.row(0), self.row(1)], fast=set(), accept=set())
        self.assertEqual((launched, rec['closers'], rec['rescue'], rec['tokens']), ([], [], False, 50))

    def test_first_accept_wins_and_cancels(self):
        rows = [self.row(s, ['55 * 15 = 825']) for s in range(4)]
        rec, launched, _ = self.run_case(rows, fast={102}, accept={102}, solved={102})
        self.assertEqual(rec['selected_slot'], 102)
        self.assertTrue(rec['rescue'] and rec['solved'] and not rec['wrong'])
        self.assertEqual(rec['cancelled_closers'] + rec['unstarted_closers'], 3)
        self.assertLess(rec['case_seconds'], 1.5)

    def test_accepted_wrong_plan_is_scored_wrong(self):
        rec, _, _ = self.run_case([self.row(4, ['55 * 15 = 825'])], fast={104}, accept={104}, solved=())
        self.assertTrue(rec['rescue'] and rec['wrong'] and not rec['solved'])

    def test_rejected_plans_do_not_rescue(self):
        rows = [self.row(s, ['55 * 15 = 825']) for s in range(3)]
        rec, launched, _ = self.run_case(rows, fast={100, 101, 102}, accept=set(), solved={101})
        self.assertFalse(rec['rescue'] or rec['solved'] or rec['wrong'])
        self.assertTrue(rec['oracle'])
        self.assertEqual(sorted(launched), [100, 101, 102])


class AskWantedRetryTests(unittest.TestCase):
    def test_transport_failure_is_retried_once(self):
        import run_judge
        attempts = []

        class Client:
            def __init__(self, endpoint, model, budget, events, seed):
                self.budget, self.seed, self.model, self.infra_failures = budget, seed, model, 0
                attempts.append(seed)

            def post(self, path, body, timeout):
                if len(attempts) == 1:
                    raise ConnectionRefusedError(61, 'Connection refused')
                return contextlib.nullcontext(io.StringIO(json.dumps(dict(tokens=[1, 2]))))

            def complete(self, agent_id, stage, ids, max_tokens, thinking_closed=False):
                self.budget.reserve(max_tokens)
                self.budget.settle(max_tokens, 20)
                return dict(text='822+3 = 825\n822-3 = 819', error=None)

        class Forced:
            ForcedClient = Client
        with tempfile.TemporaryDirectory() as d, patch.object(run_judge, '_forced72', lambda: Forced), \
                patch.object(v.time, 'sleep', lambda s: None):
            res = closers.ask_wanted('http://e/v1', Path(d) / 'w.jsonl', 77, [3], 822)
            files = sorted(p.name for p in Path(d).iterdir())
        self.assertEqual(attempts, [77, 77])
        self.assertEqual((res['values'], res['infra'], res['retry'], res['tokens']), ([825, 819], 0, True, 20))
        self.assertEqual(files, ['w.jsonl', 'w.retry.jsonl'])


class PlanOnlyTests(unittest.TestCase):
    def make_run(self, root):
        tasks = [dict(id='a', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822),
                 dict(id='b', split='evaluation', numbers=[1, 2, 3, 4, 5, 6], target=700)]
        (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=tasks)))
        run = root / 'runs' / 'arm'
        (run / 'agents').mkdir(parents=True)
        plan = dict(dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=2, seeds=[1, 2])
        (run / 'metadata.json').write_text(json.dumps(dict(protocol=plan)))

        def agent(slot, verdict=None):
            return dict(slot=slot, plan=None, verdict=verdict, started=True, cancelled=False, tokens=5)
        rows = [dict(task_id='a', seed=1, policy='roll12strategy', answered=False, tokens=100, agents=[agent(0), agent(1), agent(2, False)]),
                dict(task_id='b', seed=1, policy='roll12strategy', answered=True, tokens=40, agents=[agent(0, True)]),
                dict(task_id='b', seed=2, policy='roll12strategy', answered=False, tokens=60, agents=[agent(0), agent(1)])]
        (run / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        stem = run / 'agents'
        fake_events(stem / 'a-s1-roll12strategy-a0.jsonl', ['so 55*15=825 and 825-3 = 822', 'again 55 × 15 = 825'])
        fake_events(stem / 'a-s1-roll12strategy-a1.jsonl', ['nothing useful 3+4 = 7'])
        fake_events(stem / 'a-s1-roll12strategy-a2.jsonl', ['800+22 = 822'])
        fake_events(stem / 'b-s2-roll12strategy-a0.jsonl', ['700*2 = 1400'])
        # b s2 agent 1 has no trace (missing)
        return run

    def test_counts_without_model_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = self.make_run(root)
            buf = io.StringIO()
            boom = AssertionError('model call in plan-only')
            with patch.object(closer_replay, 'HERE', root), patch.object(closers, 'ask_wanted', side_effect=boom), \
                    patch.object(v, 'run_agent', side_effect=boom), contextlib.redirect_stdout(buf):
                self.assertEqual(closer_replay.main(['--runs', str(run), '--plan-only']), 0)
        out = [json.loads(line) for line in buf.getvalue().splitlines()]
        cases = [o for o in out if 'task_id' in o]
        self.assertEqual([(c['task_id'], c['seed'], c['case_index']) for c in cases], [('a', 1, 0), ('b', 2, 3)])
        a, b = cases
        self.assertEqual((a['failed_agents'], a['tier1_agents'], a['tier2_agents'], a['closers'], a['tier1_lines'], a['tier2_lines']),
                         (3, 1, 2, 2, 1, 2))
        self.assertEqual((b['failed_agents'], b['missing_traces'], b['tier1_agents'], b['closers']), (2, 1, 1, 1))
        total = out[-1]['total']
        self.assertEqual(out[-1]['model_calls'], 0)
        self.assertEqual((total['cases'], total['failed_agents'], total['tier1_agents'], total['tier2_agents'], total['closers']),
                         (2, 5, 2, 2, 3))

    def test_plan_only_cap_from_cli_and_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = self.make_run(root)
            (root / 'plan.json').write_text(json.dumps(dict(closers=dict(max_per_case=1))))
            totals = {}
            for name, extra in (('default', []), ('cli', ['--max-closers-per-case', '1']),
                                ('plan', ['--plan', str(root / 'plan.json')]),
                                ('cli_wins', ['--plan', str(root / 'plan.json'), '--max-closers-per-case', '3'])):
                buf = io.StringIO()
                with patch.object(closer_replay, 'HERE', root), contextlib.redirect_stdout(buf):
                    closer_replay.main(['--runs', str(run), '--plan-only'] + extra)
                last = json.loads(buf.getvalue().splitlines()[-1])
                totals[name] = (last['max_closers_per_case'], last['total']['closers'], last['total']['skipped_closers'])
        # case a has 2 agents with leads, case b has 1
        self.assertEqual(totals, dict(default=(4, 3, 0), cli=(1, 2, 1), plan=(1, 2, 1), cli_wins=(3, 3, 0)))

    def test_cli_limits(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = self.make_run(root)
            with patch.object(closer_replay, 'HERE', root):
                with self.assertRaisesRegex(Exception, '1..20'):
                    closer_replay.main(['--runs', str(run), '--plan-only', '--max-per-endpoint', '21'])
                with self.assertRaisesRegex(Exception, 'required for a run'):
                    closer_replay.main(['--runs', str(run)])


class EndpointSlotsTests(unittest.TestCase):
    def test_cap_per_endpoint(self):
        slots = closers.EndpointSlots(['e1', 'e2'], 2)
        peak, now, lock = [0], [0], threading.Lock()

        def hold():
            with slots('e1'):
                with lock:
                    now[0] += 1
                    peak[0] = max(peak[0], now[0])
                time.sleep(.05)
                with lock:
                    now[0] -= 1
        v.parallel([hold] * 6)
        self.assertEqual(peak[0], 2)


if __name__ == '__main__':
    unittest.main()
