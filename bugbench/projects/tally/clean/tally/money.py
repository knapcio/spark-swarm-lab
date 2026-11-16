"""Amounts, quantities, percentages and dates.

Every amount in tally is an ``int`` number of cents.  Exact intermediate
values are :class:`decimal.Decimal` numbers of cents; turning them into
cents always rounds half-up, away from zero on a tie (12.5 cents -> 13,
-12.5 cents -> -13).  Binary floats are refused everywhere.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import datetime
import re

from .errors import InvalidAmount

_AMOUNT = re.compile(r"^(-?)(\d{1,12})(?:\.(\d{1,2}))?$")
_PERCENT = re.compile(r"^\d{1,3}(?:\.\d{1,2})?$")
_QUANTITY = re.compile(r"^\d{1,9}(?:\.\d{1,3})?$")
HUNDRED = Decimal(100)


def parse_amount(text, allow_negative=False):
    """Parse ``"1234.5"`` into cents (123450).  At most two decimals."""
    if not isinstance(text, str):
        raise InvalidAmount(f"amounts are written as text, not {type(text).__name__}")
    match = _AMOUNT.match(text.strip())
    if not match:
        raise InvalidAmount(f"not an amount: {text!r}")
    sign, whole, fraction = match.groups()
    cents = int(whole) * 100 + int((fraction or "0").ljust(2, "0"))
    if sign:
        if not allow_negative:
            raise InvalidAmount(f"amount must not be negative: {text!r}")
        cents = -cents
    return cents


def check_cents(value, positive=False):
    """Validate an integer amount of cents (``bool`` is not an amount)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAmount(f"amount must be an int number of cents, not {value!r}")
    if value < 0 or (positive and value == 0):
        raise InvalidAmount(f"amount out of range: {value}")
    return value


def round_cents(value):
    """Round an exact Decimal number of cents to an int, half-up."""
    if not isinstance(value, (int, Decimal)) or isinstance(value, bool):
        raise InvalidAmount(f"cannot round {value!r}")
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def percent_of(cents, percent):
    """``percent`` % of ``cents``, rounded half-up to whole cents."""
    return round_cents(Decimal(cents) * percent / HUNDRED)


def parse_percent(text):
    """Parse ``"2"`` or ``"12.5"`` into a Decimal between 0 and 100."""
    if isinstance(text, Decimal):
        text = str(text)
    if not isinstance(text, str) or not _PERCENT.match(text.strip()):
        raise InvalidAmount(f"not a percentage: {text!r}")
    value = Decimal(text.strip())
    if value > HUNDRED:
        raise InvalidAmount(f"percentage above 100: {text!r}")
    return value


def parse_quantity(text):
    """Parse a positive quantity with at most three decimals (``"2"``, ``"0.25"``)."""
    if isinstance(text, int) and not isinstance(text, bool):
        text = str(text)
    if isinstance(text, Decimal):
        text = str(text)
    if not isinstance(text, str) or not _QUANTITY.match(text.strip()):
        raise InvalidAmount(f"not a quantity: {text!r}")
    value = Decimal(text.strip())
    if value <= 0:
        raise InvalidAmount("quantity must be positive")
    return value


def fmt(cents):
    """Format cents as ``"-1234.05"`` (no thousands separator)."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def parse_date(text):
    """Parse an ISO date ``YYYY-MM-DD``."""
    if isinstance(text, datetime.date) and not isinstance(text, datetime.datetime):
        return text
    if not isinstance(text, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", text.strip()):
        raise InvalidAmount(f"not a date: {text!r}")
    try:
        return datetime.date.fromisoformat(text.strip())
    except ValueError:
        raise InvalidAmount(f"not a date: {text!r}") from None


def check_date(value):
    if isinstance(value, datetime.datetime) or not isinstance(value, datetime.date):
        raise InvalidAmount(f"expected a date, got {value!r}")
    return value


def to_decimal(value):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidAmount(f"not a number: {value!r}") from None
