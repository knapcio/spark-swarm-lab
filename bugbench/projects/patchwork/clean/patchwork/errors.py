"""Exception hierarchy for patchwork.

Every error raised on purpose by the package is a :class:`PatchworkError`.
"""


class PatchworkError(Exception):
    """Base class for every error raised by patchwork."""


class PatchParseError(PatchworkError):
    """A patch text is malformed.

    ``line`` is the 1-based line number in the patch text, or None when the
    problem is not tied to one line (for example an empty patch)."""

    def __init__(self, message, line=None):
        super().__init__(message if line is None else f"line {line}: {message}")
        self.line = line


class HunkFailed(PatchworkError):
    """A hunk could not be placed in the text being patched.

    ``path`` is the file path (None for a bare text) and ``index`` the
    0-based number of the hunk inside its file patch."""

    def __init__(self, path, index, message="hunk does not apply"):
        where = f"{path}: " if path else ""
        super().__init__(f"{where}hunk {index + 1}: {message}")
        self.path = path
        self.index = index


class TreeError(PatchworkError):
    """A patch set does not fit the file tree (missing file, file already exists, ...)."""

    def __init__(self, path, message):
        super().__init__(f"{path}: {message}")
        self.path = path


class MergeConflict(PatchworkError):
    """Raised by a strict merge; ``conflicts`` is the number of conflicting regions."""

    def __init__(self, conflicts):
        super().__init__(f"{conflicts} conflicting region(s)")
        self.conflicts = conflicts
