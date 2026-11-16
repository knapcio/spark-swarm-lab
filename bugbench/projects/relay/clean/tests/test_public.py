"""The project's own regression tests (visible to everyone)."""
import unittest

from relay import (Backlog, Clock, ClockError, Dispatcher, DuplicateJob, DurationError, InvalidJob, Job, JobStateError,
                   Limiter, RateLimited, ScriptError, format_duration, parse_backoff, parse_duration, parse_rate,
                   percentile, replay, summary, timeline)
from relay.stats import key_report, order_of_starts


class ClockTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual([parse_duration(t) for t in ("250ms", "1.5s", "2m", "1m30s", "1h0.5s", 7)],
                         [250, 1500, 120000, 90000, 3600500, 7])
        self.assertEqual([format_duration(v) for v in (0, 999, 1500, 90000, 7200000, 3600250)],
                         ["0ms", "999ms", "1.5s", "1m30s", "2h", "1h0.25s"])
        for bad in ("1.0005s", "5s1m", "1s1s", "", "-1s", -3, True):
            with self.assertRaises(DurationError):
                parse_duration(bad)

    def test_clock(self):
        clock = Clock("1s")
        self.assertEqual(clock.advance("250ms"), 1250)
        with self.assertRaises(ClockError):
            clock.advance_to(1000)


class LimiterTests(unittest.TestCase):
    def test_rates(self):
        self.assertEqual(str(parse_rate("10/250ms")), "10/250ms burst 10")
        self.assertEqual(str(parse_rate("2/s", burst=5)), "2/1s burst 5")
        self.assertEqual(str(parse_rate("30/m")), "30/1m burst 30")

    def test_debt_waits(self):
        limiter = Limiter()
        limiter.configure("mail", "2/s", burst=2)
        self.assertEqual([limiter.reserve([("mail", 1)], 0)[0] for _ in range(4)], [0, 0, 500, 1000])
        self.assertEqual(limiter.available("mail", 1000), 0)
        self.assertEqual(limiter.wait("mail", 1000), 500)
        self.assertEqual(limiter.available("mail", 3000), 2)
        self.assertIsNone(limiter.available("other", 0))

    def test_max_wait_and_reservations(self):
        limiter = Limiter()
        limiter.configure("mail", "4/s", burst=1)
        limiter.configure("sms", "1/250ms", burst=1, max_wait="300ms")
        self.assertEqual(limiter.reserve([("mail", 1), ("sms", 1), ("sms", 1)], 0), [0, 0, 250])
        with self.assertRaises(RateLimited):
            limiter.reserve([("mail", 2), ("sms", 1)], 0)
        self.assertEqual(limiter.status(0), [["mail", "4/1s burst 1", 0, 250], ["sms", "1/250ms burst 1", 0, 500]])


class BackoffTests(unittest.TestCase):
    def test_policies(self):
        self.assertEqual(parse_backoff("fixed 300ms").schedule(3), [300, 300, 300])
        self.assertEqual(parse_backoff("linear 100ms +50ms").schedule(3), [100, 150, 200])
        policy = parse_backoff("exp 100ms x2 max 1s")
        self.assertEqual(policy.schedule(5), [100, 200, 400, 800, 1000])
        self.assertEqual(str(policy), "exp 100ms x2 max 1s")
        jittered = parse_backoff("exp 1s x2 jitter 50%")
        self.assertTrue(all(500 <= d <= 1000 for d in [jittered.delay(1, f"job-{n}") for n in range(20)]))
        self.assertEqual(jittered.delay(2, "job-1"), jittered.delay(2, "job-1"))


class JobAndBacklogTests(unittest.TestCase):
    def test_job_checks(self):
        for spec in ({"job_id": "bad id"}, {"job_id": "a", "priority": 10}, {"job_id": "a", "attempts": 0},
                     {"job_id": "a", "key": "Mail"}, {"job_id": "a", "takes": "soon"}):
            with self.assertRaises(InvalidJob):
                Job(**spec)

    def test_priority_then_ticket(self):
        backlog = Backlog()
        for name, priority in (("a", 1), ("b", 5), ("c", 1), ("d", 5)):
            backlog.push(Job(name, priority=priority), 0)
        backlog.push(Job("later", priority=9), 100)
        self.assertEqual([backlog.pop_ready(50).id for _ in range(4)], ["b", "d", "a", "c"])
        self.assertIsNone(backlog.pop_ready(50))
        self.assertEqual(backlog.next_ready_at(), 100)


class DispatcherTests(unittest.TestCase):
    def test_retries_and_dead_letter(self):
        dispatcher = Dispatcher(workers=2, backoff="fixed 100ms")
        dispatcher.submit("a", takes="300ms")
        dispatcher.submit("b", takes="100ms", fails=1)
        dispatcher.submit("c", takes="50ms", fails=5, attempts=2)
        dispatcher.run()
        self.assertEqual([[j.id, j.state, j.attempts] for j in dispatcher.jobs()],
                         [["a", "done", 1], ["b", "done", 2], ["c", "dead", 2]])
        self.assertEqual([j.id for j in dispatcher.dead_letter()], ["c"])
        self.assertEqual(order_of_starts(dispatcher), ["a", "b", "c"])
        self.assertEqual(dispatcher.now, 350)

    def test_cancel_revive_and_batches(self):
        dispatcher = Dispatcher()
        dispatcher.submit("a", delay="1s")
        dispatcher.submit("b", fails=3, attempts=1)
        dispatcher.cancel("a")
        dispatcher.run()
        with self.assertRaises(JobStateError):
            dispatcher.cancel("b")
        dispatcher.revive("b")
        dispatcher.run()
        self.assertEqual(dispatcher.get("b").state, "done")
        with self.assertRaises(DuplicateJob):
            dispatcher.submit_batch([{"id": "c"}, {"id": "b"}])
        self.assertEqual([j.id for j in dispatcher.jobs()], ["a", "b"])

    def test_run_until(self):
        dispatcher = Dispatcher()
        dispatcher.submit("a", takes="1s")
        self.assertEqual(dispatcher.run("500ms"), 500)
        self.assertEqual(dispatcher.running(), [[1, "a", 1000]])
        self.assertEqual(timeline(dispatcher), ["0ms submit a ready 0ms", "0ms start a on w1 attempt 1"])


class StatsAndScriptTests(unittest.TestCase):
    def test_percentiles_and_reports(self):
        self.assertEqual([percentile([5, 1, 4, 2, 3], p) for p in (20, 50, 90, 100)], [1, 3, 5, 5])
        dispatcher = Dispatcher()
        dispatcher.submit("a", key="mail", takes="100ms")
        dispatcher.submit("b", key="mail", takes="100ms")
        dispatcher.run()
        self.assertEqual(key_report(dispatcher), [["mail", 2, 2, 0, 2, 0, 100, 200]])
        self.assertEqual(summary(dispatcher)["done"], 2)

    def test_script(self):
        _, outputs = replay("workers 2\nrate mail 2/s burst 1\nsubmit a key mail takes 200ms\n"
                            "submit b key mail\nsubmit a\nrun\nstarts\nstats\n")
        self.assertEqual(outputs, ["submitted a ready 0ms", "submitted b ready 500ms", "error DuplicateJob", "now 500ms",
                                   "a#1@0ms b#1@500ms", "done 2 dead 0 queued 0 cancelled 0 runs 2 retries 0"])
        with self.assertRaises(ScriptError) as caught:
            replay("submit a\nsubmit b prio\n")
        self.assertEqual(caught.exception.line, 2)


if __name__ == "__main__":
    unittest.main()
