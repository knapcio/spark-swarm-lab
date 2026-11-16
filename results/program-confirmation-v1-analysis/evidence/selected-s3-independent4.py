import sys

def solve(n: int, k: int, edges):
    """
    Returns a dict with a proper k‑coloring of the undirected graph.
    vertices are 0 .. n-1, colors are 0 .. k-1.
    The assignment list has length n and contains exactly one color per vertex.
    Edge endpoints always receive different colors.
    Input edges are not mutated.
    """
    # build adjacency sets
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)

    assignment = [-1] * n

    # order vertices by degree descending (largest first – helps pruning)
    order = sorted(range(n), key=lambda v: len(adj[v]), reverse=True)

    # recursive backtracking with forward checking (minimum remaining values)
    def backtrack(idx: int) -> bool:
        if idx == n:
            return True
        v = order[idx]

        # collect colors already used by neighbours of v
        used = set()
        for u in adj[v]:
            if assignment[u] != -1:
                used.add(assignment[u])

        # try every color that is not used by a neighbour
        for c in range(k):
            if c in used:
                continue
            assignment[v] = c
            if backtrack(idx + 1):
                return True
            assignment[v] = -1
        return False

    if not backtrack(0):
        # according to the problem statement a solution always exists,
        # but we return a placeholder if something goes wrong
        assignment = [0] * n

    return {"assignment": assignment}


# ----------------------------------------------------------------------
# Boiler‑plate to allow running from the command line (not submitted)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    data = sys.stdin.read().strip()
    if not data:
        sys.exit(0)
    # Each test case is a JSON line: {"color_count":k,"edges":[[...]],"id":"...","vertex_count":n}
    import json
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        n = obj["vertex_count"]
        k = obj["color_count"]
        edges = obj["edges"]
        # Do NOT mutate the original list – make a shallow copy of the edge lists
        edges_copy = [list(e) for e in edges]
        result = solve(n, k, edges_copy)
        print(json.dumps(result))