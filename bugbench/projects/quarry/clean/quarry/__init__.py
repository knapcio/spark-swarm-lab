"""quarry: a small SQL query engine over in-memory tables."""
from .engine import Engine, Result, ScriptFailed, explain, format_result
from .errors import (AmbiguousColumn, ConstraintError, DuplicateKey, DuplicateTable, GroupingError, QuarryError,
                     SqlSyntaxError, TypeMismatch, UnknownColumn, UnknownTable)
from .parser import parse

__version__ = "0.4.0"
__all__ = ["AmbiguousColumn", "ConstraintError", "DuplicateKey", "DuplicateTable", "Engine", "GroupingError",
           "QuarryError", "Result", "ScriptFailed", "SqlSyntaxError", "TypeMismatch", "UnknownColumn", "UnknownTable",
           "explain", "format_result", "parse"]
