"""Hunks: the changed regions of a diff together with surrounding context.

A :class:`Hunk` has 0-based ``old_start``/``new_start`` positions and
``lines``, a list of ``(tag, text)`` pairs where the tag is ``" "``
(context, in both texts), ``"-"`` (only in the old text) or ``"+"`` (only in
the new text).  For a hunk with no old lines, ``old_start`` is the position
where the new lines are inserted; the same holds for the new side.
``old_newline``/``new_newline`` are False only when the hunk contains the
last line of the old/new text and that text does not end in a newline.

``make_hunks(a, b, context)`` groups the changes of the line diff: each
change gets up to ``context`` unchanged lines before and after it, and two
changes share one hunk when at most ``2 * context`` unchanged lines separate
them.  Inside a hunk, the deleted lines of a replaced block come before the
inserted ones.  With ``ignore_space`` lines are compared with
:func:`patchwork.text.loose`, and context lines are taken from the new text.
"""
from dataclasses import dataclass, field

from .errors import PatchworkError
from .lcs import opcodes
from .text import Text

TAGS = (" ", "-", "+")


@dataclass
class Hunk:
    old_start: int
    new_start: int
    lines: list = field(default_factory=list)
    old_newline: bool = True
    new_newline: bool = True

    @property
    def old_len(self):
        return sum(1 for tag, _ in self.lines if tag != "+")

    @property
    def new_len(self):
        return sum(1 for tag, _ in self.lines if tag != "-")

    @property
    def additions(self):
        return sum(1 for tag, _ in self.lines if tag == "+")

    @property
    def deletions(self):
        return sum(1 for tag, _ in self.lines if tag == "-")

    def old_lines(self):
        """The lines this hunk expects to find (context and deleted lines)."""
        return [text for tag, text in self.lines if tag != "+"]

    def new_lines(self):
        """The lines this hunk leaves behind (context and inserted lines)."""
        return [text for tag, text in self.lines if tag != "-"]

    def leading_context(self):
        """Number of context lines before the first changed line."""
        count = 0
        for tag, _ in self.lines:
            if tag != " ":
                break
            count += 1
        return count

    def trailing_context(self):
        """Number of context lines after the last changed line (0 for a hunk of context only)."""
        if all(tag == " " for tag, _ in self.lines):
            return 0
        count = 0
        for tag, _ in reversed(self.lines):
            if tag != " ":
                break
            count += 1
        return count

    def validate(self):
        """Raise :class:`PatchworkError` unless positions and tags are well formed."""
        for value in (self.old_start, self.new_start):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise PatchworkError("hunk positions must be integers >= 0")
        for item in self.lines:
            if len(item) != 2 or item[0] not in TAGS or not isinstance(item[1], str) or "\n" in item[1]:
                raise PatchworkError(f"bad hunk line {item!r}")
        if not any(tag != " " for tag, _ in self.lines):
            raise PatchworkError("a hunk needs at least one changed line")
        return self

    def reversed(self):
        """The hunk that undoes this one: old and new sides swap."""
        swap = {" ": " ", "-": "+", "+": "-"}
        lines = [(swap[tag], text) for tag, text in self.lines]
        # keep deletions before insertions inside every changed block
        out, block = [], []
        for tag, text in lines + [(" ", None)]:
            if tag == " ":
                out += [item for item in block if item[0] == "-"] + [item for item in block if item[0] == "+"]
                block = []
                if text is not None:
                    out.append((tag, text))
            else:
                block.append((tag, text))
        return Hunk(self.new_start, self.old_start, out, self.new_newline, self.old_newline)

    def trimmed(self, fuzz):
        """A copy without up to ``fuzz`` context lines at each end; this hunk is unchanged.

        Used by fuzzy application.  Only context lines are dropped, never a
        changed line, and the start positions move past the dropped lines."""
        front = min(fuzz, self.leading_context())
        back = min(fuzz, self.trailing_context())
        lines = list(self.lines)
        del lines[len(lines) - back:]
        del lines[:front]
        return Hunk(self.old_start + front, self.new_start + front, lines, self.old_newline, self.new_newline)


def _check_context(context):
    if not isinstance(context, int) or isinstance(context, bool) or context < 0:
        raise PatchworkError("context must be an integer >= 0")


def _build(a, b, group, context):
    first, last = group[0], group[-1]
    i1 = max(0, first[1] - context)
    i2 = min(len(a), last[2] + context)
    j1 = first[3] - (first[1] - i1)
    j2 = last[4] + (i2 - last[2])
    lines, i, j = [], i1, j1
    for _tag, a1, a2, b1, b2 in group:
        lines += [(" ", b[j + n]) for n in range(a1 - i)]
        lines += [("-", a[n]) for n in range(a1, a2)]
        lines += [("+", b[n]) for n in range(b1, b2)]
        i, j = a2, b2
    lines += [(" ", b[j + n]) for n in range(i2 - i)]
    old_newline = a.newline or i2 < len(a)
    new_newline = b.newline or j2 < len(b)
    return Hunk(i1, j1, lines, old_newline, new_newline)


def make_hunks(a, b, context=3, ignore_space=False):
    """Hunks turning text ``a`` into text ``b`` (strings or :class:`Text`)."""
    _check_context(context)
    a, b = Text.parse(a), Text.parse(b)
    changes = [op for op in opcodes(a.keys(ignore_space), b.keys(ignore_space)) if op[0] != "equal"]
    groups = []
    for op in changes:
        if groups and op[1] - groups[-1][-1][2] <= 2 * context:
            groups[-1].append(op)
        else:
            groups.append([op])
    return [_build(a, b, group, context) for group in groups]


def changed_lines(hunks):
    """``(added, removed)`` line counts over ``hunks``."""
    return sum(h.additions for h in hunks), sum(h.deletions for h in hunks)
