"""Patch sets: several file patches applied together to a file tree.

A tree is a dict ``{path: content}`` with string contents.  ``PatchSet.diff``
compares two trees: one file patch per path whose content differs, sorted
by path; a path only in the new tree is a creation (old path ``/dev/null``),
a path only in the old tree a deletion.

``PatchSet.apply(tree)`` applies the file patches in order and returns a
:class:`TreeResult` with a new tree; the given dict is never modified, and
neither is the patch set, so one patch set can be applied to any number of
trees.  It is all or nothing: if any file patch fails, the error is raised
and no tree is returned.  Per file patch:

- creation: the path must not exist yet (:class:`TreeError`); the content is
  the hunks applied to an empty text;
- deletion: the path must exist, and the hunks must apply and leave an empty
  text, otherwise :class:`HunkFailed`;
- rename: the old path must exist and the new path must not; the file is
  patched and moved;
- otherwise the path must exist and is patched in place.

The log has one line per file patch (``patching file x``, ``creating file
x``, ``deleting file x`` or ``renaming x to y``), each followed by one
line per hunk, indented by two spaces (:meth:`HunkResult.describe`).
"""
from dataclasses import dataclass, field

from .apply import apply_hunks
from .errors import HunkFailed, PatchworkError, TreeError
from .hunks import make_hunks
from .text import Text
from .unified import FilePatch, format_file_patch, parse_patch


@dataclass
class TreeResult:
    tree: dict
    log: list = field(default_factory=list)
    results: dict = field(default_factory=dict)

    @property
    def offsets(self):
        """``{path: [offset per applied hunk]}``."""
        return {path: [r.offset for r in found if r.applied] for path, found in self.results.items()}

    @property
    def fuzzy(self):
        """Paths where at least one hunk needed fuzz, sorted."""
        return sorted(path for path, found in self.results.items() if any(r.fuzz for r in found))


def _check_tree(tree):
    if not isinstance(tree, dict):
        raise PatchworkError("a tree must be a dict of path -> text")
    for path, content in tree.items():
        if not isinstance(path, str) or not path or not isinstance(content, str):
            raise PatchworkError("a tree must be a dict of path -> text")


class PatchSet:
    """An ordered list of :class:`FilePatch` objects."""

    def __init__(self, files=()):
        self.files = list(files)
        for item in self.files:
            if not isinstance(item, FilePatch):
                raise PatchworkError("a patch set holds FilePatch objects")

    @classmethod
    def parse(cls, text, strip=1):
        """Read a multi-file unified diff."""
        return cls(parse_patch(text, strip))

    @classmethod
    def diff(cls, old_tree, new_tree, context=3, ignore_space=False):
        """The patch set turning ``old_tree`` into ``new_tree``."""
        _check_tree(old_tree)
        _check_tree(new_tree)
        files = []
        for path in sorted(set(old_tree) | set(new_tree)):
            old, new = old_tree.get(path), new_tree.get(path)
            if old == new:
                continue
            hunks = make_hunks(old or "", new or "", context, ignore_space)
            if not hunks:
                continue
            files.append(FilePatch(None if old is None else path, None if new is None else path, hunks))
        return cls(files)

    def __str__(self):
        return "".join(format_file_patch(item) for item in self.files)

    def __len__(self):
        return len(self.files)

    def paths(self):
        """Every path the patch set reads or writes, sorted."""
        found = set()
        for item in self.files:
            found.update(path for path in (item.old_path, item.new_path) if path is not None)
        return sorted(found)

    def reversed(self):
        """The patch set that undoes this one (file patches in reverse order)."""
        return PatchSet(item.reversed() for item in reversed(self.files))

    def apply(self, tree, fuzz=2, reverse=False, ignore_space=False):
        """Apply to ``tree``; returns a :class:`TreeResult` (see the module docstring)."""
        _check_tree(tree)
        files = self.reversed().files if reverse else self.files
        work = dict(tree)
        log, results = [], {}
        for item in files:
            source, target = item.old_path, item.new_path
            if source is None:
                if target in work:
                    raise TreeError(target, "file already exists")
                log.append(f"creating file {target}")
                base = ""
            else:
                if source not in work:
                    raise TreeError(source, "file does not exist")
                if item.is_rename and target in work:
                    raise TreeError(target, "rename target already exists")
                base = work[source]
                if target is None:
                    log.append(f"deleting file {source}")
                elif item.is_rename:
                    log.append(f"renaming {source} to {target}")
                else:
                    log.append(f"patching file {source}")
            outcome = apply_hunks(base, item.hunks, fuzz=fuzz, ignore_space=ignore_space, path=item.path)
            log += ["  " + result.describe() for result in outcome.hunks]
            results[item.path] = outcome.hunks
            if target is None:
                if len(outcome.text):
                    raise HunkFailed(source, len(item.hunks) - 1, "file is not empty after deletion")
                del work[source]
                continue
            if item.is_rename:
                del work[source]
            work[target] = str(outcome.text)
        return TreeResult(dict(sorted(work.items())), log, results)


def diff_texts(old, new, old_path="a", new_path=None, context=3, ignore_space=False):
    """Unified diff text for two strings (empty string when they are equal)."""
    hunks = make_hunks(Text.parse(old), Text.parse(new), context, ignore_space)
    if not hunks:
        return ""
    return format_file_patch(FilePatch(old_path, new_path or old_path, hunks))
