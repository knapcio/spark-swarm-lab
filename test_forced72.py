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
        self.retry_delay = 0

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
        bad = lambda: io.BytesIO(b'data: {"error": {"message": "boom"}}\n\n')
        c, result = self.run_case([bad(), bad()])
        self.assertFalse(result['solved'])
        self.assertEqual((c.infra_failures, len(c.bodies)), (1, 2))  # retried once, then a failure as before

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

    def test_long_variant_uses_whole_context_budget(self):
        c = FakeForced([sse('notes', [7] * 14848, 'length'), sse('</think>{"moves":[{"i":0,"j":1,"op":"+"}]}', [8] * 20, 'stop')])
        c.budget = h.Budget(2, 16000)
        e = engine(c)
        c.events = e.events
        result = f.run_forced(e, STATE, 'p', 'long_forced_explicit')
        self.assertTrue(result['solved'] and result['budget_forced'])
        self.assertEqual((c.bodies[0]['max_tokens'], c.bodies[1]['max_tokens']), (14848, 16000 - 14848))

    def test_original_variant_uses_original_prompt(self):
        c, _ = self.run_case([sse('n</think>' + GOOD, [5], 'stop')], variant='forced_original')
        self.assertNotIn('Leftover numbers are allowed', c.prompt)


def disconnect_after(text, ids):
    """A stream that delivered some tokens, then the shim's error chunk for an upstream disconnect."""
    chunk = dict(choices=[dict(text=text, token_ids=ids, finish_reason=None)])
    error = {'error': {'message': 'ServerDisconnectedError: Server disconnected'}}
    return io.BytesIO(b'data: ' + json.dumps(chunk).encode() + b'\n\ndata: ' + json.dumps(error).encode() + b'\n\n')


class RetryTests(unittest.TestCase):
    def run_case(self, replies, variant='forced_explicit'):
        c = FakeForced(replies)
        e = engine(c)
        c.events = e.events
        return c, f.run_forced(e, STATE, 'p', variant)

    def rows(self, c, kind):
        return [r for r in c.events.rows if r['type'] == kind]

    def test_disconnect_is_retried_once_with_the_same_body(self):
        c, result = self.run_case([disconnect_after('partial', [4] * 17), sse('notes</think>' + GOOD, [5] * 40, 'stop')])
        self.assertTrue(result['solved'])
        self.assertEqual((c.infra_failures, len(c.bodies)), (0, 2))
        self.assertEqual(c.bodies[0], c.bodies[1])  # same prompt, seed and caps
        retry, = self.rows(c, 'request_retry')
        self.assertEqual((retry['attempt'], retry['lost_completion_tokens'], retry['stage']), (1, 17, 'plan'))
        self.assertIn('ServerDisconnectedError', retry['error'])
        end, = self.rows(c, 'request_end')
        self.assertEqual((end['error'], end['retries'], end['token_ids']), (None, 1, [5] * 40))
        self.assertEqual(c.budget.snapshot()['completion_tokens_charged'], 40)  # lost attempt is logged, not charged

    def test_second_disconnect_fails_like_before(self):
        c, result = self.run_case([disconnect_after('a', [4] * 3), disconnect_after('b', [4] * 5)])
        self.assertFalse(result['solved'] or result['budget_forced'])
        self.assertEqual((c.infra_failures, len(c.bodies), len(self.rows(c, 'request_retry'))), (1, 2, 1))
        end, = self.rows(c, 'request_end')
        self.assertTrue(end['error'].startswith('ConnectionError: server stream error'))
        self.assertFalse(end['response_received'])

    def test_raw_connection_reset_and_cut_stream_are_retried(self):
        cut = io.BytesIO(b'data: ' + json.dumps(dict(choices=[dict(text='x', token_ids=[1], finish_reason=None)])).encode() + b'\n\n')
        c, result = self.run_case([ConnectionResetError('reset by peer'), sse('n</think>' + GOOD, [5], 'stop')])
        self.assertTrue(result['solved'])
        self.assertEqual(self.rows(c, 'request_retry')[0]['lost_completion_tokens'], 0)
        c, result = self.run_case([cut, sse('n</think>' + GOOD, [5], 'stop')])
        self.assertTrue(result['solved'])
        self.assertIn('without finish_reason', self.rows(c, 'request_retry')[0]['error'])

    def test_timeouts_and_upstream_4xx_are_not_retried(self):
        for reply in (TimeoutError('read timed out'),
                      io.BytesIO(b'data: {"error": {"message": "ConnectionError: upstream HTTP 400: too long"}}\n\n')):
            c, result = self.run_case([reply])
            self.assertEqual((c.infra_failures, len(c.bodies), self.rows(c, 'request_retry')), (1, 1, []))

    def test_retry_inside_forced_answer(self):
        c, result = self.run_case([sse('notes', [7] * f.THINK_CAP, 'length'), disconnect_after('', []),
                                   sse(GOOD, [8] * 20, 'stop')])
        self.assertTrue(result['solved'] and result['budget_forced'])
        self.assertEqual(c.bodies[1], c.bodies[2])
        self.assertEqual(self.rows(c, 'request_retry')[0]['stage'], 'forced_answer')

    def test_successful_request_events_unchanged(self):
        c, _ = self.run_case([sse('notes</think>' + GOOD, [5] * 40, 'stop')])
        self.assertEqual(self.rows(c, 'request_retry'), [])
        end, = self.rows(c, 'request_end')
        self.assertNotIn('retries', end)
        self.assertEqual(list(end)[:6], ['type', 'request_id', 'agent_id', 'endpoint_index', 'stage', 'latency_ms'])

    def test_retryable_classification(self):
        import http.client, urllib.error
        self.assertTrue(f.retryable(http.client.RemoteDisconnected('closed')))
        self.assertTrue(f.retryable(http.client.IncompleteRead(b'')))
        self.assertTrue(f.retryable(urllib.error.URLError(ConnectionResetError('reset'))))
        self.assertTrue(f.retryable(urllib.error.URLError(ConnectionRefusedError('refused'))))  # one 2 s retry, harmless
        self.assertFalse(f.retryable(TimeoutError('idle')))
        self.assertFalse(f.retryable(ValueError('bad json')))


class LeftoverTests(unittest.TestCase):
    def run_variant(self, variant, extra=''):
        c = FakeForced([sse('n</think>' + GOOD, [5], 'stop')])
        c.budget = h.Budget(2, 32768)
        e = engine(c)
        c.events = e.events
        result = f.run_forced(e, STATE, 'p', variant, extra=extra)
        return c, result

    def test_leftover_adds_one_sentence_at_the_end_of_the_task_text(self):
        base, _ = self.run_variant('xl_forced_original')
        c, result = self.run_variant('xl_forced_leftover')
        self.assertTrue(result['solved'])
        self.assertEqual(c.prompt, base.prompt + ' Unused numbers are allowed; stop as soon as the target appears.')
        self.assertEqual(c.bodies[0]['max_tokens'], 30720)
        self.assertEqual(f.CAPS['xl_forced_leftover'], f.CAPS['xl_forced_original'])

    def test_leftover_sentence_precedes_the_agent_extra(self):
        base, _ = self.run_variant('xl_forced_original', extra='Try products first.')
        c, _ = self.run_variant('xl_forced_leftover', extra='Try products first.')
        task, hint = base.prompt.split('\n')
        self.assertEqual(c.prompt, task + ' ' + f.LEFTOVER_SENTENCE + '\n' + hint)

    def test_other_variants_have_no_leftover_sentence(self):
        for variant in sorted(f.VARIANTS):
            if variant != 'xl_forced_leftover':
                self.assertNotIn(f.LEFTOVER_SENTENCE, f.task_prompt(engine(FakeForced([])), STATE, variant))


if __name__ == '__main__':
    unittest.main()
