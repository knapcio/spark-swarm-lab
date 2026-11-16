"""Built-in functions.

Scalar functions: UPPER, LOWER, LENGTH, ABS, ROUND (half away from zero),
SUBSTR (1-based) and COALESCE.  They return NULL for a NULL argument, except
COALESCE, which returns its first non-NULL argument.

Aggregate functions: COUNT, SUM, AVG, MIN and MAX.

Aggregates skip NULL values; ``COUNT(*)`` counts rows.  Over no values,
COUNT is 0 and the others are NULL.  ``DISTINCT`` drops repeated values
before aggregating.  SUM of INTEGER values is an INTEGER, AVG is always
REAL, and MIN/MAX use the usual ordering of their type.
"""
from decimal import ROUND_HALF_UP, Decimal
import re

from .errors import TypeMismatch
from .values import compare, is_number, type_name

AGGREGATES = ("count", "sum", "avg", "min", "max")


def contains_aggregate(node):
    """True if the expression tree contains an aggregate call."""
    from .expr import Call, _children
    if isinstance(node, Call) and node.name in AGGREGATES:
        return True
    return any(contains_aggregate(child) for child in _children(node))


def _numbers(name, values):
    for value in values:
        if not is_number(value):
            raise TypeMismatch(f"{name}() needs numbers, not {type_name(value)}")
    return values


def _extreme(values, sign):
    best = values[0]
    for value in values[1:]:
        if compare(value, best) == sign:
            best = value
    return best


def aggregate(name, values, distinct=False, star=False):
    """Aggregate ``values`` (one per row; for ``COUNT(*)`` the rows themselves)."""
    if star:
        if name != "count":
            raise TypeMismatch(f"{name}(*) is not allowed")
        return len(values)
    present = [value for value in values if value is not None]
    if distinct:
        unique = []
        for value in present:
            if not any(type_name(value) == type_name(seen) and value == seen for seen in unique):
                unique.append(value)
        present = unique
    if name == "count":
        return len(present)
    if not present:
        return None
    if name == "sum":
        return sum(_numbers(name, present))
    if name == "avg":
        return sum(_numbers(name, present)) / len(present)
    return _extreme(present, -1 if name == "min" else 1)


def like(value, pattern):
    """SQL LIKE: ``%`` matches any run of characters, ``_`` one character; case-sensitive."""
    if value is None or pattern is None:
        return None
    if type_name(value) != "TEXT" or type_name(pattern) != "TEXT":
        raise TypeMismatch("LIKE needs TEXT operands")
    regex = "".join(".*" if char == "%" else "." if char == "_" else re.escape(char) for char in pattern)
    return re.fullmatch(regex, value, re.DOTALL) is not None


def _round(value, places=0):
    if value is None or places is None:
        return None
    if not is_number(value) or type_name(places) != "INTEGER" or places < 0:
        raise TypeMismatch("ROUND needs a number and a non-negative INTEGER")
    if isinstance(value, int):
        return value
    return float(Decimal(repr(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _text(function):
    def wrapped(value, *rest):
        if value is None:
            return None
        if type_name(value) != "TEXT":
            raise TypeMismatch("text function needs TEXT")
        return function(value, *rest)
    return wrapped


def _substr(value, start, length=None):
    if start is None or type_name(start) != "INTEGER" or start < 1:
        raise TypeMismatch("SUBSTR start must be an INTEGER >= 1")
    if length is not None and (type_name(length) != "INTEGER" or length < 0):
        raise TypeMismatch("SUBSTR length must be a non-negative INTEGER")
    return value[start - 1:] if length is None else value[start - 1:start - 1 + length]


def _abs(value):
    if value is None:
        return None
    if not is_number(value):
        raise TypeMismatch("ABS needs a number")
    return abs(value)


SCALARS = {"upper": (_text(str.upper), 1, 1), "lower": (_text(str.lower), 1, 1), "length": (_text(len), 1, 1),
           "abs": (_abs, 1, 1), "round": (_round, 1, 2), "substr": (_text(_substr), 2, 3),
           "coalesce": (lambda *values: next((v for v in values if v is not None), None), 1, 99)}
