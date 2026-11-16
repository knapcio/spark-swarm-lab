"""The backlog: queued jobs waiting for a worker.

A job is *ready* once the clock has reached its ``ready_at``.  Every push
issues a new ticket, so a job that comes back for a retry queues behind the
jobs that are already waiting.

``pop_ready`` takes the ready job with the highest priority; among equal
priorities the one that became ready first; among those the one with the
lowest ticket.  ``pending`` lists all queued jobs, ready or not, in the order
they become ready (ties: higher priority first, then ticket).
"""
from .errors import UnknownJob


class Backlog:
    def __init__(self):
        self._jobs = []
        self._next_ticket = 1

    def __len__(self):
        return len(self._jobs)

    def __contains__(self, job_id):
        return any(job.id == job_id for job in self._jobs)

    def push(self, job, ready_at):
        """Queue ``job`` to become ready at ``ready_at`` (a new ticket every time)."""
        job.ready_at = ready_at
        job.ticket = self._next_ticket
        self._next_ticket += 1
        self._jobs.append(job)
        return job.ticket

    def pop_ready(self, now):
        """Remove and return the next ready job (see the module docs), or None."""
        ready = [job for job in self._jobs if job.ready_at <= now]
        if not ready:
            return None
        job = min(ready, key=lambda job: (-job.priority, job.ready_at, job.ticket))
        self._jobs.remove(job)
        return job

    def withdraw(self, job_id):
        """Remove the queued job ``job_id`` and return it."""
        for index, job in enumerate(self._jobs):
            if job.id == job_id:
                return self._jobs.pop(index)
        raise UnknownJob(f"{job_id} is not in the backlog")

    def next_ready_at(self):
        """The earliest ``ready_at`` in the backlog, or None when it is empty."""
        return min((job.ready_at for job in self._jobs), default=None)

    def ready_count(self, now):
        return sum(1 for job in self._jobs if job.ready_at <= now)

    def pending(self):
        """All queued jobs in the order they become ready (ties: priority, then ticket)."""
        return sorted(self._jobs, key=lambda job: (job.ready_at, -job.priority, job.ticket))

    def by_key(self):
        """``{key: number of queued jobs}`` sorted by key."""
        counts = {}
        for job in self._jobs:
            counts[job.key] = counts.get(job.key, 0) + 1
        return dict(sorted(counts.items()))
