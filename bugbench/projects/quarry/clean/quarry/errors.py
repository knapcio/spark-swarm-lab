"""Exception hierarchy for quarry.

All errors derive from :class:`QuarryError`.  A statement either completes
or raises without changing any table.
"""


class QuarryError(Exception):
    """Base class for all errors raised by this package."""


class SqlSyntaxError(QuarryError):
    """The statement text cannot be tokenized or parsed.

    ``position`` is the 0-based character offset of the offending token.
    """

    def __init__(self, message, position):
        super().__init__(f"{message} at position {position}")
        self.position = position


class UnknownTable(QuarryError):
    """No table with this name exists."""


class DuplicateTable(QuarryError):
    """A table with this name already exists."""


class UnknownColumn(QuarryError):
    """A column name does not resolve to any column in scope."""


class AmbiguousColumn(QuarryError):
    """An unqualified column name matches columns of more than one table."""


class TypeMismatch(QuarryError):
    """A value or an operand has the wrong type."""


class ConstraintError(QuarryError):
    """A NOT NULL constraint would be violated."""


class DuplicateKey(ConstraintError):
    """A primary key value would occur twice."""


class GroupingError(QuarryError):
    """A grouped query uses a column outside an aggregate that it does not group by."""
