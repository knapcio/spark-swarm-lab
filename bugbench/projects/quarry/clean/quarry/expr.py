"""Expression trees, column scopes and expression compilation.

``compile_expr`` turns a tree into a Python function of one row (a tuple of
column values in scope order) or, in a grouped query, of one group.
Conditions use three-valued logic: ``NULL AND FALSE`` is FALSE,
``NULL OR TRUE`` is TRUE, and anything else involving NULL is NULL.
"""
from dataclasses import dataclass
from . import functions
from .errors import AmbiguousColumn, GroupingError, QuarryError, UnknownColumn
from .values import arithmetic, compare, render, truth

PRECEDENCE = {"OR": 1, "AND": 2, "=": 4, "<>": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
              "||": 5, "+": 6, "-": 6, "*": 7, "/": 7, "%": 7}
COMPARISONS = {"=": lambda c: c == 0, "<>": lambda c: c != 0, "<": lambda c: c < 0, "<=": lambda c: c <= 0,
               ">": lambda c: c > 0, ">=": lambda c: c >= 0}
ASSOCIATIVE = ("OR", "AND", "||", "+", "*")


@dataclass(frozen=True)
class Literal:
    value: object


@dataclass(frozen=True)
class Column:
    table: object
    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Test:
    """``IS NULL``, ``IN (...)``, ``BETWEEN`` and ``LIKE``, optionally negated."""
    kind: str
    operand: object
    args: tuple
    negated: bool = False


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple
    distinct: bool = False
    star: bool = False


@dataclass(frozen=True)
class Star:
    table: object = None


class Scope:
    """The columns visible to an expression: ``(qualifier, name, type)`` in row order."""

    def __init__(self, columns=()):
        self.columns = list(columns)

    def extend(self, qualifier, names_and_types):
        return Scope(self.columns + [(qualifier, name, kind) for name, kind in names_and_types])

    def resolve(self, column):
        found = [index for index, (qualifier, name, _) in enumerate(self.columns)
                 if name == column.name and (column.table is None or qualifier == column.table)]
        if not found:
            raise UnknownColumn(describe(column))
        if len(found) > 1:
            raise AmbiguousColumn(describe(column))
        return found[0]


class Group:
    def __init__(self, rows):
        self.rows = rows


def describe(node):
    """Canonical SQL text of an expression (used for unnamed result columns)."""
    if isinstance(node, Literal):
        if isinstance(node.value, str):
            return "'" + node.value.replace("'", "''") + "'"
        return "NULL" if node.value is None else render(node.value).upper() if isinstance(node.value, bool) else render(node.value)
    if isinstance(node, Column):
        return node.name if node.table is None else f"{node.table}.{node.name}"
    if isinstance(node, Star):
        return "*" if node.table is None else f"{node.table}.*"
    if isinstance(node, Unary):
        inner = describe(node.operand)
        if isinstance(node.operand, (Binary, Test)):
            inner = f"({inner})"
        return f"NOT {inner}" if node.op == "NOT" else f"-{inner}"
    if isinstance(node, Binary):
        prec = PRECEDENCE[node.op]
        left, right = describe(node.left), describe(node.right)
        if isinstance(node.left, Binary) and PRECEDENCE[node.left.op] < prec:
            left = f"({left})"
        if isinstance(node.right, Binary) and (PRECEDENCE[node.right.op] < prec or (
                PRECEDENCE[node.right.op] == prec and not (node.op == node.right.op and node.op in ASSOCIATIVE))):
            right = f"({right})"
        return f"{left} {node.op} {right}"
    if isinstance(node, Test):
        operand, args = describe(node.operand), [describe(arg) for arg in node.args]
        word = {"null": "IS NULL", "in": "IN", "between": "BETWEEN", "like": "LIKE"}[node.kind]
        if node.negated:
            word = "IS NOT NULL" if node.kind == "null" else "NOT " + word
        if node.kind == "in":
            return f"{operand} {word} ({', '.join(args)})"
        if node.kind == "between":
            return f"{operand} {word} {args[0]} AND {args[1]}"
        return f"{operand} {word}" + (f" {args[0]}" if args else "")
    if isinstance(node, Call):
        inner = "*" if node.star else ", ".join(describe(arg) for arg in node.args)
        return f"{node.name}({'DISTINCT ' if node.distinct else ''}{inner})"
    raise QuarryError(f"cannot describe {node!r}")


def _logic(op, left, right):
    left, right = truth(left, op), truth(right, op)
    stop = op == "OR"
    if left is stop or right is stop:
        return stop
    if left is None or right is None:
        return None
    return not stop


def compile_expr(node, scope, grouped=None):
    """A function of a row, or of a :class:`Group` when ``grouped`` is the set of grouped column indexes."""
    if isinstance(node, Literal):
        return lambda row: node.value
    if isinstance(node, Column):
        index = scope.resolve(node)
        if grouped is None:
            return lambda row: row[index]
        if index not in grouped:
            raise GroupingError(f"{describe(node)} must be grouped or used in an aggregate")
        return lambda group: group.rows[0][index] if group.rows else None
    if isinstance(node, Star):
        raise QuarryError("* is only allowed in the select list and COUNT(*)")
    if isinstance(node, Call) and node.name in functions.AGGREGATES:
        if grouped is None:
            raise GroupingError(f"aggregate {node.name}() is not allowed here")
        if not node.star and len(node.args) != 1:
            raise QuarryError(f"{node.name}() takes one argument")
        inner = None if node.star else compile_expr(node.args[0], scope)
        if any(functions.contains_aggregate(arg) for arg in node.args):
            raise GroupingError("aggregates cannot be nested")
        return lambda group: functions.aggregate(node.name, [row if inner is None else inner(row) for row in group.rows],
                                           node.distinct, node.star)
    parts = [compile_expr(child, scope, grouped) for child in _children(node)]
    if isinstance(node, Unary):
        (operand,) = parts
        if node.op == "NOT":
            return lambda row: _negate(truth(operand(row), "NOT"))
        return lambda row: arithmetic("-", 0, operand(row))
    if isinstance(node, Binary):
        left, right = parts
        if node.op in ("AND", "OR"):
            return lambda row: _logic(node.op, left(row), right(row))
        if node.op in COMPARISONS:
            test = COMPARISONS[node.op]
            return lambda row: _apply(test, compare(left(row), right(row)))
        return lambda row: arithmetic(node.op, left(row), right(row))
    if isinstance(node, Test):
        return _compile_test(node, parts)
    if isinstance(node, Call):
        if node.name not in functions.SCALARS or node.star or node.distinct:
            raise QuarryError(f"unknown function {node.name}()")
        function, low, high = functions.SCALARS[node.name]
        if not low <= len(parts) <= high:
            raise QuarryError(f"{node.name}() takes {low} to {high} arguments")
        return lambda row: function(*[part(row) for part in parts])
    raise QuarryError(f"cannot compile {node!r}")


def _children(node):
    if isinstance(node, Unary):
        return [node.operand]
    if isinstance(node, Binary):
        return [node.left, node.right]
    if isinstance(node, Test):
        return [node.operand] + list(node.args)
    if isinstance(node, Call):
        return list(node.args)
    return []


def _negate(value):
    return None if value is None else not value


def _apply(test, comparison):
    return None if comparison is None else test(comparison)


def _compile_test(node, parts):
    operand, rest = parts[0], parts[1:]
    if node.kind == "null":
        return lambda row: (operand(row) is None) != node.negated
    if node.kind == "like":
        return lambda row: _flip(functions.like(operand(row), rest[0](row)), node.negated)
    if node.kind == "between":
        def between(row):
            value = operand(row)
            low = _apply(COMPARISONS[">="], compare(value, rest[0](row)))
            high = _apply(COMPARISONS["<="], compare(value, rest[1](row)))
            return _flip(_logic("AND", low, high), node.negated)
        return between

    def member(row):
        value, found = operand(row), False
        for item in rest:
            result = _apply(COMPARISONS["="], compare(value, item(row)))
            if result:
                return _flip(True, node.negated)
            if result is None:
                found = None
        return _flip(found, node.negated)
    return member


def _flip(value, negated):
    return _negate(value) if negated else value
