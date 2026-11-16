# Delay of a night train does not show on the next morning's board

The TLK8 night train leaves Warsaw at 23:20 and calls at Radom at 00:37 the
next morning (`24:35 24:37` in its stop list). Our station screen showed the
Radom board for 10 March, then the operator sent a 25-minute delay for the
train that left Warsaw on 9 March:

```python
from junction import Junction

text = """
station WAW "Warszawa Centralna" zone 1 transfer 6
station RAD "Radom" zone 3 transfer 3
station KIE "Kielce" zone 5
service NT daily 2026-03-01..2026-03-31
trip NX1 TLK8 NT
  WAW 23:20
  RAD 24:35 24:37
  KIE 25:40
"""
junction = Junction.from_text(text)
print(junction.board("RAD", "2026-03-10", "00:00", "02:00"))
junction.apply("delay NX1 2026-03-09 +25\n")
print(junction.board("RAD", "2026-03-10", "00:00", "02:00"))
print(junction.plan("RAD", "KIE", "2026-03-10", "00:00").summary())
```

Expected after the delay: the board shows `01:02 +25   TLK8   Kielce`, and
the journey is `01:02 RAD -> 02:05 KIE`.
Actual: the board still shows `00:37` without a delay, and the planner
offers `00:37 RAD -> 01:40 KIE`.

The README says delays and cancellations take effect at once everywhere,
including the after-midnight part of a trip shown on the next calendar day.
If nobody looked at the 10 March board before the delay arrived, the delay
is shown correctly. Delays of daytime trips always appear at once, and the
line summary for 9 March does show `+25`. We see the same with
cancellations of night trips.
