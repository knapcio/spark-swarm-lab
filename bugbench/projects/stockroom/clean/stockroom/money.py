"""Exact money arithmetic on top of :class:`decimal.Decimal`.

Amounts are always held at the minor-unit precision of their currency (two
decimal places for PLN, EUR, USD and GBP, none for JPY, three for KWD).  Every
rounding step uses ROUND_HALF_UP, the convention used on Polish VAT invoices.
Binary floats are rejected: pass amounts as ``str``, ``int`` or ``Decimal``.
"""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
import functools
import re

from .errors import CurrencyMismatch, InvalidAmount

EXPONENTS = {"PLN": 2, "EUR": 2, "USD": 2, "GBP": 2, "JPY": 0, "KWD": 3}
_PARSE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s+([A-Z]{3})\s*$")


def to_decimal(value):
    """Convert ``value`` to a finite Decimal, refusing floats and booleans."""
    if isinstance(value, (bool, float)):
        raise InvalidAmount(f"refusing inexact amount {value!r}; pass a str, int or Decimal")
    if isinstance(value, (int, Decimal)):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation:
            raise InvalidAmount(f"not a number: {value!r}") from None
    else:
        raise InvalidAmount(f"unsupported amount type {type(value).__name__}")
    if not result.is_finite():
        raise InvalidAmount(f"amount must be finite: {value!r}")
    return result


def quantum(currency):
    """Return the smallest representable step of ``currency``, e.g. 0.01."""
    try:
        return Decimal(1).scaleb(-EXPONENTS[currency])
    except KeyError:
        raise InvalidAmount(f"unsupported currency {currency!r}") from None


@functools.total_ordering
class Money:
    """An immutable amount in one currency, kept at minor-unit precision."""

    __slots__ = ("_amount", "_currency")

    def __init__(self, amount, currency):
        step = quantum(currency)
        object.__setattr__(self, "_amount", to_decimal(amount).quantize(step, rounding=ROUND_HALF_UP))
        object.__setattr__(self, "_currency", currency)

    def __setattr__(self, name, value):
        raise AttributeError("Money is immutable")

    @property
    def amount(self):
        return self._amount

    @property
    def currency(self):
        return self._currency

    @classmethod
    def zero(cls, currency):
        return cls(0, currency)

    @classmethod
    def parse(cls, text):
        """Parse ``"12.50 PLN"`` (amount, one space, ISO currency code)."""
        match = _PARSE.match(text) if isinstance(text, str) else None
        if not match:
            raise InvalidAmount(f"cannot parse money from {text!r}")
        return cls(match.group(1), match.group(2))

    @classmethod
    def from_minor(cls, units, currency):
        """Build an amount from an integer number of minor units (grosze, cents)."""
        if isinstance(units, bool) or not isinstance(units, int):
            raise InvalidAmount("minor units must be an int")
        return cls(Decimal(units).scaleb(-EXPONENTS.get(currency, 0)), currency)

    @property
    def minor_units(self):
        return int(self._amount.scaleb(EXPONENTS[self._currency]))

    def _same_currency(self, other):
        if not isinstance(other, Money):
            raise InvalidAmount(f"expected Money, got {type(other).__name__}")
        if other._currency != self._currency:
            raise CurrencyMismatch(f"{self._currency} vs {other._currency}")

    def __add__(self, other):
        self._same_currency(other)
        return Money(self._amount + other._amount, self._currency)

    def __sub__(self, other):
        self._same_currency(other)
        return Money(self._amount - other._amount, self._currency)

    def __neg__(self):
        return Money(-self._amount, self._currency)

    def __eq__(self, other):
        if not isinstance(other, Money):
            return NotImplemented
        return self._currency == other._currency and self._amount == other._amount

    def __lt__(self, other):
        self._same_currency(other)
        return self._amount < other._amount

    def __hash__(self):
        return hash((self._amount, self._currency))

    def __bool__(self):
        return self._amount != 0

    def times(self, factor):
        """Multiply by a quantity or Decimal factor, rounding half-up once."""
        return Money(self._amount * to_decimal(factor), self._currency)

    def percent(self, rate):
        """Return ``rate`` percent of this amount, rounded half-up once."""
        return Money(self._amount * to_decimal(rate) / 100, self._currency)

    def allocate(self, ratios):
        """Split into parts proportional to ``ratios`` without losing a minor unit.

        Each part first receives ``floor(units * ratio / sum(ratios))`` minor
        units of the absolute amount.  The few units left over are then handed
        out one at a time to the parts in list order, starting with the first
        part.  The sign of the original amount is applied to every part, so the
        parts always add up exactly to the original amount.
        """
        weights = [to_decimal(ratio) for ratio in ratios]
        if not weights or any(weight < 0 for weight in weights) or sum(weights) == 0:
            raise InvalidAmount("ratios must be non-negative and not all zero")
        units = self.minor_units
        sign = -1 if units < 0 else 1
        units = abs(units)
        total_weight = sum(weights)
        shares = [int((units * weight / total_weight).to_integral_value(rounding=ROUND_FLOOR)) for weight in weights]
        leftover = units - sum(shares)
        for index in range(leftover):
            shares[index] += 1
        return [Money.from_minor(sign * share, self._currency) for share in shares]

    def __repr__(self):
        return f"Money({str(self._amount)!r}, {self._currency!r})"

    def __str__(self):
        return f"{self._amount} {self._currency}"


def total(amounts, currency):
    """Sum an iterable of Money values; an empty iterable gives zero."""
    result = Money.zero(currency)
    for amount in amounts:
        result = result + amount
    return result
