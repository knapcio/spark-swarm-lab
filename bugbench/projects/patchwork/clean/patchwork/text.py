"""Text values: a tuple of lines plus whether the last line ends in a newline.

``Text.parse`` splits on ``"\\n"`` only; a ``"\\r"`` stays part of its line.
The empty string is the empty text: no lines, and ``newline`` is True.  A
non-empty string that does not end in ``"\\n"`` gives ``newline == False``.
``str(text)`` restores the original string exactly.

Two texts are equal when their lines and their ``newline`` flags are equal.
For diffing, :meth:`Text.keys` marks a last line without a newline so that
it never equals the same line with a newline.
"""
import re

from .errors import PatchworkError

_SPACE_RUN = re.compile(r"[ \t]+")


class Text:
    """An immutable sequence of lines (without their ``"\\n"``)."""

    __slots__ = ("lines", "newline")

    def __init__(self, lines=(), newline=True):
        lines = tuple(lines)
        for line in lines:
            if not isinstance(line, str) or "\n" in line:
                raise PatchworkError("lines must be strings without newline characters")
        if not isinstance(newline, bool):
            raise PatchworkError("newline must be True or False")
        object.__setattr__(self, "lines", lines)
        object.__setattr__(self, "newline", newline if lines else True)

    def __setattr__(self, name, value):
        raise AttributeError("Text is immutable")

    @classmethod
    def parse(cls, value):
        """A :class:`Text` from a string; a Text is returned unchanged."""
        if isinstance(value, Text):
            return value
        if not isinstance(value, str):
            raise PatchworkError("text must be a string")
        if value == "":
            return cls()
        newline = value.endswith("\n")
        body = value[:-1] if newline else value
        return cls(body.split("\n"), newline)

    def __str__(self):
        if not self.lines:
            return ""
        return "\n".join(self.lines) + ("\n" if self.newline else "")

    def __repr__(self):
        return f"Text({str(self)!r})"

    def __len__(self):
        return len(self.lines)

    def __iter__(self):
        return iter(self.lines)

    def __getitem__(self, index):
        return self.lines[index]

    def __eq__(self, other):
        if not isinstance(other, Text):
            return NotImplemented
        return self.lines == other.lines and self.newline == other.newline

    def __hash__(self):
        return hash((self.lines, self.newline))

    def replace(self, lines=None, newline=None):
        """A new Text with ``lines`` and/or ``newline`` replaced."""
        return Text(self.lines if lines is None else lines, self.newline if newline is None else newline)

    def keys(self, ignore_space=False):
        """Comparison keys for diffing, one per line.

        With ``ignore_space`` each key is :func:`loose` of the line.  The key of a
        last line without a newline is marked, so it differs from the same
        line followed by a newline."""
        out = [loose(line) if ignore_space else line for line in self.lines]
        if out and not self.newline:
            out[-1] = (out[-1], "no newline")
        return out


def loose(line):
    """Whitespace-insensitive form: runs of spaces and tabs become one space; ends are stripped."""
    return _SPACE_RUN.sub(" ", line).strip()


def same_line(a, b, ignore_space=False):
    """Whether two lines are equal, optionally ignoring whitespace differences."""
    return loose(a) == loose(b) if ignore_space else a == b


def same_lines(found, wanted, ignore_space=False):
    """Whether two equally long line sequences match line by line."""
    return len(found) == len(wanted) and all(same_line(a, b, ignore_space) for a, b in zip(found, wanted))
