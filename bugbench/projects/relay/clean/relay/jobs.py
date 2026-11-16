"""Jobs and their life cycle.

States: ``queued`` -> ``running`` -> ``done``.  A failed run sends the job back
to ``queued`` for a retry while it has attempts left, otherwise to ``dead``.  A
queued job can be ``cancelled``; a dead job can be revived (``queued`` again,
with a fresh set of attempts).

``attempts`` counts the runs started since the job was submitted or revived.
A run fails if it is one of the first ``fails`` runs (scripted failures, used
by the script language and tests) or if the job's handler raises; otherwise
it succeeds and the handler's return value becomes the job's ``result``.

``history`` is a list of ``(time, event, detail)`` tuples in the order the
events happened.
"""
import re

from .clock import format_duration, parse_duration
from .errors import DurationError, InvalidJob, JobStateError
from .limiter import check_key

STATES = ("queued", "running", "done", "dead", "cancelled")
FINISHED = ("done", "dead", "cancelled")
JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
MAX_PRIORITY = 9
MAX_ATTEMPTS = 20


def _whole(value, what, low, high):
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidJob(f"{what} must be a whole number from {low} to {high}, not {value!r}")
    return value


class Job:
    """One unit of work.  Validates its specification on creation."""

    def __init__(self, job_id, key="default", priority=0, takes=0, attempts=3, fails=0, cost=1, handler=None):
        if not isinstance(job_id, str) or not JOB_ID.match(job_id):
            raise InvalidJob(f"invalid job id {job_id!r}")
        try:
            self.key = check_key(key)
            self.takes = parse_duration(takes)
        except DurationError as exc:
            raise InvalidJob(f"{job_id}: bad duration {takes!r}") from exc
        except Exception as exc:
            raise InvalidJob(f"{job_id}: bad key {key!r}") from exc
        if handler is not None and not callable(handler):
            raise InvalidJob(f"{job_id}: handler must be callable")
        self.id = job_id
        self.priority = _whole(priority, "priority", 0, MAX_PRIORITY)
        self.max_attempts = _whole(attempts, "attempts", 1, MAX_ATTEMPTS)
        self.fails = _whole(fails, "fails", 0, MAX_ATTEMPTS)
        self.cost = _whole(cost, "cost", 1, 1000)
        self.handler = handler
        self.state = "queued"
        self.attempts = 0
        self.ticket = None
        self.ready_at = None
        self.submitted_at = None
        self.started_at = None
        self.finished_at = None
        self.result = None
        self.error = None
        self.history = []

    @property
    def finished(self):
        return self.state in FINISHED

    def _require(self, *states):
        if self.state not in states:
            raise JobStateError(f"{self.id} is {self.state}, expected {' or '.join(states)}")

    def record(self, now, event, detail=""):
        self.history.append((now, event, detail))

    def outcome(self):
        """``(ok, value)`` for the run that has just started (see the module docs)."""
        if self.attempts <= self.fails:
            return False, f"scripted failure {self.attempts}"
        if self.handler is None:
            return True, None
        try:
            return True, self.handler(self)
        except Exception as exc:  # a handler failure is a failed run, not an error of relay
            return False, f"{type(exc).__name__}: {exc}"

    def mark_submitted(self, now, ready_at):
        self.submitted_at = now
        self.record(now, "submitted", f"ready {format_duration(ready_at)}")

    def mark_started(self, now, worker):
        self._require("queued")
        self.state = "running"
        self.attempts += 1
        if self.started_at is None:
            self.started_at = now
        self.record(now, "started", f"w{worker} attempt {self.attempts}")

    def mark_done(self, now, result):
        self._require("running")
        self.state, self.result, self.finished_at = "done", result, now
        self.record(now, "done")

    def mark_failed(self, now, error, retry_at):
        """A failed run; ``retry_at`` is the retry time, or None when the job is dead."""
        self._require("running")
        self.error = error
        if retry_at is None:
            self.state, self.finished_at = "dead", now
            self.record(now, "dead", error)
        else:
            self.state = "queued"
            self.record(now, "failed", f"{error}; retry {format_duration(retry_at)}")

    def mark_cancelled(self, now):
        self._require("queued")
        self.state, self.finished_at = "cancelled", now
        self.record(now, "cancelled")

    def revive(self, now):
        """Give a dead job a fresh set of attempts; the caller queues it again."""
        self._require("dead")
        self.state, self.attempts, self.fails = "queued", 0, 0
        self.finished_at = self.error = None
        self.record(now, "revived")

    @property
    def wait_time(self):
        """Milliseconds from submission to the first start, or None if it never started."""
        return None if self.started_at is None else self.started_at - self.submitted_at

    @property
    def latency(self):
        """Milliseconds from submission to completion of a done job, else None."""
        return self.finished_at - self.submitted_at if self.state == "done" else None

    def describe(self):
        """One line: ``<id> <key> p<priority> <state> attempts <n>/<max>``."""
        return f"{self.id} {self.key} p{self.priority} {self.state} attempts {self.attempts}/{self.max_attempts}"

    def __repr__(self):
        return f"Job({self.describe()})"
