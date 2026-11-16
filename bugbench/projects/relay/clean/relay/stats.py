"""Reports over a dispatcher: counts, per-key figures, percentiles and timelines.

Definitions:

* a job's *wait* is the time from submission to its first start;
* a done job's *latency* is the time from submission to completion;
* *runs* counts started runs, *retries* the runs after a job's first;
* percentiles use the nearest-rank method: the ``p``-th percentile of ``n``
  sorted values is the value at rank ``ceil(p * n / 100)`` (1-based), and
  ``p`` must be in ``(0, 100]``.  The percentile of no values is None.

Times in printed reports use the duration syntax (``1.5s``, ``250ms``).
"""
from .clock import ceil_div, format_duration
from .errors import RelayError
from .jobs import STATES


def percentile(values, pct):
    """Nearest-rank percentile of ``values`` (see the module docs)."""
    if isinstance(pct, bool) or not isinstance(pct, int) or not 0 < pct <= 100:
        raise RelayError(f"percentile must be a whole number in (0, 100], not {pct!r}")
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[ceil_div(pct * len(ordered), 100) - 1]


def summary(dispatcher):
    """``{"now", <state>: count for every state, "runs", "retries", "dead_letter"}``."""
    jobs = dispatcher.jobs()
    out = {"now": dispatcher.now}
    for state in STATES:
        out[state] = sum(1 for job in jobs if job.state == state)
    runs = [entry for job in jobs for entry in job.history if entry[1] == "started"]
    out["runs"] = len(runs)
    out["retries"] = len(runs) - sum(1 for job in jobs if job.started_at is not None)
    out["dead_letter"] = [job.id for job in dispatcher.dead_letter()]
    return out


def key_report(dispatcher):
    """Per key, by key name: ``[key, jobs, done, dead, runs, p50 wait, max wait, p90 latency]``."""
    keys = {}
    for job in dispatcher.jobs():
        keys.setdefault(job.key, []).append(job)
    rows = []
    for key in sorted(keys):
        jobs = keys[key]
        waits = [job.wait_time for job in jobs if job.wait_time is not None]
        latencies = [job.latency for job in jobs if job.latency is not None]
        runs = sum(1 for job in jobs for entry in job.history if entry[1] == "started")
        rows.append([key, len(jobs), sum(job.state == "done" for job in jobs), sum(job.state == "dead" for job in jobs),
                     runs, percentile(waits, 50), max(waits, default=None), percentile(latencies, 90)])
    return rows


def start_times(dispatcher, job_id=None):
    """``[[job id, attempt, start time]]`` for every started run, in the order they started."""
    found = []
    for when, text in dispatcher.log:
        words = text.split()
        if words[0] == "start" and (job_id is None or words[1] == job_id):
            found.append([words[1], int(words[-1]), when])
    return found


def order_of_starts(dispatcher):
    """Job ids in the order their first runs started."""
    return [job_id for job_id, attempt, _ in start_times(dispatcher) if attempt == 1]


def timeline(dispatcher, job_id=None, since=0):
    """Log lines ``"<time> <text>"`` from ``since`` on, the time right-aligned; one job's lines with ``job_id``."""
    picked = [(when, text) for when, text in dispatcher.log
              if when >= since and (job_id is None or text.split()[1] == job_id)]
    width = max((len(format_duration(when)) for when, _ in picked), default=0)
    return [f"{format_duration(when):>{width}} {text}" for when, text in picked]


def format_table(rows, headers):
    """A plain text table; None prints as ``-`` and numbers are right-aligned."""
    cells = [[str(h) for h in headers]] + [["-" if value is None else str(value) for value in row] for row in rows]
    widths = [max(len(row[column]) for row in cells) for column in range(len(headers))]
    lines = []
    for number, row in enumerate(cells):
        parts = []
        for column, text in enumerate(row):
            value = rows[number - 1][column] if number else None
            numeric = isinstance(value, int) and not isinstance(value, bool)
            parts.append(text.rjust(widths[column]) if numeric else text.ljust(widths[column]))
        lines.append("  ".join(parts).rstrip())
    return "\n".join(lines)


def key_table(dispatcher):
    """:func:`key_report` as a table with waits and latencies printed as durations."""
    rows = []
    for row in key_report(dispatcher):
        rows.append(row[:5] + [None if value is None else format_duration(value) for value in row[5:]])
    return format_table(rows, ["key", "jobs", "done", "dead", "runs", "p50 wait", "max wait", "p90 latency"])
