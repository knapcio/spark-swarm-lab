"""Virtual time in whole milliseconds and the duration syntax.

relay never reads the wall clock.  Every timestamp is an ``int`` number of
milliseconds on a :class:`Clock` that only moves when it is told to.

Duration syntax: one or more ``<number><unit>`` parts with the units ``h``,
``m``, ``s`` and ``ms``, largest unit first and each unit at most once, for
example ``250ms``, ``1.5s``, ``2m``, ``1m30s`` or ``1h0.5s``.  Numbers may have
a fractional part, but the total must be a whole number of milliseconds
(``1.0005s`` is rejected).  A plain non-negative ``int`` is taken as
milliseconds.  :func:`format_duration` is the inverse: it prints the shortest
form, for example ``0ms``, ``999ms``, ``1.5s``, ``1m30s``, ``2h`` or
``1h0.25s``.
"""
import re
from fractions import Fraction

from .errors import ClockError, DurationError

UNITS = {"h": 3_600_000, "m": 60_000, "s": 1000, "ms": 1}
_ORDER = list(UNITS)
_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def parse_duration(value):
    """Milliseconds (an ``int``) for a duration text or a non-negative ``int``."""
    if isinstance(value, bool):
        raise DurationError("a duration cannot be a boolean")
    if isinstance(value, int):
        if value < 0:
            raise DurationError(f"negative duration {value}")
        return value
    if not isinstance(value, str):
        raise DurationError(f"not a duration: {value!r}")
    text = value.strip()
    if not text:
        raise DurationError("empty duration")
    total, position, previous = Fraction(0), 0, None
    for match in _PART.finditer(text):
        if match.start() != position:
            raise DurationError(f"malformed duration {value!r}")
        rank = _ORDER.index(match.group(2))
        if previous is not None and rank <= previous:
            raise DurationError(f"units out of order or repeated in {value!r}")
        previous = rank
        total += Fraction(match.group(1)) * UNITS[match.group(2)]
        position = match.end()
    if previous is None or position != len(text):
        raise DurationError(f"malformed duration {value!r}")
    if total.denominator != 1:
        raise DurationError(f"{value!r} is not a whole number of milliseconds")
    return int(total)


def format_duration(ms):
    """The shortest duration text for ``ms`` milliseconds (see the module docs)."""
    ms = parse_duration(ms)
    if ms < 1000:
        return f"{ms}ms"
    hours, rest = divmod(ms, UNITS["h"])
    minutes, rest = divmod(rest, UNITS["m"])
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if rest:
        seconds, millis = divmod(rest, 1000)
        parts.append(f"{seconds}.{millis:03d}".rstrip("0").rstrip(".") + "s")
    return "".join(parts)


def ceil_div(numerator, denominator):
    """``numerator / denominator`` rounded up, for integers (``denominator > 0``)."""
    return -(-numerator // denominator)


class Clock:
    """A virtual clock in milliseconds, starting at ``start`` (default 0)."""

    def __init__(self, start=0):
        self._now = parse_duration(start)

    @property
    def now(self):
        return self._now

    def advance(self, duration):
        """Move forward by ``duration``; returns the new time."""
        self._now += parse_duration(duration)
        return self._now

    def advance_to(self, when):
        """Move to the absolute time ``when``; moving backwards raises ClockError."""
        when = parse_duration(when)
        if when < self._now:
            raise ClockError(f"cannot go back from {self._now} ms to {when} ms")
        self._now = when
        return self._now

    def __repr__(self):
        return f"Clock({format_duration(self._now)})"
