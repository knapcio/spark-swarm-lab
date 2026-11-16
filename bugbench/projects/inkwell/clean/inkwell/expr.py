"""Expression syntax tree and parser.

Operators, from lowest to highest binding::

    or
    and
    not                         (prefix)
    == != < <= > >= in  not in  (comparisons do not chain)
    ~                           (string concatenation)
    + -
    * / // %
    -                           (prefix minus)
    .name  [key]  |filter(...)  (postfix, left to right)

Binary operators of the same level group from the left.  Parentheses group
explicitly.  ``and`` and ``or`` short-circuit and return one of their
operands, like Python.  Literals: integers, decimals (``2.50`` becomes a
``Decimal``), single- or double-quoted strings, ``true``, ``false``, ``none``
and lists ``[a, b]``.
"""
from dataclasses import dataclass

from .errors import TemplateSyntaxError

KEYWORDS = frozenset({"and", "or", "not", "in", "if", "else", "true", "false", "none"})
CONSTANTS = {"true": True, "false": False, "none": None}
PRECEDENCE = {
    "or": 1,
    "and": 2,
    "==": 4, "!=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4, "in": 4, "not in": 4,
    "~": 5,
    "+": 6, "-": 6,
    "*": 7, "/": 7, "//": 7, "%": 7,
}
NOT_LEVEL = 3


@dataclass(frozen=True)
class Literal:
    value: object
    line: int


@dataclass(frozen=True)
class Name:
    name: str
    line: int


@dataclass(frozen=True)
class Attr:
    obj: object
    name: str
    line: int


@dataclass(frozen=True)
class Item:
    obj: object
    key: object
    line: int


@dataclass(frozen=True)
class ListLit:
    items: tuple
    line: int


@dataclass(frozen=True)
class Unary:
    op: str  # "not" or "-"
    operand: object
    line: int


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object
    line: int


@dataclass(frozen=True)
class Filter:
    value: object
    name: str
    args: tuple
    kwargs: tuple  # ((name, node), ...)
    line: int


class ExpressionParser:
    """Recursive parser over a list of :class:`~inkwell.lexer.ExprToken`.

    ``parse`` reads one expression and stops at the first token that cannot
    continue it, so callers can parse trailing syntax such as ``if``.
    """

    def __init__(self, tokens, line=1):
        self.tokens = list(tokens)
        self.index = 0
        self.line = line

    # -- cursor helpers -----------------------------------------------------
    def peek(self, offset=0):
        index = self.index + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def at_end(self):
        return self.index >= len(self.tokens)

    def next(self):
        token = self.peek()
        if token is None:
            raise TemplateSyntaxError("unexpected end of expression", self.line)
        self.index += 1
        self.line = token.line
        return token

    def is_op(self, value, offset=0):
        token = self.peek(offset)
        return token is not None and token.kind == "op" and token.value == value

    def is_word(self, value, offset=0):
        token = self.peek(offset)
        return token is not None and token.kind == "name" and token.value == value

    def expect_op(self, value):
        if not self.is_op(value):
            token = self.peek()
            found = repr(token.value) if token else "end of expression"
            raise TemplateSyntaxError(f"expected {value!r}, found {found}", token.line if token else self.line)
        return self.next()

    def fail_unless_end(self):
        if not self.at_end():
            token = self.peek()
            raise TemplateSyntaxError(f"unexpected {token.value!r}", token.line)

    # -- grammar --------------------------------------------------------------
    def parse(self):
        return self._binary(0)

    def _operator(self):
        token = self.peek()
        if token is None:
            return None
        if token.kind == "op" and token.value in PRECEDENCE:
            return token.value
        if token.kind == "name" and token.value in ("and", "or", "in"):
            return token.value
        if self.is_word("not") and self.is_word("in", 1):
            return "not in"
        return None

    def _binary(self, min_level):
        left = self._unary()
        while True:
            op = self._operator()
            if op is None or PRECEDENCE[op] < min_level:
                return left
            token = self.next()
            if op == "not in":
                self.next()
            right = self._binary(PRECEDENCE[op] + 1)
            left = Binary(op, left, right, token.line)

    def _unary(self):
        token = self.peek()
        if token is None:
            raise TemplateSyntaxError("unexpected end of expression", self.line)
        if self.is_word("not"):
            self.next()
            return Unary("not", self._binary(NOT_LEVEL), token.line)
        if self.is_op("-"):
            self.next()
            return Unary("-", self._unary(), token.line)
        return self._postfix(self._primary())

    def _primary(self):
        token = self.next()
        if token.kind in ("int", "decimal", "string"):
            return Literal(token.value, token.line)
        if token.kind == "name":
            if token.value in CONSTANTS:
                return Literal(CONSTANTS[token.value], token.line)
            if token.value in KEYWORDS:
                raise TemplateSyntaxError(f"unexpected keyword {token.value!r}", token.line)
            return Name(token.value, token.line)
        if token.value == "(":
            node = self._binary(0)
            self.expect_op(")")
            return node
        if token.value == "[":
            items = []
            while not self.is_op("]"):
                items.append(self._binary(0))
                if not self.is_op("]"):
                    self.expect_op(",")
            self.next()
            return ListLit(tuple(items), token.line)
        raise TemplateSyntaxError(f"unexpected {token.value!r}", token.line)

    def _postfix(self, node):
        while True:
            if self.is_op("."):
                token = self.next()
                name = self.next()
                if name.kind != "name":
                    raise TemplateSyntaxError("expected an attribute name after '.'", token.line)
                node = Attr(node, name.value, token.line)
            elif self.is_op("["):
                token = self.next()
                key = self._binary(0)
                self.expect_op("]")
                node = Item(node, key, token.line)
            elif self.is_op("|"):
                token = self.next()
                name = self.next()
                if name.kind != "name" or name.value in KEYWORDS:
                    raise TemplateSyntaxError("expected a filter name after '|'", token.line)
                args, kwargs = self._call_arguments() if self.is_op("(") else ((), ())
                node = Filter(node, name.value, args, kwargs, token.line)
            else:
                return node

    def _call_arguments(self):
        self.expect_op("(")
        args, kwargs = [], []
        while not self.is_op(")"):
            token = self.peek()
            if token is not None and token.kind == "name" and self.is_op("=", 1):
                self.index += 2
                kwargs.append((token.value, self._binary(0)))
            elif kwargs:
                raise TemplateSyntaxError("positional argument after keyword argument", self.line)
            else:
                args.append(self._binary(0))
            if not self.is_op(")"):
                self.expect_op(",")
        self.next()
        return tuple(args), tuple(kwargs)


def parse_expression(tokens, line):
    """Parse a complete expression; trailing tokens are a syntax error."""
    parser = ExpressionParser(tokens, line)
    node = parser.parse()
    parser.fail_unless_end()
    return node
