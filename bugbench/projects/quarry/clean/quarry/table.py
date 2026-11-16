"""Tables and the database catalog.

A table keeps its rows in insertion order; queries without ORDER BY return
rows in that order.  Columns are typed (INTEGER, REAL, TEXT, BOOLEAN), may
be NOT NULL, and at most one column is the PRIMARY KEY, which implies NOT
NULL and must be unique.  REAL columns accept INTEGER values and store them
as REAL.

``insert``, ``update`` and ``delete`` are atomic: when any row fails a check,
the table, including its primary key index, is left exactly as it was.
"""
from dataclasses import dataclass
import re

from .errors import ConstraintError, DuplicateKey, DuplicateTable, QuarryError, UnknownColumn, UnknownTable
from .values import TYPES, coerce

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: str
    not_null: bool = False
    primary_key: bool = False


class Table:
    def __init__(self, name, columns):
        if not columns:
            raise QuarryError("a table needs at least one column")
        names = [column.name for column in columns]
        if len(set(names)) != len(names):
            raise QuarryError(f"duplicate column name in {name}")
        keys = [index for index, column in enumerate(columns) if column.primary_key]
        if len(keys) > 1:
            raise QuarryError("a table can have only one PRIMARY KEY")
        for column in columns:
            if not _NAME.match(column.name) or column.type not in TYPES:
                raise QuarryError(f"bad column definition {column!r}")
        self.name = name
        self.columns = tuple(columns)
        self.key_index = keys[0] if keys else None
        self._rows = []
        self._keys = set()

    @property
    def column_names(self):
        return [column.name for column in self.columns]

    def index_of(self, name):
        try:
            return self.column_names.index(name)
        except ValueError:
            raise UnknownColumn(f"{self.name}.{name}") from None

    def rows(self):
        """A new list of the rows (tuples) in insertion order."""
        return list(self._rows)

    def __len__(self):
        return len(self._rows)

    def _check(self, values):
        if len(values) != len(self.columns):
            raise QuarryError(f"{self.name} has {len(self.columns)} columns, got {len(values)} values")
        row = []
        for column, value in zip(self.columns, values):
            value = coerce(value, column.type)
            if value is None and column.not_null:
                raise ConstraintError(f"{self.name}.{column.name} may not be NULL")
            row.append(value)
        return tuple(row)

    def insert(self, rows):
        """Append ``rows`` (sequences of values in column order); returns how many were added."""
        checked, seen = [], set()
        for values in rows:
            row = self._check(values)
            if self.key_index is not None:
                key = row[self.key_index]
                if key in self._keys or key in seen:
                    raise DuplicateKey(f"{self.name}: duplicate key {key!r}")
                seen.add(key)
            checked.append(row)
        self._rows.extend(checked)
        self._keys.update(seen)
        return len(checked)

    def update(self, changes):
        """Replace rows: ``changes`` maps row positions to new value sequences; returns the count."""
        new_rows = list(self._rows)
        for position, values in changes.items():
            new_rows[position] = self._check(values)
        keys = set()
        if self.key_index is not None:
            for row in new_rows:
                if row[self.key_index] in keys:
                    raise DuplicateKey(f"{self.name}: duplicate key {row[self.key_index]!r}")
                keys.add(row[self.key_index])
        self._rows = new_rows
        self._keys = keys
        return len(changes)

    def delete(self, positions):
        """Remove the rows at ``positions``; the others keep their order.  Returns the count."""
        doomed = set(positions)
        kept = [row for position, row in enumerate(self._rows) if position not in doomed]
        removed = len(self._rows) - len(kept)
        self._rows = kept
        if self.key_index is not None:
            self._keys = {row[self.key_index] for row in kept}
        return removed


class Database:
    def __init__(self):
        self._tables = {}

    def create_table(self, name, columns):
        if not isinstance(name, str) or not _NAME.match(name):
            raise QuarryError(f"bad table name {name!r}")
        if name in self._tables:
            raise DuplicateTable(name)
        table = Table(name, [column if isinstance(column, ColumnDef) else ColumnDef(*column) for column in columns])
        self._tables[name] = table
        return table

    def drop_table(self, name):
        self.table(name)
        del self._tables[name]

    def table(self, name):
        try:
            return self._tables[name]
        except (KeyError, TypeError):
            raise UnknownTable(name) from None

    def table_names(self):
        return sorted(self._tables)
