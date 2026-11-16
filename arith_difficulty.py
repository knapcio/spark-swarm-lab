"""Exact difficulty statistics for countdown-style tasks (CPU, offline, task SELECTION only).

Never used by any agent at runtime. For every subset of the numbers, the set of values reachable
by combining exactly that subset (positive-integer intermediates, ordered - and /) and the number
of derivation trees reaching each value. Leftovers are allowed, so the minimal number of moves to
reach a target is (smallest subset that can make it) - 1.
"""
from functools import lru_cache

CAP = 1_000_000


def combine(a, b):
    """All legal results of a op b and b op a for one unordered pair of values."""
    out = [('+', a, b, a + b), ('*', a, b, a * b)]
    if a > b:
        out.append(('-', a, b, a - b))
    elif b > a:
        out.append(('-', b, a, b - a))
    if b and a % b == 0:
        out.append(('/', a, b, a // b))
    if a and b % a == 0 and a != b:
        out.append(('/', b, a, b // a))
    return [o for o in out if 0 < o[3] <= CAP]


def tables(numbers):
    """counts[mask] = {value: number of derivation trees using exactly that subset}."""
    n = len(numbers)
    counts = {}
    for mask in range(1, 1 << n):
        bits = [i for i in range(n) if mask >> i & 1]
        if len(bits) == 1:
            counts[mask] = {numbers[bits[0]]: 1}
            continue
        table = {}
        low = mask & -mask
        sub = (mask - 1) & mask
        while sub:
            if sub & low:  # each unordered split once: the part holding the lowest bit
                rest = mask ^ sub
                if rest:
                    for a, ca in counts[sub].items():
                        for b, cb in counts[rest].items():
                            for _, _, _, value in combine(a, b):
                                table[value] = table.get(value, 0) + ca * cb
            sub = (sub - 1) & mask
        counts[mask] = table
    return counts


def stats(numbers, target):
    numbers = list(numbers)
    counts = tables(numbers)
    best, derivations, subsets = None, 0, 0
    for mask, table in counts.items():
        size = bin(mask).count('1')
        if target in table and size >= 2:
            if best is None or size < best:
                best, derivations, subsets = size, 0, 0
            if size == best:
                derivations += table[target]
                subsets += 1
    total = sum(t.get(target, 0) for m, t in counts.items() if bin(m).count('1') >= 2)
    return dict(min_numbers=best, min_moves=None if best is None else best - 1,
                derivations_at_min=derivations, subsets_at_min=subsets, derivations_total=total)


def witness(numbers, target):
    """One move list (frozen harness index semantics) reaching target with the fewest numbers."""
    numbers = list(numbers)
    counts = tables(numbers)

    @lru_cache(maxsize=None)
    def build(mask, value):
        bits = [i for i in range(len(numbers)) if mask >> i & 1]
        if len(bits) == 1:
            return ('leaf', bits[0])
        low = mask & -mask
        sub = (mask - 1) & mask
        while sub:
            if sub & low and mask ^ sub:
                rest = mask ^ sub
                for a in counts[sub]:
                    for b in counts[rest]:
                        for op, x, y, result in combine(a, b):
                            if result == value:
                                if x == a and y == b:
                                    return (op, build(sub, a), build(rest, b))
                                return (op, build(rest, b), build(sub, a))
            sub = (sub - 1) & mask
        raise ValueError('no derivation')

    candidates = [(bin(m).count('1'), m) for m, t in counts.items() if target in t and bin(m).count('1') >= 2]
    if not candidates:
        return None
    tree = build(min(candidates)[1], target)
    state = [(v, i) for i, v in enumerate(numbers)]  # (value, original leaf index or None)
    moves = []

    produced = {}

    def emit_index(node):
        if node[0] == 'leaf':
            return next(k for k, (_, tag) in enumerate(state) if tag == node[1])
        return produced[id(node)]

    def run(node):
        if node[0] == 'leaf':
            return
        op, left, right = node
        run(left)
        run(right)
        li, ri = emit_index(left), emit_index(right)
        a, b = state[li][0], state[ri][0]
        value = {'+': a + b, '-': a - b, '*': a * b, '/': a // b}[op]
        moves.append(dict(i=li, j=ri, op=op))
        keep = [s for k, s in enumerate(state) if k not in (li, ri)]
        # Indices of earlier produced subtrees shift when items before them are removed.
        for key, index in list(produced.items()):
            produced[key] = index - sum(1 for k in (li, ri) if k < index)
        state[:] = keep + [(value, None)]
        produced[id(node)] = len(state) - 1

    run(tree)
    return moves
