"""Unified diff format: writing and reading file patches.

A file patch starts with ``--- <old path>`` and ``+++ <new path>`` lines;
``/dev/null`` stands for a missing file (creation or deletion).  Anything
after a tab in a path line (a timestamp) is ignored, and ``strip`` leading
path components are removed (default 1: ``a/src/x.py`` becomes
``src/x.py``).  Lines outside file patches (``diff --git ...``, commit
messages) are ignored.

Each hunk starts with ``@@ -<old> +<new> @@``, where a range is
``line,count``.  A count of 1 is written by omitting it, and an omitted
count is read as 1.  For a range of count 0, ``line`` is the line *after
which* the hunk applies (0 = before the first line); otherwise ``line`` is
the first line of the range.  Text after the closing ``@@`` is ignored.

The hunk body is read by its counts: `` `` (space) marks a context line,
``-`` an old-only line and ``+`` a new-only line; an empty body line is an
empty context line.  ``\\ No newline at end of file`` refers to the line
just before it: after a context line both the old and the new text end
without a newline, after a ``-`` line only the old text, after a ``+`` line
only the new text.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from .errors import PatchParseError
from .hunks import Hunk

NO_NEWLINE = "\\ No newline at end of file"
DEV_NULL = "/dev/null"
_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")


@dataclass
class FilePatch:
    old_path: Optional[str]
    new_path: Optional[str]
    hunks: list = field(default_factory=list)

    @property
    def path(self):
        """The path the patch writes (the old path for a deletion)."""
        return self.new_path if self.new_path is not None else self.old_path

    @property
    def is_new(self):
        return self.old_path is None

    @property
    def is_deleted(self):
        return self.new_path is None

    @property
    def is_rename(self):
        return None not in (self.old_path, self.new_path) and self.old_path != self.new_path

    def reversed(self):
        """The file patch that undoes this one."""
        return FilePatch(self.new_path, self.old_path, [hunk.reversed() for hunk in self.hunks])

    def __str__(self):
        return format_file_patch(self)


def _range(start, length):
    line = start + 1 if length else start
    return str(line) if length == 1 else f"{line},{length}"


def format_header(hunk):
    """``@@ -l,s +l,s @@`` for ``hunk`` (see the module docstring for the rules)."""
    return f"@@ -{_range(hunk.old_start, hunk.old_len)} +{_range(hunk.new_start, hunk.new_len)} @@"


def format_hunk(hunk):
    """The header and body lines of ``hunk``, without line terminators."""
    out = [format_header(hunk)]
    old_seen = new_seen = 0
    old_len, new_len = hunk.old_len, hunk.new_len
    for tag, text in hunk.lines:
        out.append(tag + text)
        old_seen += tag != "+"
        new_seen += tag != "-"
        old_end = tag != "+" and old_seen == old_len and not hunk.old_newline
        new_end = tag != "-" and new_seen == new_len and not hunk.new_newline
        if old_end or new_end:
            out.append(NO_NEWLINE)
    return out


def _path_line(prefix, path, side):
    return f"{prefix} {DEV_NULL if path is None else side + path}"


def format_file_patch(patch, prefixes=True):
    """One file patch in unified format, ending with a newline."""
    old_side, new_side = ("a/", "b/") if prefixes else ("", "")
    out = [_path_line("---", patch.old_path, old_side), _path_line("+++", patch.new_path, new_side)]
    for hunk in patch.hunks:
        out += format_hunk(hunk)
    return "\n".join(out) + "\n"


def _parse_path(raw, strip, number):
    path = raw.split("\t", 1)[0].strip()
    if path == DEV_NULL:
        return None
    parts = [part for part in path.split("/") if part]
    if len(parts) <= strip:
        raise PatchParseError(f"cannot strip {strip} component(s) from {path!r}", number)
    return "/".join(parts[strip:])


def _position(start, count, number):
    start = int(start)
    count = 1 if count is None else int(count)
    if count == 0:
        return start, 0
    if start == 0:
        raise PatchParseError("line 0 is only allowed for an empty range", number)
    return start - 1, count


def _read_hunk(match, lines, i):
    old_start, old_left = _position(match.group(1), match.group(2), i)
    new_start, new_left = _position(match.group(3), match.group(4), i)
    hunk = Hunk(old_start, new_start, [])
    last = None
    while old_left or new_left or (i < len(lines) and lines[i].startswith("\\") and last is not None):
        if i >= len(lines):
            raise PatchParseError("hunk body ends early", i)
        line = lines[i]
        tag, text = (line[0], line[1:]) if line else (" ", "")
        if tag == "\\":
            if last is None:
                raise PatchParseError("newline marker without a line before it", i + 1)
            if last != "+":
                hunk.old_newline = False
            if last != "-":
                hunk.new_newline = False
            last = None
        elif tag == " " and old_left and new_left:
            old_left, new_left, last = old_left - 1, new_left - 1, tag
        elif tag == "-" and old_left:
            old_left, last = old_left - 1, tag
        elif tag == "+" and new_left:
            new_left, last = new_left - 1, tag
        else:
            raise PatchParseError(f"unexpected line in hunk: {line[:40]!r}", i + 1)
        if tag != "\\":
            hunk.lines.append((tag, text))
        i += 1
    if not any(tag != " " for tag, _ in hunk.lines):
        raise PatchParseError("hunk without changes", i)
    return hunk, i


def parse_patch(text, strip=1):
    """All file patches in ``text``, in order.  Raises :class:`PatchParseError`."""
    if not isinstance(text, str):
        raise PatchParseError("patch must be a string")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    patches, current, i = [], None, 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old, new = _parse_path(line[4:], strip, i + 1), _parse_path(lines[i + 1][4:], strip, i + 2)
            if old is None and new is None:
                raise PatchParseError("both paths are /dev/null", i + 1)
            current = FilePatch(old, new, [])
            patches.append(current)
            i += 2
            continue
        match = _HEADER.match(line)
        if match:
            if current is None:
                raise PatchParseError("hunk before any file header", i + 1)
            hunk, i = _read_hunk(match, lines, i + 1)
            if current.hunks and hunk.old_start < current.hunks[-1].old_start + current.hunks[-1].old_len:
                raise PatchParseError("hunks overlap or are out of order", i)
            current.hunks.append(hunk)
            continue
        i += 1
    if not patches:
        raise PatchParseError("no file patches found")
    for patch in patches:
        if not patch.hunks:
            raise PatchParseError(f"file patch for {patch.path} has no hunks")
    return patches
