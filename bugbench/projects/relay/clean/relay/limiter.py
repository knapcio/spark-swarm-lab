"""Intake rate limits: per-key token buckets with debt, on the virtual clock.

A rate ``N/P`` (for example ``3/s``, ``10/m`` or ``5/250ms``) earns N tokens
every P milliseconds, continuously, up to a burst capacity (default N).  A new
bucket starts full.  Internally a bucket counts in *units*: one token is P
units and every millisecond adds N units, so all arithmetic is exact.

Taking tokens never fails by itself: the bucket may go into debt, and the
taker learns how long it has to wait until the tokens are fully earned.  That
wait is rounded *up* to a whole millisecond: at the returned time the tokens
exist, one millisecond earlier they do not.  A key may set ``max_wait``; a take
that would wait longer raises :class:`RateLimited` and changes nothing.

Keys without their own rate use the limiter's default rate; with no default
they are unlimited (every wait is 0).
"""
import re
from dataclasses import dataclass

from .clock import format_duration, parse_duration
from .errors import ClockError, DurationError, RateError, RateLimited, RelayError

KEY = re.compile(r"[a-z][a-z0-9_-]*\Z")
_RATE = re.compile(r"(\d+)/(\S+)\Z")


def check_key(key):
    """``key`` if it is a valid key name (lower case, digits, ``_`` and ``-``)."""
    if not isinstance(key, str) or not KEY.match(key):
        raise RelayError(f"invalid key {key!r}")
    return key


def _count(value, what):
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RateError(f"{what} must be a positive whole number, not {value!r}")
    return value


@dataclass(frozen=True)
class Rate:
    tokens: int     # earned per period
    period: int     # milliseconds
    burst: int      # bucket capacity in tokens

    def __str__(self):
        return f"{self.tokens}/{format_duration(self.period)} burst {self.burst}"


def parse_rate(text, burst=None):
    """A :class:`Rate` for ``"N/period"``; the period is a duration or a bare unit (``s``, ``m``, ``h``, ``ms``)."""
    if isinstance(text, Rate):
        return text if burst is None else Rate(text.tokens, text.period, _count(burst, "burst"))
    if not isinstance(text, str):
        raise RateError(f"not a rate: {text!r}")
    match = _RATE.match(text.replace(" ", ""))
    if not match:
        raise RateError(f"malformed rate {text!r}")
    tokens, period = int(match.group(1)), match.group(2)
    try:
        period = parse_duration("1" + period if period in ("h", "m", "s", "ms") else period)
    except DurationError as exc:
        raise RateError(f"malformed period in {text!r}") from exc
    if tokens < 1 or period < 1:
        raise RateError(f"rate {text!r} must earn at least one token per non-empty period")
    return Rate(tokens, period, tokens if burst is None else _count(burst, "burst"))


class Bucket:
    """The token bucket of one key; ``units`` is negative while in debt."""

    def __init__(self, key, rate, now, max_wait=None):
        self.key = key
        self.rate = rate
        self.max_wait = max_wait
        self.units = rate.burst * rate.period
        self.stamp = now

    def _refill(self, now):
        if now < self.stamp:
            raise ClockError(f"bucket {self.key} was used at {self.stamp} ms, cannot go back to {now} ms")
        capacity = self.rate.burst * self.rate.period
        self.units = min(capacity, self.units + (now - self.stamp) * self.rate.tokens)
        self.stamp = now

    def _ms_for(self, missing):
        """Whole milliseconds needed to earn ``missing`` units."""
        return -(-missing // self.rate.tokens)

    def available(self, now):
        """Whole tokens that could be taken at ``now`` without waiting."""
        self._refill(now)
        return max(0, self.units // self.rate.period)

    def wait(self, now, cost=1):
        """Milliseconds from ``now`` until ``cost`` tokens are available (0 if they already are)."""
        self._refill(now)
        missing = cost * self.rate.period - self.units
        return self._ms_for(missing) if missing > 0 else 0

    def take(self, now, cost=1):
        """Take ``cost`` tokens at ``now``; returns the wait until they are earned."""
        self._refill(now)
        after = self.units - cost * self.rate.period
        wait = self._ms_for(-after) if after < 0 else 0
        if self.max_wait is not None and wait > self.max_wait:
            raise RateLimited(self.key, wait, self.max_wait)
        self.units = after
        return wait

    def state(self):
        return (self.units, self.stamp)

    def restore(self, state):
        self.units, self.stamp = state


class Limiter:
    """Buckets for many keys, created on first use."""

    def __init__(self, default=None):
        self.default = None if default is None else parse_rate(default)
        self._settings = {}
        self._buckets = {}

    def configure(self, key, rate, burst=None, max_wait=None):
        """Set the rate (and optional burst and maximum wait) of ``key``; its bucket starts full again."""
        check_key(key)
        rate = parse_rate(rate, burst)
        max_wait = None if max_wait is None else parse_duration(max_wait)
        self._settings[key] = (rate, max_wait)
        self._buckets.pop(key, None)
        return rate

    def rate_for(self, key):
        """The rate that applies to ``key``, or None when it is unlimited."""
        found = self._settings.get(check_key(key))
        return found[0] if found else self.default

    def bucket(self, key, now):
        """The bucket of ``key`` (created full at ``now``), or None for an unlimited key."""
        if key not in self._buckets:
            rate = self.rate_for(key)
            if rate is None:
                return None
            self._buckets[key] = Bucket(key, rate, now, self._settings.get(key, (None, None))[1])
        return self._buckets[key]

    def reserve(self, requests, now):
        """Take ``cost`` tokens for every ``(key, cost)`` request in order, all or nothing.

        Returns the list of waits.  If any request would wait longer than its
        key's ``max_wait``, every bucket is left exactly as it was before the
        call and :class:`RateLimited` is raised."""
        checked = [(check_key(key), _count(cost, "cost")) for key, cost in requests]
        saved, waits = {}, []
        try:
            for key, cost in checked:
                bucket = self.bucket(key, now)
                if bucket is None:
                    waits.append(0)
                    continue
                saved.setdefault(key, bucket.state())
                waits.append(bucket.take(now, cost))
        except RateLimited:
            for key, state in saved.items():
                self._buckets[key].restore(state)
            raise
        return waits

    def available(self, key, now):
        """Whole tokens of ``key`` available at ``now``; None for an unlimited key."""
        bucket = self.bucket(check_key(key), now)
        return None if bucket is None else bucket.available(now)

    def wait(self, key, now, cost=1):
        """Milliseconds until ``cost`` tokens of ``key`` are available; 0 for an unlimited key."""
        bucket = self.bucket(check_key(key), now)
        return 0 if bucket is None else bucket.wait(now, _count(cost, "cost"))

    def status(self, now):
        """``[key, rate text, available tokens, wait for one token]`` for every configured or used key, by key."""
        keys = sorted(set(self._settings) | set(self._buckets))
        return [[key, str(self.rate_for(key)), self.available(key, now), self.wait(key, now)] for key in keys]
