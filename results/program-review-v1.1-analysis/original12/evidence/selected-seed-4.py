import sys
from collections import deque

def solve(n: int, k: int, edges: list[list[int]]) -> dict:
    # Build adjacency sets; we never mutate the input `edges` list.
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)

    # Order vertices by decreasing degree (static heuristic).
    order = sorted(range(n), key=lambda v: len(adj[v]), reverse=True)

    assignment = [-1] * n  # -1 means uncolored

    # Recursive backtracking with forward checking / MRG.
    def backtrack(idx: int) -> bool:
        if idx == n:
            return True

        v = order[idx]

        # Try each color in 0..k-1.
        for c in range(k):
            # Check if color c is valid for v given current assignment.
            ok = True
            for u in adj[v]:
                if assignment[u] == c:
                    ok = False
                    break
            if not ok:
                continue

            # Forward checking: ensure every uncolored neighbor still has
            # at least one admissible color left.
            # We only need to examine colors that are still possible.
            saved = {}
            feasible = True
            for u in adj[v]:
                if assignment[u] != -1:
                    continue
                # count how many colors remain for u after assigning c to v
                # We can just count colors not used by already colored neighbors.
                # Since k is tiny (3 or 4) we can just test.
                # But we need to ensure *all* uncolored neighbors survive.
                # Simple check: after assigning c, does u still have >=1 color?
                # We'll compute the set of forbidden colors for u.
                forbidden = set()
                for w in adj[u]:
                    if assignment[w] != -1:
                        forbidden.add(assignment[w])
                # If v is already colored in this trial, add c.
                # (v is currently being assigned, so its color is c.)
                remaining = k - len(forbidden)
                # But we must also consider that v's color c is now forbidden for u.
                # The above already includes all currently colored neighbors; we just added c implicitly?
                # Actually forbidden only contains already assigned neighbors. We need to add c.
                # Let's redo more cleanly:
                pass  # placeholder, will rewrite below

            # The above forward-checking block was overly complicated; we'll use a
            # simpler yet effective check: after assigning c to v, verify that every
            # uncolored neighbor still has at least one color available.
            # Since k <= 4, we can just compute available colors per neighbor.

            # Re-do the feasibility test cleanly:
            feasible = True
            for u in adj[v]:
                if assignment[u] != -1:
                    continue
                # compute colors already used by u's colored neighbors
                used = set()
                for w in adj[u]:
                    if assignment[w] != -1:
                        used.add(assignment[w])
                # c is now also forbidden for u because u is adjacent to v
                if c not in used:
                    used.add(c)
                # available colors for u
                avail = k - len(used)
                if avail == 0:
                    feasible = False
                    break
                # store for potential restoration (not needed if we just revert assignment)
                # but we must not permanently mutate anything else.
            if not feasible:
                continue

            # Assign color c to v
            assignment[v] = c

            if backtrack(idx + 1):
                return True

            # Undo assignment (backtrack)
            assignment[v] = -1

        return False

    # Run the solver
    if not backtrack(0):
        # According to the problem statement the graphs are colorable,
        # but fallback: return empty assignment (should not happen).
        assignment = [0] * n

    return {"assignment": assignment}


# ----------------------------------------------------------------------
# Boilerplate to allow running as a script with JSON arguments (optional).
# The function signature must remain solve(n,k,edges) per the specification.
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Minimal CLI support: python solve.py n k '[[...]]'
    # Not required by the statement but handy for local testing.
    import json
    if len(sys.argv) == 4:
        n = int(sys.argv[1])
        k = int(sys.argv[2])
        edges = json.loads(sys.argv[3])
        result = solve(n, k, edges)
        print(json.dumps(result))
    else:
        print("Usage: python solve.py <n> <k> '<edges>'", file=sys.stderr)