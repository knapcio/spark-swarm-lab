"""Recurrence rules for repeating events.

``Rule(freq, interval=1, count=None, until=None, weekdays=None, monthday=None)``

* ``freq`` is ``daily``, ``weekly``, ``monthly`` or ``yearly``; ``interval``
  repeats every n-th day, week, month or year.
* Weekly rules may list ``weekdays`` (Monday = 0), in any order and with
  repeats; the default is the weekday of the first start.  Weeks start on
  Monday, and ``interval`` counts weeks from the week of the first start.
* Monthly rules use ``monthday`` (default: the day of the first start).  A
  day past the end of a shorter month falls on that month's last day; ``-1``
  is always the last day.  Yearly rules on 29 February use 28 February in
  other years.
* An occurrence is every date produced by the rule on or after the first
  start's date, at the first start's time of day.
* ``count`` is the total number of occurrences the rule generates, including
  occurrences that are later cancelled.  ``until`` is the last allowed date,
  inclusive.  With both, the series stops at whichever comes first.

Every method that returns starts returns them in chronological order.
"""
import datetime
import itertools

from .errors import InvalidRule
from .timeutil import WEEKDAYS, add_months, check_minute, monday_of, parse_date, parse_weekdays

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
_UNITS = {"days": "daily", "weeks": "weekly", "months": "monthly", "years": "yearly"}


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidRule(f"{what} must be a positive int, got {value!r}")
    return value


class Rule:
    def __init__(self, freq, interval=1, count=None, until=None, weekdays=None, monthday=None):
        if freq not in FREQUENCIES:
            raise InvalidRule(f"unknown frequency {freq!r}")
        self.freq = freq
        self.interval = _positive_int(interval, "interval")
        self.count = None if count is None else _positive_int(count, "count")
        if until is not None and (not isinstance(until, datetime.date) or isinstance(until, datetime.datetime)):
            raise InvalidRule("until must be a date")
        self.until = until
        if weekdays is not None:
            if freq != "weekly" or not weekdays:
                raise InvalidRule("weekdays need a weekly rule and at least one day")
            if any(isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in weekdays):
                raise InvalidRule("weekdays are ints from 0 (Monday) to 6 (Sunday)")
            weekdays = tuple(sorted(set(weekdays)))
        self.weekdays = weekdays
        if monthday is not None:
            if freq != "monthly" or isinstance(monthday, bool) or not isinstance(monthday, int) \
                    or monthday == 0 or not -31 <= monthday <= 31:
                raise InvalidRule("monthday needs a monthly rule and an int from 1 to 31 or -31 to -1")
        self.monthday = monthday

    def replace(self, **changes):
        values = dict(freq=self.freq, interval=self.interval, count=self.count, until=self.until,
                      weekdays=self.weekdays, monthday=self.monthday)
        values.update(changes)
        return Rule(**values)

    def _key(self):
        return (self.freq, self.interval, self.count, self.until, self.weekdays, self.monthday)

    def __eq__(self, other):
        return isinstance(other, Rule) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __repr__(self):
        return f"Rule({self.describe()!r})"

    def _dates(self, first):
        """Candidate dates on or after ``first`` (unbounded)."""
        step = self.interval
        if self.freq == "daily":
            day = first
            while True:
                yield day
                day += datetime.timedelta(days=step)
        elif self.freq == "weekly":
            days, week = self.weekdays or (first.weekday(),), monday_of(first)
            while True:
                for weekday in days:
                    day = week + datetime.timedelta(days=weekday)
                    if day >= first:
                        yield day
                week += datetime.timedelta(weeks=step)
        else:
            months = step if self.freq == "monthly" else 12 * step
            for index in itertools.count():
                day = add_months(first, index * months, self.monthday)
                if day >= first:
                    yield day

    def starts(self, first):
        """Every occurrence start for a series whose first start is ``first``."""
        first = check_minute(first)
        produced = 0
        for day in self._dates(first.date()):
            if self.until is not None and day > self.until:
                return
            yield datetime.datetime.combine(day, first.time())
            produced += 1
            if self.count is not None and produced >= self.count:
                return

    def between(self, first, start, end):
        """Occurrence starts ``s`` with ``start <= s < end``."""
        found = []
        for moment in self.starts(first):
            if moment >= end:
                break
            if moment >= start:
                found.append(moment)
        return found

    def is_start(self, first, moment):
        for candidate in self.starts(first):
            if candidate == moment:
                return True
            if candidate > moment:
                return False
        return False

    def is_finite(self):
        return self.count is not None or self.until is not None

    def describe(self):
        """Readable summary, e.g. ``every 2 weeks on mon, fri; 6 times; until 2026-05-01``."""
        unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[self.freq]
        text = f"every {unit}" if self.interval == 1 else f"every {self.interval} {unit}s"
        if self.weekdays:
            text += " on " + ", ".join(WEEKDAYS[day] for day in self.weekdays)
        if self.monthday is not None:
            text += f" on day {self.monthday}"
        if self.count is not None:
            text += f"; {self.count} times"
        if self.until is not None:
            text += f"; until {self.until.isoformat()}"
        return text


def parse_rule(words):
    """Rule from words such as ``every 2 weeks on mon,fri count 6`` or ``monthly on day -1 until 2026-12-31``."""
    words, kwargs = list(words), {}
    if not words:
        raise InvalidRule("missing frequency")
    head = words.pop(0)
    if head in FREQUENCIES:
        freq = head
    elif head == "every" and len(words) >= 2 and words[0].isdigit() and words[1] in _UNITS:
        kwargs["interval"], freq = int(words[0]), _UNITS[words[1]]
        del words[:2]
    else:
        raise InvalidRule(f"cannot parse frequency starting at {head!r}")
    while words:
        word = words.pop(0)
        if word == "on" and freq == "weekly" and words:
            kwargs["weekdays"] = parse_weekdays(words.pop(0))
        elif word == "on" and freq == "monthly" and len(words) >= 2 and words[0] == "day":
            try:
                kwargs["monthday"] = int(words[1])
            except ValueError:
                raise InvalidRule(f"bad month day {words[1]!r}") from None
            del words[:2]
        elif word == "count" and words and words[0].isdigit():
            kwargs["count"] = int(words.pop(0))
        elif word == "until" and words:
            kwargs["until"] = parse_date(words.pop(0))
        else:
            raise InvalidRule(f"unexpected {word!r} in rule")
    return Rule(freq, **kwargs)
