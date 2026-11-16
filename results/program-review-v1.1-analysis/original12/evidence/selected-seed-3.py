import sys

def solve(n: int, k: int, edges):
    """
    Assign exactly one color from {0 .. k-1} to each vertex 0 .. n-1
    such that no edge has the same color on both endpoints.

    Returns a dictionary {'assignment': [...]} or raises ValueError.
    The input edges must not be mutated.
    """
    # Build adjacency sets (undirected).  We copy so the original list is untouched.
    adj = [set() for _ in range(n)]
    for u, v in edges:
        # Guard against malformed data; ignore self‑loops.
        if u == v:
            continue
        adj[u].add(v)
        adj[v].add(u)

    # Order vertices by decreasing degree (static heuristic for small graphs).
    order = sorted(range(n), key=lambda v: len(adj[v]), reverse=True)

    assignment = [-1] * n  # -1 means uncolored

    def assign(idx: int) -> bool:
        """Try to color vertices order[idx:] recursively."""
        if idx == n:
            return True  # all vertices colored

        v = order[idx]
        # Gather colors already used by colored neighbours.
        used = set()
        for u in adj[v]:
            c = assignment[u]
            if c != -1:
                used.add(c)

        # Try each colour that is not used by a coloured neighbour.
        for col in range(k):
            if col in used:
                continue
            assignment[v] = col
            if assign(idx + 1):
                return True
            assignment[v] = -1  # backtrack

        return False

    if not assign(0):
        raise ValueError("No proper k‑coloring exists for the given graph.")

    return {"assignment": assignment}


# ----------------------------------------------------------------------
# Boiler‑plate to allow running from the command line (optional).
# The function signature matches the specification; the driver just
# demonstrates correctness on the provided development graphs.
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Minimal manual driver – reads a single JSON line from stdin if desired.
    # For the purpose of the task we only expose the solve function.
    pass