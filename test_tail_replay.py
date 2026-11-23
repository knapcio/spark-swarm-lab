"""tail_replay on authored recorded runs with a mocked transport; no network, no model calls."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import forced72 as f
import tail_replay as t
from followup72 import sha
from test_forced72 import sse

NUMBERS, TARGET = [2, 6, 25, 100], 187
PROMPT_IDS = [1, 2, 3]
THINK, TOTAL = f.CAPS['xl_forced_original']
# 100+6=106 -> [2,25,106]; 106*2=212 -> [25,212]; 212-25=187
GOOD = '{"moves":[{"i":3,"j":1,"op":"+"},{"i":2,"j":0,"op":"*"},{"i":1,"j":0,"op":"-"}]}'
VARIED = ''.join(f'step {i}: try {i * 37 % 101} times {i % 7} gives {i * 37 % 101 * (i % 7)}; ' for i in range(300))
LOOP = 'so the answer is 5 and the answer is 5. ' * 600


def agent_file(directory, stem, *, reasoning='notes', response=None, ids=None, finish='length', max_tokens=THINK,
               prompt_sha=None, extra='', started=True, variant='xl_forced_original', usage=True):
    ids = [7] * THINK if ids is None else ids
    rows = [dict(type='run_start', config=dict(variant=variant, puzzle='2,6,25,100:187', seed=16400)),
            dict(type='extra_prompt', text=extra)]
    if started:
        rows.append(dict(type='request_start', request_id='orig1', stage='plan', request_max_tokens=max_tokens,
                         request_body=dict(seed=123), prompt_ids_sha256=prompt_sha or sha(json.dumps(PROMPT_IDS))))
        rows.append(dict(type='request_end', request_id='orig1', stage='plan', error=None, response_received=True,
                         finish_reason=finish, closed_thinking=response is not None, reasoning=reasoning,
                         response=response, token_ids=ids, usage=dict(completion_tokens=len(ids)) if usage else {}))
        rows.append(dict(type='puzzle_end', plan=None, solved=False))
    path = Path(directory) / 'agents' / (stem + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return path


def cases_file(directory, verdicts, answered, infra=None):
    Path(directory).mkdir(parents=True, exist_ok=True)
    with open(Path(directory) / 'cases.jsonl', 'w') as handle:
        for (task, seed), slots in verdicts.items():
            handle.write(json.dumps(dict(task_id=task, seed=seed, answered=answered[(task, seed)],
                                         solved=answered[(task, seed)], wrong=False,
                                         infra=(infra or {}).get((task, seed), 0),
                                         agents=[dict(slot=s, verdict=v) for s, v in slots.items()])) + '\n')


def corpus(root, run):
    """metadata + corpus so case_index follows run_variants: seeds [1, 2] x tasks [eva-h1, eva-h2]."""
    data = Path(root) / 'datasets' / 'd' / 'tasks.json'
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps(dict(protocol='d', tasks=[dict(id='eva-h0', split='development', numbers=NUMBERS),
                                                         dict(id='eva-h1', split='evaluation', numbers=NUMBERS),
                                                         dict(id='eva-h2', split='evaluation', numbers=NUMBERS)])))
    Path(run).mkdir(parents=True, exist_ok=True)
    (Path(run) / 'metadata.json').write_text(json.dumps(dict(protocol=dict(
        dataset='datasets/d/tasks.json', dataset_protocol='d', split='evaluation', tasks=2, seeds=[1, 2]))))


class Transport:
    """Mocked shim: /tokenize renders one token per character (chat prompt -> PROMPT_IDS), completions are queued."""
    def __init__(self, replies):
        self.replies, self.bodies, self.paths = list(replies), [], []

    def __call__(self, client, path, body, timeout):
        self.paths.append(path)
        if path == '/tokenize':
            if 'messages' in body:
                self.prompt = body['messages'][1]['content']
                return io.BytesIO(json.dumps(dict(tokens=PROMPT_IDS)).encode())
            if body['prompt'] == f.FORCE_TEXT:
                return io.BytesIO(json.dumps(dict(tokens=[9, 13, 9])).encode())
            return io.BytesIO(json.dumps(dict(tokens=[1000 + ord(c) for c in body['prompt']])).encode())
        self.bodies.append(body)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def text_ids(text):
    return [1000 + ord(c) for c in text]


class ControllerTextTests(unittest.TestCase):
    def test_recall_values_are_plain_arithmetic_positive_integers_only(self):
        values = dict(t.recall_values(NUMBERS, TARGET))
        self.assertEqual(values['187+2'], 189)
        self.assertEqual(values['187-100'], 87)
        self.assertEqual(values['187*25'], 4675)
        self.assertNotIn('187/2', values)  # not an integer
        self.assertEqual(dict(t.recall_values([10, 10, 5], 5)), {'5+10': 15, '5*10': 50, '5+5': 10, '5*5': 25, '5/5': 1})

    def test_recall_text_wording(self):
        text = t.recall_text(NUMBERS, TARGET)
        self.assertTrue(text.startswith('\n\nBefore answering: the target plus, minus, times and divided by each given'))
        self.assertIn('187+2=189, 187-2=185, 187*2=374, 187+6=193', text)
        self.assertTrue(text.endswith('. Did any of these values, or the target itself, appear as a result above? '
                                      'If yes, write that derivation as the plan.\n'))
        self.assertNotIn(f.END_THINK, text)

    def test_loop_trigger_twelve_checks(self):
        self.assertIsNone(t.loop_trigger(VARIED))
        trigger = t.loop_trigger(VARIED + LOOP)
        self.assertEqual(trigger['checks'], 12)
        self.assertEqual(trigger['fire_char'] - trigger['loop_start_char'], t.LOOP_WINDOW + 11 * t.LOOP_STEP)
        self.assertLess(abs(trigger['loop_start_char'] - len(VARIED)), t.LOOP_WINDOW)
        self.assertLess(t.loop_trigger(VARIED + LOOP, hits=2)['fire_char'], trigger['fire_char'])
        self.assertEqual(t.rewind_cut_char(trigger), trigger['loop_start_char'] - t.REWIND_MARGIN_CHARS)
        self.assertIsNone(t.loop_trigger(VARIED + f.END_THINK + LOOP))  # only while thinking is open


class RunDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs' / 'swarm-x'
        self.addCleanup(self.tmp.cleanup)

    def build(self):
        loop_text = VARIED + LOOP
        corpus(self.root, self.run)
        # (eva-h1, 1): abstained in the recording
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a0')                          # exhausted, rejected
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a1', reasoning=loop_text, ids=[7] * 5000)  # loop, rejected
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a2', started=False)            # cancelled
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a3', reasoning='n', response=GOOD, ids=[5] * 40, finish='stop')
        # (eva-h2, 1): answered in the recording
        agent_file(self.run, 'eva-h2-s1-roll12strategy-a0', usage=False)              # exhausted, usage missing
        agent_file(self.run, 'eva-h2-s1-roll12strategy-a1', reasoning='n', response=GOOD, ids=[5] * 40,
                   finish='stop')                                                     # accepted
        agent_file(self.run, 'eva-h2-s1-roll12strategy-a4', reasoning=loop_text)      # exhausted AND looping, accepted
        agent_file(self.run, 'eva-h2-s1-roll12strategy-a5', reasoning='n', response=GOOD, ids=[5] * 40,
                   finish='stop', usage=False)                                        # no usage, not a length cut
        # (eva-h1, 2): not in cases.jsonl
        agent_file(self.run, 'eva-h1-s2-roll12strategy-a0')
        cases_file(self.run, {('eva-h1', 1): {0: False, 1: False, 2: None, 3: False},
                              ('eva-h2', 1): {0: None, 1: True, 4: True, 5: False}},
                   {('eva-h1', 1): False, ('eva-h2', 1): True})
        return t.load_runs([self.run])


class PlanOnlyTests(RunDir):
    def test_default_cohort_is_the_recorded_abstentions(self):
        agents = self.build()
        recall = t.plan_listing(agents, 'recall')
        self.assertEqual([i['stem'] for i in recall['items']], ['eva-h1-s1-roll12strategy-a0'])
        self.assertEqual(recall['skipped'], {'case_answered': 4, 'case_not_recorded': 1, 'no_finished_plan_stream': 1,
                                             'not_at_thinking_budget': 1, 'not_length': 1})
        self.assertEqual((recall['cohort'], recall['cohort_cases'], recall['cases'], recall['experimental']),
                         ('abstained', 1, 1, False))
        rewind = t.plan_listing(agents, 'rewind')
        self.assertTrue(rewind['experimental'])
        self.assertEqual([i['stem'] for i in rewind['items']], ['eva-h1-s1-roll12strategy-a1'])
        item = rewind['items'][0]
        self.assertEqual(item['kept_tokens_estimate'], round(item['cut_char'] * 5000 / len(VARIED + LOOP)))

    def test_case_list_freezes_the_cohort(self):
        agents = self.build()
        cohort = {('eva-h2', 1), ('eva-h9', 1)}
        recall = t.plan_listing(agents, 'recall', cohort=cohort)
        self.assertEqual([i['stem'] for i in recall['items']], ['eva-h2-s1-roll12strategy-a0'])  # usage missing, length
        self.assertEqual(recall['skipped'], {'accepted': 1, 'case_not_in_case_list': 5, 'not_length': 1,
                                             'token_ids_missing_or_inconsistent': 1})
        self.assertEqual((recall['cohort'], recall['case_list_missing']), ('case_list', [['eva-h9', 1]]))
        self.assertEqual(t.plan_listing(agents, 'recall', include_accepted=True, cohort=cohort)['eligible'], 2)

    def test_case_index_follows_run_variants(self):
        agents = self.build()
        index = {(a['task_id'], a['seed']): a['case_index'] for a in agents}
        self.assertEqual((index['eva-h1', 1], index['eva-h2', 1], index['eva-h1', 2]), (0, 1, 2))
        self.assertEqual(t.judge_seed(agents[0]), 90000 + 1000 * 1 + 10 * 0 + 0)

    def test_read_case_list(self):
        path = self.root / 'cases.json'
        path.write_text(json.dumps([['eva-h1', 1], ['eva-h2', 2]]))
        self.assertEqual(t.read_case_list(path), {('eva-h1', 1), ('eva-h2', 2)})
        for bad in ([['eva-h1', 1], ['eva-h1', 1]], [['eva-h1', '1']], {'cases': []}):
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                t.read_case_list(path)

    def test_main_plan_only_makes_no_request(self):
        self.build()
        (self.root / 'list.json').write_text(json.dumps([['eva-h1', 1]]))
        out = io.StringIO()
        with mock.patch.object(f.ForcedClient, 'post', side_effect=AssertionError('network')), \
                mock.patch.object(t, 'load_judge', side_effect=AssertionError('judge')), \
                contextlib.redirect_stdout(out):
            self.assertEqual(t.main(['--plan-only', '--mode', 'rewind', '--runs', str(self.run),
                                     '--case-list', str(self.root / 'list.json')]), 0)
        listing = json.loads(out.getvalue())
        self.assertEqual((listing['model_calls'], listing['eligible'], listing['cases'], listing['experimental']),
                         (0, 1, 1, True))

    def test_resume_segments_replace_the_faulted_case(self):
        corpus(self.root, self.run)
        resume = self.run.with_name(self.run.name + '-resume1')
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a0')                 # faulted segment: superseded
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a1')
        agent_file(self.run, 'eva-h2-s1-roll12strategy-a0')                 # clean in the first segment
        cases_file(self.run, {('eva-h1', 1): {0: False, 1: False}, ('eva-h2', 1): {0: False}},
                   {('eva-h1', 1): False, ('eva-h2', 1): False}, infra={('eva-h1', 1): 1})
        for slot in range(3):
            agent_file(resume, f'eva-h1-s1-roll12strategy-a{slot}')
        agent_file(resume, 'eva-h2-s1-roll12strategy-a0')                   # faulted rerun never replaces clean
        cases_file(resume, {('eva-h1', 1): {0: False, 1: False, 2: False}, ('eva-h2', 1): {0: False}},
                   {('eva-h1', 1): False, ('eva-h2', 1): False}, infra={('eva-h2', 1): 1})
        for runs in ([self.run], [self.run, resume], [resume]):
            agents = t.load_runs(runs)
            where = sorted((a['task_id'], a['slot'], a['segment']) for a in agents)
            self.assertEqual(where, [('eva-h1', 0, 'swarm-x-resume1'), ('eva-h1', 1, 'swarm-x-resume1'),
                                     ('eva-h1', 2, 'swarm-x-resume1'), ('eva-h2', 0, 'swarm-x')], runs)
            self.assertEqual({a['run'] for a in agents}, {'swarm-x'})
            self.assertEqual({a['case_index'] for a in agents if a['task_id'] == 'eva-h1'}, {0})  # base plan order
            listing = t.plan_listing(agents, 'recall')
            self.assertEqual((listing['cohort_cases'], listing['eligible']), (2, 4))

    def test_retried_recorded_request_is_checked_on_its_delivered_attempt(self):
        path = agent_file(self.run, 'eva-h1-s1-p-a0')
        agent = t.load_agent(path, {})
        agent['end'].update(attempts=2, attempt_completion_tokens=[100, THINK],
                            usage=dict(completion_tokens=THINK + 100, lost_attempt_completion_tokens=100))
        self.assertIsNone(t.stream_problem(agent))
        agent['end']['attempt_completion_tokens'] = [100, THINK - 1]
        self.assertEqual(t.stream_problem(agent), 'token_ids_missing_or_inconsistent')

    def test_help_marks_rewind_experimental(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(out):
            t.main(['--help'])
        self.assertIn('EXPERIMENTAL', out.getvalue())

    def test_concurrency_limit(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            t.main(['--plan-only', '--mode', 'recall', '--runs', str(self.run), '--max-concurrency', '21'])
        with self.assertRaises(ValueError):
            t.run_replays([], 'recall', ['http://x/v1'], Path(self.tmp.name) / 'o.jsonl', 0, 'm')


class ReplayTests(RunDir):
    def replay(self, stem, mode, replies, **file_kwargs):
        path = agent_file(self.run, stem, **file_kwargs)
        agent = t.load_agent(path, {})  # no cases.jsonl / corpus: case_index unknown
        transport = Transport(replies)
        with mock.patch.object(f.ForcedClient, 'post', lambda client, p, b, timeout: transport(client, p, b, timeout)), \
                mock.patch.object(f, 'RETRY_DELAY', 0):
            record = t.replay_one(agent, mode, 'http://127.0.0.1:1/v1', 'm', Path(self.tmp.name) / f'{stem}-{mode}.jsonl')
        return record, transport

    def test_recall_continues_the_same_sequence_then_forces(self):
        gen = list(range(THINK))
        record, tr = self.replay('eva-h1-s1-p-a0', 'recall', [sse('looked back, 106*2=212', [8] * t.RECALL_MAX_TOKENS, 'length'),
                                                             sse(GOOD, [9] * 30, 'stop')], ids=gen)
        recall_ids = text_ids(t.recall_text(NUMBERS, TARGET))
        first, second = tr.bodies
        self.assertEqual(first['prompt'], PROMPT_IDS + gen + recall_ids)
        self.assertEqual(first['max_tokens'], t.RECALL_MAX_TOKENS)
        self.assertEqual(second['prompt'], PROMPT_IDS + gen + recall_ids + [8] * t.RECALL_MAX_TOKENS + [9, 13, 9])
        self.assertEqual(second['max_tokens'], TOTAL - THINK)  # the worker's post-cut answer budget
        self.assertIsNone(record['error'])
        self.assertTrue(record['budget_forced'] and record['verifier_solved'])
        self.assertEqual(record['candidate'], dict(numbers=NUMBERS, target=TARGET, plan=json.loads(GOOD)))
        self.assertEqual((record['continuation_tokens'], record['answer_tokens'], record['tokens_generated']),
                         (t.RECALL_MAX_TOKENS, 30, t.RECALL_MAX_TOKENS + 30))
        self.assertEqual([c['stage'] for c in record['calls']], ['recall', 'forced_answer'])
        json.dumps(record)

    def test_recall_that_closes_thinking_itself_needs_one_call(self):
        record, tr = self.replay('eva-h1-s1-p-a0', 'recall', [sse('yes: 212-25</think>' + GOOD, [8] * 50, 'stop')])
        self.assertEqual(len(tr.bodies), 1)
        self.assertFalse(record['budget_forced'])
        self.assertEqual(record['plan'], json.loads(GOOD))

    def test_recall_unparseable_answer_has_no_candidate(self):
        record, _ = self.replay('eva-h1-s1-p-a0', 'recall', [sse('x</think>The plan: ' + GOOD, [8] * 5, 'stop')])
        self.assertIsNone(record['plan'])
        self.assertIsNone(record['candidate'])
        self.assertFalse(record['verifier_solved'])

    def test_rewind_cuts_before_the_loop_and_nudges(self):
        full = VARIED + LOOP
        gen = list(range(5000))
        cut = t.rewind_cut_char(t.loop_trigger(full))
        kept = round(cut * len(gen) / len(full))  # one token per character in the mock tokenizer
        record, tr = self.replay('eva-h1-s1-p-a1', 'rewind',
                                 [sse('fresh try ' * 5, [8] * (THINK - kept), 'length'), sse(GOOD, [9] * 20, 'stop')],
                                 reasoning=full, ids=gen, finish='stop')
        first, second = tr.bodies
        self.assertEqual(first['prompt'], PROMPT_IDS + gen[:kept] + text_ids(t.NUDGE))
        self.assertEqual(first['max_tokens'], THINK - kept)  # up to the original thinking budget
        self.assertNotEqual(first['seed'], 123)
        self.assertEqual(record['splice']['dropped_tokens'], len(gen) - kept)
        self.assertEqual(second['max_tokens'], TOTAL - THINK)  # the normal forcing path: total - kept - new
        self.assertEqual(second['prompt'][-3:], [9, 13, 9])
        self.assertTrue(record['verifier_solved'] and record['budget_forced'])
        self.assertEqual(record['splice']['cut_char'], cut)
        self.assertIsNone(record['continuation_loop_trigger'])

    def test_rewind_continuation_budget_never_exceeds_thinking_cap(self):
        full = VARIED + LOOP
        record, tr = self.replay('eva-h1-s1-p-a1', 'rewind', [sse('x</think>' + GOOD, [8] * 3, 'stop')],
                                 reasoning=full, ids=[7] * THINK)
        self.assertEqual(record['splice']['kept_tokens'] + tr.bodies[0]['max_tokens'], THINK)

    def test_prompt_mismatch_is_an_error_without_completion_calls(self):
        record, tr = self.replay('eva-h1-s1-p-a0', 'recall', [], prompt_sha='0' * 64)
        self.assertIn('prompt ids differ', record['error'])
        self.assertEqual(tr.bodies, [])

    def test_extra_prompt_is_part_of_the_rebuilt_prompt(self):
        _, tr = self.replay('eva-h1-s1-p-a0', 'recall', [sse('x</think>' + GOOD, [8], 'stop')], extra='Try products first.')
        self.assertTrue(tr.prompt.endswith('\nTry products first.'))

    def test_disconnect_in_continuation_is_retried(self):
        error = io.BytesIO(b'data: {"error": {"message": "ServerDisconnectedError: Server disconnected"}}\n\n')
        record, tr = self.replay('eva-h1-s1-p-a0', 'recall', [error, sse('x</think>' + GOOD, [8], 'stop')])
        self.assertEqual(len(tr.bodies), 2)
        self.assertEqual(tr.bodies[0], tr.bodies[1])
        self.assertIsNone(record['error'])

    def test_run_replays_judges_and_marks_rescues(self):
        agents = self.build()
        transport = Transport([sse('x</think>' + GOOD, [8] * 4, 'stop') for _ in range(2)])
        seeds = []

        def judge(candidate, endpoint, events_path, seed):
            seeds.append(seed)
            self.assertEqual(set(candidate), {'numbers', 'target', 'plan'})
            return dict(verdict=True, reason='', tokens=11, infra=0)
        out = self.root / 'recall.jsonl'
        with mock.patch.object(f.ForcedClient, 'post', lambda client, p, b, timeout: transport(client, p, b, timeout)):
            summary = t.run_replays(agents, 'recall', ['http://a/v1'], out, 1, 'm',
                                    cohort={('eva-h1', 1), ('eva-h2', 1)}, judge=judge)
        self.assertEqual(sorted(seeds), [91000, 91010])  # 90000 + 1000*seed + 10*case_index + slot
        self.assertEqual((summary['replays'], summary['plans'], summary['judge_accepted'], summary['case_rescues'],
                          summary['agent_accept_cases'], summary['judge_accepted_wrong']), (2, 2, 2, 1, 1, 0))
        records = {r['stem']: r for r in map(json.loads, out.read_text().splitlines())}
        self.assertEqual(records['eva-h1-s1-roll12strategy-a0']['accept_kind'], 'case_rescue')
        self.assertEqual(records['eva-h2-s1-roll12strategy-a0']['accept_kind'], 'agent_accept')
        rows = {(r['task_id'], r['seed']): r for r in map(json.loads, (self.root / 'recall.cases.jsonl').read_text().splitlines())}
        self.assertEqual(rows['eva-h1', 1]['outcome'], 'case_rescue')
        self.assertEqual(rows['eva-h2', 1]['outcome'], 'agent_accept')
        self.assertEqual(rows['eva-h1', 1]['accepted_stems'], ['eva-h1-s1-roll12strategy-a0'])
        with self.assertRaises(FileExistsError):  # never overwrites earlier replays
            t.run_replays(agents, 'recall', ['http://a/v1'], out, 8, 'm')

    def test_rejected_or_wrong_accepts_are_not_rescues(self):
        agents = self.build()
        base = dict(run='swarm-x', task_id='eva-h1', seed=1, error=None, tokens_generated=5)
        records = [dict(base, stem='a', plan={'moves': [1]}, verdict=True, verifier_solved=False),
                   dict(base, stem='b', plan={'moves': [1]}, verdict=False, verifier_solved=True),
                   dict(base, stem='c', plan=None, verdict=None, verifier_solved=False)]
        row, = t.case_rows(agents, records)
        self.assertEqual((row['outcome'], row['judge_accepted'], row['judge_accepted_wrong'], row['replay_plans']),
                         ('case_rescue', 1, 1, 2))  # a judge accept counts; 'wrong' flags the verifier disagreement
        row, = t.case_rows(agents, records[1:])
        self.assertEqual(row['outcome'], 'none')

    def test_unknown_case_index_skips_the_judge(self):
        record, _ = self.replay('eva-h1-s1-p-a0', 'recall', [sse('x</think>' + GOOD, [8], 'stop')])
        agent = t.load_agent(self.run / 'agents' / 'eva-h1-s1-p-a0.jsonl', {})
        t.judge_record(record, agent, 'http://x/v1', self.root / 'j.jsonl', judge=None)
        self.assertIn('case_index unknown', record['judge_error'])
        self.assertIsNone(record['verdict'])

    def test_rewind_records_are_marked_experimental(self):
        record, _ = self.replay('eva-h1-s1-p-a1', 'rewind', [sse('x</think>' + GOOD, [8] * 3, 'stop')],
                                reasoning=VARIED + LOOP, ids=[7] * 5000)
        self.assertTrue(record['experimental'])

if __name__ == '__main__':
    unittest.main()
