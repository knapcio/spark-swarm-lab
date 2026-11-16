"""Change statistics for patch sets and file patches.

``diffstat(patches, width=40)`` gives one line per file patch, in patch
order: `` <path> | <changes> <bar>``, the paths padded to the longest path
and the change counts right-aligned to the widest count.  The bar has one
``+`` per inserted and one ``-`` per deleted line.  When the largest change
count exceeds ``width``, every bar is scaled by ``width / largest``: each
part is rounded down, but a non-zero part keeps at least one character.
A renamed file is shown as ``old => new``.

The last line is the summary, ``N file(s) changed, I insertion(s)(+), D
deletion(s)(-)`` using singular words for 1; a part with zero lines is
left out, except that the file count is always shown.
"""
from .errors import PatchworkError


def _files(patches):
    files = getattr(patches, "files", patches)
    return list(files)


def file_counts(patch):
    """``(insertions, deletions, hunks)`` of one file patch."""
    return (sum(h.additions for h in patch.hunks), sum(h.deletions for h in patch.hunks), len(patch.hunks))


def summary(patches):
    """``{"files", "hunks", "insertions", "deletions"}`` over a patch set or a list of file patches."""
    files = _files(patches)
    counts = [file_counts(item) for item in files]
    return {"files": len(files), "hunks": sum(c[2] for c in counts),
            "insertions": sum(c[0] for c in counts), "deletions": sum(c[1] for c in counts)}


def _plural(count, word, suffix=""):
    return f"{count} {word}{'' if count == 1 else 's'}{suffix}"


def summary_line(patches):
    """The last line of :func:`diffstat`."""
    total = summary(patches)
    parts = [_plural(total["files"], "file") + " changed"]
    if total["insertions"]:
        parts.append(_plural(total["insertions"], "insertion", "(+)"))
    if total["deletions"]:
        parts.append(_plural(total["deletions"], "deletion", "(-)"))
    return " " + ", ".join(parts)


def _scaled(count, factor):
    if count == 0:
        return 0
    return max(1, int(count * factor))


def _label(patch):
    if patch.is_rename:
        return f"{patch.old_path} => {patch.new_path}"
    return patch.path


def diffstat(patches, width=40):
    """diffstat-style lines for a patch set or a list of file patches (see the module docstring)."""
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        raise PatchworkError("width must be a positive integer")
    files = _files(patches)
    if not files:
        return [summary_line(files)]
    rows = [(_label(item),) + file_counts(item)[:2] for item in files]
    largest = max(added + removed for _, added, removed in rows)
    factor = width / largest if largest > width else 1
    name_width = max(len(name) for name, _, _ in rows)
    count_width = max(len(str(added + removed)) for _, added, removed in rows)
    out = []
    for name, added, removed in rows:
        bar = "+" * _scaled(added, factor) + "-" * _scaled(removed, factor)
        out.append(f" {name.ljust(name_width)} | {str(added + removed).rjust(count_width)} {bar}".rstrip())
    out.append(summary_line(files))
    return out


def churn(patches):
    """``{path: insertions + deletions}`` sorted by descending churn, then path."""
    rows = [(item.path, sum(file_counts(item)[:2])) for item in _files(patches)]
    return dict(sorted(rows, key=lambda row: (-row[1], row[0])))
