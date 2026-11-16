import sys
from typing import List, Dict, Set, Tuple

# --------------------------------------------------------------
# solve(n, k, edges) – graph coloring with k colours, n ≤ 64
# Returns exactly {'assignment': [one integer color per vertex]}.
# Edge endpoints must differ (proper coloring). Input edges are not mutated.
# --------------------------------------------------------------
def solve(n: int, k: int, edges) -> Dict[str, List[int]]:
    # ------------------------------------------------------------------
    # Build adjacency bit‑masks: adj[v] has bit u set iff (u,v) is an edge.
    # ------------------------------------------------------------------
    adj = [0] * n
    for u, v in edges:
        adj[u] |= 1 << v
        adj[v] |= 1 << u

    # ------------------------------------------------------------------
    # Heuristic ordering: vertices with the highest degree first (MRV).
    # ------------------------------------------------------------------
    order = sorted(range(n), key=lambda v: adj[v].bit_count(), reverse=True)

    assignment = [-1] * n  # colour of each vertex, -1 = unassigned

    # ------------------------------------------------------------------
    # legal(v, c) – check if colour c can be given to vertex v given
    # the current partial assignment.  We only need to compare against
    # already‑assigned neighbours.
    # ------------------------------------------------------------------
    def legal(v: int, c: int) -> bool:
        neighbours = adj[v]
        # iterate over set bits of neighbours
        while neighbours:
            # isolate lowest set bit
            lsb = neighbours & -neighbours
            nb = (lsb.bit_length() - 1)  # index of that neighbour
            neighbours ^= lsb  # clear the bit
            if assignment[nb] == c:
                return False
        return True

    # ------------------------------------------------------------------
    # backtrack(pos) – assign vertices in the fixed order.
    # Returns True when a full valid coloring is found.
    # ------------------------------------------------------------------
    def backtrack(pos: int) -> bool:
        if pos == n:
            return True

        v = order[pos]

        # try colours 0 .. k-1.  We iterate in natural order; this is
        # deterministic and fast enough for n ≤ 64, k ∈ {3,4}.
        for c in range(k):
            if legal(v, c):
                assignment[v] = c
                if backtrack(pos + 1):
                    return True
                assignment[v] = -1
        return False

    # start search
    if not backtrack(0):
        # According to the problem statement a valid assignment always
        # exists for the provided graphs, but fallback to -1 just in case.
        return {"assignment": [-1] * n}

    return {"assignment": assignment}


# ----------------------------------------------------------------------
# Boiler‑plate to allow running from the command line (optional).
# Reads stdin in the format: n k u1 v1 u2 v2 ...
# ----------------------------------------------------------------------
if __name__ == "__main__":
    data = sys.stdin.read().strip().split()
    if not data:
        sys.exit(0)
    n = int(data[0])
    k = int(data[1])
    # remaining tokens are edge endpoints; they come in pairs
    pairs = list(map(int, data[2:]))
    edges: List[Tuple[int, int]] = [(pairs[i], pairs[i + 1]) for i in range(0, len(pairs), 2)]
    result = solve(n, k, edges)
    print(result)