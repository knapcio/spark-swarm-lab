# Free-slot search skips quarter-hour start times

Ann's sprint planning ends at 10:15. When we look for a 30-minute slot after
it, the first proposal is 10:30.

```python
import datetime
from agenda import Calendar, free_slots

cal = Calendar()
cal.add_event("PLAN", "Sprint planning", datetime.datetime(2026, 3, 3, 9, 0),
              datetime.timedelta(minutes=75), attendees=["ann"])
free_slots(cal, ["ann"], datetime.date(2026, 3, 3), datetime.timedelta(minutes=30))[:3]
```

Expected: 10:15, 10:30, 10:45.
Actual: 10:30, 11:00, 11:30.

The README says slots are offered every 15 minutes unless another `step` is
given. If we pass `step=15` explicitly, we get 10:15, 10:30, 10:45 as
expected. Our booking assistant never passes a step and loses the quarter-hour
slots. The `free` command in our schedule files has the same problem.
