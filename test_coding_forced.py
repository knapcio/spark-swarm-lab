"""Authored fixtures only; no model, SSH or Docker."""
import unittest
import harness as h
import coding_forced as cf
import forced72 as f
from test_forced72 import FakeForced, sse
from test_followup72 import Recorder

TASK = dict(id='t1', function_name='add', spec='Return a+b.', examples=[dict(args=[1, 2], expected=3), dict(args=[2, 2], expected=4)])
PRIVATE = dict(feedback_tests=[dict(args=[5, 5], expected=10)], holdout_tests=[dict(args=[7, 1], expected=8)])
GOOD = 'def add(a, b):\n    return a + b\n'


class FakeCoding(FakeForced, cf.CodingClient):
    pass


def evaluator(results):
    calls = []
    def run(code, name, tests, host):
        calls.append((code, name, tests, host))
        return results[len(calls) - 1]
    run.calls = calls
    return run


class CodingForcedTests(unittest.TestCase):
    def run_agent(self, replies, reports, variant='code_forced'):
        c = FakeCoding(replies)
        c.events = Recorder()
        ev = evaluator(reports)
        return c, ev, cf.run_agent(c, TASK, PRIVATE, 'Spark_01', variant, c.events, ev)

    def test_closed_thinking_code_graded_on_feedback_then_holdout(self):
        c, ev, r = self.run_agent([sse('plan</think>```python\n' + GOOD + '```', [5] * 50, 'stop')],
                                  [dict(status='passed', passed=1, total=1), dict(status='passed', passed=1, total=1)])
        self.assertTrue(r['feedback_pass'] and r['holdout_pass'] and r['solved'])
        self.assertEqual([call[2] for call in ev.calls], [PRIVATE['feedback_tests'], PRIVATE['holdout_tests']])
        self.assertEqual(ev.calls[0][3], 'Spark_01')
        self.assertIn('Return complete Python function source only', c.prompt)

    def test_forced_continuation_produces_code(self):
        c, ev, r = self.run_agent([sse('thinking', [7] * f.THINK_CAP, 'length'), sse(GOOD, [8] * 20, 'stop')],
                                  [dict(status='passed', passed=1, total=1), dict(status='failed', passed=0, total=1)])
        self.assertTrue(r['budget_forced'] and r['feedback_pass'])
        self.assertFalse(r['holdout_pass'] or r['solved'])
        self.assertEqual(c.bodies[1]['prompt'], [1, 2, 3] + [7] * f.THINK_CAP + [9, 13, 9])

    def test_no_code_means_no_grading(self):
        c, ev, r = self.run_agent([sse('thinking', [7] * f.TOTAL, 'length')], [], variant='code_plain')
        self.assertFalse(r['parsed'] or r['budget_forced'])
        self.assertEqual((len(ev.calls), len(c.bodies)), (0, 1))

    def test_grader_exception_is_infrastructure(self):
        c = FakeCoding([sse('p</think>' + GOOD, [5], 'stop')])
        c.events = Recorder()
        def boom(*a):
            raise OSError('ssh down')
        r = cf.run_agent(c, TASK, PRIVATE, 'Spark_01', 'code_forced', c.events, boom)
        self.assertEqual(r['grader_infrastructure_errors'], 2)
        self.assertFalse(r['solved'])

    def test_unfenced_prose_is_not_repaired(self):
        _, ev, r = self.run_agent([sse('p</think>Here is the code: ' + GOOD, [5], 'stop')],
                                  [dict(status='error', error='SyntaxError: x'), dict(status='error', error='SyntaxError: x')])
        self.assertTrue(r['parsed'])  # prose is passed through verbatim; the sandbox rejects it
        self.assertFalse(r['feedback_pass'])


if __name__ == '__main__':
    unittest.main()
