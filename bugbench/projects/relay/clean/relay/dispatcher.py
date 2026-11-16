"""The dispatcher: intake, backlog, workers, retries and the dead-letter list.

``submit`` checks the job, takes ``cost`` intake tokens from the job's key
(see the limiter) and queues it.  The job becomes ready at
``now + max(delay, intake wait)``.  ``submit_batch`` does the same for several
jobs, all or nothing: if any job is invalid, reuses an id, or would wait
longer than its key's maximum wait, nothing is submitted and no intake tokens
are used.  Cancelling a queued job does not give its intake tokens back.

``run`` simulates the workers on the virtual clock.  At each moment, runs that
end are completed first (by end time, then worker number), then free workers,
lowest number first, take ready jobs from the backlog.  A run lasts the job's
``takes``.  After a failed run the job is retried ``backoff.delay(attempt)``
after the run ended while it has attempts left; otherwise it is dead and goes
to the dead-letter list.  ``run(until)`` handles every moment up to and
including ``until`` and leaves the clock at ``until``; ``run()`` goes on until
nothing is left to do.
"""
from .backlog import Backlog
from .backoff import DEFAULT_BACKOFF, parse_backoff
from .clock import Clock, format_duration, parse_duration
from .errors import ClockError, DuplicateJob, InvalidJob, JobStateError, UnknownJob
from .jobs import Job
from .limiter import Limiter

SPEC_FIELDS = ("id", "key", "priority", "takes", "delay", "attempts", "fails", "cost", "handler")
MAX_WORKERS = 64


class Dispatcher:
    def __init__(self, workers=1, limiter=None, backoff=None, clock=None):
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= MAX_WORKERS:
            raise InvalidJob(f"workers must be a whole number from 1 to {MAX_WORKERS}")
        self.clock = clock or Clock()
        self.limiter = limiter if limiter is not None else Limiter()
        self.backoff = parse_backoff(DEFAULT_BACKOFF if backoff is None else backoff)
        self.backlog = Backlog()
        self.log = []
        self._jobs = {}
        self._dead = []
        self._slots = [None] * workers

    @property
    def now(self):
        return self.clock.now

    @property
    def workers(self):
        return len(self._slots)

    def _note(self, when, text):
        self.log.append((when, text))

    # --- intake -----------------------------------------------------------------
    def _build(self, spec, taken):
        if not isinstance(spec, dict) or "id" not in spec:
            raise InvalidJob(f"a job specification must be a dict with an id, not {spec!r}")
        unknown = sorted(set(spec) - set(SPEC_FIELDS))
        if unknown:
            raise InvalidJob(f"unknown job fields {unknown}")
        fields = {name: value for name, value in spec.items() if name not in ("id", "delay")}
        job = Job(spec["id"], **fields)
        if job.id in self._jobs or job.id in taken:
            raise DuplicateJob(f"job {job.id} already exists")
        try:
            delay = parse_duration(spec.get("delay", 0))
        except Exception as exc:
            raise InvalidJob(f"{job.id}: bad delay {spec.get('delay')!r}") from exc
        return job, delay

    def submit(self, job_id, **fields):
        """Submit one job; ``fields`` are the keyword fields of a batch specification."""
        return self.submit_batch([dict(fields, id=job_id)])[0]

    def submit_batch(self, specs):
        """Submit several jobs at once, all or nothing (see the module docs)."""
        if not isinstance(specs, (list, tuple)) or not specs:
            raise InvalidJob("a batch needs at least one job")
        built, taken = [], set()
        for spec in specs:
            job, delay = self._build(spec, taken)
            taken.add(job.id)
            built.append((job, delay))
        now = self.now
        waits = self.limiter.reserve([(job.key, job.cost) for job, _ in built], now)
        for (job, delay), wait in zip(built, waits):
            self._jobs[job.id] = job
            self.backlog.push(job, now + max(delay, wait))
            job.mark_submitted(now, job.ready_at)
            self._note(now, f"submit {job.id} ready {format_duration(job.ready_at)}")
        return [job for job, _ in built]

    # --- queries and job control ----------------------------------------------------
    def get(self, job_id):
        try:
            return self._jobs[job_id]
        except (KeyError, TypeError):
            raise UnknownJob(f"no job {job_id!r}") from None

    def jobs(self):
        """Every job in submission order."""
        return list(self._jobs.values())

    def dead_letter(self):
        """Dead jobs in the order they died (revived jobs leave the list)."""
        return list(self._dead)

    def running(self):
        """``[worker number, job id, end time]`` for every busy worker."""
        return [[index + 1, slot[0].id, slot[1]] for index, slot in enumerate(self._slots) if slot is not None]

    def cancel(self, job_id):
        job = self.get(job_id)
        if job.state != "queued":
            raise JobStateError(f"{job_id} is {job.state}; only queued jobs can be cancelled")
        self.backlog.withdraw(job_id)
        job.mark_cancelled(self.now)
        self._note(self.now, f"cancel {job_id}")
        return job

    def revive(self, job_id, delay=0):
        """Queue a dead job again with fresh attempts, ready after ``delay``; uses no intake tokens."""
        job = self.get(job_id)
        if job.state != "dead":
            raise JobStateError(f"{job_id} is {job.state}; only dead jobs can be revived")
        ready_at = self.now + parse_duration(delay)
        job.revive(self.now)
        self._dead.remove(job)
        self.backlog.push(job, ready_at)
        self._note(self.now, f"revive {job_id} ready {format_duration(ready_at)}")
        return job

    # --- simulation -----------------------------------------------------------------
    def _next_moment(self):
        moments = [slot[1] for slot in self._slots if slot is not None]
        if None in self._slots and len(self.backlog):
            moments.append(max(self.now, self.backlog.next_ready_at()))
        return min(moments, default=None)

    def _complete(self, moment):
        ending = sorted((slot[1], index) for index, slot in enumerate(self._slots) if slot and slot[1] <= moment)
        for end, index in ending:
            job, _, ok, value = self._slots[index]
            self._slots[index] = None
            if ok:
                job.mark_done(end, value)
                self._note(end, f"done {job.id}")
            elif job.attempts < job.max_attempts:
                retry_at = end + self.backoff.delay(job.attempts, job.id)
                job.mark_failed(end, value, retry_at)
                self.backlog.push(job, retry_at)
                self._note(end, f"fail {job.id} attempt {job.attempts}, retry at {format_duration(retry_at)}")
            else:
                job.mark_failed(end, value, None)
                self._dead.append(job)
                self._note(end, f"dead {job.id} after {job.attempts} attempts")

    def _dispatch(self, moment):
        for index, slot in enumerate(self._slots):
            if slot is not None:
                continue
            job = self.backlog.pop_ready(moment)
            if job is None:
                break
            job.mark_started(moment, index + 1)
            ok, value = job.outcome()
            self._slots[index] = (job, moment + job.takes, ok, value)
            self._note(moment, f"start {job.id} on w{index + 1} attempt {job.attempts}")

    def step(self):
        """Handle the next moment with something to do; returns its time, or None when idle."""
        moment = self._next_moment()
        if moment is None:
            return None
        self.clock.advance_to(moment)
        self._complete(moment)
        self._dispatch(moment)
        return moment

    def run(self, until=None):
        """Simulate up to and including ``until`` (or until idle); returns the clock time."""
        limit = None if until is None else parse_duration(until)
        if limit is not None and limit < self.now:
            raise ClockError(f"cannot run until {limit} ms, it is already {self.now} ms")
        while True:
            moment = self._next_moment()
            if moment is None or (limit is not None and moment > limit):
                break
            self.step()
        if limit is not None:
            self.clock.advance_to(limit)
        return self.now

    @property
    def idle(self):
        return not len(self.backlog) and all(slot is None for slot in self._slots)
