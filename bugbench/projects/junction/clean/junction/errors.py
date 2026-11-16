"""Exception hierarchy for junction.

Every error raised on purpose derives from :class:`JunctionError`, so callers
can catch one type.  Parse errors carry the 1-based line number of the text
they were read from.
"""


class JunctionError(Exception):
    """Base class for every error raised by junction."""


class InvalidTime(JunctionError):
    """A time of day is malformed or outside 00:00-47:59."""


class UnknownStation(JunctionError):
    """A station code is not part of the network."""


class UnknownTrip(JunctionError):
    """A trip id is not part of the timetable."""


class NotRunning(JunctionError):
    """The trip does not run on the requested service day."""


class NoConnection(JunctionError):
    """No journey reaches the destination under the planning rules."""


class ParseError(JunctionError):
    """A timetable or disruption text could not be read."""

    def __init__(self, line, reason):
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason
