"""Events and the calendar that stores them.

An event has an id, a title, a first start, a duration, an optional
recurrence rule, an optional room and attendees.  Single occurrences of an
event are identified by their *original* start, the start its rule
generated.  An occurrence can be cancelled or moved to another time; a moved
occurrence keeps its original start as its identity.

Listings use the half-open window ``start <= occurrence start < end`` and are
sorted by start, then event id.  A moved occurrence is listed at its new time
only.  Cancelling an occurrence does not shift the series: the rule still
generated it, so it still counts toward the rule's ``count``.
"""
from dataclasses import dataclass, field
import datetime
import re

from .errors import AgendaError, DuplicateEvent, InvalidRule, InvalidTime, NotAnOccurrence, UnknownEvent
from .recurrence import Rule
from .timeutil import Interval, check_minute, whole_minutes

_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_PERSON = re.compile(r"^[a-z][a-z0-9_.-]{0,31}$")
_KEEP = object()


def _check_id(event_id):
    if not isinstance(event_id, str) or not _ID.match(event_id):
        raise AgendaError(f"bad event id {event_id!r}")
    return event_id


def _people(attendees):
    people = tuple(sorted(set(attendees)))
    for person in people:
        if not isinstance(person, str) or not _PERSON.match(person):
            raise AgendaError(f"bad attendee name {person!r}")
    return people


@dataclass(frozen=True)
class Occurrence:
    event_id: str
    title: str
    start: datetime.datetime
    end: datetime.datetime
    room: object
    attendees: tuple
    original_start: datetime.datetime

    @property
    def moved(self):
        return self.start != self.original_start

    @property
    def interval(self):
        return Interval(self.start, self.end)


@dataclass
class Event:
    event_id: str
    title: str
    start: datetime.datetime
    duration: datetime.timedelta
    rule: object = None
    room: object = None
    attendees: tuple = ()
    cancelled: set = field(default_factory=set)
    moved: dict = field(default_factory=dict)

    def originals_between(self, start, end):
        """Original starts generated in ``[start, end)``, cancelled ones included."""
        if self.rule is None:
            return [self.start] if start <= self.start < end else []
        return self.rule.between(self.start, start, end)

    def is_original(self, moment):
        if self.rule is None:
            return moment == self.start
        return self.rule.is_start(self.start, moment)

    def occurrence(self, original, start):
        return Occurrence(self.event_id, self.title, start, start + self.duration, self.room, self.attendees, original)


class Calendar:
    def __init__(self):
        self._events = {}
        self.holidays = set()

    # -- events -----------------------------------------------------------------
    def add_event(self, event_id, title, start, duration, rule=None, room=None, attendees=()):
        """Add an event; for a repeating event ``start`` must be one of its rule's dates."""
        _check_id(event_id)
        if event_id in self._events:
            raise DuplicateEvent(event_id)
        if not isinstance(title, str) or not title.strip():
            raise AgendaError("an event needs a title")
        check_minute(start)
        if not isinstance(duration, datetime.timedelta) or duration <= datetime.timedelta(0):
            raise InvalidTime("duration must be a positive timedelta")
        whole_minutes(duration)
        if rule is not None and (not isinstance(rule, Rule) or not rule.is_start(start, start)):
            raise InvalidRule("the first start must be an occurrence of the rule")
        if room is not None and (not isinstance(room, str) or not room):
            raise AgendaError("room must be a non-empty string")
        event = Event(event_id, title, start, duration, rule, room, _people(attendees))
        self._events[event_id] = event
        return event

    def get(self, event_id):
        try:
            return self._events[event_id]
        except KeyError:
            raise UnknownEvent(event_id) from None

    def remove(self, event_id):
        self.get(event_id)
        del self._events[event_id]

    def event_ids(self):
        return sorted(self._events)

    def add_holiday(self, day):
        if not isinstance(day, datetime.date) or isinstance(day, datetime.datetime):
            raise InvalidTime("a holiday is a date")
        self.holidays.add(day)

    def is_working_day(self, day):
        return day.weekday() < 5 and day not in self.holidays

    # -- single occurrences ----------------------------------------------------------
    def _original(self, event, moment):
        if not isinstance(moment, datetime.datetime) or not event.is_original(moment):
            raise NotAnOccurrence(f"{event.event_id} has no occurrence starting {moment}")
        return moment

    def cancel(self, event_id, original_start):
        """Cancel one occurrence (also if it was moved).  Cancelling twice is allowed."""
        event = self.get(event_id)
        self._original(event, original_start)
        event.cancelled.add(original_start)
        event.moved.pop(original_start, None)

    def move(self, event_id, original_start, new_start):
        """Move one occurrence; moving it back to its original start clears the move."""
        event = self.get(event_id)
        self._original(event, original_start)
        check_minute(new_start)
        if original_start in event.cancelled:
            raise NotAnOccurrence(f"{event_id} occurrence {original_start} is cancelled")
        if new_start == original_start:
            event.moved.pop(original_start, None)
        else:
            event.moved[original_start] = new_start

    # -- listings ----------------------------------------------------------------------
    def occurrences(self, start, end, attendee=None, room=None):
        """Visible occurrences starting in ``[start, end)``, optionally for one attendee or room."""
        if not start < end:
            raise InvalidTime("the window must end after it starts")
        found = []
        for event in self._events.values():
            if attendee is not None and attendee not in event.attendees:
                continue
            if room is not None and event.room != room:
                continue
            for original in event.originals_between(start, end):
                if original not in event.cancelled and original not in event.moved:
                    found.append(event.occurrence(original, original))
            for original, moved_to in event.moved.items():
                if start <= moved_to < end:
                    found.append(event.occurrence(original, moved_to))
        found.sort(key=lambda item: (item.start, item.event_id))
        return found

    def series(self, event_id):
        """Every visible occurrence of a finite event, in start order."""
        event = self.get(event_id)
        if event.rule is not None and not event.rule.is_finite():
            raise InvalidRule(f"{event_id} repeats forever; use occurrences() with a window")
        found = [event.occurrence(original, event.moved.get(original, original))
                 for original in (event.rule.starts(event.start) if event.rule else [event.start])
                 if original not in event.cancelled]
        return sorted(found, key=lambda item: item.start)

    # -- editing a series ---------------------------------------------------------------
    def split(self, event_id, at, new_id, title=None, duration=None, room=_KEEP, attendees=None):
        """End a repeating series before ``at`` and continue it as event ``new_id``.

        ``at`` must be an original start of the series other than the first.
        The old series keeps exactly the occurrences its rule generated before
        ``at``.  The new event starts at ``at`` with the same rule; with a
        ``count``, it gets the occurrences the old series had not generated
        yet, so the total stays the same.  Cancellations and moves of
        occurrences whose original start is at or after ``at`` go to the new
        event.  Monthly rules keep their day of the month.  Returns the new event.
        """
        event = self.get(event_id)
        if event.rule is None:
            raise InvalidRule("only repeating events can be split")
        _check_id(new_id)
        if new_id in self._events:
            raise DuplicateEvent(new_id)
        self._original(event, at)
        if at == event.start:
            raise NotAnOccurrence("cannot split at the first occurrence")
        if duration is not None and (not isinstance(duration, datetime.timedelta) or duration <= datetime.timedelta(0)):
            raise InvalidTime("duration must be a positive timedelta")
        generated = event.rule.between(event.start, event.start, at)
        done = len(generated)
        rule = event.rule
        if rule.freq == "monthly" and rule.monthday is None:
            rule = rule.replace(monthday=event.start.day)
        tail = rule.replace(count=None if rule.count is None else rule.count - done)
        new = Event(new_id, title or event.title, at, duration or event.duration, tail,
                    event.room if room is _KEEP else room,
                    event.attendees if attendees is None else _people(attendees))
        new.cancelled = {moment for moment in event.cancelled if moment >= at}
        new.moved = {original: moved_to for original, moved_to in event.moved.items() if original >= at}
        event.rule = rule.replace(count=done)
        event.cancelled -= new.cancelled
        for original in new.moved:
            del event.moved[original]
        self._events[new_id] = new
        return new
