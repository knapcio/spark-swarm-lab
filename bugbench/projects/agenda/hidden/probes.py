"""Hidden behavioural probes for the agenda project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY 9b52e0c7-bugbench-agenda-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""
import datetime

D = datetime.datetime
DAY = datetime.date
MIN = datetime.timedelta(minutes=1)


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _s(moment):
    return moment.strftime("%Y-%m-%d %H:%M") if isinstance(moment, D) else moment.isoformat()


def _starts(rule, first, limit=40):
    out = []
    for moment in rule.starts(first):
        out.append(_s(moment))
        if len(out) >= limit:
            break
    return out


def _series(cal, event_id):
    return [_s(item.start) for item in cal.series(event_id)]


def _clock(slots):
    return [slot.strftime("%H:%M") for slot in slots]


# --- time utilities ------------------------------------------------------------------
def probe_time_parsing():
    from agenda.timeutil import (add_months, days_in_month, format_duration, parse_date, parse_duration, parse_time,
                                 parse_weekdays)
    return [str(parse_date(" 2028-02-29 ")), str(parse_time("07:05")), parse_duration("2h") // MIN,
            parse_duration("45m") // MIN, parse_duration("1h05m") // MIN, format_duration(60 * MIN),
            format_duration(5 * MIN), format_duration(605 * MIN),
            parse_weekdays("sun, Mon,weekdays"), days_in_month(2028, 2), days_in_month(2100, 2),
            [str(add_months(DAY(2026, 1, 31), n)) for n in (1, 2, -2, 25)],
            [str(add_months(DAY(2026, 5, 10), 1, day)) for day in (31, -1, -2, -31, 3)],
            [_error(parse_date, text) for text in ("2026-02-30", "2026-2-1", "")],
            [_error(parse_time, text) for text in ("24:00", "7:05")],
            [_error(parse_duration, text) for text in ("0h", "h", "90", "1h30")], _error(parse_weekdays, "mon,xyz")]


def probe_interval_merge():
    from agenda.timeutil import Interval, merge
    a, b = Interval(D(2026, 3, 2, 9), D(2026, 3, 2, 10)), Interval(D(2026, 3, 2, 10), D(2026, 3, 2, 11))
    c = Interval(D(2026, 3, 2, 9, 30), D(2026, 3, 2, 9, 45))
    merged = merge([b, c, a, Interval(D(2026, 3, 2, 12), D(2026, 3, 2, 13))])
    return [a.overlaps(b), b.overlaps(a), a.overlaps(c), a.contains(D(2026, 3, 2, 10)), a.contains(D(2026, 3, 2, 9)),
            a.duration // MIN, [[_s(i.start), _s(i.end)] for i in merged],
            _error(Interval, D(2026, 3, 2, 9), D(2026, 3, 2, 9))]


# --- recurrence -----------------------------------------------------------------------
def probe_rule_frequencies():
    from agenda import Rule
    return [_starts(Rule("daily", interval=3, count=4), D(2026, 2, 26, 8)),
            _starts(Rule("weekly", count=3), D(2026, 3, 4, 18, 30)),
            _starts(Rule("weekly", interval=2, weekdays=[1, 3], until=DAY(2026, 3, 26)), D(2026, 3, 4, 7)),
            _starts(Rule("monthly", monthday=-1, count=4), D(2026, 1, 31, 12)),
            _starts(Rule("monthly", monthday=15, count=3), D(2026, 1, 15, 12)),
            _starts(Rule("monthly", interval=5, count=3), D(2026, 8, 31, 9)),
            _starts(Rule("yearly", count=5), D(2028, 2, 29, 9)),
            _starts(Rule("daily", count=10, until=DAY(2026, 3, 3)), D(2026, 3, 1, 9)),
            _starts(Rule("daily", count=2, until=DAY(2026, 3, 30)), D(2026, 3, 1, 9)),
            [_s(m) for m in Rule("daily").between(D(2026, 1, 1, 6), D(2026, 3, 1, 6), D(2026, 3, 4, 6))],
            [Rule("daily", interval=7).is_start(D(2026, 3, 1, 6), D(2026, 3, d, 6)) for d in (8, 9, 15)],
            [Rule("weekly", weekdays=[0, 3]).is_start(D(2026, 3, 2, 6), D(2026, 3, d, 6)) for d in (2, 3, 5, 9)]]


def probe_rule_validation_and_describe():
    from agenda import Rule
    bad = [dict(freq="hourly"), dict(freq="daily", interval=0), dict(freq="daily", count=True),
           dict(freq="daily", until=D(2026, 1, 1)), dict(freq="daily", weekdays=[1]), dict(freq="weekly", weekdays=[]),
           dict(freq="weekly", weekdays=[7]), dict(freq="monthly", monthday=0), dict(freq="weekly", monthday=3),
           dict(freq="monthly", monthday=32)]
    rule = Rule("weekly", interval=2, weekdays=[1, 1, 3], count=6, until=DAY(2026, 5, 1))
    return [[_error(Rule, **kwargs) for kwargs in bad], rule.describe(), list(rule.weekdays),
            Rule("monthly", monthday=-1).describe(), Rule("yearly", interval=2).describe(),
            rule.replace(count=None).describe(), rule == Rule("weekly", interval=2, weekdays=[1, 3], count=6, until=DAY(2026, 5, 1)),
            rule.replace(interval=1) == rule, rule.is_finite(), Rule("daily").is_finite()]


def probe_parse_rule():
    from agenda import parse_rule
    texts = ["daily count 3", "every 2 weeks on tue,thu until 2026-06-30", "monthly on day -1", "weekly on weekdays",
             "every 3 months count 4 until 2027-01-01", "yearly"]
    out = [parse_rule(text.split()).describe() for text in texts]
    for bad in ("", "hourly", "every two weeks", "weekly on day 3", "monthly on day x", "daily count", "daily until 2026-13-01",
                "daily please"):
        out.append(_error(parse_rule, bad.split()))
    return out


# --- calendar -------------------------------------------------------------------------
def _calendar():
    from agenda import Calendar, Rule
    cal = Calendar()
    cal.add_event("SYNC", "Team sync", D(2026, 3, 2, 10), 30 * MIN, Rule("daily", count=5), room="R1",
                  attendees=["bob", "ann", "bob"])
    cal.add_event("ONE", "One-off", D(2026, 3, 3, 10), 60 * MIN, attendees=["cy"])
    cal.add_event("ALPHA", "Alpha", D(2026, 3, 3, 10), 15 * MIN, room="R2", attendees=["ann"])
    return cal


def probe_calendar_add_validation():
    from agenda import Rule
    cal = _calendar()
    add = cal.add_event
    return [list(cal.get("SYNC").attendees), cal.event_ids(),
            _error(add, "SYNC", "x", D(2026, 3, 2, 10), MIN), _error(add, "9X", "x", D(2026, 3, 2, 10), MIN),
            _error(add, "X", " ", D(2026, 3, 2, 10), MIN), _error(add, "X", "x", D(2026, 3, 2, 10, 0, 30), MIN),
            _error(add, "X", "x", D(2026, 3, 2, 10), 0 * MIN), _error(add, "X", "x", D(2026, 3, 2, 10), MIN, room=""),
            _error(add, "X", "x", D(2026, 3, 3, 10), MIN, Rule("weekly", weekdays=[0])),
            _error(add, "X", "x", D(2026, 3, 2, 10), MIN, attendees=["Ann"]), _error(cal.get, "NOPE"),
            _error(cal.remove, "NOPE"), _error(cal.add_holiday, D(2026, 1, 1))]


def probe_cancel_move_listing():
    from agenda import reports
    cal = _calendar()
    cal.move("SYNC", D(2026, 3, 3, 10), D(2026, 3, 3, 16))
    cal.move("SYNC", D(2026, 3, 4, 10), D(2026, 3, 9, 8))
    cal.cancel("SYNC", D(2026, 3, 5, 10))
    out = [_error(cal.move, "SYNC", D(2026, 3, 5, 10), D(2026, 3, 5, 11)), _error(cal.cancel, "SYNC", D(2026, 3, 5, 11)),
           _error(cal.cancel, "ONE", D(2026, 3, 4, 10)), _error(cal.move, "SYNC", D(2026, 3, 6, 10), DAY(2026, 3, 6))]
    out.append([[i.event_id, _s(i.start), _s(i.original_start), i.moved]
                for i in cal.occurrences(D(2026, 3, 2), D(2026, 3, 10))])
    out.append(reports.day_agenda(cal, DAY(2026, 3, 9)) + reports.day_agenda(cal, DAY(2026, 3, 3), attendee="ann"))
    cal.move("SYNC", D(2026, 3, 3, 10), D(2026, 3, 3, 10))
    cal.cancel("SYNC", D(2026, 3, 4, 10))
    cal.cancel("SYNC", D(2026, 3, 4, 10))
    out.append(_series(cal, "SYNC"))
    out.append([i.event_id for i in cal.occurrences(D(2026, 3, 3), D(2026, 3, 4), room="R1")])
    return out


def probe_occurrence_window():
    from agenda import Rule
    cal = _calendar()
    cal.add_event("LATE", "Late", D(2026, 3, 2, 23, 30), 60 * MIN, Rule("weekly"), attendees=["ann"])
    return [[[i.event_id, _s(i.start)] for i in cal.occurrences(D(2026, 3, 3, 10), D(2026, 3, 4, 10))],
            len(cal.occurrences(D(2026, 3, 2), D(2026, 4, 1))), len(cal.occurrences(D(2026, 3, 2), D(2026, 4, 1), attendee="ann")),
            _error(cal.occurrences, D(2026, 3, 2), D(2026, 3, 2)), _error(cal.series, "LATE"), _series(cal, "ONE")]


def probe_split_without_cancellations():
    from agenda import Rule
    cal = _calendar()
    cal.add_event("COURSE", "Course", D(2026, 1, 31, 17), 90 * MIN, Rule("monthly", count=6), room="R3", attendees=["dee"])
    cal.cancel("COURSE", D(2026, 5, 31, 17))
    cal.move("COURSE", D(2026, 6, 30, 17), D(2026, 7, 1, 17))
    new = cal.split("COURSE", D(2026, 4, 30, 17), "COURSE-2", title="Course II", attendees=["eve"])
    out = [_series(cal, "COURSE"), _series(cal, "COURSE-2"), new.rule.describe(), cal.get("COURSE").rule.describe(),
           [new.title, new.room, list(new.attendees)], sorted(_s(m) for m in new.cancelled)]
    cal.add_event("DAILY", "Daily", D(2026, 3, 2, 8), 15 * MIN, Rule("daily", until=DAY(2026, 3, 8)))
    cal.split("DAILY", D(2026, 3, 5, 8), "DAILY-2", room=None, duration=30 * MIN)
    out += [_series(cal, "DAILY"), _series(cal, "DAILY-2"), cal.get("DAILY-2").duration // MIN]
    out += [_error(cal.split, "ONE", D(2026, 3, 3, 10), "Z"), _error(cal.split, "SYNC", D(2026, 3, 2, 10), "Z"),
            _error(cal.split, "SYNC", D(2026, 3, 4, 11), "Z"), _error(cal.split, "SYNC", D(2026, 3, 4, 10), "ONE"),
            _error(cal.split, "SYNC", D(2026, 3, 4, 10), "Z", duration=-MIN), _series(cal, "SYNC")]
    return out


# --- availability -------------------------------------------------------------------------
def probe_busy_and_minutes():
    from agenda import busy, busy_minutes
    cal = _calendar()
    cal.add_event("NIGHT", "Night shift", D(2026, 3, 2, 22), 12 * 60 * MIN, attendees=["ann"])
    day = DAY(2026, 3, 3)
    return [[[_s(i.start), _s(i.end)] for i in busy(cal, "ann", day)], busy_minutes(cal, "ann", day),
            busy_minutes(cal, "ann", day, hours=(datetime.time(8), datetime.time(9, 30))), busy_minutes(cal, "cy", day),
            _error(busy_minutes, cal, "ann", day, hours=(datetime.time(10), datetime.time(9)))]


def probe_free_slots_explicit_step():
    from agenda import free_slots
    cal = _calendar()
    cal.add_holiday(DAY(2026, 3, 4))
    day = DAY(2026, 3, 3)
    return [_clock(free_slots(cal, ["ann", "cy"], day, 60 * MIN, step=60)),
            _clock(free_slots(cal, "ann", day, 45 * MIN, step=20, hours=(datetime.time(9, 50), datetime.time(12)))),
            _clock(free_slots(cal, ["bob"], DAY(2026, 3, 2), 30 * MIN, step=30, hours=(datetime.time(9, 30), datetime.time(11)))),
            free_slots(cal, ["ann"], DAY(2026, 3, 4), 30 * MIN, step=60), free_slots(cal, ["ann"], DAY(2026, 3, 8), MIN, step=60),
            _clock(free_slots(cal, ["zed"], day, 8 * 60 * MIN, step=5)),
            _error(free_slots, cal, [], day, MIN), _error(free_slots, cal, ["ann"], day, MIN, step=0),
            _error(free_slots, cal, ["ann"], day, 0 * MIN), _error(free_slots, cal, ["ann"], day, MIN, step=True)]


# --- reports and schedule language -------------------------------------------------------------
def probe_reports():
    from agenda import reports
    cal = _calendar()
    cal.move("SYNC", D(2026, 3, 4, 10), D(2026, 3, 3, 10, 5))
    return [reports.day_agenda(cal, DAY(2026, 3, 3)), reports.day_agenda(cal, DAY(2026, 3, 3), room="R2"),
            reports.week_hours(cal, DAY(2026, 3, 8)), reports.week_hours(cal, DAY(2026, 3, 9)),
            reports.conflicts(cal, D(2026, 3, 2), D(2026, 3, 9)), reports.series_dates(cal, "SYNC")]


def probe_schedule_replay():
    from agenda import ScheduleError, replay
    from agenda.schedule import tokenize
    text = ('# team\nholiday 2026-03-06\n'
            'event SYNC "Team \\"sync\\"" at 2026-03-02 10:00 for 30m repeat daily count 4 room R1 with ann,bob\n'
            'event REV "Review" at 2026-03-03 11:00 for 1h with ann\n'
            "cancel SYNC 2026-03-03 10:00\nmove SYNC 2026-03-04 10:00 to 2026-03-04 15:00\n"
            "agenda 2026-03-04 for ann\nhours 2026-03-02\nremove REV\nagenda 2026-03-03\n")
    cal, results = replay(text)
    out = [results, tokenize('a "b c" "" d'), cal.event_ids()]
    for bad in ('event X "x" at 2026-03-02 10:00 for 30m\nevent X "y" at 2026-03-02 11:00 for 30m',
                "frobnicate", 'event X "unterminated', "\n\nmove A 2026-03-02 10:00 2026-03-02 11:00",
                'event X "x" at 2026-03-02 10:00 for 30m repeat weekly on day 3',
                'event X "x" at 2026-03-02 10:00 for 30m\nsplit X at 2026-03-02 10:00 as Y'):
        try:
            replay(bad)
            out.append(None)
        except ScheduleError as exc:
            out.append([exc.line, type(exc.__cause__).__name__ if exc.__cause__ else None])
    return out


def probe_validation_and_boundary_edges():
    from agenda import Calendar, Rule, free_slots, parse_rule
    from agenda.timeutil import Interval, check_minute, days_in_month, merge, parse_time
    cal = Calendar()
    cal.add_event("ONE", "Single", D(2026, 3, 3, 12), 30 * MIN, attendees=["zed", "amy", "kim", "bea", "lou", "amy"])
    cal.add_event("REP", "Repeat", D(2026, 3, 2, 9), 30 * MIN, Rule("daily", count=3), room="R1")
    cal.move("REP", D(2026, 3, 3, 9), D(2026, 3, 3, 12))
    cal.move("REP", D(2026, 3, 4, 9), D(2026, 3, 4, 8))
    utc = D(2026, 3, 3, 9, tzinfo=datetime.timezone.utc)
    merged = merge([Interval(D(2026, 3, 2, 9), D(2026, 3, 2, 10)), Interval(D(2026, 3, 2, 11), D(2026, 3, 2, 12)),
                    Interval(D(2026, 3, 2, 11, 30), D(2026, 3, 2, 13))])
    return [list(cal.get("ONE").attendees),
            [[i.event_id, _s(i.start)] for i in cal.occurrences(D(2026, 3, 2, 9, 30), D(2026, 3, 3, 12))],
            [[i.event_id, _s(i.start)] for i in cal.occurrences(D(2026, 3, 3, 12), D(2026, 3, 4, 8))],
            len(free_slots(cal, ["kim"], DAY(2026, 3, 7), 30 * MIN, step=60)), len(free_slots(cal, ["kim"], DAY(2026, 3, 3), MIN, step=1)),
            [_error(free_slots, cal, ["kim"], DAY(2026, 3, 3), MIN, hours=hours)
             for hours in ((datetime.time(10), datetime.time(10)), ("09:00", datetime.time(17)), (datetime.time(9), "17:00"))],
            [_error(Rule, "weekly", weekdays=[True]), _error(Rule, "monthly", monthday=True), Rule("monthly", monthday=-31).describe(),
             Rule("monthly", monthday=31).describe(), _error(Rule, "monthly", monthday=-32), _error(Rule, "monthly", monthday="1")],
            [Rule("daily", count=2).is_start(D(2026, 3, 2, 9), D(2026, 3, 9, 9)), _error(cal.cancel, "REP", D(2026, 3, 5, 9))],
            [parse_rule("every 2 days".split()).describe(), _error(parse_rule, "daily until".split()),
             parse_rule("monthly on day 5 count 2".split()).describe()],
            [str(parse_time("23:59")), days_in_month(2026, 12), [[_s(i.start), _s(i.end)] for i in merged],
             _error(check_minute, D(2026, 3, 3, 9, 0, 0, 5)), _error(check_minute, utc)],
            _error(cal.split, "REP", D(2026, 3, 3, 9), "REP-2", duration=0 * MIN)]


def probe_split_boundary_and_reports_edges():
    from agenda import Calendar, Rule, reports
    from agenda.schedule import tokenize
    cal = Calendar()
    cal.add_event("W", "Weekly", D(2026, 3, 2, 9), 60 * MIN, Rule("weekly", count=5), room="R1", attendees=["zoe"])
    cal.cancel("W", D(2026, 3, 16, 9))
    cal.move("W", D(2026, 3, 23, 9), D(2026, 3, 23, 11))
    cal.split("W", D(2026, 3, 16, 9), "W2")
    cal.add_event("V", "Moved at split", D(2026, 3, 2, 8), 30 * MIN, Rule("daily", count=4))
    cal.move("V", D(2026, 3, 4, 8), D(2026, 3, 4, 7))
    cal.split("V", D(2026, 3, 4, 8), "V2")
    out = [_series(cal, "W"), _series(cal, "W2"), sorted(_s(m) for m in cal.get("W2").cancelled), _series(cal, "V"),
           _series(cal, "V2")]
    cal.add_event("A", "Back", D(2026, 3, 2, 10), 60 * MIN, room="R1", attendees=["kim", "amy", "lou"])
    cal.add_event("B", "To back", D(2026, 3, 2, 11), 60 * MIN, room="R1", attendees=["kim"])
    cal.add_event("C", "Overlap", D(2026, 3, 2, 11, 30), 30 * MIN, room="R2", attendees=["lou", "kim", "amy"])
    cal.add_event("D", "Huddle", D(2026, 3, 2, 11, 15), 30 * MIN, room="R3", attendees=["zoe", "lou", "kim", "amy"])
    out.append(reports.conflicts(cal, D(2026, 3, 2), D(2026, 3, 3)))
    out.append(reports.week_hours(cal, DAY(2026, 3, 2)))
    out.append([tokenize('  x  "" y '), tokenize('"a b"c d')])
    return out


def probe_schedule_usage_errors():
    from agenda import ScheduleError, replay
    out = []
    for bad in ('event X "t" on 2026-03-02 10:00 for 1h', 'event X "t" at 2026-03-02 10:00 in 1h',
                'event X "t" at 2026-03-02 10:00 for 1h repeat daily\nsplit X on 2026-03-03 10:00 as Y',
                'event X "t" at 2026-03-02 10:00 for 1h repeat daily\nsplit X at 2026-03-03 10:00 to Y',
                "free ann at 2026-03-03 for 1h", "free ann on 2026-03-03 in 1h", "agenda", "hours",
                'event X "t" at 2026-03-02 10:00 for 1h frobnicate'):
        try:
            replay(bad)
            out.append(None)
        except ScheduleError as exc:
            out.append([exc.line, type(exc.__cause__).__name__ if exc.__cause__ else None])
    return out


# --- target probes: default free-slot grid ----------------------------------------------------
def _busy_morning():
    from agenda import Calendar
    cal = Calendar()
    cal.add_event("PLAN", "Planning", D(2026, 3, 3, 9), 75 * MIN, attendees=["ann"])
    cal.add_event("CALL", "Call", D(2026, 3, 3, 11, 5), 40 * MIN, attendees=["bob"])
    cal.add_event("FULL", "Workshop", D(2026, 3, 4, 9), 7 * 60 * MIN + 15 * MIN, attendees=["ann"])
    return cal


def probe_free_slots_default_grid():
    from agenda import free_slots
    cal = _busy_morning()
    return [_clock(free_slots(cal, ["ann"], DAY(2026, 3, 3), 30 * MIN, hours=(datetime.time(9), datetime.time(11)))),
            _clock(free_slots(cal, ["ann", "bob"], DAY(2026, 3, 3), 45 * MIN, hours=(datetime.time(10), datetime.time(13)))),
            _clock(free_slots(cal, ["ann"], DAY(2026, 3, 4), 30 * MIN))]


def probe_first_common_slot_default_grid():
    from agenda import first_common_slot
    cal = _busy_morning()
    return [_s(first_common_slot(cal, ["ann"], DAY(2026, 3, 3), 60 * MIN)),
            _s(first_common_slot(cal, ["ann"], DAY(2026, 3, 4), 30 * MIN)),
            _s(first_common_slot(cal, ["ann", "bob"], DAY(2026, 3, 3), 60 * MIN, hours=(datetime.time(11), datetime.time(17))))]


def probe_free_command_default_grid():
    from agenda import replay
    _, results = replay('event M "Kickoff" at 2026-03-10 09:00 for 1h45m with ann,cy\n'
                        "free ann,cy on 2026-03-10 for 1h\n")
    return results[-1]["slots"][:6]


# --- target probes: weekday order in weekly rules ------------------------------------------------
def probe_weekly_unsorted_days_count():
    from agenda import Rule
    return [_starts(Rule("weekly", weekdays=[4, 0], count=4), D(2026, 3, 6, 18)),
            _starts(Rule("weekly", interval=2, weekdays=[3, 1], count=3), D(2026, 3, 5, 7)),
            _starts(Rule("weekly", weekdays=[2, 2, 0], count=3), D(2026, 3, 4, 7))]


def probe_weekly_unsorted_days_until_and_window():
    from agenda import Rule
    rule = Rule("weekly", weekdays=[5, 1], until=DAY(2026, 3, 12))
    open_rule = Rule("weekly", weekdays=[3, 0])
    return [_starts(rule, D(2026, 3, 3, 9)), [_s(m) for m in open_rule.between(D(2026, 3, 2, 9), D(2026, 3, 9), D(2026, 3, 12))],
            open_rule.is_start(D(2026, 3, 5, 9), D(2026, 3, 9, 9))]


def probe_weekly_unsorted_days_calendar():
    from agenda import Calendar, Rule, reports
    cal = Calendar()
    cal.add_event("GYM", "Gym", D(2026, 3, 6, 18), 60 * MIN, Rule("weekly", weekdays=[4, 0], count=5), attendees=["ann"])
    out = [_series(cal, "GYM"), _error(cal.cancel, "GYM", D(2026, 3, 9, 18)), _series(cal, "GYM")]
    cal.add_event("RUN", "Run", D(2026, 3, 3, 7), 30 * MIN, Rule("weekly", weekdays=[3, 1]), attendees=["ann"])
    out.append(reports.day_agenda(cal, DAY(2026, 3, 10)))
    out.append(reports.week_hours(cal, DAY(2026, 3, 10)))
    return out


def probe_weekly_unsorted_days_schedule():
    from agenda import replay, reports
    cal, _ = replay('event TRAIN "Training" at 2026-03-06 18:00 for 1h repeat weekly on fri,mon count 4 with ann\n'
                    'event YOGA "Yoga" at 2026-03-04 07:00 for 1h repeat every 2 weeks on wed,sun,mon until 2026-03-30\n')
    return [reports.series_dates(cal, "TRAIN"), reports.series_dates(cal, "YOGA")]


# --- target probes: split after cancellations ----------------------------------------------------
def probe_split_after_cancellation_count():
    from agenda import Calendar, Rule
    cal = Calendar()
    cal.add_event("COURSE", "Course", D(2026, 3, 2, 13), 120 * MIN, Rule("weekly", count=6), room="R2", attendees=["ann"])
    cal.cancel("COURSE", D(2026, 3, 9, 13))
    new = cal.split("COURSE", D(2026, 3, 23, 13), "COURSE-B", room="R3")
    return [_series(cal, "COURSE"), _series(cal, "COURSE-B"), new.rule.count, cal.get("COURSE").rule.count]


def probe_split_after_cancellation_until():
    from agenda import Calendar, Rule
    cal = Calendar()
    cal.add_event("DESK", "Desk duty", D(2026, 4, 1, 8), 60 * MIN, Rule("daily", interval=2, until=DAY(2026, 4, 15)),
                  attendees=["bob"])
    cal.cancel("DESK", D(2026, 4, 3, 8))
    cal.cancel("DESK", D(2026, 4, 5, 8))
    cal.split("DESK", D(2026, 4, 9, 8), "DESK-2", attendees=["cy"])
    return [_series(cal, "DESK"), _series(cal, "DESK-2")]


def probe_split_after_cancellation_schedule():
    from agenda import replay, reports
    cal, results = replay('event CLUB "Book club" at 2026-01-15 19:00 for 2h repeat monthly count 8 with ann,bob\n'
                          "cancel CLUB 2026-02-15 19:00\ncancel CLUB 2026-04-15 19:00\nmove CLUB 2026-03-15 19:00 to 2026-03-16 19:00\n"
                          "split CLUB at 2026-05-15 19:00 as CLUB-2 room LIB\nhours 2026-05-15\n")
    return [reports.series_dates(cal, "CLUB"), reports.series_dates(cal, "CLUB-2"), results[-1]["hours"]]
