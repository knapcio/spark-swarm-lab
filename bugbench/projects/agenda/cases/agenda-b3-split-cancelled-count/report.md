# A session disappears after we move the rest of a course to a new room

Our pottery course has six weekly sessions in room R2. The session on
9 March was cancelled. From 23 March the course moves to room R3, so we split
the series:

```
event COURSE "Pottery course" at 2026-03-02 13:00 for 2h repeat weekly count 6 room R2 with ann
cancel COURSE 2026-03-09 13:00
split COURSE at 2026-03-23 13:00 as COURSE-B room R3
```

After `cal, _ = replay(text)`, we list the sessions with
`agenda.reports.series_dates`:

Expected: COURSE on 2026-03-02 and 2026-03-16; COURSE-B on 2026-03-23,
2026-03-30 and 2026-04-06 (five sessions, as before the split).
Actual: COURSE only on 2026-03-02; COURSE-B on 2026-03-23, 2026-03-30,
2026-04-06 and 2026-04-13.

The 16 March session vanished and an extra session appeared on 13 April.
Without the cancelled session the split works and all dates stay the same.
The README says a split must not change the dates or the number of sessions.
