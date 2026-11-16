"""Exception hierarchy for agenda.

All errors derive from :class:`AgendaError`.  Calendar operations either
complete or raise before changing anything.
"""


class AgendaError(Exception):
    """Base class for all errors raised by this package."""


class InvalidTime(AgendaError):
    """A date, time, datetime or duration is malformed or out of range."""


class InvalidRule(AgendaError):
    """A recurrence rule is malformed or contradictory."""


class UnknownEvent(AgendaError):
    """No event with this identifier exists."""


class DuplicateEvent(AgendaError):
    """An event with this identifier already exists."""


class NotAnOccurrence(AgendaError):
    """The given start is not a start of the event (for cancel, move or split)."""


class ScheduleError(AgendaError):
    """A schedule line could not be parsed or executed.

    ``line`` is the 1-based line number in the schedule text.  When the line
    parsed but the calendar operation failed, the original exception is
    available as ``__cause__``.
    """

    def __init__(self, line, message):
        super().__init__(f"line {line}: {message}")
        self.line = line
