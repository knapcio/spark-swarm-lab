"""A small line-based script language for driving a dispatcher.

One command per line; blank lines and ``#`` comments are ignored.

==============================================  =============================================
``workers N``                                   number of workers (before the first job)
``backoff <policy>``                            retry policy (before the first job)
``rate <key> <N/period> [burst B] [maxwait D]`` intake rate of a key; ``*`` sets the default
``submit <id> [option value]...``               submit one job
``batch <id> [options] ; <id> [options] ...``   submit several jobs, all or nothing
``cancel <id>`` / ``revive <id> [after D]``     job control
``run [until T]`` / ``advance D``               simulate until T (absolute) or idle / move the clock
``show <id>``, ``starts [id]``, ``stats``,      outputs (see :func:`replay`)
``tokens <key>``, ``keys``
==============================================  =============================================

Job options: ``key``, ``prio``, ``takes``, ``delay``, ``attempts``, ``fails``
and ``cost``.  A command that fails with a relay error has no effect and
produces the output ``error <ErrorName>``; the script goes on.  A line that
cannot be parsed raises :class:`ScriptError` with its line number.
"""
from .backoff import parse_backoff
from .clock import format_duration, parse_duration
from .dispatcher import Dispatcher
from .errors import RelayError, ScriptError
from .limiter import Limiter, parse_rate
from .stats import key_table, start_times, summary

OPTIONS = {"key": "key", "prio": "priority", "takes": "takes", "delay": "delay", "attempts": "attempts",
           "fails": "fails", "cost": "cost"}


def _job_spec(words, number):
    if not words:
        raise ScriptError(number, "a job needs an id")
    spec, rest = {"id": words[0]}, words[1:]
    if len(rest) % 2:
        raise ScriptError(number, f"option {rest[-1]!r} needs a value")
    for name, value in zip(rest[::2], rest[1::2]):
        if name not in OPTIONS:
            raise ScriptError(number, f"unknown job option {name!r}")
        if OPTIONS[name] in spec:
            raise ScriptError(number, f"option {name!r} given twice")
        spec[OPTIONS[name]] = value
    return spec


class _Session:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.workers = 1
        self.backoff = None
        self.limiter = Limiter()

    def ensure(self):
        if self.dispatcher is None:
            self.dispatcher = Dispatcher(self.workers, self.limiter, self.backoff)
        return self.dispatcher

    def configure(self, command, words, number):
        if self.dispatcher is not None:
            raise ScriptError(number, f"{command} must come before the first job")
        if command == "workers":
            if len(words) != 1 or not words[0].isdigit():
                raise ScriptError(number, "workers needs a number")
            self.workers = int(words[0])
        else:
            try:
                self.backoff = parse_backoff(" ".join(words))
            except RelayError as exc:
                raise ScriptError(number, str(exc)) from exc

    def rate(self, words, number):
        if len(words) not in (2, 4, 6):
            raise ScriptError(number, "usage: rate <key> <N/period> [burst B] [maxwait D]")
        options = dict(zip(words[2::2], words[3::2]))
        if set(options) - {"burst", "maxwait"} or len(options) != len(words[2:]) // 2:
            raise ScriptError(number, "rate options are burst and maxwait, each at most once")
        limiter = self.dispatcher.limiter if self.dispatcher is not None else self.limiter
        if words[0] == "*":
            if "maxwait" in options:
                raise ScriptError(number, "the default rate has no maxwait")
            limiter.default = parse_rate(words[1], options.get("burst"))
        else:
            limiter.configure(words[0], words[1], options.get("burst"), options.get("maxwait"))


def _execute(session, command, words, number, outputs):
    if command in ("workers", "backoff"):
        session.configure(command, words, number)
    elif command == "rate":
        session.rate(words, number)
    elif command == "submit":
        job = session.ensure().submit_batch([_job_spec(words, number)])[0]
        outputs.append(f"submitted {job.id} ready {format_duration(job.ready_at)}")
    elif command == "batch":
        groups = " ".join(words).split(";")
        specs = [_job_spec(group.split(), number) for group in groups]
        jobs = session.ensure().submit_batch(specs)
        outputs.append("submitted " + ", ".join(f"{job.id}@{format_duration(job.ready_at)}" for job in jobs))
    elif command in ("cancel", "show") and len(words) == 1:
        dispatcher = session.ensure()
        if command == "cancel":
            dispatcher.cancel(words[0])
            outputs.append(f"cancelled {words[0]}")
        else:
            job = dispatcher.get(words[0])
            outputs.append(f"{job.describe()} ready {format_duration(job.ready_at)}")
    elif command == "revive" and len(words) in (1, 3) and words[1:2] in ([], ["after"]):
        job = session.ensure().revive(words[0], words[2] if len(words) == 3 else 0)
        outputs.append(f"revived {job.id} ready {format_duration(job.ready_at)}")
    elif command == "run" and (not words or (len(words) == 2 and words[0] == "until")):
        outputs.append(f"now {format_duration(session.ensure().run(words[1] if words else None))}")
    elif command == "advance" and len(words) == 1:
        dispatcher = session.ensure()
        dispatcher.run(dispatcher.now + parse_duration(words[0]))
        outputs.append(f"now {format_duration(dispatcher.now)}")
    elif command == "starts" and len(words) <= 1:
        found = start_times(session.ensure(), words[0] if words else None)
        outputs.append(" ".join(f"{job_id}#{attempt}@{format_duration(when)}" for job_id, attempt, when in found))
    elif command == "stats" and not words:
        counts = summary(session.ensure())
        outputs.append(" ".join(f"{name} {counts[name]}" for name in ("done", "dead", "queued", "cancelled", "runs", "retries")))
    elif command == "tokens" and len(words) == 1:
        dispatcher = session.ensure()
        available = dispatcher.limiter.available(words[0], dispatcher.now)
        outputs.append(f"{words[0]} {'unlimited' if available is None else available}")
    elif command == "keys" and not words:
        outputs.append(key_table(session.ensure()))
    else:
        raise ScriptError(number, f"cannot parse {command!r} command")


def replay(text, dispatcher=None):
    """Run a script; returns ``(dispatcher, outputs)``.  An existing dispatcher can be continued."""
    if not isinstance(text, str):
        raise ScriptError(0, "a script must be text")
    session = _Session(dispatcher)
    outputs = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        command, *words = line.split()
        try:
            _execute(session, command, words, number, outputs)
        except ScriptError:
            raise
        except RelayError as exc:
            outputs.append(f"error {type(exc).__name__}")
    return session.ensure(), outputs
