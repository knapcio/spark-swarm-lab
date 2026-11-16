"""Line diff by longest common subsequence.

``opcodes(a, b)`` returns the edit script that turns sequence ``a`` into
sequence ``b`` as ``(tag, i1, i2, j1, j2)`` tuples, meaning ``a[i1:i2]``
becomes ``b[j1:j2]``.  Tags are ``equal``, ``delete``, ``insert`` and
``replace`` (deleted lines directly followed by inserted lines).  The
opcodes cover both sequences without gaps, in order.

Common leading and trailing lines are always matched.  When several longest
common subsequences exist, the script is the one found by walking both
sequences from the start: equal lines are matched at once, otherwise a
line of ``a`` is deleted when that still allows a longest subsequence, and
only then a line of ``b`` is inserted.  For ``a = x y`` and ``b = y x`` the
script deletes ``x``, keeps ``y`` and inserts ``x``.
"""


def _common_prefix(a, b):
    n = 0
    limit = min(len(a), len(b))
    while n < limit and a[n] == b[n]:
        n += 1
    return n


def _common_suffix(a, b, prefix):
    n = 0
    limit = min(len(a), len(b)) - prefix
    while n < limit and a[len(a) - 1 - n] == b[len(b) - 1 - n]:
        n += 1
    return n


def lcs_lengths(a, b):
    """Table ``t`` with ``t[i][j]`` = length of the longest common subsequence of ``a[i:]`` and ``b[j:]``."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        row, below = rows[i], rows[i + 1]
        for j in range(len(b) - 1, -1, -1):
            if a[i] == b[j]:
                row[j] = below[j + 1] + 1
            else:
                row[j] = max(below[j], row[j + 1])
    return rows


def matches(a, b):
    """Matched index pairs ``[(i, j), ...]`` of the longest common subsequence, in increasing order."""
    a, b = list(a), list(b)
    prefix = _common_prefix(a, b)
    suffix = _common_suffix(a, b, prefix)
    pairs = [(n, n) for n in range(prefix)]
    mid_a = a[prefix:len(a) - suffix]
    mid_b = b[prefix:len(b) - suffix]
    table = lcs_lengths(mid_a, mid_b)
    i = j = 0
    while i < len(mid_a) and j < len(mid_b):
        if mid_a[i] == mid_b[j]:
            pairs.append((prefix + i, prefix + j))
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    pairs += [(len(a) - suffix + n, len(b) - suffix + n) for n in range(suffix)]
    return pairs


def opcodes(a, b):
    """Edit script turning ``a`` into ``b`` (see the module docstring)."""
    a, b = list(a), list(b)
    codes = []
    i = j = 0
    for mi, mj in matches(a, b) + [(len(a), len(b))]:
        if i < mi and j < mj:
            codes.append(("replace", i, mi, j, mj))
        elif i < mi:
            codes.append(("delete", i, mi, j, j))
        elif j < mj:
            codes.append(("insert", i, i, j, mj))
        if mi < len(a) and mj < len(b):
            if codes and codes[-1][0] == "equal" and codes[-1][2] == mi and codes[-1][4] == mj:
                last = codes.pop()
                codes.append(("equal", last[1], mi + 1, last[3], mj + 1))
            else:
                codes.append(("equal", mi, mi + 1, mj, mj + 1))
        i, j = mi + 1, mj + 1
    return codes


def similarity(a, b):
    """``2 * M / (len(a) + len(b))`` rounded to 4 places, M = common lines; 1.0 for two empty sequences."""
    total = len(a) + len(b)
    if total == 0:
        return 1.0
    return round(2 * len(matches(a, b)) / total, 4)


def edit_distance(a, b):
    """Number of deleted plus inserted lines in the edit script."""
    return len(a) + len(b) - 2 * len(matches(a, b))
