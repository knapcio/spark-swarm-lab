import sys
import copy

def solve(n, k, edges):
    """
    Backtracking graph coloring solver for small graphs (n <= 64, k in {3,4}).

    Returns a dict with a single key 'assignment' mapping each vertex to an
    integer color in [0, k-1] such that adjacent vertices receive different
    colors.  The input ``edges`` list is never mutated.
    """
    # Build adjacency bit‑masks; each mask fits in a Python int (unlimited size).
    adj = [0] * n
    for u, v in edges:
        adj[u] |= 1 << v
        adj[v] |= 1 << u

    # Order vertices by degree descending – this usually prunes the search tree
    # earlier.  We keep the original indices to be able to map the assignment back.
    order = sorted(range(n), key=lambda v: adj[v], reverse=True)
    # Position of each original vertex in the ordering (0 = most constrained).
    pos = {v: i for i, v in enumerate(order)}

    # colour[c] = vertex (original index) assigned colour c, or -1 if unassigned.
    colour = [-1] * k
    # colour_of[v] = colour assigned to original vertex v, or -1.
    colour_of = [-1] * n

    # Depth‑first search over the ordered vertices.
    def dfs(idx: int) -> bool:
        """Try to colour vertex order[idx] and all later vertices."""
        if idx == n:
            return True  # all vertices coloured

        v = order[idx]

        # Try every colour 0 .. k-1
        for c in range(k):
            # Check whether any already‑coloured neighbour has colour c.
            # Neighbour test uses the bit‑mask of v restricted to already
            # processed vertices (those with position < idx).
            # We build a mask of coloured neighbours on the fly.
            ok = True
            # iterate over neighbours of v
            # Using while‑loop on bits is fast enough for n <= 64.
            neighbours = adj[v]
            # We only need to look at neighbours that are already assigned.
            # Those are exactly the vertices among {order[0..idx-1]} that are adjacent to v.
            # We can test assignment status via colour_of.
            # Simple loop over neighbours list (max degree <= n-1 <= 63) is fine.
            nb = neighbours
            while nb:
                # extract lowest set bit
                lsb = nb & -nb
                u = (lsb.bit_length() - 1)  # vertex index
                nb ^= lsb
                if colour_of[u] == c:
                    ok = False
                    break
            if not ok:
                continue

            # Assign colour c to v
            colour[c] = v
            colour_of[v] = c

            if dfs(idx + 1):
                return True

            # Backtrack
            colour[c] = -1
            colour_of[v] = -1

        return False

    # The problem guarantees a solution exists for the provided test data.
    # Run the solver; if for any reason it fails, return an empty assignment.
    if not dfs(0):
        return {"assignment": [-1] * n}

    # Build result in original vertex order 0 .. n-1
    assignment = [colour_of[v] for v in range(n)]
    return {"assignment": assignment}