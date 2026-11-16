# relay

Intake rate limits and a job queue on a virtual clock: token buckets with
debt, a priority backlog, simulated workers, retries with backoff, a
dead-letter list, reports and a small script language. Standard library
only, Python 3.10+. Nothing reads the wall clock; every time is an integer
number of milliseconds.

```python
from relay import Dispatcher, Limiter

limiter = Limiter()
limiter.configure("mail", "3/s", burst=1)
dispatcher = Dispatcher(workers=2, limiter=limiter, backoff="exp 100ms x2 max 2s")
dispatcher.submit("welcome", key="mail", takes="200ms")
dispatcher.submit("digest", key="mail", takes="1s", fails=1)
dispatcher.run()
print(dispatcher.log)
```

The same with the script language:

```python
from relay import replay

dispatcher, outputs = replay("""
workers 2
backoff exp 100ms x2 max 2s
rate mail 3/s burst 1
submit welcome key mail takes 200ms
submit digest key mail takes 1s fails 1
run
starts
""")
```

## Modules

| Module | Responsibility |
|---|---|
| `clock.py` | Virtual clock, duration parsing and formatting |
| `limiter.py` | Rates, per-key token buckets with debt, all-or-nothing reservations |
| `backoff.py` | Retry policies: fixed, linear, exponential, cap, reproducible jitter |
| `jobs.py` | `Job`: specification checks, states, attempts, history |
| `backlog.py` | Queued jobs, readiness and the dispatch order |
| `dispatcher.py` | `Dispatcher`: submit, batches, cancel, revive, worker simulation, retries, dead letters |
| `stats.py` | Summary, per-key report, nearest-rank percentiles, start times, timelines |
| `script.py` | The script language (`replay`) |
| `errors.py` | Exception hierarchy |

## Rules

- Durations: `250ms`, `1.5s`, `2m`, `1m30s`, `1h0.5s` (largest unit first,
  each unit once, a whole number of milliseconds in total); a plain `int` is
  milliseconds.
- A rate `N/P` earns N tokens every P milliseconds, continuously, up to its
  burst (default N). A new bucket is full. Taking tokens may put a bucket into
  debt; the taker then waits until the tokens are fully earned. Waits are
  whole milliseconds, rounded up: at the returned time the tokens exist, one
  millisecond earlier they do not.
- A key with a maximum wait rejects (`RateLimited`) a take that would wait
  longer, and the bucket is unchanged. A reservation of several takes is all
  or nothing: when one take is rejected, every bucket is left exactly as it
  was before the reservation.
- Every job takes `cost` (default 1) intake tokens from its key when it is
  submitted, and becomes ready at `submit time + max(delay, intake wait)`.
  A batch is all or nothing: a rejected batch submits no job and uses no
  intake tokens. Cancelling a queued job does not return its tokens; reviving
  a dead job uses none.
- Dispatch order among ready jobs: higher priority first; among equal
  priorities the job that became ready first; then the job that entered the
  backlog first. A job that comes back for a retry enters the backlog again.
- At each moment, runs that end are completed first (by end time, then worker
  number); then free workers, lowest number first, take ready jobs.
- After failed attempt n, a job with attempts left is retried
  `backoff.delay(n)` after the run ended; otherwise it is dead. Exponential
  delays are `base * factor ** (n - 1)`, capped by `max`, then shortened by
  the jitter, then rounded to the nearest millisecond (halves up).
- Percentiles use the nearest-rank method.

Run the tests with `python -m unittest discover -s tests`.
