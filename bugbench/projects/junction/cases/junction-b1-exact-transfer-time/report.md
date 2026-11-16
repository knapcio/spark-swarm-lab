# Planner ignores a change that takes exactly the transfer time

Krakow Glowny has a minimum transfer time of 5 minutes. Our R5 train from
Wieliczka arrives there at 07:57 and the IC31 to Rzeszow leaves at 08:02:

```python
from junction import Junction

text = """
station KRK "Krakow Glowny" zone 1 transfer 5
station KRB "Krakow Bus Station" zone 1
station WIE "Wieliczka" zone 2
station RZE "Rzeszow Glowny" zone 4
footpath KRB KRK 240
service WK mon-fri 2026-03-02..2026-03-31
trip R1 R5 WK
  WIE 07:45
  KRK 07:57
trip B1 B7 WK
  WIE 07:30
  KRB 07:52
trip IC1 IC31 WK
  KRK 08:02
  RZE 09:30
"""
print(Junction.from_text(text).plan("WIE", "RZE", "2026-03-02", "07:00").describe())
```

Expected: `07:45 WIE -> 09:30 RZE, 1h 45m, 1 transfer`, riding R5 to Krakow
Glowny and changing to the 08:02.
Actual: `07:30 WIE -> 09:30 RZE, 2h 00m, 1 transfer`, taking the 07:30 bus
to the bus station and walking 3 minutes instead.

Both arrive at 09:30 with one transfer, so the later departure should win.
The README says that arriving 07:57 at a station with 5 minutes, the 08:02
can be caught. If the R5 arrives at 07:56 instead, the planner does pick it.
