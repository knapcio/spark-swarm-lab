# agenda

A small calendar: one-off and repeating events with rooms and attendees,
cancelled and moved occurrences, splitting a series, free-slot search, day
agendas, weekly hours, conflict reports and a line-oriented schedule
language. Standard library only, Python 3.10+.

```python
import datetime
from agenda import Calendar, Rule, free_slots

cal = Calendar()
cal.add_event("STANDUP", "Daily standup", datetime.datetime(2026, 3, 2, 9, 30), datetime.timedelta(minutes=15),
              Rule("weekly", weekdays=[0, 1, 2, 3, 4], until=datetime.date(2026, 3, 31)), room="R1",
              attendees=["ann", "bob"])
print(free_slots(cal, ["ann", "bob"], datetime.date(2026, 3, 3), datetime.timedelta(minutes=30))[:3])
```

## Modules

| Module | Responsibility |
|---|---|
| `timeutil.py` | Parsing dates, times and durations; month arithmetic; half-open intervals |
| `recurrence.py` | `Rule`: daily/weekly/monthly/yearly recurrence, count and until |
| `calendar.py` | `Calendar`, events, occurrences, cancel, move, split |
| `availability.py` | Busy time, free slots, first common slot |
| `reports.py` | Day agenda, series dates, weekly hours, conflicts |
| `schedule.py` | Text command language and replay |
| `errors.py` | Exception hierarchy |

## Rules

- Times are naive local datetimes with whole minutes. Occurrences are
  half-open: a meeting from 10:00 to 11:00 and one from 11:00 to 12:00 do not
  overlap.
- Weekly rules accept weekdays in any order. Occurrences are generated in
  chronological order, and `count` and `until` apply in that order.
- `count` is the number of occurrences a rule generates. A cancelled
  occurrence still counts: cancelling cancels that date, it does not
  postpone the series. `until` is inclusive.
- Monthly rules on a day that a month does not have fall on that month's
  last day.
- Splitting a series at an occurrence keeps the earlier occurrences in the
  old event and moves the rest to a new event; the dates and the total
  number of occurrences do not change.
- Free slots start at the beginning of working hours (09:00-17:00 by
  default) and then every 15 minutes unless another `step` is given. A slot
  may start exactly when a meeting ends. Weekends and holidays have no slots.
- Listings and reports are sorted by start time, then event id.

Run the tests with `python -m unittest discover -s tests`.
