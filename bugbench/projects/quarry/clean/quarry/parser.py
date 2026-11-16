"""Statement parser.

Operator precedence, loosest first: ``OR``; ``AND``; ``NOT``; comparisons
with ``IS [NOT] NULL``, ``[NOT] IN``, ``[NOT] BETWEEN`` and ``[NOT] LIKE``;
``||``; ``+ -``; ``* / %``; unary ``-``.  Binary operators of the same
precedence group from left to right, so ``10 - 4 - 3`` is ``(10 - 4) - 3``.
"""
from collections import namedtuple

from .errors import SqlSyntaxError
from .expr import PRECEDENCE, Binary, Call, Column, Literal, Star, Test, Unary
from .lexer import tokenize
from .values import TYPES


Select = namedtuple("Select", "items table joins where group_by having order_by limit offset distinct")
CreateTable = namedtuple("CreateTable", "name columns")  # columns: (name, type, not_null, primary_key)
DropTable = namedtuple("DropTable", "name")
Insert = namedtuple("Insert", "table columns rows")
Delete = namedtuple("Delete", "table where")
Update = namedtuple("Update", "table assignments where")


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.index = 0

    # -- token helpers ------------------------------------------------------------
    @property
    def token(self):
        return self.tokens[self.index]

    def error(self, message):
        return SqlSyntaxError(message, self.token.position)

    def accept(self, kind, value=None):
        if self.token.is_(kind, value):
            self.index += 1
            return self.tokens[self.index - 1]
        return None

    def expect(self, kind, value=None):
        token = self.accept(kind, value)
        if token is None:
            raise self.error(f"expected {value or kind}")
        return token

    def keyword(self, *words):
        return any(self.token.is_("keyword", word) for word in words)

    def name(self):
        return self.expect("name").value

    def comma_list(self, item):
        values = [item()]
        while self.accept("punct", ","):
            values.append(item())
        return values

    # -- statements ---------------------------------------------------------------
    def statement(self):
        if self.accept("keyword", "SELECT"):
            result = self.select()
        elif self.accept("keyword", "CREATE"):
            self.expect("keyword", "TABLE")
            result = CreateTable(self.name(), self.parenthesized(self.column_definition))
        elif self.accept("keyword", "DROP"):
            self.expect("keyword", "TABLE")
            result = DropTable(self.name())
        elif self.accept("keyword", "INSERT"):
            self.expect("keyword", "INTO")
            table = self.name()
            columns = self.parenthesized(self.name) if self.token.is_("punct", "(") else None
            self.expect("keyword", "VALUES")
            result = Insert(table, columns, self.comma_list(lambda: self.parenthesized(self.expression)))
        elif self.accept("keyword", "DELETE"):
            self.expect("keyword", "FROM")
            table = self.name()
            result = Delete(table, self.expression() if self.accept("keyword", "WHERE") else None)
        elif self.accept("keyword", "UPDATE"):
            table = self.name()
            self.expect("keyword", "SET")
            assignments = self.comma_list(self.assignment)
            result = Update(table, assignments, self.expression() if self.accept("keyword", "WHERE") else None)
        else:
            raise self.error("expected a statement")
        self.accept("punct", ";")
        if not self.token.is_("end"):
            raise self.error("unexpected text after the statement")
        return result

    def parenthesized(self, item):
        self.expect("punct", "(")
        values = self.comma_list(item)
        self.expect("punct", ")")
        return values

    def column_definition(self):
        name = self.name()
        if not self.keyword(*TYPES):
            raise self.error("expected a column type")
        kind = self.expect("keyword").value
        not_null = primary = False
        while True:
            if self.accept("keyword", "NOT"):
                self.expect("keyword", "NULL")
                not_null = True
            elif self.accept("keyword", "PRIMARY"):
                self.expect("keyword", "KEY")
                primary = True
            else:
                return (name, kind, not_null or primary, primary)

    def assignment(self):
        name = self.name()
        self.expect("op", "=")
        return (name, self.expression())

    def select(self):
        distinct = bool(self.accept("keyword", "DISTINCT"))
        items = self.comma_list(self.select_item)
        table, joins, where, group_by, having, order_by, limit, offset = None, [], None, [], None, [], None, 0
        if self.accept("keyword", "FROM"):
            table = self.table_reference()
            while self.keyword("JOIN", "INNER", "LEFT"):
                left = bool(self.accept("keyword", "LEFT"))
                self.accept("keyword", "INNER")
                self.expect("keyword", "JOIN")
                joined = self.table_reference()
                self.expect("keyword", "ON")
                joins.append((joined, self.expression(), left))
        if self.accept("keyword", "WHERE"):
            where = self.expression()
        if self.accept("keyword", "GROUP"):
            self.expect("keyword", "BY")
            group_by = self.comma_list(self.expression)
        if self.accept("keyword", "HAVING"):
            having = self.expression()
        if self.accept("keyword", "ORDER"):
            self.expect("keyword", "BY")
            order_by = self.comma_list(self.order_item)
        if self.accept("keyword", "LIMIT"):
            limit = self.expect("integer").value
            if self.accept("keyword", "OFFSET"):
                offset = self.expect("integer").value
        return Select(items, table, joins, where, group_by, having, order_by, limit, offset, distinct)

    def select_item(self):
        if self.accept("op", "*"):
            return (Star(), None)
        if self.token.kind == "name" and self.tokens[self.index + 1].is_("punct", ".") \
                and self.tokens[self.index + 2].is_("op", "*"):
            table = self.name()
            self.index += 2
            return (Star(table), None)
        node = self.expression()
        if self.accept("keyword", "AS"):
            return (node, self.name())
        return (node, self.name() if self.token.kind == "name" else None)

    def table_reference(self):
        name = self.name()
        self.accept("keyword", "AS")
        return (name, self.name() if self.token.kind == "name" else name)

    def order_item(self):
        node = self.expression()
        if self.accept("keyword", "DESC"):
            return (node, True)
        self.accept("keyword", "ASC")
        return (node, False)

    # -- expressions --------------------------------------------------------------
    def binary_operator(self):
        token = self.token
        if token.kind == "op" and token.value in PRECEDENCE:
            return token.value
        if token.kind == "keyword" and token.value in ("AND", "OR"):
            return token.value
        if token.kind == "keyword" and token.value in ("IS", "IN", "BETWEEN", "LIKE", "NOT"):
            return "test"
        return None

    def expression(self, min_prec=1):
        left = self.primary()
        while True:
            op = self.binary_operator()
            prec = 4 if op == "test" else PRECEDENCE.get(op)
            if op is None or prec < min_prec:
                return left
            if op == "test":
                left = self.test(left)
                continue
            self.index += 1
            right = self.expression(prec + 1)
            left = Binary(op, left, right)

    def test(self, operand):
        if self.accept("keyword", "IS"):
            negated = bool(self.accept("keyword", "NOT"))
            self.expect("keyword", "NULL")
            return Test("null", operand, (), negated)
        negated = bool(self.accept("keyword", "NOT"))
        if self.accept("keyword", "IN"):
            return Test("in", operand, tuple(self.parenthesized(self.expression)), negated)
        if self.accept("keyword", "BETWEEN"):
            low = self.expression(5)
            self.expect("keyword", "AND")
            return Test("between", operand, (low, self.expression(5)), negated)
        if self.accept("keyword", "LIKE"):
            return Test("like", operand, (self.expression(5),), negated)
        raise self.error("expected IN, BETWEEN or LIKE")

    def primary(self):
        token = self.token
        if self.accept("keyword", "NOT"):
            return Unary("NOT", self.expression(3))
        if self.accept("op", "-"):
            return Unary("-", self.expression(8))
        if token.kind in ("integer", "real", "string"):
            self.index += 1
            return Literal(token.value)
        if self.accept("keyword", "NULL"):
            return Literal(None)
        if self.keyword("TRUE", "FALSE"):
            self.index += 1
            return Literal(token.value == "TRUE")
        if self.accept("punct", "("):
            node = self.expression()
            self.expect("punct", ")")
            return node
        if token.kind == "name":
            name = self.name()
            if self.accept("punct", "("):
                return self.call(name)
            if self.accept("punct", "."):
                return Column(name, self.name())
            return Column(None, name)
        raise self.error("expected an expression")

    def call(self, name):
        if self.accept("op", "*"):
            self.expect("punct", ")")
            return Call(name, (), star=True)
        distinct = bool(self.accept("keyword", "DISTINCT"))
        args = () if self.token.is_("punct", ")") else tuple(self.comma_list(self.expression))
        self.expect("punct", ")")
        return Call(name, args, distinct)


def parse(text):
    """Parse one statement (a trailing ``;`` is allowed)."""
    return Parser(text).statement()
