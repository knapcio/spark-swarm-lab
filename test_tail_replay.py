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
               prompt_sha=None, extra='', started=True, variant='xl_forced_original'):
    ids = [7] * THINK if ids is None else ids
    rows = [dict(type='run_start', config=dict(variant=variant, puzzle='2,6,25,100:187', seed=16400)),
            dict(type='extra_prompt', text=extra)]
    if started:
        rows.append(dict(type='request_start', request_id='orig1', stage='plan', request_max_tokens=max_tokens,
                         request_body=dict(seed=123), prompt_ids_sha256=prompt_sha or sha(json.dumps(PROMPT_IDS))))
        rows.append(dict(type='request_end', request_id='orig1', stage='plan', error=None, response_received=True,
                         finish_reason=finish, closed_thinking=response is not None, reasoning=reasoning,
                         response=response, token_ids=ids, usage=dict(completion_tokens=len(ids))))
        rows.append(dict(type='puzzle_end', plan=None, solved=False))
    path = Path(directory) / 'agents' / (stem + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return path


def cases_file(directory, verdicts):
    with open(Path(directory) / 'cases.jsonl', 'w') as handle:
        for (task, seed), slots in verdicts.items():
            handle.write(json.dumps(dict(task_id=task, seed=seed, agents=[dict(slot=s, verdict=v) for s, v in slots.items()])) + '\n')


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
        self.run = Path(self.tmp.name) / 'swarm-x'
        self.addCleanup(self.tmp.cleanup)

    def build(self):
        loop_text = VARIED + LOOP
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a0')                          # exhausted, rejected
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a1', reasoning=loop_text, ids=[7] * 5000)  # loop, rejected
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a2', started=False)            # cancelled
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a3', reasoning='n', response=GOOD, ids=[5] * 40,
                   finish='stop')                                                     # accepted
        agent_file(self.run, 'eva-h1-s1-roll12strategy-a4', reasoning=loop_text)      # exhausted AND looping, accepted
        agent_file(self.run, 'eva-h2-s1-roll12strategy-a0', ids=[7] * 100)            # length, below budget
        cases_file(self.run, {('eva-h1', 1): {0: False, 1: False, 2: None, 3: True, 4: True}, ('eva-h2', 1): {0: None}})
        return t.load_runs([self.run])


class PlanOnlyTests(RunDir):
    def test_listing_counts_both_modes(self):
        agents = self.build()
        recall = t.plan_listing(agents, 'recall')
        self.assertEqual([i['stem'] for i in recall['items']], ['eva-h1-s1-roll12strategy-a0'])
        self.assertEqual(recall['skipped'], {'accepted': 1, 'no_finished_plan_stream': 1, 'not_at_thinking_budget': 2,
                                             'not_length': 1})
        rewind = t.plan_listing(agents, 'rewind')
        self.assertEqual([i['stem'] for i in rewind['items']], ['eva-h1-s1-roll12strategy-a1'])
        self.assertEqual(rewind['skipped'], {'accepted': 1, 'no_finished_plan_stream': 1, 'no_loop_trigger': 3})
        item = rewind['items'][0]
        self.assertEqual(item['kept_tokens_estimate'], round(item['cut_char'] * 5000 / len(VARIED + LOOP)))
        self.assertEqual(t.plan_listing(agents, 'recall', include_accepted=True)['eligible'], 2)

    def test_main_plan_only_makes_no_request(self):
        self.build()
        out = io.StringIO()
        with mock.patch.object(f.ForcedClient, 'post', side_effect=AssertionError('network')), \
                contextlib.redirect_stdout(out):
            self.assertEqual(t.main(['--plan-only', '--mode', 'rewind', '--runs', str(self.run)]), 0)
        listing = json.loads(out.getvalue())
        self.assertEqual((listing['model_calls'], listing['eligible'], listing['cases']), (0, 1, 1))

    def test_concurrency_limit(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            t.main(['--plan-only', '--mode', 'recall', '--runs', str(self.run), '--max-concurrency', '21'])
        with self.assertRaises(ValueError):
            t.run_replays([], 'recall', ['http://x/v1'], Path(self.tmp.name) / 'o.jsonl', 0, 'm')


class ReplayTests(RunDir):
    def replay(self, stem, mode, replies, **file_kwargs):
        path = agent_file(self.run, stem, **file_kwargs)
        agent = t.load_agent(path, {})
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

    def test_run_replays_writes_records(self):
        self.build()
        agents = t.load_runs([self.run])
        transport = Transport([sse('x</think>' + GOOD, [8] * 4, 'stop')])
        out = Path(self.tmp.name) / 'recall.jsonl'
        with mock.patch.object(f.ForcedClient, 'post', lambda client, p, b, timeout: transport(client, p, b, timeout)):
            summary = t.run_replays(agents, 'recall', ['http://a/v1', 'http://b/v1'], out, 8, 'm')
        self.assertEqual((summary['replays'], summary['plans'], summary['errors'], summary['tokens_generated']), (1, 1, 0, 4))
        record, = map(json.loads, out.read_text().splitlines())
        self.assertEqual(record['stem'], 'eva-h1-s1-roll12strategy-a0')
        self.assertTrue(Path(record['events']).exists())
        with self.assertRaises(FileExistsError):  # never overwrites earlier replays
            t.run_replays(agents, 'recall', ['http://a/v1'], out, 8, 'm')


if __name__ == '__main__':
    unittest.main()
