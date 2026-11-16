"""Variable scopes, undefined values and loop information.

Lookup order is innermost scope first: loop iteration, then template
variables (including ``set`` at the top level), then the variables passed to
``render``, then environment globals.  ``set`` always binds in the innermost
scope.  The dictionaries passed to ``render`` and the environment globals are
never modified.

A name that is not found evaluates to an :class:`Undefined`.  Undefined
values are false in conditions and are accepted by the ``default`` filter in
every mode.  In a lenient environment they render as an empty string and
iterate as an empty sequence; a strict environment raises
:class:`~inkwell.errors.UndefinedError` instead, pointing at the line where
the missing name appears.
"""
from dataclasses import dataclass

from .errors import TemplateError, UndefinedError

MAX_INCLUDE_DEPTH = 16


class Undefined:
    """Placeholder for a missing variable, attribute or item."""

    __slots__ = ("name", "line")

    def __init__(self, name, line):
        self.name = name
        self.line = line

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __str__(self):
        return ""

    def __repr__(self):
        return f"Undefined({self.name!r})"


@dataclass(frozen=True)
class LoopInfo:
    """The ``loop`` variable inside a for loop body."""

    index0: int
    length: int

    @property
    def index(self):
        return self.index0 + 1

    @property
    def revindex(self):
        return self.length - self.index0

    @property
    def first(self):
        return self.index0 == 0

    @property
    def last(self):
        return self.index0 == self.length - 1


class Context:
    """The scope chain of one render (or of one included template)."""

    def __init__(self, env, frames, name, depth=0):
        self.env = env
        self.frames = frames
        self.name = name
        self.depth = depth

    @classmethod
    def root(cls, env, variables, name):
        return cls(env, [env.globals, dict(variables), {}], name)

    def derive(self, name):
        """Scope for an included template: sees everything, binds only its own names.

        Includes may nest up to MAX_INCLUDE_DEPTH levels; one more raises TemplateError."""
        if self.depth + 1 > MAX_INCLUDE_DEPTH:
            raise TemplateError("includes nested too deeply", None, self.name)
        return Context(self.env, self.frames + [{}], name, self.depth + 1)

    def push(self, values=None):
        frame = dict(values or {})
        self.frames.append(frame)
        return frame

    def pop(self):
        self.frames.pop()

    def set(self, name, value):
        self.frames[-1][name] = value

    def lookup(self, name, line):
        for frame in reversed(self.frames):
            if name in frame:
                return frame[name]
        return Undefined(name, line)

    def require(self, value, line=None):
        """Return ``value``; in strict mode an Undefined raises UndefinedError."""
        if isinstance(value, Undefined) and self.env.strict:
            raise UndefinedError(f"{value.name!r} is undefined", value.line if line is None else line, self.name)
        return value

    def attribute(self, obj, name, line):
        """``obj.name``: dictionary key first, then a public, non-callable attribute."""
        if isinstance(obj, Undefined):
            self.require(obj)
            return Undefined(f"{obj.name}.{name}", line)
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif not name.startswith("_"):
            value = getattr(obj, name, _MISSING)
            if value is not _MISSING and not callable(value):
                return value
        return Undefined(f"{_label(obj)}.{name}", line)

    def item(self, obj, key, line):
        """``obj[key]``: dictionary key, or integer index of a list, tuple or string."""
        self.require(obj)
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
        elif isinstance(obj, (list, tuple, str)) and isinstance(key, int) and not isinstance(key, bool):
            if -len(obj) <= key < len(obj):
                return obj[key]
        return Undefined(f"{_label(obj)}[{key!r}]", line)


_MISSING = object()


def _label(obj):
    return obj.name if isinstance(obj, Undefined) else type(obj).__name__


def truthy(value):
    return bool(value)
