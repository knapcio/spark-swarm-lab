"""Three-way merge of texts with conflict markers.

``merge3(base, ours, theirs)`` lines up both sides with the base using the
line diff (:func:`patchwork.lcs.matches`).  A base line matched on both
sides is *stable*; the regions between stable lines are compared:

- unchanged on one side: the other side's lines are taken;
- changed identically on both sides: taken once;
- changed differently: a conflict, written as::

      <<<<<<< ours
      (our lines)
      =======
      (their lines)
      >>>>>>> theirs

  With ``show_base=True`` a ``||||||| base`` section with the base lines
  goes between our lines and ``=======``.

The merged text ends with a newline unless the side whose final newline is
used lacks one: ours, if ours changed the final newline relative to the
base, else theirs.  ``strict=True`` raises :class:`MergeConflict` instead
of returning a result with conflicts.
"""
from dataclasses import dataclass, field

from .errors import MergeConflict, PatchworkError
from .lcs import matches
from .text import Text


@dataclass
class MergeResult:
    text: Text
    conflicts: int = 0
    regions: list = field(default_factory=list)   # [(kind, line count)] kind: same/ours/theirs/both/conflict

    @property
    def clean(self):
        return self.conflicts == 0


def _mapping(base, side):
    return {i: j for i, j in matches(base, side)}


def _stable_points(base, ours, theirs):
    """``[(i, j, k)]``: base line ``i`` matched with our line ``j`` and their line ``k``, increasing."""
    to_ours, to_theirs = _mapping(base, ours), _mapping(base, theirs)
    return [(i, to_ours[i], to_theirs[i]) for i in range(len(base)) if i in to_ours and i in to_theirs]


def _labels(labels):
    if not (isinstance(labels, tuple) and len(labels) == 2 and all(isinstance(x, str) and x for x in labels)):
        raise PatchworkError("labels must be a pair of non-empty strings")
    return labels


def merge3(base, ours, theirs, labels=("ours", "theirs"), show_base=False, strict=False):
    """Merge ``ours`` and ``theirs`` (both derived from ``base``); returns a :class:`MergeResult`."""
    ours_label, theirs_label = _labels(labels)
    base, ours, theirs = Text.parse(base), Text.parse(ours), Text.parse(theirs)
    b, o, t = list(base.lines), list(ours.lines), list(theirs.lines)
    out, regions, conflicts = [], [], 0
    i = j = k = 0
    for si, sj, sk in _stable_points(b, o, t) + [(len(b), len(o), len(t))]:
        old, mine, yours = b[i:si], o[j:sj], t[k:sk]
        if old or mine or yours:
            if mine == old:
                kind, chosen = "theirs", yours
            elif yours == old or mine == yours:
                kind, chosen = ("ours" if yours == old else "both"), mine
            else:
                kind, chosen = "conflict", None
            if chosen is not None:
                out += chosen
                regions.append((kind, len(chosen)))
            else:
                conflicts += 1
                block = [f"<<<<<<< {ours_label}"] + mine
                if show_base:
                    block += ["||||||| base"] + old
                block += ["======="] + yours + [f">>>>>>> {theirs_label}"]
                out += block
                regions.append(("conflict", len(block)))
        if si < len(b):
            out.append(b[si])
            if regions and regions[-1][0] == "same":
                regions[-1] = ("same", regions[-1][1] + 1)
            else:
                regions.append(("same", 1))
        i, j, k = si + 1, sj + 1, sk + 1
    if strict and conflicts:
        raise MergeConflict(conflicts)
    newline = ours.newline if ours.newline != base.newline else theirs.newline
    return MergeResult(Text(out, newline), conflicts, regions)


def merge_text(base, ours, theirs, **options):
    """Shortcut: the merged text as a string."""
    return str(merge3(base, ours, theirs, **options).text)


def conflict_count(text):
    """Number of ``<<<<<<<`` conflict openings in a merged text (string or :class:`Text`)."""
    return sum(1 for line in Text.parse(text).lines if line.startswith("<<<<<<< "))
