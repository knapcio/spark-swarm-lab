"""Authored transport fixtures only; no model calls."""
from fractions import Fraction as F
import io
import json
import unittest
import harness as h
import forced72 as f
from test_followup72 import Recorder, engine

STATE = (F(2), F(3), F(7))  # target 5 in engine(); move 0+1 -> 5
GOOD = '{"moves":[{"i":0,"j":1,"op":"+"}]}'


def sse(text, ids, finish, completion=None):
    chunks = [dict(choices=[dict(text=text, token_ids=ids, finish_reason=finish)])]
    chunks.append(dict(choices=[], usage=dict(prompt_tokens=10, completion_tokens=len(ids) if completion is None else completion)))
    return io.BytesIO(b''.join(b'data: ' + json.dumps(c).encode() + b'\n\n' for c in chunks) + b'data: [DONE]\n\n')


class FakeForced(f.ForcedClient):
    def __init__(self, replies):
        super().__init__('http://x/v1', 'm', h.Budget(2, 8192), Recorder(), 1)
        self.replies, self.bodies = list(replies), []

    def chat_prompt_ids(self, prompt):
        self.prompt = prompt
        return [1, 2, 3]

    def force_ids(self):
        return [9, 13, 9]

    def post(self, path, body, timeout):
        self.bodies.append(body)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class ForcedTests(unittest.TestCase):
    def run_case(self, replies, variant='forced_explicit'):
        c = FakeForced(replies)
        e = engine(c)
        c.events = e.events
        return c, f.run_forced(e, STATE, 'p', variant)

    def test_split_answer_uses_last_marker(self):
        self.assertEqual(f.split_answer('think</think>more</think>ANS'), ('ANS', 'think</think>more'))
        self.assertEqual(f.split_answer('only thinking'), (None, 'only thinking'))

    def test_self_closed_thinking_needs_one_call(self):
        c, result = self.run_case([sse('notes</think>' + GOOD, [5] * 40, 'stop')])
        self.assertTrue(result['solved'])
        self.assertFalse(result['budget_forced'])
        self.assertEqual(len(c.bodies), 1)
        self.assertEqual((c.bodies[0]['max_tokens'], c.bodies[0]['prompt']), (f.THINK_CAP, [1, 2, 3]))
        self.assertIn('Leftover numbers are allowed', c.prompt)

    def test_truncated_thinking_continues_same_sequence(self):
        first = [7] * f.THINK_CAP
        c, result = self.run_case([sse('long notes', first, 'length'),
                                   sse(' wrap up</think>' + GOOD, [8] * 30, 'stop')])
        self.assertTrue(result['solved'] and result['budget_forced'] and result['forced_closed_thinking_again'])
        self.assertEqual(c.bodies[1]['prompt'], [1, 2, 3] + first + [9, 13, 9])
        self.assertEqual(c.bodies[1]['max_tokens'], f.TOTAL - f.THINK_CAP)
        self.assertEqual(c.budget.snapshot()['completion_tokens_charged'], f.THINK_CAP + 30)

    def test_continuation_without_marker_is_the_answer(self):
        c, result = self.run_case([sse('notes', [7] * f.THINK_CAP, 'length'), sse(GOOD, [8] * 20, 'stop')])
        self.assertTrue(result['solved'])
        self.assertFalse(result['forced_closed_thinking_again'])

    def test_unparseable_answer_is_not_repaired(self):
        _, result = self.run_case([sse('n</think>The answer: ' + GOOD, [5] * 10, 'stop')])
        self.assertFalse(result['solved'])

    def test_idle_timeout_is_infrastructure_failure_and_no_force(self):
        c, result = self.run_case([TimeoutError('read timed out')])
        self.assertFalse(result['solved'] or result['budget_forced'])
        self.assertEqual((c.infra_failures, len(c.bodies)), (1, 1))

    def test_reported_usage_mismatch_blocks_force_and_counts_as_fault(self):
        c, result = self.run_case([sse('notes', [7] * 100, 'length', completion=101)])
        self.assertFalse(result['budget_forced'])
        self.assertEqual((len(c.bodies), c.infra_failures), (1, 1))

    def test_cut_answer_after_closed_thinking_continues_without_force(self):
        first = [7] * f.THINK_CAP
        c, result = self.run_case([sse('notes</think>{"moves":[{"i":0,', first, 'length'),
                                   sse('"j":1,"op":"+"}]}', [8] * 10, 'stop')])
        self.assertTrue(result['solved'] and result['answer_continued'])
        self.assertFalse(result['budget_forced'])
        self.assertEqual(c.bodies[1]['prompt'], [1, 2, 3] + first)

    def test_stream_error_chunk_is_infrastructure_failure(self):
        bad = io.BytesIO(b'data: {"error": {"message": "boom"}}\n\n')
        c, result = self.run_case([bad])
        self.assertFalse(result['solved'])
        self.assertEqual(c.infra_failures, 1)

    def test_forced_answer_logged_and_token_ids_traced(self):
        c, _ = self.run_case([sse('notes', [7] * f.THINK_CAP, 'length'), sse(GOOD, [8] * 20, 'stop')])
        ends = [r for r in c.events.rows if r['type'] == 'request_end']
        self.assertEqual(ends[1]['response'], GOOD)
        self.assertEqual(ends[0]['token_ids'], [7] * f.THINK_CAP)

    def test_plain_original_is_one_uncapped_call_without_forcing(self):
        c, result = self.run_case([sse('notes', [7] * f.TOTAL, 'length')], variant='plain_original')
        self.assertEqual(len(c.bodies), 1)
        self.assertEqual(c.bodies[0]['max_tokens'], f.TOTAL)
        self.assertFalse(result['solved'] or result['budget_forced'])
        self.assertNotIn('Leftover numbers are allowed', c.prompt)

    def test_original_variant_uses_original_prompt(self):
        c, _ = self.run_case([sse('n</think>' + GOOD, [5], 'stop')], variant='forced_original')
        self.assertNotIn('Leftover numbers are allowed', c.prompt)


if __name__ == '__main__':
    unittest.main()
