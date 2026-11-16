"""Applying hunks to a text.

Hunks are applied in order.  For each hunk the search starts at its old
position (``old_start``), shifted by the line-count change of the hunks
applied before it and by the offset of the previous applied hunk.  The
hunk's old lines (context and deleted lines) are looked for at increasing
distance from that start, the earlier position first when two are equally
far.  A hunk is never placed before the end of the previous applied hunk.

When the old lines are not found anywhere, the hunk is retried with fuzz 1,
then fuzz 2, up to ``fuzz``: fuzz ``k`` ignores up to ``k`` context lines at
the start and at the end of the hunk (see :meth:`Hunk.trimmed`).

The reported ``offset`` of a hunk is its placed position minus its old
position shifted by the line-count change of the earlier hunks; ``line`` is
the 1-based line where the hunk's first remaining line was placed, counted
in the text as it was when the hunk was applied.

The patched text ends with a newline like the input, unless an applied
hunk's old lines reached the end of the text; then the hunk's
``new_newline`` decides.  Applying never modifies the input text or the
hunks.  ``reverse=True`` applies :meth:`Hunk.reversed` of every hunk.
"""
from dataclasses import dataclass, field

from .errors import HunkFailed, PatchworkError
from .text import Text, same_lines

MAX_FUZZ = 3


@dataclass
class HunkResult:
    index: int
    applied: bool
    line: int = 0
    offset: int = 0
    fuzz: int = 0

    def describe(self):
        """``hunk 2 applied at line 14 (offset +3, fuzz 1)`` or ``hunk 2 rejected``."""
        if not self.applied:
            return f"hunk {self.index + 1} rejected"
        extra = []
        if self.offset:
            extra.append(f"offset {self.offset:+d}")
        if self.fuzz:
            extra.append(f"fuzz {self.fuzz}")
        return f"hunk {self.index + 1} applied at line {self.line}" + (f" ({', '.join(extra)})" if extra else "")


@dataclass
class ApplyResult:
    text: Text
    hunks: list = field(default_factory=list)

    @property
    def rejected(self):
        """0-based indexes of the hunks that were not applied."""
        return [result.index for result in self.hunks if not result.applied]

    @property
    def clean(self):
        """True when every hunk applied without offset or fuzz."""
        return all(r.applied and not r.offset and not r.fuzz for r in self.hunks)


def find(lines, wanted, start, floor=0, ignore_space=False):
    """Position of ``wanted`` in ``lines`` nearest to ``start`` (earlier first on ties), or None.

    Only positions ``>= floor`` are considered.  An empty ``wanted`` is
    found at ``start`` clamped into ``[floor, len(lines)]``."""
    last = len(lines) - len(wanted)
    if not wanted:
        return min(max(start, floor), len(lines))
    if last < floor:
        return None
    start = min(max(start, floor), last)
    for distance in range(0, max(start - floor, last - start) + 1):
        for position in (start - distance, start + distance):
            if floor <= position <= last and same_lines(lines[position:position + len(wanted)], wanted, ignore_space):
                return position
    return None


def _check_fuzz(fuzz):
    if not isinstance(fuzz, int) or isinstance(fuzz, bool) or not 0 <= fuzz <= MAX_FUZZ:
        raise PatchworkError(f"fuzz must be an integer from 0 to {MAX_FUZZ}")


def _place(lines, hunk, shift, carry, floor, fuzz, ignore_space):
    room = max(hunk.leading_context(), hunk.trailing_context())
    for level in range(min(fuzz, room) + 1):
        candidate = hunk if level == 0 else hunk.trimmed(level)
        expected = candidate.old_start + shift
        position = find(lines, candidate.old_lines(), expected + carry, floor, ignore_space)
        if position is not None:
            return candidate, position, position - expected, level
    return None


def apply_hunks(text, hunks, fuzz=2, reverse=False, ignore_space=False, partial=False, path=None):
    """Apply ``hunks`` to ``text`` (a string or :class:`Text`); returns an :class:`ApplyResult`.

    By default every hunk must apply, otherwise :class:`HunkFailed` is raised
    for the first failing hunk.  With ``partial=True`` failing hunks are
    reported as rejected and the others are applied."""
    _check_fuzz(fuzz)
    text = Text.parse(text)
    lines = list(text.lines)
    newline = text.newline
    shift = carry = floor = 0
    results = []
    for index, original in enumerate(hunks):
        hunk = original.reversed() if reverse else original
        placed = _place(lines, hunk, shift, carry, floor, fuzz, ignore_space)
        if placed is None:
            if not partial:
                raise HunkFailed(path, index)
            results.append(HunkResult(index, False))
            continue
        candidate, position, offset, level = placed
        old, new = candidate.old_lines(), candidate.new_lines()
        if position + len(old) == len(lines):
            newline = candidate.new_newline
        lines[position:position + len(old)] = new
        floor = position + len(new)
        shift += len(new) - len(old)
        carry = offset
        results.append(HunkResult(index, True, position + 1, offset, level))
    return ApplyResult(Text(lines, newline), results)


def apply_text(text, hunks, **options):
    """Shortcut: the patched text as a string."""
    return str(apply_hunks(text, hunks, **options).text)


def is_applied(text, hunks, ignore_space=False):
    """True when ``hunks`` look already applied: the reversed hunks apply without fuzz."""
    try:
        apply_hunks(text, hunks, fuzz=0, reverse=True, ignore_space=ignore_space)
    except HunkFailed:
        return False
    return True
