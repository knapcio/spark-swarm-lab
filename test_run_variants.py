"""Offline orchestration tests for swarm variants (no model)."""
import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import run_variants as v

PLAN = dict(agent_variant='long_forced_original', agent_wall_deadline_seconds=3600,
            seed_offsets=dict(deep4=1400, strategy4=1500, repair4=1600, board2x2=1700))
TASK = dict(id='t', numbers=[1, 2, 3, 4], target=10)


class VariantTests(unittest.TestCase):
    def run_policy(self, policy, verdicts, plans=True):
        seen = []

        def execute(job, deadline_seconds):
            c = job['command']
            seen.append(Path(c[c.index('--extra-file') + 1]).read_text() if '--extra-file' in c else '')
            return dict(deadline=False)

        def plan_of(path):
            return dict(plan={'moves': [1]} if plans else None, verifier_solved=False, tokens=1, infra=0)

        calls = iter(verdicts)

        def judge(cand, endpoint, events_path, seed):
            return dict(verdict=next(calls), reason='move 2 uses index 5', infra=0, tokens=1)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute', execute), patch.object(v, 'plan_of', plan_of), \
                patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            (out / 'agents').mkdir(); (out / 'extra').mkdir(); (out / 'judges').mkdir()
            rec = v.run_policy(PLAN, Path('/src'), out, TASK, 1, 0, policy, v.Slots(8))
        return rec, seen

    def test_strategy_hints_are_distinct(self):
        rec, seen = self.run_policy('strategy4', [False] * 4)
        self.assertEqual(sorted(seen), sorted(v.STRATEGIES))

    def test_repair_feeds_critique_and_stops_on_accept(self):
        rec, seen = self.run_policy('repair4', [False, True])
        self.assertEqual(rec['calls'], 2)
        self.assertEqual(seen[0], '')
        self.assertIn('move 2 uses index 5', seen[1])
        self.assertTrue(rec['answered'])

    def test_board_round_two_sees_round_one(self):
        rec, seen = self.run_policy('board2x2', [False, False, False, False])
        self.assertEqual(rec['calls'], 4)
        self.assertTrue(all('Shared board' in s for s in seen[2:]))
        self.assertEqual(seen[:2], ['', ''])

    def test_board_skips_round_two_when_accepted(self):
        rec, _ = self.run_policy('board2x2', [True, False])
        self.assertEqual(rec['calls'], 2)


class CancelPolicyTests(unittest.TestCase):
    """deep4cancel / waves2cancel with a fake worker that runs until cancelled unless it is a 'fast' slot."""
    def run_policy(self, policy, fast, accept, boom=()):
        import threading, time
        started = []

        def execute(job, deadline_seconds, cancel=None):
            slot = int(job['events'].rsplit('-a', 1)[1].split('.')[0])
            started.append(slot)
            if slot in boom:
                raise RuntimeError('controller bug')
            if slot in fast:
                return dict(deadline=False, cancelled=False, returncode=0)
            for _ in range(200):  # slow agent: runs until the controller cancels it
                if cancel is not None and cancel.is_set():
                    return dict(deadline=False, cancelled=True, returncode=-15)
                time.sleep(.01)
            return dict(deadline=False, cancelled=False, returncode=0)

        def plan_of(path):
            return dict(plan={'moves': [1]}, verifier_solved=True, tokens=5, infra=0)

        def judge(cand, endpoint, events_path, seed):
            slot = int(str(events_path).rsplit('-a', 1)[1].split('.')[0])
            return dict(verdict=slot in accept, reason='', infra=0, tokens=1)
        plan = dict(PLAN, seed_offsets=dict(PLAN['seed_offsets'], deep4cancel=1400, waves2cancel=1400, roll8cancel=1400, roll12burst=1400, roll8repair=1400, roll8strategy=1400, roll3to8=1400, roll3strategy=1400, roll12strategy=1400, esc_none=1400, esc_strategy=1400, esc_h02=1400, esc_split=1400, esc_extra=1400), burst_seconds=0.3)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute', execute), patch.object(v, 'plan_of', plan_of), \
                patch.object(v, 'execute_cancellable', execute), patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            (out / 'agents').mkdir(); (out / 'extra').mkdir(); (out / 'judges').mkdir()
            self.last_out = d
            rec = v.run_policy(plan, Path('/src'), out, TASK, 1, 0, policy, v.Slots(8))
        return rec, started

    def test_first_accept_cancels_the_rest(self):
        rec, started = self.run_policy('deep4cancel', fast={2}, accept={2})
        self.assertIn(2, started)
        self.assertEqual(rec['selected_slot'], 2)
        self.assertTrue(rec['solved'] and rec['answered'])
        # every other agent is either terminated or never started (it may reach its slot after the accept)
        self.assertEqual(rec['cancelled_agents'] + rec['unstarted_agents'], 3)
        self.assertEqual(rec['calls'], 4)
        self.assertEqual(rec['infra'], 0)
        self.assertLess(rec['case_seconds'], 1.5)
        self.assertIsNotNone(rec['answer_seconds'])

    def test_rejected_fast_plan_does_not_cancel(self):
        rec, _ = self.run_policy('deep4cancel', fast={0, 1, 2, 3}, accept=set())
        self.assertFalse(rec['answered'])
        self.assertEqual(rec['cancelled_agents'], 0)
        self.assertIsNone(rec['selected_slot'])
        self.assertEqual(rec['calls'], 4)

    def test_waves_skip_second_wave_when_first_accepted(self):
        rec, started = self.run_policy('waves2cancel', fast={1}, accept={1})
        self.assertLessEqual(set(started), {0, 1})
        self.assertEqual(rec['selected_slot'], 1)
        self.assertEqual(rec['cancelled_agents'] + rec['unstarted_agents'], 3)

    def test_waves_run_second_wave_after_rejections(self):
        rec, started = self.run_policy('waves2cancel', fast={0, 1, 3}, accept={3})
        self.assertEqual(sorted(started), [0, 1, 2, 3])
        self.assertEqual(rec['selected_slot'], 3)
        self.assertEqual(rec['cancelled_agents'], 1)

    def test_roll_replaces_failures_until_accept(self):
        # slots 0-3 end fast and are rejected; replacements 4,5 fast rejected, 6 accepted; 7 may start and is cancelled
        rec, started = self.run_policy('roll8cancel', fast={0, 1, 2, 3, 4, 5, 6}, accept={6})
        self.assertEqual(rec['selected_slot'], 6)
        self.assertTrue(rec['answered'])
        self.assertLessEqual(set(started), set(range(8)))
        self.assertIn(6, started)
        self.assertGreaterEqual(rec['escalated_agents'], 3)

    def test_roll_caps_at_eight_agents(self):
        rec, started = self.run_policy('roll8cancel', fast=set(range(8)), accept=set())
        self.assertEqual(sorted(started), list(range(8)))
        self.assertFalse(rec['answered'])
        self.assertEqual(rec['escalated_agents'], 4)

    def test_roll_without_failures_is_deep4cancel(self):
        rec, started = self.run_policy('roll8cancel', fast={1}, accept={1})
        self.assertEqual(rec['selected_slot'], 1)
        self.assertEqual(rec['escalated_agents'], 0)
        self.assertLessEqual(set(started), {0, 1, 2, 3})

    def test_burst_adds_agents_when_no_accept_by_deadline(self):
        # slots 0-3 slow (run until cancelled); burst at 0.3 s starts slots 4-7; slot 5 is accepted
        rec, started = self.run_policy('roll12burst', fast={5}, accept={5})
        self.assertEqual(rec['selected_slot'], 5)
        self.assertTrue(rec['burst'])
        self.assertTrue({0, 1, 2, 3, 4, 5} <= set(started))
        self.assertLessEqual(max(started), 7)

    def test_burst_caps_at_twelve(self):
        rec, started = self.run_policy('roll12burst', fast=set(range(12)), accept=set())
        self.assertEqual(sorted(started), list(range(12)))
        self.assertFalse(rec['answered'])

    def test_no_burst_when_accepted_early(self):
        rec, started = self.run_policy('roll12burst', fast={2}, accept={2})
        self.assertFalse(rec['burst'])
        self.assertLessEqual(set(started), {0, 1, 2, 3})

    def test_roll8_unchanged_by_burst_code(self):
        rec, started = self.run_policy('roll8cancel', fast=set(range(8)), accept=set())
        self.assertEqual(sorted(started), list(range(8)))
        self.assertEqual(rec['escalated_agents'], 4)

    def test_repair_escalation_sees_rejected_plans_with_reasons(self):
        rec, started = self.run_policy('roll8repair', fast={0, 1, 2, 3, 4}, accept={4})
        self.assertEqual(rec['selected_slot'], 4)
        self.assertGreaterEqual(rec['escalated_agents'], 1)
        self.assertTrue(rec['agents'][4]['extra'])
        self.assertFalse(any(a['extra'] for a in rec['agents'][:4]))

    def test_strategy_escalation_gets_hints_only_after_failures(self):
        rec, started = self.run_policy('roll8strategy', fast=set(range(8)), accept=set())
        self.assertEqual(sorted(started), list(range(8)))
        self.assertFalse(any(a['extra'] for a in rec['agents'][:4]))
        self.assertTrue(all(a['extra'] for a in rec['agents'][4:]))

    def test_width3_starts_three_and_escalates_to_eight(self):
        rec, started = self.run_policy('roll3to8', fast=set(range(8)), accept=set())
        self.assertEqual(sorted(started), list(range(8)))
        self.assertEqual(rec['escalated_agents'], 5)

    def test_width3_accept_in_first_wave(self):
        rec, started = self.run_policy('roll3to8', fast={1}, accept={1})
        self.assertEqual(rec['selected_slot'], 1)
        self.assertLessEqual(set(started), {0, 1, 2})

    def test_width3_strategy_hints_from_slot_three(self):
        rec, started = self.run_policy('roll3strategy', fast=set(range(8)), accept=set())
        self.assertEqual(sorted(started), list(range(8)))
        self.assertFalse(any(a['extra'] for a in rec['agents'][:3]))
        self.assertTrue(all(a['extra'] for a in rec['agents'][3:]))
        self.assertEqual(rec['escalated_agents'], 5)

    def test_cap12_strategy_escalates_to_twelve_on_failures(self):
        rec, started = self.run_policy('roll12strategy', fast=set(range(12)), accept=set())
        self.assertEqual(sorted(started), list(range(12)))
        self.assertEqual(rec['escalated_agents'], 8)
        self.assertTrue(all(a['extra'] for a in rec['agents'][4:]))

    def test_escalation_only_arms_run_slots_4_to_11_with_their_hints(self):
        for policy, hints in (('esc_none', ['']*8), ('esc_strategy', [v.STRATEGIES[i % 4] for i in range(8)]),
                              ('esc_h02', [v.STRATEGIES[(0, 2)[i % 2]] for i in range(8)]), ('esc_split', [v.SPLIT_HINTS[i % 4] for i in range(8)])):
            rec, started = self.run_policy(policy, fast=set(range(12)), accept=set())
            self.assertEqual(sorted(started), list(range(4, 12)), policy)
            self.assertEqual([a['slot'] for a in rec['agents']], list(range(4, 12)))
            self.assertEqual([bool(a['extra']) for a in rec['agents']], [bool(h) for h in hints], policy)
            self.assertEqual([v.ESC_HINTS[policy](slot) for slot in range(4, 12)], hints, policy)
            self.assertEqual(rec['escalated_agents'], 8)
            self.assertFalse(rec['answered'])

    def test_escalation_only_arm_cancels_on_accept(self):
        rec, started = self.run_policy('esc_split', fast={5}, accept={5})
        self.assertEqual(rec['selected_slot'], 5)
        self.assertTrue(rec['solved'])
        self.assertTrue(set(started) <= set(range(4, 12)))
        self.assertLess(rec['case_seconds'], 1.5)

    def test_esc_extra_runs_slots_12_to_19_with_continued_hints(self):
        rec, started = self.run_policy('esc_extra', fast=set(range(20)), accept=set())
        self.assertEqual(sorted(started), list(range(12, 20)))
        self.assertEqual([a['slot'] for a in rec['agents']], list(range(12, 20)))
        self.assertEqual([v.ESC_HINTS['esc_extra'](s) for s in range(12, 20)], [v.STRATEGIES[i % 4] for i in range(8)])
        self.assertTrue(all(a['extra'] for a in rec['agents']))
        self.assertEqual(rec['escalated_agents'], 8)
        self.assertEqual(rec['unstarted_agents'], 0)
        self.assertEqual(v.ELIGIBLE_SLOTS['esc_extra'], 8)
        self.assertFalse(rec['answered'])

    def test_esc_extra_cancels_on_accept_and_counts_unstarted(self):
        rec, started = self.run_policy('esc_extra', fast={14}, accept={14})
        self.assertEqual(rec['selected_slot'], 14)
        self.assertTrue(rec['solved'])
        self.assertLessEqual(set(started), set(range(12, 20)))
        self.assertEqual(rec['cancelled_agents'], len(started) - 1)
        self.assertEqual(rec['unstarted_agents'], 8 - len(started))
        self.assertLess(rec['case_seconds'], 1.5)

    def test_esc_extra_keeps_eight_in_flight_two_per_node(self):
        import threading, time
        lock, state, nodes = threading.Lock(), dict(now=0, peak=0), {}

        def execute(job, deadline_seconds, cancel=None):
            with lock:
                state['now'] += 1
                state['peak'] = max(state['peak'], state['now'])
                nodes[job['endpoint']] = nodes.get(job['endpoint'], 0) + 1
                seed = int(job['command'][job['command'].index('--seed') + 1])
                state.setdefault('seeds', []).append(seed)
            time.sleep(.2)
            with lock:
                state['now'] -= 1
            return dict(deadline=False, cancelled=False, returncode=0)
        plan = dict(PLAN, seed_offsets=dict(esc_extra=1400))
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute_cancellable', execute), \
                patch.object(v, 'plan_of', lambda p: dict(plan=None, verifier_solved=False, tokens=1, infra=0)):
            out = Path(d)
            (out / 'agents').mkdir(); (out / 'extra').mkdir(); (out / 'judges').mkdir()
            rec = v.run_policy(plan, Path('/src'), out, TASK, 3, 1, 'esc_extra', v.Slots(20))
        self.assertEqual(state['peak'], 8)
        self.assertEqual(sorted(nodes.values()), [2, 2, 2, 2])
        self.assertEqual(sorted(state['seeds']), [3000 + 1400 + s for s in range(12, 20)])
        self.assertEqual(rec['escalated_agents'], 8)

    def test_per_node_request_cap_is_enforced(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tasks = [dict(id='t0', split='evaluation', numbers=[1, 2, 3, 4, 5, 6], target=7)]
            (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=tasks)))
            plan = dict(protocol='swarm-variants-screen-v1', source_revision='x', dataset=str(root / 'data.json'),
                        dataset_protocol='p', split='evaluation', tasks=1, seeds=[1], policies=['esc_extra'],
                        concurrent_policy_cases=1, concurrent_requests_per_endpoint=26)
            (root / 'plan.json').write_text(json.dumps(plan))
            with patch.object(v, 'validate_source', lambda *a: None), self.assertRaisesRegex(Exception, 'above 25'):
                v.main(['--plan', str(root / 'plan.json'), '--output', str(root / 'out'), '--source', d])
            (root / 'plan.json').write_text(json.dumps(dict(plan, concurrent_requests_per_endpoint=25)))
            with patch.object(v, 'validate_source', lambda *a: None):
                self.assertEqual(v.main(['--plan', str(root / 'plan.json'), '--output', str(root / 'out'), '--source', d]), 0)

    def test_rolling_agent_exception_is_an_infra_fault(self):
        # slot 4 raises at once; 5-7 run until their deadline loop ends; no replacement may start after the fault
        rec, started = self.run_policy('esc_none', fast=set(), accept=set(), boom={4})
        self.assertEqual(sorted(started), [4, 5, 6, 7])
        self.assertEqual([a['slot'] for a in rec['agents']], [4, 5, 6, 7])
        self.assertEqual(rec['infra'], 1)
        self.assertIn('RuntimeError', rec['agents'][0]['agent_error'])
        self.assertEqual(rec['unstarted_agents'], 4)
        self.assertFalse(rec['answered'])

    def test_rolling_exception_never_drops_a_slot(self):
        for policy in ('roll12strategy', 'roll8repair', 'esc_strategy'):
            rec, started = self.run_policy(policy, fast=set(range(12)), accept=set(), boom={5})
            self.assertEqual(sorted(a['slot'] for a in rec['agents']), sorted(started), policy)
            self.assertGreaterEqual(rec['infra'], 1, policy)

    def test_unstarted_counts_unlaunched_rolling_slots(self):
        for policy, eligible in (('esc_split', 8), ('roll12strategy', 12), ('roll8strategy', 8)):
            first = 4 if policy.startswith('esc_') else 0
            rec, started = self.run_policy(policy, fast={first + 1}, accept={first + 1})
            self.assertEqual(rec['selected_slot'], first + 1, policy)
            # all four first slots launch; one that reaches its slot after the accept never starts (started=False)
            self.assertEqual([a['slot'] for a in rec['agents']], list(range(first, first + 4)), policy)
            self.assertEqual(rec['cancelled_agents'], len(started) - 1, policy)
            self.assertEqual(rec['unstarted_agents'], eligible - len(started), policy)
            self.assertGreaterEqual(rec['unstarted_agents'], eligible - 4, policy)

    def test_unstarted_width3_and_full_cap(self):
        rec, started = self.run_policy('roll3to8', fast={1}, accept={1})
        self.assertEqual(rec['unstarted_agents'], 8 - len(started))
        self.assertGreaterEqual(rec['unstarted_agents'], 5)
        rec, _ = self.run_policy('roll8cancel', fast=set(range(8)), accept=set())
        self.assertEqual(rec['unstarted_agents'], 0)

    def test_deep4_keeps_slot_order_selection(self):
        rec, started = self.run_policy('deep4', fast={0, 1, 2, 3}, accept={1, 3})
        self.assertEqual(rec['selected_slot'], 1)
        self.assertNotIn('cancelled_agents', rec)


class CaseListTests(unittest.TestCase):
    def plan_mode(self, cases):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tasks = [dict(id=f't{i}', split='evaluation', numbers=[1, 2, 3, 4, 5, 6], target=7) for i in range(3)]
            (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=tasks)))
            (root / 'cases.json').write_text(json.dumps(dict(cases=cases)))
            (root / 'plan.json').write_text(json.dumps(dict(
                protocol='swarm-variants-screen-v1', source_revision='x', dataset=str(root / 'data.json'),
                dataset_protocol='p', split='evaluation', tasks=3, numbers_count=6, seeds=[1, 2], policies=['esc_none'],
                case_list=str(root / 'cases.json'), concurrent_policy_cases=1)))
            with patch.object(v, 'validate_source', lambda *a: None):
                return v.main(['--plan', str(root / 'plan.json'), '--output', str(root / 'out'), '--source', d])

    def test_case_list_filters(self):
        self.assertEqual(self.plan_mode([['t0', 1], ['t2', 2]]), 0)

    def test_case_list_rejects_duplicates(self):
        with self.assertRaisesRegex(Exception, 'duplicate'):
            self.plan_mode([['t0', 1], ['t2', 2], ['t0', 1]])

    def test_case_list_rejects_unknown(self):
        with self.assertRaisesRegex(Exception, 'does not match'):
            self.plan_mode([['t0', 1], ['t9', 1]])


class StrictHardCasesTests(unittest.TestCase):
    from inkling import strict_hard_cases as shc
    EXPECTED = {('a', 1), ('a', 2), ('b', 1), ('b', 2)}

    def row(self, t, s, **kw):
        return dict(dict(task_id=t, seed=s, infra=0, answered=False, solved=False, wrong=False), **kw)

    def test_expected_keys_follow_wave_plan(self):
        import json
        plan = json.loads((Path(v.HERE) / 'SWARM_HINTS_HARD16_WAVE_PLAN.json').read_text())
        tasks = [dict(id=f't{i}', split='evaluation', numbers=[1] * 6) for i in range(24)]
        tasks += [dict(id='x5', split='evaluation', numbers=[1] * 5), dict(id='d6', split='development', numbers=[1] * 6)]
        self.assertEqual(len(self.shc.expected_keys(plan, dict(tasks=tasks))), 192)
        with self.assertRaises(ValueError):
            self.shc.expected_keys(plan, dict(tasks=tasks[1:]))

    def test_complete_wave_selects(self):
        rows = [self.row(t, s, answered=(t == 'a')) for t, s in sorted(self.EXPECTED)]
        self.assertEqual(set(self.shc.select([rows], self.EXPECTED)), self.EXPECTED)

    def test_missing_case_fails(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.shc.select([[self.row(t, s) for t, s in sorted(self.EXPECTED)[:3]]], self.EXPECTED)

    def test_unresolved_infra_or_error_fails(self):
        clean = [self.row(t, s) for t, s in sorted(self.EXPECTED)[:3]]
        for bad in (self.row('b', 2, infra=1), dict(task_id='b', seed=2, error='boom')):
            with self.assertRaisesRegex(ValueError, 'infra fault or error'):
                self.shc.select([clean + [bad]], self.EXPECTED)

    def test_fault_rerun_in_resume_segment_is_accepted(self):
        seg0 = [self.row(t, s) for t, s in sorted(self.EXPECTED)[:3]] + [self.row('b', 2, infra=1)]
        cases = self.shc.select([seg0, [self.row('b', 2)]], self.EXPECTED)
        self.assertEqual(cases[('b', 2)]['infra'], 0)

    def test_duplicate_clean_or_unknown_case_fails(self):
        rows = [self.row(t, s) for t, s in sorted(self.EXPECTED)]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.shc.select([rows, [self.row('a', 1)]], self.EXPECTED)
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.shc.select([rows + [self.row('z', 1)]], self.EXPECTED)


class JudgeRetryTests(unittest.TestCase):
    """judge_with_reason with a fake ChatJudge client (no HTTP)."""
    STREAM = "ConnectionError: server stream error: {'message': 'ServerDisconnectedError: Server disconnected'}"

    def run_judge(self, behaviors):
        import json, urllib.error
        import run_judge
        made = []

        class Fake:
            def __init__(self, endpoint, model, budget, events, seed):
                self.budget, self.events, self.seed, self.infra_failures = budget, events, seed, 0
                self.behavior = behaviors[len(made)]
                made.append(self)

            def chat_prompt_ids(self, prompt, thinking=True):
                if self.behavior == 'refused':
                    raise urllib.error.URLError(ConnectionRefusedError(61, 'Connection refused'))
                if self.behavior == 'bad_request':
                    raise urllib.error.HTTPError('u', 400, 'Bad Request', {}, None)
                return [1, 2, 3]

            def force_ids(self):
                return [9]

            def complete(self, agent_id, stage, ids, max_tokens, thinking_closed=False):
                self.budget.reserve(max_tokens)
                if self.behavior in ('stream', 'mismatch'):
                    self.infra_failures += 1
                    self.budget.settle(max_tokens, None if self.behavior == 'stream' else 100)
                    error = Self.STREAM if self.behavior == 'stream' else 'token id count 99 != reported 100'
                    return dict(error=error, answer=None, finish_reason=None, token_ids=[])
                self.budget.settle(max_tokens, 100)
                return dict(error=None, answer=json.dumps(dict(valid=self.behavior == 'ok_true', reason='r')),
                            finish_reason='stop', token_ids=[5] * 100)
        Self = self
        sleeps = []
        cand = dict(numbers=[1, 2, 3, 4], target=10, plan={'moves': [{'i': 0, 'j': 1, 'op': '+'}]})
        with tempfile.TemporaryDirectory() as d, patch.object(run_judge, 'ChatJudge', Fake), \
                patch.object(v.time, 'sleep', sleeps.append):
            path = Path(d) / 't-s1-esc_extra-a12.jsonl'
            try:
                result = v.judge_with_reason(cand, 'http://e/v1', path, 4242)
            except Exception as exc:
                result = exc
                if isinstance(exc, urllib.error.HTTPError):
                    exc.close()
            files = sorted(p.name for p in Path(d).iterdir())
        return result, made, sleeps, files

    def test_success_is_unchanged(self):
        res, made, sleeps, files = self.run_judge(['ok_true'])
        self.assertEqual(res, dict(verdict=True, reason='r', infra=0, tokens=100))
        self.assertEqual((len(made), sleeps, files), (1, [], ['t-s1-esc_extra-a12.jsonl']))

    def test_stream_error_retried_once_with_same_seed(self):
        res, made, sleeps, files = self.run_judge(['stream', 'ok_false'])
        self.assertEqual((res['verdict'], res['infra'], res['retry']), (False, 0, True))
        self.assertIn('server stream error', res['first_error'])
        self.assertEqual(res['tokens'], 6144 + 100)
        self.assertEqual([m.seed for m in made], [4242, 4242])
        self.assertEqual(sleeps, [v.JUDGE_RETRY_SECONDS])
        self.assertEqual(files, ['t-s1-esc_extra-a12.jsonl', 't-s1-esc_extra-a12.retry.jsonl'])

    def test_retry_failure_returns_infra(self):
        res, made, sleeps, _ = self.run_judge(['stream', 'stream'])
        self.assertEqual((res['verdict'], res['infra'], res['retry'], len(made)), (None, 1, True, 2))

    def test_refused_connection_on_tokenize_is_retried(self):
        res, made, sleeps, _ = self.run_judge(['refused', 'ok_true'])
        self.assertEqual((res['verdict'], res['infra'], res['retry'], res['tokens']), (True, 0, True, 100))
        self.assertIn('Connection refused', res['first_error'])

    def test_refused_twice_raises_as_today(self):
        res, made, _, _ = self.run_judge(['refused', 'refused'])
        self.assertIsInstance(res, OSError)
        self.assertEqual(len(made), 2)

    def test_non_transport_faults_are_not_retried(self):
        res, made, sleeps, _ = self.run_judge(['mismatch'])
        self.assertEqual((res['infra'], len(made), sleeps), (1, 1, []))
        self.assertNotIn('retry', res)
        res, made, _, _ = self.run_judge(['bad_request'])
        self.assertIsInstance(res, Exception)
        self.assertEqual(len(made), 1)

    def test_transport_classifier(self):
        for e in (self.STREAM, 'ConnectionError: stream ended without finish_reason',
                  'URLError: <urlopen error [Errno 61] Connection refused>', 'RemoteDisconnected: Remote end closed',
                  'TimeoutError: timed out', 'HTTPError: HTTP Error 503: Service Unavailable'):
            self.assertTrue(v.transport_error(e), e)
        for e in (None, '', 'token id count 3 != reported 4', 'budget_exhausted', 'HTTPError: HTTP Error 400: Bad Request',
                  'ValueError: bad json'):
            self.assertFalse(v.transport_error(e), e)

    def test_agent_records_judge_retry(self):
        def judge(cand, endpoint, events_path, seed):
            return dict(verdict=True, reason='', infra=0, tokens=7, retry=True, first_error=self.STREAM)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute', lambda job, deadline_seconds: dict(deadline=False)), \
                patch.object(v, 'plan_of', lambda p: dict(plan={'moves': [1]}, verifier_solved=True, tokens=1, infra=0)), \
                patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            (out / 'agents').mkdir(); (out / 'extra').mkdir(); (out / 'judges').mkdir()
            rec = v.run_policy(PLAN, Path('/src'), out, TASK, 1, 0, 'deep4', v.Slots(8))
        self.assertTrue(all(a['judge_retry'] for a in rec['agents']))
        self.assertEqual(rec['agents'][0]['judge_first_error'], self.STREAM)
        self.assertEqual(rec['infra'], 0)


class ExecuteCancellableTests(unittest.TestCase):
    """The real process-group executor with a fake worker process (no model)."""
    def case(self, root, sleep):
        import json, sys
        trace = root / 'a.jsonl'
        rec = json.dumps(dict(event_id=1, run_id='r', method='m', type='request_start', request_id='x'))
        code = f"import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(sys.argv[2]); time.sleep({sleep})"
        return dict(arm='deep4cancel', events=str(trace), stdout=str(root / 'o.log'), stderr=str(root / 'e.log'),
                    command=[sys.executable, '-c', code, str(trace), rec + '\n'])

    def test_cancel_terminates_process_group(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            root, cancel = Path(d), threading.Event()
            threading.Timer(.3, cancel.set).start()
            row = v.execute_cancellable(self.case(root, 30), 60, cancel)
            last = v.read_trace(root / 'a.jsonl')[0][-1]
        self.assertTrue(row['cancelled'])
        self.assertEqual(row['status'], 'cancelled')
        self.assertFalse(row['deadline'])
        self.assertLess(row['returncode'], 0)
        self.assertLess(row['wall_seconds'], 5)
        self.assertEqual((last['type'], last['status']), ('controller_stop', 'cancelled'))

    def test_unset_cancel_lets_worker_finish(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            row = v.execute_cancellable(self.case(Path(d), .2), 60, threading.Event())
        self.assertFalse(row['cancelled'] or row['deadline'] or row['controller_stop'])
        self.assertEqual(row['returncode'], 0)

    def test_deadline_still_applies(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            row = v.execute_cancellable(self.case(Path(d), 30), .3, threading.Event())
        self.assertTrue(row['deadline'])
        self.assertFalse(row['cancelled'])


if __name__ == '__main__':
    unittest.main()
