import sys
from collections import defaultdict

# ------------------------------------------------------------
# Backtracking solver for graph coloring with k colours (k in {3,4})
# ------------------------------------------------------------
def solve(n: int, k: int, edges) -> dict:
    """
    Return a valid colouring as {'assignment': [c0, c1, ..., c_{n-1}]}
    where each ci is in 0 .. k-1 and no edge has equal colours on its ends.
    The input edges list is not mutated.
    """
    # Build adjacency sets (undirected)
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)

    # Order vertices by descending degree (static MRV heuristic)
    order = sorted(range(n), key=lambda v: len(adj[v]), reverse=True)

    assignment = [-1] * n          # final colour of each vertex
    domain = [set(range(k)) for _ in range(n)]  # remaining colours per vertex

    # --------------------------------------------------------
    def backtrack(idx: int) -> bool:
        """Try to colour vertices order[idx:] returning True on success."""
        if idx == n:
            return True

        v = order[idx]

        # Choose colours that are still legal for v
        # (a colour is illegal if a neighbour already has it)
        legal = set()
        for c in domain[v]:
            ok = True
            for nb in adj[v]:
                if assignment[nb] == c:
                    ok = False
                    break
            if ok:
                legal.add(c)

        if not legal:
            return False

        # Try each legal colour; keep domains for possible later undo,
        # but for simplicity and speed we just assign and rely on
        # the loop to restore domain state via copy-on-write.
        for c in legal:
            assignment[v] = c

            # Save domain of neighbours that lose colour c
            lost = []
            for nb in adj[v]:
                if c in domain[nb]:
                    domain[nb].discard(c)
                    lost.append(nb)

            # Recurse
            if backtrack(idx + 1):
                return True

            # Undo changes
            for nb in lost:
                domain[nb].add(c)
            assignment[v] = -1

        return False

    # Run solver
    if not backtrack(0):
        # According to the problem statement a solution always exists
        # for the given constraints; raise a clear error otherwise.
        raise RuntimeError("No valid colouring found")

    # Build result mapping original vertex index -> colour
    result = [assignment[i] for i in range(n)]
    return {"assignment": result}


# ------------------------------------------------------------
# Boiler‑plate to allow running from command line (optional)
# ------------------------------------------------------------
if __name__ == "__main__":
    # Minimal CLI just to demonstrate the function; not used by the
    # automated test harness.  Format: n k u1 v1 u2 v2 ...
    data = list(map(int, sys.stdin.read().split()))
    if not data:
        sys.exit(0)
    n, k = data[0], data[1]
    m = (len(data) - 2) // 2
    edges = [(data[2 + 2 * i], data[2 + 2 * i + 1]) for i in range(m)]
    print(solve(n, k, edges))  # prints the dict