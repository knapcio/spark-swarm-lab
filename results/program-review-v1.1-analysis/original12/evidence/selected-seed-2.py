import sys
from functools import lru_cache
from typing import List, Dict

# ------------------------------------------------------------
# solve(n, k, edges) – graph coloring with exactly k colors
# ------------------------------------------------------------
def solve(n: int, k: int, edges) -> Dict[str, List[int]]:
    """
    Return a dict {'assignment': list[int]} where assignment[i] is a color
    in 0..k-1 and every edge has distinct endpoint colors.
    The graph has n <= 64 vertices and k in {3,4}.
    Input edges must not be mutated.
    """
    # --------------------------------------------------------
    # Build adjacency bit‑masks (undirected, no self‑loops)
    # --------------------------------------------------------
    adj = [0] * n
    for u, v in edges:
        adj[u] |= 1 << v
        adj[v] |= 1 << u

    # --------------------------------------------------------
    # Order vertices by static MRV: degree descending
    # --------------------------------------------------------
    order = sorted(range(n), key=lambda i: adj[i].bit_count(), reverse=True)

    # colour of each vertex in the original indexing
    color = [-1] * n

    # For each vertex, a bitmask of colours already used by its
    # already‑coloured neighbours.
    used_mask = [0] * n

    # --------------------------------------------------------
    # Depth‑first search with forward checking
    # --------------------------------------------------------
    def dfs(pos: int) -> bool:
        """Colour vertices order[pos:]."""
        if pos == n:
            return True                     # all vertices coloured

        v = order[pos]

        # Allowed colours for v are those not forbidden by already
        # coloured neighbours.
        forbidden = used_mask[v]

        # Try each colour that is not forbidden
        for c in range(k):
            if (forbidden >> c) & 1:
                continue

            # Assign colour c to v
            color[v] = c

            # Collect neighbours of v (only those that exist – n <= 64)
            nb = adj[v]

            # Save old masks for all neighbours so we can restore later
            # We iterate over set bits of nb to avoid touching every index.
            # Because n <= 64 we may also just iterate range(n) but we must
            # ensure the old list size matches the number of neighbours we
            # will restore.  Using set‑bit iteration is safest.
            neighbours = []
            # extract set bits
            tmp = nb
            while tmp:
                lsb = tmp & -tmp                # lowest set bit
                u = (lsb.bit_length() - 1)      # vertex index
                neighbours.append(u)
                tmp ^= lsb

            old = [used_mask[u] for u in neighbours]

            # Propagate the new colour to all neighbours
            for u in neighbours:
                used_mask[u] |= 1 << c

            # Recurse
            if dfs(pos + 1):
                return True

            # Backtrack: restore masks and colour
            for i, u in enumerate(neighbours):
                used_mask[u] = old[i]
            color[v] = -1

        return False

    # --------------------------------------------------------
    # Run the solver
    # --------------------------------------------------------
    if dfs(0):
        # Build assignment in original vertex order 0..n-1
        assignment = [0] * n
        for i, v in enumerate(order):
            assignment[v] = color[v]
        return {"assignment": assignment}
    else:
        # The problem guarantees a valid coloring exists, but return a
        # sensible fallback just in case.
        return {"assignment": [-1] * n}


# ------------------------------------------------------------
# Boiler‑plate for standalone execution (optional)
# ------------------------------------------------------------
if __name__ == "__main__":
    # Simple CLI: python solve.py n k "[[0,1],[1,2]]"
    if len(sys.argv) == 4:
        n = int(sys.argv[1])
        k = int(sys.argv[2])
        edges = eval(sys.argv[3])          # safe here – we control input
        print(solve(n, k, edges))
    else:
        # Demo with the first development graph
        dev = {
            "color_count": 3,
            "edges": [[0,7],[0,8],[0,12],[0,15],[0,22],[0,23],[1,2],[1,11],[1,19],[2,17],[2,19],[3,9],[3,10],[4,16],[4,20],[4,21],[5,6],[5,9],[5,13],[5,15],[6,17],[6,20],[7,16],[7,19],[8,12],[8,14],[8,16],[8,19],[9,12],[10,13],[10,14],[14,18],[17,19],[18,19],[18,20],[18,21],[18,23],[19,20]],
            "vertex_count": 24
        }
        print(solve(dev["vertex_count"], dev["color_count"], dev["edges"]))