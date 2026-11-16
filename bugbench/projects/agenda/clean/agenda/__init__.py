"""agenda: a small calendar with recurring events, free-slot search, reports and a schedule language."""
from .availability import busy, busy_minutes, first_common_slot, free_slots
from .calendar import Calendar, Event, Occurrence
from .errors import (AgendaError, DuplicateEvent, InvalidRule, InvalidTime, NotAnOccurrence, ScheduleError,
                     UnknownEvent)
from .recurrence import Rule, parse_rule
from .schedule import replay
from .timeutil import Interval, parse_duration

__version__ = "0.2.0"
__all__ = ["AgendaError", "Calendar", "DuplicateEvent", "Event", "Interval", "InvalidRule", "InvalidTime",
           "NotAnOccurrence", "Occurrence", "Rule", "ScheduleError", "UnknownEvent", "busy", "busy_minutes",
           "first_common_slot", "free_slots", "parse_duration", "parse_rule", "replay"]
