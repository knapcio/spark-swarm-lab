# Training series ends on the wrong date

Our club trains on Mondays and Fridays, four sessions in total, starting
Friday 6 March:

```
event TRAIN "Training" at 2026-03-06 18:00 for 1h repeat weekly on fri,mon count 4 with ann
```

After `cal, _ = replay(text)`, `agenda.reports.series_dates(cal, "TRAIN")` gives:

Expected: 2026-03-06, 2026-03-09, 2026-03-13 and 2026-03-16 (all at 18:00).
Actual: 2026-03-06, 2026-03-09, 2026-03-13 and 2026-03-20.

The fourth session lands on Friday 20 March although Monday 16 March comes
first. If we write `on mon,fri` instead, we get the expected dates. The README
says weekly rules accept weekdays in any order, so both spellings should give
the same series.
