"""Exception hierarchy for relay.

Every error raised on purpose derives from :class:`RelayError`, so callers can
catch one type.  The script runner reports a failed command by the class name
of its error.
"""


class RelayError(Exception):
    """Base class for every error raised by relay."""


class DurationError(RelayError):
    """A duration is malformed, negative or not a whole number of milliseconds."""


class ClockError(RelayError):
    """The virtual clock would have to go backwards."""


class RateError(RelayError):
    """A rate or a rate-limit setting is malformed."""


class RateLimited(RelayError):
    """A request would have to wait longer than its key's maximum wait.

    ``wait`` is the wait in milliseconds the request would have needed."""

    def __init__(self, key, wait, max_wait):
        super().__init__(f"{key}: would wait {wait} ms, the limit is {max_wait} ms")
        self.key = key
        self.wait = wait
        self.max_wait = max_wait


class BackoffError(RelayError):
    """A retry policy is malformed or asked for an impossible attempt number."""


class InvalidJob(RelayError):
    """A job specification is malformed."""


class DuplicateJob(RelayError):
    """A job id is already in use."""


class UnknownJob(RelayError):
    """No job with this id exists (or it is not where the operation needs it)."""


class JobStateError(RelayError):
    """The operation is not allowed in the job's current state."""


class ScriptError(RelayError):
    """A script line cannot be parsed; ``line`` is 1-based."""

    def __init__(self, line, message):
        super().__init__(f"line {line}: {message}")
        self.line = line
