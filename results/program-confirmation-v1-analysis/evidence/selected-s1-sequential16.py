import sys
import copy

def solve(n, k, edges):
    """
    Solve graph coloring for an undirected graph.
    n     : number of vertices (0 .. n-1)
    k     : number of colors (3 or 4)
    edges : list of [u, v] pairs, 0‑based vertex indices
    Returns a dict with a valid coloring or raises an exception if impossible.
    """
    # Build adjacency bit‑masks; we keep the original list untouched.
    adj = [0] * n
    for u, v in edges:
        adj[u] |= 1 << v
        adj[v] |= 1 << u

    # Order vertices by degree descending (largest first) – improves pruning.
    order = sorted(range(n), key=lambda x: adj[x], reverse=True)

    # backtracking state
    assignment = [-1] * n          # color of each vertex (in original index)
    # we will assign colors according to 'order', but store by original index.

    # Helper: check whether vertex `v` (original index) can receive `col`
    # given the already assigned vertices.
    def safe(v, col):
        # iterate over neighbors that are already assigned
        mask = adj[v]
        # we only need to test neighbors that appear before v in the ordering.
        # Since order is static, we can test by checking assignment of those neighbors.
        # Simple loop is fast enough for n <= 64.
        for u in range(n):
            if (mask >> u) & 1 and assignment[u] == col:
                return False
        return True

    # Recursive DFS
    def dfs(pos):
        """pos is the index in `order` we are about to assign."""
        if pos == n:
            return True
        v = order[pos]
        # try each color 0 .. k-1
        for col in range(k):
            if safe(v, col):
                assignment[v] = col
                if dfs(pos + 1):
                    return True
                assignment[v] = -1
        return False

    if not dfs(0):
        raise ValueError("No valid coloring exists for the given parameters.")

    # Build result in vertex order 0..n-1
    result = {"assignment": [assignment[i] for i in range(n)]}
    return result


# ----------------------------------------------------------------------
# Boiler‑plate to allow running from command line (not required by the task,
# but useful for local testing).  The function signature matches the spec.
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Minimal argument parsing: first arg = n, second = k, remaining = edges.
    # Edges are given as "u,v,u,v,..." – this matches the auto‑generated tester.
    if len(sys.argv) < 3:
        print("Usage: python solver.py <n> <k> [u1,v1 u2,v2 ...]", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])
    k = int(sys.argv[2])
    edge_strs = sys.argv[3].split() if len(sys.argv) > 3 else []
    edges = []
    for s in edge_strs:
        u_str, v_str = s.split(",")
        edges.append([int(u_str), int(v_str)])
    try:
        sol = solve(n, k, edges)
        print(sol)
    except ValueError as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(2)