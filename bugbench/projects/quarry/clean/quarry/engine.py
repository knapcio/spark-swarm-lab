"""``Engine``: parse and run statements against an in-memory database.

``execute`` runs one statement and returns a :class:`Result`.  For SELECT,
``columns`` and ``rows`` hold the answer; for the other statements
``rowcount`` says how many rows were inserted, changed or deleted.

``run_script`` runs statements separated by ``;`` in order and stops at the
first failure by raising :class:`ScriptFailed`, whose ``statement`` is the
1-based number of the failing statement; earlier statements stay applied.

``format_result`` renders a SELECT result as a text table: numbers are
right-aligned, everything else left-aligned, values as shown by
:func:`quarry.values.render`, followed by a ``(N rows)`` line.
"""
from dataclasses import dataclass, field

from .errors import QuarryError
from .expr import Scope, compile_expr, describe
from .lexer import split_statements
from .parser import CreateTable, Delete, DropTable, Insert, Select, Update, parse
from .planner import run_select
from .table import ColumnDef, Database
from .values import is_number, render, truth


@dataclass
class Result:
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    rowcount: int = 0

    def scalar(self):
        """The single value of a one-row, one-column result."""
        if len(self.rows) != 1 or len(self.columns) != 1:
            raise QuarryError(f"expected one value, got {len(self.rows)} rows of {len(self.columns)} columns")
        return self.rows[0][0]


class ScriptFailed(QuarryError):
    def __init__(self, statement, cause):
        super().__init__(f"statement {statement}: {cause}")
        self.statement = statement


def _constant(node):
    return compile_expr(node, Scope())(())


class Engine:
    def __init__(self):
        self.db = Database()

    def execute(self, sql):
        statement = parse(sql)
        if isinstance(statement, Select):
            columns, rows = run_select(self.db, statement)
            return Result(columns, rows, len(rows))
        if isinstance(statement, CreateTable):
            self.db.create_table(statement.name, [ColumnDef(*column) for column in statement.columns])
            return Result()
        if isinstance(statement, DropTable):
            self.db.drop_table(statement.name)
            return Result()
        if isinstance(statement, Insert):
            return Result(rowcount=self._insert(statement))
        if isinstance(statement, Delete):
            table, test = self._target(statement.table, statement.where)
            return Result(rowcount=table.delete([i for i, row in enumerate(table.rows()) if test(row)]))
        if isinstance(statement, Update):
            return Result(rowcount=self._update(statement))
        raise QuarryError(f"cannot execute {statement!r}")

    def query(self, sql):
        """The rows of a SELECT."""
        return self.execute(sql).rows

    def run_script(self, text):
        results = []
        for number, sql in enumerate(split_statements(text), 1):
            try:
                results.append(self.execute(sql))
            except QuarryError as exc:
                raise ScriptFailed(number, exc) from exc
        return results

    def _target(self, name, where):
        table = self.db.table(name)
        scope = Scope().extend(name, [(c.name, c.type) for c in table.columns])
        if where is None:
            return table, lambda row: True
        condition = compile_expr(where, scope)
        return table, lambda row: truth(condition(row), "WHERE") is True

    def _insert(self, statement):
        table = self.db.table(statement.table)
        if statement.columns is None:
            positions = list(range(len(table.columns)))
        else:
            positions = [table.index_of(name) for name in statement.columns]
            if len(set(positions)) != len(positions):
                raise QuarryError("a column is listed twice")
        rows = []
        for values in statement.rows:
            if len(values) != len(positions):
                raise QuarryError(f"expected {len(positions)} values, got {len(values)}")
            row = [None] * len(table.columns)
            for position, node in zip(positions, values):
                row[position] = _constant(node)
            rows.append(row)
        return table.insert(rows)

    def _update(self, statement):
        table, test = self._target(statement.table, statement.where)
        scope = Scope().extend(statement.table, [(c.name, c.type) for c in table.columns])
        assignments = []
        for name, node in statement.assignments:
            assignments.append((table.index_of(name), compile_expr(node, scope)))
        if len({position for position, _ in assignments}) != len(assignments):
            raise QuarryError("a column is assigned twice")
        changes = {}
        for position, row in enumerate(table.rows()):
            if test(row):
                values = list(row)
                for index, function in assignments:
                    values[index] = function(row)
                changes[position] = values
        return table.update(changes)


def explain(sql):
    """Canonical text of the expressions in a SELECT list (handy to check grouping of operators)."""
    statement = parse(sql)
    if not isinstance(statement, Select):
        raise QuarryError("explain needs a SELECT")
    return [describe(node) for node, _ in statement.items]


def format_result(result):
    """Render a :class:`~quarry.engine.Result` of a SELECT as text."""
    header = list(result.columns)
    cells = [[render(value) for value in row] for row in result.rows]
    widths = [max([len(name)] + [len(row[i]) for row in cells]) for i, name in enumerate(header)]
    numeric = [bool(result.rows) and all(is_number(row[i]) or row[i] is None for row in result.rows) and
               any(is_number(row[i]) for row in result.rows) for i in range(len(header))]
    lines = [" | ".join(name.ljust(width) for name, width in zip(header, widths)).rstrip(),
             "-+-".join("-" * width for width in widths)]
    for row in cells:
        parts = [value.rjust(width) if right else value.ljust(width) for value, width, right in zip(row, widths, numeric)]
        lines.append(" | ".join(parts).rstrip())
    count = len(result.rows)
    lines.append(f"({count} row{'s' if count != 1 else ''})")
    return "\n".join(lines)


def format_values(values):
    """``"a, b, NULL"`` for a list of values."""
    return ", ".join(render(value) for value in values)
