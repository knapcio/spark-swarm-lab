"""Hidden behavioural probes for the relay project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY 7b3e9a51-bugbench-relay-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _value(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__


def _jobs(dispatcher):
    return [[j.id, j.state, j.attempts, j.ready_at, j.started_at, j.finished_at] for j in dispatcher.jobs()]


def _starts(dispatcher):
    from relay import start_times
    return [f"{job_id}#{attempt}@{when}" for job_id, attempt, when in start_times(dispatcher)]


# --- clock ------------------------------------------------------------------------------
def probe_duration_parsing():
    from relay import parse_duration
    good = ["0ms", "250ms", "1.5s", "2m", "1m30s", "1h0.5s", " 3s ", "1h2m3.004s", "0.001s", "1.25m", "0s", "10h",
            "1h30m", "2s500ms", "0.5h"]
    out = [[t, parse_duration(t)] for t in good]
    out.append([parse_duration(v) for v in (0, 7, 123456)])
    out.append([_error(parse_duration, t) for t in ("1.0005s", "5s1m", "1s1s", "", "  ", "-1s", -3, True, 1.5, None,
                                                       "1 s", "s", "1x", "1.s", "ms5", "1ms2s", "1.0001m", "1sx", "2m30",
                                                       "1s 5ms")])
    return out


def probe_duration_formatting():
    from relay import format_duration
    values = [0, 1, 999, 1000, 1001, 1500, 12345, 59999, 60000, 60500, 90000, 3599999, 3600000, 3600250, 3661500,
              7200000, 3605000, "1m30s"]
    return [[v, format_duration(v)] for v in values] + [_error(format_duration, -1), _error(format_duration, "x")]


def probe_clock():
    from relay import Clock
    clock = Clock("1s")
    out = [clock.now, clock.advance("250ms"), clock.advance(0), clock.advance_to("2s"), clock.advance_to(2000),
           _error(clock.advance_to, 1999), clock.now, _error(clock.advance, "-1ms"), repr(clock), Clock().now,
           _error(Clock, -5)]
    return out


# --- limiter ----------------------------------------------------------------------------
def probe_rate_parsing():
    from relay import Rate, parse_rate
    texts = ["2/s", "10/250ms", "30/m", "5/h", "4/ms", "3/2s", " 6 / 1.5s ", "1/1m30s"]
    out = [[t, str(parse_rate(t))] for t in texts]
    out.append([str(parse_rate("2/s", burst=5)), str(parse_rate("2/s", burst="7")), str(parse_rate(Rate(3, 1000, 3), 9)),
                parse_rate(Rate(3, 1000, 3)) == Rate(3, 1000, 3)])
    out.append([_error(parse_rate, t) for t in ("0/s", "2/0ms", "2", "2/x", "/s", "2/s/s", 5, None, "-1/s", "2/-1s")])
    out.append([_error(parse_rate, "2/s", burst=b) for b in (0, -1, True, "x", 1.5)])
    rate = parse_rate("4/s")
    out.append([rate.tokens, rate.period, rate.burst])
    return out


def probe_bucket_refill_and_debt():
    from relay import Bucket, Rate
    bucket = Bucket("api", Rate(2, 1000, 3), 1000)
    out = [bucket.available(1000), [bucket.take(1000) for _ in range(5)], bucket.available(1000), bucket.wait(1000),
           bucket.wait(1000, 2), bucket.available(2000), bucket.wait(2000), bucket.available(2500), bucket.available(4000),
           bucket.available(9000), bucket.take(9000, 3), bucket.wait(9000), bucket.state(), _error(bucket.wait, 8000)]
    fives = Bucket("x", Rate(5, 1000, 1), 0)
    out.append([fives.take(0), fives.take(0), fives.take(0), fives.take(100), fives.take(100), fives.available(1000),
                fives.wait(1000), fives.wait(1000, 2)])
    quarter = Bucket("q", Rate(1, 250, 2), 0)
    out.append([quarter.take(0, 2), quarter.take(10), quarter.take(10), quarter.available(760), quarter.wait(760),
                quarter.state()])
    slow = Bucket("s", Rate(10, 60000, 10), 0)
    out.append([slow.take(0, 10), slow.take(0), slow.take(1000), slow.wait(7000)])
    return out


def probe_bucket_max_wait():
    from relay import Bucket, Rate, RateLimited
    bucket = Bucket("api", Rate(2, 1000, 1), 0, max_wait=500)
    out = [bucket.take(0), bucket.take(0), bucket.state()]
    try:
        bucket.take(0)
    except RateLimited as exc:
        out.append([type(exc).__name__, exc.key, exc.wait, exc.max_wait])
    out += [bucket.state(), bucket.take(500), _error(bucket.take, 500, 2), bucket.state(), bucket.take(1000)]
    exact = Bucket("e", Rate(4, 1000, 1), 0, max_wait=250)
    out.append([exact.take(0), exact.take(0), _error(exact.take, 0), exact.take(250), exact.state()])
    zero = Bucket("z", Rate(1, 100, 2), 0, max_wait=0)
    out.append([zero.take(0), zero.take(0), _error(zero.take, 0), zero.take(100), _error(zero.take, 150)])
    return out


def probe_limiter_settings_and_status():
    from relay import Limiter
    limiter = Limiter(default="5/s")
    out = [str(limiter.rate_for("anything")), limiter.wait("anything", 0), limiter.reserve([("anything", 5)], 0),
           limiter.wait("anything", 0), limiter.available("anything", 600)]
    out.append(str(limiter.configure("mail", "2/s", burst=1, max_wait="1s")))
    out += [limiter.reserve([("mail", 1), ("mail", 1)], 600), _error(limiter.reserve, [("mail", 2)], 600),
            limiter.status(600)]
    limiter.configure("mail", "2/s")
    out += [limiter.available("mail", 700), limiter.reserve([("mail", 1)] * 4, 700), limiter.status(1200)]
    plain = Limiter()
    out += [plain.rate_for("free"), plain.available("free", 0), plain.wait("free", 0, 9), plain.reserve([("free", 9)], 0),
            plain.status(0), _error(plain.reserve, [("Bad", 1)], 0), _error(plain.reserve, [("ok", 0)], 0),
            _error(plain.configure, "x y", "1/s"), _error(plain.wait, "a", 0, True), _error(plain.configure, "k", "1/s", 0),
            _error(plain.configure, "k", "1/s", None, "soon"), _error(Limiter, "fast")]
    return out


def probe_reserve_all_or_nothing_once_each():
    from relay import Limiter, RateLimited
    limiter = Limiter()
    limiter.configure("mail", "2/s", burst=2, max_wait="1s")
    limiter.configure("sms", "1/500ms", burst=1, max_wait="400ms")
    limiter.configure("push", "10/s", burst=10)
    out = [limiter.reserve([("mail", 1), ("sms", 1), ("push", 3), ("free", 2)], 0)]
    before = [limiter.bucket(k, 0).state() for k in ("mail", "sms", "push")]
    try:
        limiter.reserve([("push", 2), ("mail", 1), ("sms", 1)], 0)
    except RateLimited as exc:
        out.append([exc.key, exc.wait])
    out.append([limiter.bucket(k, 0).state() for k in ("mail", "sms", "push")] == before)
    out.append(limiter.reserve([("mail", 2)], 100))
    out.append(_error(limiter.reserve, [("mail", 1)], 100))
    out.append([limiter.available(k, 2000) for k in ("mail", "sms", "push", "free")])
    return out


# --- backoff ----------------------------------------------------------------------------
def probe_backoff_kinds():
    from relay import parse_backoff
    out = [parse_backoff("fixed 300ms").schedule(3), parse_backoff("linear 100ms +50ms").schedule(4),
           parse_backoff("linear 1s +0ms max 500ms").schedule(2), parse_backoff("exp 100ms x2").schedule(6),
           parse_backoff("exp 100ms x2 max 1s").schedule(6), parse_backoff("exp 250ms x3 max 2s").schedule(4),
           parse_backoff("linear 0ms +1s max 2.5s").schedule(5), parse_backoff("fixed 0ms").schedule(2),
           parse_backoff("exp 1s x1").schedule(3), parse_backoff("exp 300ms x2 max 1.2s").schedule(4)]
    policy = parse_backoff("exp 100ms x2")
    out.append([str(policy.raw(3)), _error(policy.raw, 0), _error(policy.delay, True), _error(policy.raw, "2"),
                policy.schedule(0)])
    return out


def probe_backoff_fractional_rounding():
    from relay import parse_backoff
    return [parse_backoff("exp 75ms x1.5").schedule(5), parse_backoff("exp 10ms x2.5").schedule(5),
            parse_backoff("exp 1ms x1.5").schedule(6), parse_backoff("exp 3ms x1.25 max 5ms").schedule(5),
            parse_backoff("exp 200ms x1.1").schedule(4), str(parse_backoff("exp 75ms x1.50 max 1m30s"))]


def probe_backoff_jitter():
    from relay import jitter_fraction, parse_backoff
    out = [[str(jitter_fraction(job, n)) for job in ("a", "job-1", "mail-7") for n in (1, 2, 3)]]
    policy = parse_backoff("exp 1s x2 max 3s jitter 40%")
    out.append([policy.schedule(4, job) for job in ("a", "job-1", "mail-7", "")])
    out.append(parse_backoff("fixed 333ms jitter 100%").schedule(3, "z"))
    out.append(parse_backoff("linear 10ms +5ms jitter 15%").schedule(4, "k"))
    out.append([str(policy), str(parse_backoff("fixed 1s jitter 0%")), parse_backoff("fixed 1s jitter 0%").jitter])
    return out


def probe_backoff_parsing():
    from relay import Backoff, parse_backoff
    out = [str(parse_backoff(t)) for t in ("fixed 2s", "linear 1s +250ms max 1m", "exp 50ms x3 jitter 10%",
                                           "exp 1.5s x1.75 max 20s jitter 5%")]
    out.append([_error(parse_backoff, t) for t in ("", "fixed", "exp 1s", "exp 1s x0.5", "exp 1s 2", "linear 1s",
                                                   "linear 1s 5ms", "fixed 1s max", "fixed 1s jitter",
                                                   "fixed 1s jitter 101%", "fixed 1s jitter 5", "fixed 1s soon",
                                                   "fixed x", "slow 1s", "fixed 1s jitter 5% max 2s", 5,
                                                   "exp 1s x2 max -1s", "linear 1s +x")])
    policy = parse_backoff("exp 100ms x2")
    out.append([parse_backoff(policy) is policy, isinstance(policy, Backoff), policy.kind, policy.base, policy.cap])
    return out


# --- jobs and backlog -------------------------------------------------------------------
def probe_job_validation():
    from relay import Job
    bad = [{"job_id": "bad id"}, {"job_id": ""}, {"job_id": 5}, {"job_id": "-a"}, {"job_id": "a", "priority": 10},
           {"job_id": "a", "priority": -1}, {"job_id": "a", "priority": True}, {"job_id": "a", "attempts": 0},
           {"job_id": "a", "attempts": 21}, {"job_id": "a", "fails": -1}, {"job_id": "a", "key": "Mail"},
           {"job_id": "a", "takes": "soon"}, {"job_id": "a", "cost": 0}, {"job_id": "a", "cost": 1001},
           {"job_id": "a", "handler": 5}, {"job_id": "a", "takes": -5}]
    out = [_error(lambda spec=spec: Job(**spec)) for spec in bad]
    job = Job("a.b_c-9", key="mail", priority="9", takes="1.5s", attempts="20", fails="2", cost="1000")
    out.append([job.id, job.key, job.priority, job.takes, job.max_attempts, job.fails, job.cost, job.state,
                job.attempts, job.describe(), repr(job)])
    edge = Job("Z", priority=0, attempts=1, fails=20, cost=1)
    out.append([edge.priority, edge.max_attempts, edge.fails, edge.key])
    return out


def probe_job_lifecycle():
    from relay import Job
    calls = []

    def handler(job):
        calls.append(job.attempts)
        if job.attempts == 2:
            raise ValueError("flaky")
        return job.attempts * 10
    job = Job("h", fails=1, attempts=4, handler=handler)
    job.mark_submitted(0, 0)
    out = [job.wait_time, job.latency, job.finished]
    for now in (10, 20, 30):
        job.mark_started(now, 2)
        ok, value = job.outcome()
        out.append([ok, value])
        if ok:
            job.mark_done(now + 5, value)
        else:
            job.mark_failed(now + 5, value, now + 8)
    out += [job.state, job.result, job.error, job.wait_time, job.latency, job.finished, calls, job.history,
            _error(job.mark_started, 40, 1), _error(job.mark_cancelled, 40), _error(job.revive, 40)]
    dead = Job("d", attempts=1, fails=1)
    dead.mark_submitted(0, 0)
    dead.mark_started(0, 1)
    dead.mark_failed(3, dead.outcome()[1], None)
    out += [dead.state, dead.finished_at, dead.latency, dead.finished, _error(dead.mark_done, 4, None)]
    dead.revive(9)
    out += [dead.state, dead.attempts, dead.fails, dead.finished_at, dead.error, dead.outcome(), dead.history[-1]]
    gone = Job("c")
    gone.mark_cancelled(4)
    out += [gone.state, gone.finished_at, gone.finished, _error(gone.mark_started, 5, 1)]
    return out


def probe_backlog_priority_and_tickets():
    from relay import Backlog, Job
    backlog = Backlog()
    for name, priority in (("a", 1), ("b", 5), ("c", 1), ("d", 5), ("e", 0), ("f", 9)):
        backlog.push(Job(name, priority=priority), 100)
    backlog.push(Job("late", priority=9), 300)
    out = [backlog.pop_ready(99), backlog.ready_count(99), backlog.ready_count(100), len(backlog)]
    out.append([backlog.pop_ready(200).id for _ in range(3)])
    job = Job("c2", priority=1)
    out.append(backlog.push(job, 150))
    out.append([backlog.pop_ready(400).id for _ in range(5)])
    out += [backlog.pop_ready(400), backlog.next_ready_at(), len(backlog)]
    return out


def probe_backlog_pending_withdraw():
    from relay import Backlog, Job
    backlog = Backlog()
    specs = [("a", 1, 300), ("b", 5, 300), ("c", 9, 100), ("d", 5, 300), ("e", 0, 0), ("f", 2, 0)]
    for name, priority, ready in specs:
        backlog.push(Job(name, priority=priority, key="k" + str(priority % 2)), ready)
    out = [[j.id for j in backlog.pending()], [j.ticket for j in backlog.pending()], list(backlog.by_key()),
           "c" in backlog, "zz" in backlog, backlog.next_ready_at()]
    out.append(backlog.withdraw("c").id)
    out += [_error(backlog.withdraw, "c"), "c" in backlog, [j.id for j in backlog.pending()], backlog.by_key(), len(backlog)]
    out.append([backlog.pop_ready(0).id, backlog.pop_ready(0).id, backlog.pop_ready(0)])
    empty = Backlog()
    out += [empty.next_ready_at(), empty.pending(), empty.by_key(), empty.ready_count(10**9)]
    return out


# --- dispatcher -------------------------------------------------------------------------
def probe_dispatcher_submit_checks():
    from relay import Dispatcher, Limiter
    limiter = Limiter()
    limiter.configure("mail", "1/s", burst=1)
    dispatcher = Dispatcher(limiter=limiter)
    out = [_error(dispatcher.submit_batch, []), _error(dispatcher.submit_batch, "a"), _error(dispatcher.submit_batch, [{}]),
           _error(dispatcher.submit_batch, [["a"]]), _error(dispatcher.submit_batch, [{"id": "a", "colour": "red"}]),
           _error(dispatcher.submit_batch, [{"id": "a"}, {"id": "a"}]),
           _error(dispatcher.submit_batch, [{"id": "a", "key": "mail"}, {"id": "b", "delay": "soon"}]),
           _error(dispatcher.submit_batch, [{"id": "a", "key": "mail"}, {"id": "b", "delay": -1}]),
           _error(dispatcher.submit, "b", priority=12), dispatcher.jobs(), limiter.available("mail", 0)]
    jobs = dispatcher.submit_batch([{"id": "a", "key": "mail"}, {"id": "b", "key": "mail", "delay": "200ms"},
                                    {"id": "c", "delay": "2s", "key": "mail"}])
    out.append([[j.id, j.ready_at, j.submitted_at, j.ticket] for j in jobs])
    out += [_error(dispatcher.submit, "a"), _error(dispatcher.get, "zz"), _error(dispatcher.get, None),
            dispatcher.get("b").ready_at, [_error(Dispatcher, n) for n in (0, 65, True, "2")], Dispatcher(workers=64).workers,
            str(Dispatcher().backoff), dispatcher.idle, Dispatcher().idle, dispatcher.log]
    return out


def probe_dispatcher_workers_and_moments():
    from relay import Dispatcher
    dispatcher = Dispatcher(workers=3)
    for name, takes in (("a", "300ms"), ("b", "100ms"), ("c", "0ms"), ("d", "200ms"), ("e", "100ms"), ("f", "0ms")):
        dispatcher.submit(name, takes=takes)
    out = [dispatcher.step(), dispatcher.running(), dispatcher.now]
    out.append(dispatcher.run())
    out += [_starts(dispatcher), _jobs(dispatcher), dispatcher.log[-6:], dispatcher.step(), dispatcher.idle]
    tie = Dispatcher(workers=2)
    tie.submit("x", takes="100ms")
    tie.submit("y", takes="100ms")
    tie.submit("z", takes="100ms", priority=1)
    tie.submit("w", takes="50ms")
    tie.run()
    out += [_starts(tie), [entry for entry in tie.log if entry[1].startswith("done")]]
    return out


def probe_dispatcher_retries_and_dead_letter():
    from relay import Dispatcher
    dispatcher = Dispatcher(workers=1, backoff="exp 100ms x3 max 500ms")
    dispatcher.submit("a", takes="50ms", fails=3, attempts=4)
    dispatcher.submit("b", takes="10ms", fails=2, attempts=2)
    dispatcher.submit("c", takes="1s", priority=2)
    dispatcher.run()
    out = [_starts(dispatcher), _jobs(dispatcher), [j.id for j in dispatcher.dead_letter()],
           [text for _, text in dispatcher.log if text.startswith(("fail", "dead"))], dispatcher.get("b").error,
           dispatcher.get("a").history[-3:]]
    return out


def probe_dispatcher_handlers():
    from relay import Dispatcher
    seen = []

    def flaky(job):
        seen.append([job.id, job.attempts])
        if job.attempts < 3:
            raise RuntimeError("try again")
        return {"sent": job.id}

    def broken(job):
        raise KeyError(job.id)
    dispatcher = Dispatcher(workers=2, backoff="linear 10ms +10ms")
    dispatcher.submit("ok", handler=lambda job: "fine", takes="5ms")
    dispatcher.submit("flaky", handler=flaky, takes="5ms", attempts=3)
    dispatcher.submit("broken", handler=broken, attempts=2)
    dispatcher.submit("scripted", handler=lambda job: job.attempts, fails=1)
    dispatcher.run()
    return [[j.id, j.state, j.result, j.error, j.attempts] for j in dispatcher.jobs()] + [seen, _starts(dispatcher)]


def probe_dispatcher_cancel_and_revive():
    from relay import Dispatcher, Limiter
    limiter = Limiter()
    limiter.configure("mail", "1/s", burst=1)
    dispatcher = Dispatcher(limiter=limiter, backoff="fixed 100ms")
    dispatcher.submit("a", key="mail", delay="500ms", takes="100ms")
    dispatcher.submit("b", fails=5, attempts=2, takes="10ms")
    dispatcher.submit("c", takes="300ms")
    out = [dispatcher.cancel("a").state, _error(dispatcher.cancel, "a"), _error(dispatcher.cancel, "zz"),
           limiter.available("mail", 0)]
    dispatcher.run("150ms")
    out += [_error(dispatcher.cancel, "c"), _error(dispatcher.revive, "c"), dispatcher.get("b").state]
    dispatcher.run()
    out += [dispatcher.get("b").state, [j.id for j in dispatcher.dead_letter()], _error(dispatcher.revive, "a")]
    out.append(dispatcher.revive("b", "250ms").ready_at)
    out += [dispatcher.dead_letter(), dispatcher.get("b").attempts, _error(dispatcher.revive, "b")]
    dispatcher.run()
    out += [_jobs(dispatcher), _starts(dispatcher), limiter.available("mail", dispatcher.now), dispatcher.log[-3:]]
    return out


def probe_dispatcher_run_until():
    from relay import Dispatcher
    dispatcher = Dispatcher(workers=1, backoff="fixed 200ms")
    dispatcher.submit("a", takes="1s")
    dispatcher.submit("b", takes="500ms", fails=1)
    out = [dispatcher.run("999ms"), dispatcher.running(), dispatcher.run("1s"), dispatcher.running(),
           _error(dispatcher.run, "500ms"), dispatcher.run("1.5s"), dispatcher.get("b").state, dispatcher.get("b").ready_at,
           dispatcher.run("1.7s"), dispatcher.running(), dispatcher.run(), dispatcher.run(), dispatcher.run("5s"),
           dispatcher.idle]
    return out + [_starts(dispatcher)]


def probe_dispatcher_intake_delay_and_cost():
    from relay import Dispatcher, Limiter
    limiter = Limiter(default="10/s")
    limiter.configure("mail", "2/s", burst=2)
    dispatcher = Dispatcher(workers=4, limiter=limiter)
    dispatcher.submit("m1", key="mail", cost=2)
    dispatcher.submit("m2", key="mail", delay="300ms")
    dispatcher.submit("m3", key="mail", delay="2s")
    dispatcher.submit("m4", key="mail", cost=3)
    dispatcher.submit("d1", key="bulk", cost=10)
    dispatcher.submit("d2", key="bulk", cost=5, delay="100ms")
    out = [[j.id, j.ready_at] for j in dispatcher.jobs()]
    dispatcher.run()
    out += [_starts(dispatcher), limiter.status(dispatcher.now)]
    return out


# --- stats ------------------------------------------------------------------------------
def probe_stats_percentile():
    from relay import percentile
    values = [15, 20, 35, 40, 50]
    out = [[p, percentile(values, p)] for p in (1, 5, 20, 21, 30, 40, 41, 50, 60, 61, 80, 99, 100)]
    out += [percentile([7], 1), percentile([7], 100), percentile([], 50), percentile(range(1, 11), 90),
            percentile([3, 1, 2], 67), percentile([3, 1, 2], 66), percentile([3, 1, 2], 34), percentile([3, 1, 2], 33)]
    out.append([_error(percentile, values, p) for p in (0, 101, -5, 50.0, True, "50")])
    return out


def probe_stats_reports():
    from relay import Dispatcher, Limiter, key_report, key_table, order_of_starts, summary, timeline
    from relay.stats import format_table
    limiter = Limiter()
    limiter.configure("mail", "4/s", burst=1)
    dispatcher = Dispatcher(workers=2, limiter=limiter, backoff="fixed 100ms")
    for n in range(4):
        dispatcher.submit(f"m{n}", key="mail", takes="100ms", fails=1 if n == 2 else 0)
    dispatcher.submit("x", key="sms", takes="1s", fails=3, attempts=3)
    dispatcher.submit("y", key="sms", delay="5s")
    dispatcher.run("3s")
    out = [summary(dispatcher), key_report(dispatcher), key_table(dispatcher), order_of_starts(dispatcher),
           timeline(dispatcher, "m2"), timeline(dispatcher, since=2000), timeline(dispatcher)[:3]]
    out.append(format_table([[1, None, "ab"], [22, True, "c"]], ["n", "flag", "name"]))
    dispatcher.run()
    out += [summary(dispatcher), key_report(dispatcher)[1], timeline(Dispatcher())]
    return out


# --- script -----------------------------------------------------------------------------
def probe_script_flow():
    from relay import replay
    dispatcher, outputs = replay("""
# comment line
workers 2
backoff linear 100ms +100ms max 250ms
rate mail 2/s burst 2 maxwait 1s   # trailing comment
rate * 5/s burst 1
submit a key mail takes 300ms prio 1
submit b key mail takes 100ms fails 3 attempts 4
batch c key mail ; d key bulk cost 2 delay 150ms
submit e key mail
submit z fails 9 attempts 1 delay 600ms
cancel d
show a
tokens mail
run until 450ms
starts
revive zz
run
revive z after 250ms
run
starts b
stats
keys
tokens bulk
advance 1.5s
show b
""")
    return [outputs, dispatcher.now, dispatcher.workers, str(dispatcher.backoff)]


def probe_script_errors():
    from relay import ScriptError, replay
    bad = ["submit", "submit a prio", "submit a colour red", "submit a prio 1 prio 2", "rate mail", "rate mail 2/s burst",
           "rate mail 2/s speed 3", "rate mail 2/s burst 1 burst 2", "rate * 1/s maxwait 1s", "workers two", "workers",
           "backoff slow", "submit a\nworkers 2", "submit a\nbackoff fixed 1s", "run later 5s", "advance", "show",
           "revive a later 1s", "launch a", "stats now", "cancel a b", "starts a b", "keys x", "tokens"]
    out = []
    for text in bad:
        try:
            replay(text)
            out.append(None)
        except ScriptError as exc:
            out.append(exc.line)
    out.append(_error(replay, 5))
    _, outputs = replay("submit a\nsubmit a\ncancel zz\nrevive a\nrate bad-Key 1/s\nrate k 0/s\nsubmit b takes x\n"
                        "run until 0ms\nrun\nrun until 0ms\nshow a\nbatch c ; c\nbatch c prio 3 ; d prio 99\nstarts\n"
                        "tokens free\nadvance 1s\nshow c\n")
    out.append(outputs)
    return out


# --- planted-behaviour targets: intake waits round up ------------------------------------
def probe_intake_wait_rounds_up():
    from relay import Bucket, Limiter, Rate
    bucket = Bucket("api", Rate(3, 1000, 1), 0)
    out = [[bucket.take(0) for _ in range(4)], bucket.wait(0), bucket.available(1000), bucket.wait(1000),
           bucket.available(1001), bucket.wait(1001)]
    sevens = Bucket("s", Rate(7, 2000, 2), 0)
    out.append([sevens.take(0, 2), sevens.take(0), sevens.take(0), sevens.take(100, 3), sevens.wait(100)])
    limiter = Limiter()
    limiter.configure("api", "6/s", burst=1, max_wait="166ms")
    out += [limiter.reserve([("api", 1)], 0), _error(limiter.reserve, [("api", 1)], 0), limiter.wait("api", 0),
            limiter.wait("api", 1), limiter.wait("api", 166), limiter.available("api", 166), limiter.wait("api", 167),
            limiter.available("api", 167), limiter.reserve([("api", 1)], 167)]
    return out


def probe_intake_wait_start_times():
    from relay import Dispatcher, Limiter
    limiter = Limiter()
    limiter.configure("mail", "3/s", burst=1)
    limiter.configure("sms", "9/2s", burst=2)
    dispatcher = Dispatcher(workers=3, limiter=limiter)
    for n in range(4):
        dispatcher.submit(f"m{n}", key="mail", takes="10ms")
    for n in range(4):
        dispatcher.submit(f"s{n}", key="sms", takes="10ms")
    out = [[j.id, j.ready_at] for j in dispatcher.jobs()]
    dispatcher.run()
    return out + [_starts(dispatcher)]


def probe_intake_wait_script():
    from relay import replay
    _, outputs = replay("rate api 7/s burst 2\nbatch a key api ; b key api ; c key api ; d key api cost 2\n"
                        "rate web 3/2s burst 1 maxwait 667ms\nsubmit w1 key web\nsubmit w2 key web\nsubmit w3 key web\n"
                        "run\nstarts\ntokens api\n")
    return outputs


# --- planted-behaviour targets: dispatch order among ready jobs ----------------------------
def probe_ready_time_breaks_ties():
    from relay import Backlog, Job
    backlog = Backlog()
    backlog.push(Job("early-ticket", priority=2), 400)
    backlog.push(Job("late-ticket", priority=2), 100)
    backlog.push(Job("other", priority=2), 400)
    backlog.push(Job("high", priority=3), 450)
    backlog.push(Job("low", priority=1), 0)
    out = [backlog.pop_ready(399).id, [backlog.pop_ready(500).id for _ in range(4)]]
    again = Backlog()
    for name, ready in (("first", 50), ("second", 20), ("third", 20)):
        again.push(Job(name), ready)
    out.append([again.pop_ready(60).id for _ in range(3)])
    return out


def probe_retry_ready_order():
    from relay import Dispatcher
    dispatcher = Dispatcher(workers=1, backoff="fixed 100ms")
    dispatcher.submit("report", delay="600ms", takes="10ms")
    dispatcher.submit("long", takes="1s")
    dispatcher.submit("email", delay="100ms", takes="10ms")
    dispatcher.submit("sync", takes="50ms", fails=1, priority=0)
    dispatcher.run()
    out = [_starts(dispatcher)]
    two = Dispatcher(workers=2, backoff="exp 50ms x2")
    two.submit("p", takes="400ms", priority=5)
    two.submit("q", takes="400ms", priority=5)
    two.submit("flaky", takes="20ms", fails=2, priority=1, delay="10ms")
    two.submit("batch", takes="20ms", priority=1, delay="200ms")
    two.submit("tail", takes="20ms", priority=1, delay="30ms")
    two.run()
    out.append(_starts(two))
    return out


def probe_ready_order_script():
    from relay import replay
    _, outputs = replay("rate mail 1/250ms burst 1\nsubmit big takes 1s\nsubmit m1 key mail\nsubmit m2 key mail\n"
                        "submit m3 key mail\nsubmit nudge delay 300ms\nsubmit later delay 900ms\nsubmit urgent delay 950ms prio 1\n"
                        "run\nstarts\n")
    return outputs


# --- planted-behaviour targets: a rejected reservation leaves no trace ------------------------
def probe_rejected_reservation_restores():
    from relay import Limiter, RateLimited
    limiter = Limiter()
    limiter.configure("mail", "2/s", burst=3, max_wait="1s")
    limiter.configure("sms", "1/500ms", burst=1, max_wait="0ms")
    out = [limiter.reserve([("mail", 1)], 0)]
    before = [limiter.bucket("mail", 0).state(), limiter.bucket("sms", 0).state()]
    for requests in ([("mail", 1), ("mail", 1), ("sms", 1), ("sms", 1)],
                     [("mail", 1), ("mail", 1), ("mail", 1), ("mail", 1), ("mail", 1)],
                     [("sms", 1), ("mail", 2), ("mail", 3)]):
        try:
            limiter.reserve(requests, 0)
            out.append("accepted")
        except RateLimited as exc:
            out.append([exc.key, exc.wait])
        out.append([limiter.bucket("mail", 0).state(), limiter.bucket("sms", 0).state()] == before)
    out += [limiter.available("mail", 0), limiter.available("sms", 0), _value(limiter.reserve, [("mail", 2), ("mail", 1)], 0)]
    return out


def probe_rejected_batch_then_submit():
    from relay import Dispatcher, Limiter
    limiter = Limiter()
    limiter.configure("mail", "4/s", burst=2, max_wait="500ms")
    limiter.configure("sms", "1/s", burst=1, max_wait="0ms")
    dispatcher = Dispatcher(workers=4, limiter=limiter)
    dispatcher.submit("m0", key="mail", takes="10ms")
    batch = [{"id": "m1", "key": "mail"}, {"id": "m2", "key": "mail"}, {"id": "s1", "key": "sms"},
             {"id": "s2", "key": "sms"}]
    out = [_error(dispatcher.submit_batch, batch), [j.id for j in dispatcher.jobs()]]
    out.append([_error(dispatcher.submit, name, key=key, takes="10ms") for name, key in (("m3", "mail"), ("m4", "mail"),
                                                                                         ("s3", "sms"), ("m5", "mail"))])
    out.append([[j.id, j.ready_at] for j in dispatcher.jobs()])
    dispatcher.run()
    return out + [_starts(dispatcher)]


def probe_rejected_batch_script():
    from relay import replay
    _, outputs = replay("rate api 5/s burst 2 maxwait 400ms\nsubmit warm key api\n"
                        "batch a key api ; b key api ; c key api ; d key api ; e key api\n"
                        "tokens api\nsubmit f key api\nsubmit g key api\nrun\nstarts\n")
    return outputs
