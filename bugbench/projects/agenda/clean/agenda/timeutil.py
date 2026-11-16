"""Dates, times, durations and half-open intervals.

All times are naive local ``datetime`` values with whole minutes.  Durations
are ``timedelta`` values of whole minutes, written like ``45m``, ``2h`` or
``1h30m``.  Weekdays are numbered Monday = 0 .. Sunday = 6 and written as
three-letter English abbreviations (``mon`` .. ``sun``).
"""
from dataclasses import dataclass
import datetime
import re

from .errors import InvalidTime

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_TIME = re.compile(r"^(\d{2}):(\d{2})$")
_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")


def parse_date(text):
    match = _DATE.match(str(text).strip())
    if not match:
        raise InvalidTime(f"expected YYYY-MM-DD, got {text!r}")
    try:
        return datetime.date(*(int(part) for part in match.groups()))
    except ValueError as exc:
        raise InvalidTime(str(exc)) from None


def parse_time(text):
    match = _TIME.match(str(text).strip())
    if not match:
        raise InvalidTime(f"expected HH:MM, got {text!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise InvalidTime(f"no such time {text!r}")
    return datetime.time(hour, minute)


def parse_datetime(date_text, time_text):
    return datetime.datetime.combine(parse_date(date_text), parse_time(time_text))


def parse_duration(text):
    """``1h30m`` -> 90 minutes.  Zero and empty durations are rejected."""
    match = _DURATION.match(str(text).strip())
    if not match or not any(match.groups()):
        raise InvalidTime(f"expected a duration like 45m, 2h or 1h30m, got {text!r}")
    minutes = int(match.group(1) or 0) * 60 + int(match.group(2) or 0)
    if minutes == 0:
        raise InvalidTime("a duration must be positive")
    return datetime.timedelta(minutes=minutes)


def format_duration(delta):
    """``timedelta(minutes=90)`` -> ``1h30m``; ``0m`` for zero."""
    minutes = whole_minutes(delta)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}h{rest:02d}m"
    return f"{hours}h" if hours else f"{rest}m"


def whole_minutes(delta):
    seconds = delta.total_seconds()
    if seconds % 60:
        raise InvalidTime("durations must be whole minutes")
    return int(seconds // 60)


def check_minute(moment):
    """Return ``moment`` if it is a datetime on a whole minute; raise InvalidTime otherwise."""
    if not isinstance(moment, datetime.datetime) or moment.second or moment.microsecond or moment.tzinfo:
        raise InvalidTime(f"expected a naive datetime on a whole minute, got {moment!r}")
    return moment


def parse_weekdays(text):
    """``"mon,fri"`` -> ``[0, 4]`` in the order written; ``weekdays`` expands to mon..fri."""
    days = []
    for part in str(text).split(","):
        name = part.strip().lower()
        if name == "weekdays":
            days.extend(range(5))
        elif name in WEEKDAYS:
            days.append(WEEKDAYS.index(name))
        else:
            raise InvalidTime(f"unknown weekday {part.strip()!r}")
    return days


def days_in_month(year, month):
    following = datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
    return (following - datetime.date(year, month, 1)).days


def add_months(day, months, monthday=None):
    """The date ``months`` later on ``monthday`` (default: the same day).

    A positive ``monthday`` past the end of the target month gives that
    month's last day; ``-1`` means the last day, ``-2`` the day before it.
    """
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    length = days_in_month(year, month)
    wanted = day.day if monthday is None else monthday
    if wanted < 0:
        wanted = max(1, length + 1 + wanted)
    return datetime.date(year, month, min(wanted, length))


def monday_of(day):
    return day - datetime.timedelta(days=day.weekday())


@dataclass(frozen=True)
class Interval:
    """Half-open time range ``start <= t < end``; back-to-back intervals do not overlap."""

    start: datetime.datetime
    end: datetime.datetime

    def __post_init__(self):
        if not self.start < self.end:
            raise InvalidTime("an interval must end after it starts")

    def overlaps(self, other):
        return self.start < other.end and other.start < self.end

    def contains(self, moment):
        return self.start <= moment < self.end

    @property
    def duration(self):
        return self.end - self.start


def merge(intervals):
    """Sorted union of intervals; touching intervals are joined."""
    merged = []
    for interval in sorted(intervals, key=lambda item: (item.start, item.end)):
        if merged and interval.start <= merged[-1].end:
            if interval.end > merged[-1].end:
                merged[-1] = Interval(merged[-1].start, interval.end)
        else:
            merged.append(interval)
    return merged
