"""SQL values, column types, comparison, arithmetic and ordering.

Values are Python objects: ``None`` is NULL, ``int`` is INTEGER, ``float``
is REAL, ``str`` is TEXT and ``bool`` is BOOLEAN.  INTEGER and REAL compare
and combine with each other; any other mix of types is a
:class:`TypeMismatch`.  Every operator returns NULL when an operand is NULL.

Integer division truncates toward zero (``-7 / 2`` is ``-3``), ``%`` keeps
the sign of the left operand (``-7 % 3`` is ``-1``), and dividing by zero
gives NULL.  In ascending order NULL sorts before every other value.
"""
import math

from .errors import TypeMismatch

TYPES = ("INTEGER", "REAL", "TEXT", "BOOLEAN")


def type_name(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, str):
        return "TEXT"
    raise TypeMismatch(f"unsupported value {value!r}")


def is_number(value):
    return type_name(value) in ("INTEGER", "REAL")


def coerce(value, column_type):
    """Convert ``value`` for storage in a column of ``column_type`` (NULL passes)."""
    kind = type_name(value)
    if kind == "NULL" or kind == column_type:
        return value
    if column_type == "REAL" and kind == "INTEGER":
        return float(value)
    raise TypeMismatch(f"cannot store {kind} in a {column_type} column")


def compare(left, right):
    """-1, 0 or 1; ``None`` when either side is NULL."""
    if left is None or right is None:
        return None
    if not (is_number(left) and is_number(right)) and type_name(left) != type_name(right):
        raise TypeMismatch(f"cannot compare {type_name(left)} with {type_name(right)}")
    return (left > right) - (left < right)


def truth(value, what="condition"):
    """A condition's value: True, False or None (NULL)."""
    if value is not None and not isinstance(value, bool):
        raise TypeMismatch(f"{what} must be BOOLEAN, not {type_name(value)}")
    return value


_RANK = {"BOOLEAN": 1, "INTEGER": 2, "REAL": 2, "TEXT": 3}


def sort_key(value):
    """Ascending key: NULL first, then BOOLEAN, numbers and TEXT."""
    if value is None:
        return (0, 0)
    return (_RANK[type_name(value)], value)


def arithmetic(op, left, right):
    if left is None or right is None:
        return None
    if op == "||":
        return render(left) + render(right)
    if not (is_number(left) and is_number(right)):
        raise TypeMismatch(f"{op} needs numbers, not {type_name(left)} and {type_name(right)}")
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if right == 0:
        return None
    if op == "/":
        if isinstance(left, int) and isinstance(right, int):
            quotient = abs(left) // abs(right)
            return quotient if (left < 0) == (right < 0) else -quotient
        return left / right
    if op == "%":
        if not (isinstance(left, int) and isinstance(right, int)):
            raise TypeMismatch("% needs INTEGER operands")
        return int(math.fmod(left, right))
    raise TypeMismatch(f"unknown operator {op}")


def render(value):
    """Text form used by ``||`` and result tables: NULL, true/false, numbers, text."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(round(value, 6)) if value != int(value) else f"{int(value)}.0"
    return str(value)
