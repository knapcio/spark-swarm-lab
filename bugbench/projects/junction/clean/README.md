# junction

A small rail timetable planner: stations with transfer times and footpaths,
service calendars, trips that run past midnight, delays and cancellations,
a journey planner with transfers, departure boards and zone fares. Standard
library only, Python 3.10+.

```python
from junction import Junction

text = """
station KRK "Krakow Glowny" zone 1 transfer 5
station TRN "Tarnow" zone 3 transfer 4
station RZE "Rzeszow Glowny" zone 4
service WK mon-fri 2026-03-02..2026-03-31 except 2026-03-13
trip T1 IC31 WK
  KRK 08:02
  TRN 08:41 08:43
  RZE 09:30
"""
junction = Junction.from_text(text)
journey = junction.plan("KRK", "RZE", "2026-03-02", "07:30")
print(journey.describe(), junction.fare(journey))
junction.apply("delay T1 2026-03-02 +15 from TRN\n")
print(junction.board("TRN", "2026-03-02"))
```

## Modules

| Module | Responsibility |
|---|---|
| `clock.py` | Times (`HH:MM` up to `47:59`), durations, dates, weekday sets, service calendars |
| `network.py` | Stations, fare zones, minimum transfer times, footpaths and walking times |
| `timetable.py` | Trips, delays and cancellations, the daily connection listing |
| `planner.py` | Journey planning with transfers and tie-breaks |
| `journey.py` | Rides, walks, journeys, summaries |
| `fares.py` | Zone fares, night surcharge, concessions, day ticket cap |
| `boards.py` | Departure and arrival boards, line summaries |
| `loader.py` | Timetable text, disruption feeds, the `Junction` facade |
| `errors.py` | Exception hierarchy |

## Rules

- Trip times are minutes after midnight of the service day. A trip that runs
  past midnight keeps counting: 00:40 the next morning is `24:40`.
  Passengers see `00:40+1`.
- A service runs on its weekdays from its first to its last date, both
  included, except removed dates; added dates always run.
- The listing of a calendar day holds all trips of that service day and the
  part of the previous service day's trips that departs at 24:00 or later
  (shown at its clock time, e.g. 00:10). Boards and the planner read it.
- Changing trips at a station needs at least the station's minimum transfer
  time: arriving 07:57 at a station with 5 minutes, the 08:02 can be caught.
- A footpath's walking time is its length divided by 80 metres per minute,
  rounded up to a whole minute (250 m take 4 minutes, 240 m take 3). The walk
  replaces the transfer time.
- A journey starts and ends with a ride and has at most 4 rides. The planner
  returns the journey that arrives earliest; among those the one with the
  fewest rides; among those the one that departs latest.
- Delays and cancellations take effect at once for every listing, board and
  journey, including the after-midnight part of a trip shown on the next
  calendar day. A delay applies from the given stop on (its arrival there
  and every later time); a new delay for the same trip and day replaces the
  old one.
- Boards are sorted by expected time, then line, then trip id.
- Fares: zones travelled = highest - lowest zone of every station the
  journey touches, plus one; 1 zone 4.00, 2 zones 5.60, 3 zones 7.20, each
  further zone 1.50 more; departures 23:00-03:59 pay 2.00 extra. Concessions
  (senior 37 %, student 51 %) are rounded half up to 0.10. The day ticket
  caps a day's total at 16.00 (reduced the same way for concessions).

Run the tests with `python -m unittest discover -s tests`.
