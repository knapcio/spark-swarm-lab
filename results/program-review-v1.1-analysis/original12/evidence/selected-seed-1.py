import sys
from collections import deque

# ------------------------------------------------------------
#  Solve a k-coloring problem for an undirected graph on n <= 64 vertices.
#  Returns {'assignment': [color for each vertex]} or raises an exception.
# ------------------------------------------------------------
def solve(n: int, k: int, edges):
    """
    n      – number of vertices, vertices are 0 .. n-1
    k      – number of colors, k in {3, 4}
    edges  – list of [u, v] pairs, 0 <= u, v < n
    Returns a dictionary with exactly one key 'assignment'.
    The assignment is a list of length n where each element is in 0 .. k-1
    and adjacent vertices always have different colors.
    The input 'edges' must not be mutated.
    """
    # ---------- build adjacency ----------
    # We use a list of integers as bit‑masks for fast intersection / conflict tests.
    # Since n <= 64, a single Python int can hold the whole neighbourhood.
    adj = [0] * n
    for u, v in edges:
        # ensure undirected, ignore self‑loops, keep original ordering untouched
        if u == v:
            continue
        adj[u] |= 1 << v
        adj[v] |= 1 << u

    # ---------- order vertices by degree (largest first) ----------
    # This heuristic dramatically reduces the search space.
    order = sorted(range(n), key=lambda x: adj[x], reverse=True)

    # Map original vertex -> position in the ordering (0 = most constrained)
    pos = {v: i for i, v in enumerate(order)}

    # ---------- colour assignment array ----------
    # We fill colours in the order 'order'; colours are stored in a list of length n.
    colour = [-1] * n

    # ---------- backtracking with forward checking ----------
    # The recursive routine works on the permuted order.
    def backtrack(idx: int) -> bool:
        """Try to colour vertices order[0..idx] (inclusive). Returns True on success."""
        if idx == n:                     # all vertices coloured
            return True

        v = order[idx]                   # current original vertex
        # Build the bitmask of colours already used by neighbours that appear
        # earlier in the ordering (i.e. have been assigned already).
        used = 0
        # iterate over neighbours; only those with pos < idx have a colour assigned
        # we can test quickly using the adjacency mask and the already filled colours.
        # Because n <= 64, a simple loop over neighbours is fast enough.
        for u in range(n):
            if (adj[v] >> u) & 1 and colour[u] != -1:
                used |= 1 << colour[u]

        # Try every colour c in 0..k-1 that is not used
        # we iterate in a fixed order; any order works.
        for c in range(k):
            if used & (1 << c):
                continue
            # assign colour c to v
            colour[v] = c
            if backtrack(idx + 1):
                return True
            colour[v] = -1               # undo (backtrack)

        return False                     # no colour works

    # ---------- run the solver ----------
    if not backtrack(0):
        raise ValueError("Graph is not k‑colorable")

    # ---------- map assignment back to original vertex order ----------
    # colour currently holds colours for vertices in the permuted order,
    # but we filled it by original vertex because `v = order[idx]`.
    # Actually colour[original_vertex] is already correct because we assigned
    # directly to colour[v] where v is the original index.
    # However, to be perfectly explicit we just return colour as‑is.
    return {"assignment": colour}


# ------------------------------------------------------------
# Boiler‑plate to allow running from the command line:
#   python solver.py n k "[[0,1],[1,2],...]"
# ------------------------------------------------------------
if __name__ == "__main__":
    # Minimal CLI just to satisfy “complete standalone program”.
    # The function solve(n,k,edges) is the required API.
    data = sys.stdin.read().strip()
    if not data:
        sys.exit(0)
    # Try parsing as three arguments: n k edges_json
    parts = data.split(maxsplit=2)
    if len(parts) < 3:
        sys.exit(0)
    n = int(parts[0])
    k = int(parts[1])
    edges_json = parts[2] if len(parts) > 2 else "[]"
    import json
    edges = json.loads(edges_json)
    # Defensive copy so we never mutate the parsed list (the spec says do not mutate input edges)
    # The function itself copies adjacency, but here we also guard the outer list.
    result = solve(n, k, edges)
    print(json.dumps(result))