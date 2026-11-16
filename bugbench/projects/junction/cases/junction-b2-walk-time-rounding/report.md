# Planner sends passengers to a bus they cannot reach on foot

Katowice station and the Katowice bus stop are joined by a 250 m footpath.
Our train arrives at 07:26 and buses to Sosnowiec leave the bus stop at 07:29
and 07:40:

```python
from junction import Junction

text = """
station GLW "Gliwice" zone 1 transfer 4
station KAT "Katowice" zone 2 transfer 5
station KTB "Katowice Bus" zone 2 transfer 2
station SOS "Sosnowiec" zone 3
footpath KAT KTB 250
service ALL daily 2026-05-01..2026-05-31
trip G1 KS1 ALL
  GLW 07:00
  KAT 07:26
trip M1 B12 ALL
  KTB 07:29
  SOS 07:50
trip M2 B12 ALL
  KTB 07:40
  SOS 08:01
"""
print(Junction.from_text(text).plan("GLW", "SOS", "2026-05-12", "06:30").describe())
```

Expected: `walk 4 min (250 m) KAT -> KTB`, then the 07:40 bus, arriving in
Sosnowiec at 08:01.
Actual: `walk 3 min (250 m) KAT -> KTB`, then the 07:29 bus, arriving at
07:50.

The README says walking takes the length divided by 80 metres per minute,
rounded up, and that 250 m take 4 minutes. A 240 m footpath correctly takes
3 minutes. Passengers following the plan miss the bus.
