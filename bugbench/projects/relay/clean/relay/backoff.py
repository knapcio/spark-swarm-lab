"""Retry delays.

A policy text is one of

* ``fixed <d>``: every retry waits ``d``;
* ``linear <d> +<step>``: the retry after attempt n waits ``d + (n - 1) * step``;
* ``exp <d> x<factor>``: the retry after attempt n waits ``d * factor ** (n - 1)``.
  The factor may be fractional (``x1.5``) and must be at least 1;

optionally followed by ``max <d>`` (a cap) and ``jitter <p>%`` (0 to 100), in
that order.  The cap is applied first.  Jitter then shortens the delay by up to
``p`` percent, by a fraction that depends only on the job id and the attempt
number: the CRC-32 of ``"<job id>#<attempt>"`` modulo 1001, divided by 1000.
Runs are therefore reproducible.  The final delay is rounded to the nearest
millisecond, halves rounded up.
"""
import math
import re
import zlib
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .clock import format_duration, parse_duration
from .errors import BackoffError, DurationError

DEFAULT_BACKOFF = "exp 100ms x2 max 10s"
_FACTOR = re.compile(r"x(\d+(?:\.\d+)?)\Z")
_STEP = re.compile(r"\+(\S+)\Z")
_JITTER = re.compile(r"(\d+)%\Z")


def jitter_fraction(job_id, attempt):
    """The reproducible jitter fraction in ``[0, 1]`` for one retry."""
    return Fraction(zlib.crc32(f"{job_id}#{attempt}".encode()) % 1001, 1000)


def _decimal_text(value):
    if value.denominator == 1:
        return str(value.numerator)
    return str(Decimal(value.numerator) / Decimal(value.denominator))


@dataclass(frozen=True)
class Backoff:
    kind: str
    base: int
    step: int = 0
    factor: Fraction = Fraction(1)
    cap: int | None = None
    jitter: int = 0

    def raw(self, attempt):
        """The delay after failed attempt ``attempt`` (1-based), before cap, jitter and rounding."""
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise BackoffError(f"attempt must be a positive whole number, not {attempt!r}")
        if self.kind == "fixed":
            return Fraction(self.base)
        if self.kind == "linear":
            return Fraction(self.base + (attempt - 1) * self.step)
        return self.base * self.factor ** (attempt - 1)

    def delay(self, attempt, job_id=""):
        """Milliseconds to wait after failed attempt ``attempt`` of job ``job_id``."""
        value = self.raw(attempt)
        if self.cap is not None and value > self.cap:
            value = Fraction(self.cap)
        if self.jitter:
            value -= value * self.jitter * jitter_fraction(job_id, attempt) / 100
        return math.floor(value + Fraction(1, 2))

    def schedule(self, attempts, job_id=""):
        """The delays after attempts 1 to ``attempts``."""
        return [self.delay(attempt, job_id) for attempt in range(1, attempts + 1)]

    def __str__(self):
        text = f"{self.kind} {format_duration(self.base)}"
        if self.kind == "linear":
            text += f" +{format_duration(self.step)}"
        elif self.kind == "exp":
            text += f" x{_decimal_text(self.factor)}"
        if self.cap is not None:
            text += f" max {format_duration(self.cap)}"
        if self.jitter:
            text += f" jitter {self.jitter}%"
        return text


def _duration(text, what):
    try:
        return parse_duration(text)
    except DurationError as exc:
        raise BackoffError(f"bad {what} {text!r}") from exc


def parse_backoff(text):
    """A :class:`Backoff` for a policy text (see the module docs); a Backoff is returned as is."""
    if isinstance(text, Backoff):
        return text
    if not isinstance(text, str):
        raise BackoffError(f"not a retry policy: {text!r}")
    words = text.split()
    if len(words) < 2 or words[0] not in ("fixed", "linear", "exp"):
        raise BackoffError(f"malformed retry policy {text!r}")
    kind, base, rest = words[0], _duration(words[1], "delay"), words[2:]
    step, factor = 0, Fraction(1)
    if kind != "fixed":
        if not rest:
            raise BackoffError(f"{kind} needs a {'step' if kind == 'linear' else 'factor'}")
        if kind == "linear":
            match = _STEP.match(rest[0])
            if not match:
                raise BackoffError(f"malformed step {rest[0]!r}")
            step = _duration(match.group(1), "step")
        else:
            match = _FACTOR.match(rest[0])
            if not match or Fraction(match.group(1)) < 1:
                raise BackoffError(f"malformed factor {rest[0]!r}")
            factor = Fraction(match.group(1))
        rest = rest[1:]
    cap = jitter = None
    if rest[:1] == ["max"]:
        if len(rest) < 2:
            raise BackoffError("max needs a duration")
        cap, rest = _duration(rest[1], "cap"), rest[2:]
    if rest[:1] == ["jitter"]:
        match = _JITTER.match(rest[1]) if len(rest) > 1 else None
        if not match or int(match.group(1)) > 100:
            raise BackoffError("jitter needs a percentage from 0% to 100%")
        jitter, rest = int(match.group(1)), rest[2:]
    if rest:
        raise BackoffError(f"unexpected {' '.join(rest)!r} in retry policy")
    return Backoff(kind, base, step, factor, cap, jitter or 0)
