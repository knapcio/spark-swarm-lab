```python
import sys
from collections import deque

# ---------- 2-SAT solver (iterative) ----------
def two_sat(n_vars, clauses):
    """
    n_vars: number of boolean variables (each variable x has two literals: 2*x and 2*x+1)
    clauses: list of (l1, l2) where each literal is an integer; positive means variable,
             negative means negation.  Each clause must have exactly two literals.
    Returns a satisfying assignment as a list of bools of length n_vars, or None if unsatisfiable.
    """
    N = 2 * n_vars
    # adjacency list for implication graph
    adj = [[] for _ in range(N)]

    def add_impl(u, v):
        adj[u].append(v)

    for a, b in clauses:
        # (a ∨ b)  →  (~a → b)  and  (~b → a)
        add_impl(N - 1 - a, b)
        add_impl(N - 1 - b, a)

    # Kosaraju iterative
    visited = [False] * N
    order = []

    for start in range(N):
        if visited[start]:
            continue
        # dfs1
        stack = [(start, 0)]  # (node, next_child_index)
        while stack:
            v, idx = stack[-1]
            if idx == 0:
                # first time we see v
                pass
            if idx < len(adj[v]):
                w = adj[v][idx]
                stack[-1] = (v, idx + 1)
                if not visited[w]:
                    visited[w] = True
                    stack.append((w, 0))
            else:
                # all children processed
                order.append(v)
                stack.pop()

    # reverse graph
    radj = [[] for _ in range(N)]
    for u in range(N):
        for v in adj[u]:
            radj[v].append(u)

    comp = [-1] * N
    comp_id = 0
    # process in reverse finishing order
    for v in reversed(order):
        if comp[v] != -1:
            continue
        # dfs2 on reverse graph
        stack = [v]
        comp[v] = comp_id
        while stack:
            u = stack.pop()
            for w in radj[u]:
                if comp[w] == -1:
                    comp[w] = comp_id
                    stack.append(w)
        comp_id += 1

    # check contradiction
    assignment = [False] * n_vars
    for i in range(n_vars):
        if comp[2 * i] == comp[2 * i + 1]:
            return None  # unsatisfiable
        assignment[i] = comp[2 * i] > comp[2 * i + 1]
    return assignment


# ---------- main solver ----------
def solve(n, k, edges):
    """
    n      : number of vertices (0 .. n-1)
    k      : number of colors (3 or 4)
    edges  : list of [u, v] (undirected, no self-loops)

    Returns a dict {'assignment': list of length n, each entry in 0..k-1}
    such that no edge has both endpoints with the same color.
    The input edges must not be mutated.
    """
    # Build adjacency sets for quick conflict checks
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)

    # ----- k = 3 -----
    if k == 3:
        # We'll use 2-SAT per vertex: choose one of three colors.
        # For each vertex i we have three booleans p_i, q_i.
        # Color mapping:
        #   0 -> (p=False, q=False)
        #   1 -> (p=True,  q=False)
        #   2 -> (p=False, q=True)
        #   (the third combination p=True,q=True is unused)
        # Conflict: if two vertices share a color, we forbid the corresponding
        #            literal pair.
        # Clauses are of the form (¬l1 ∨ ¬l2)  i.e. at most one of the two literals true.
        # We'll generate all binary clauses needed.

        N_vars = 2 * n  # p_i and q_i for each vertex i (i from 0..n-1)
        sat_clauses = []  # list of (l1, l2)  each literal in [0, 2*N_vars-1]

        def lit(p_idx, var_idx, pos):
            """literal index: var_idx = 2*i + (1 if p else 0) ... we use a flat scheme.
               Let's define:
                 variable i (0..n-1) has two boolean vars:
                    p_i  -> variable number 2*i
                    q_i  -> variable number 2*i+1
                 literal 2*i      : p_i true
                 literal 2*i+1    : q_i true
                 negation          : 2*i+1 for p, 2*i for q
               We'll keep it simple: assign each boolean a unique id 0..2*n-1.
               p_i   = id 2*i
               q_i   = id 2*i+1
               ¬p_i  = 2*i+1
               ¬q_i  = 2*i
            """
            # We'll just use the literal number directly as the identifier.
            # The solver expects literals 0..2*N-1 where even = positive, odd = negative of var.
            # To avoid confusion, we will map our own literals to the solver's format later.
            # For now, return an integer that we'll convert.
            # We'll use a global mapping later; here just return a unique int.
            pass

        # Simpler approach: use classic reduction to 2-SAT.
        # For each vertex i we have three colors 0,1,2.
        # We'll create two boolean variables per vertex: x_i, y_i.
        # Assignment:
        #   color 0 : x_i = False, y_i = False
        #   color 1 : x_i = True,  y_i = False
        #   color 2 : x_i = False, y_i = True
        # (x_i=True, y_i=True never occurs)
        # For each vertex we enforce ¬(x_i ∧ y_i) i.e. clause (¬x_i ∨ ¬y_i).

        # Conflict clauses:
        # If two vertices u,v cannot share color c, we add clause that forbids the
        # corresponding literal pair.
        # For color 0: ¬(¬x_u ∧ ¬y_u ∧ ¬x_v ∧ ¬y_v) ... actually we need at most one vertex gets color 0 in any conflict.
        # Better: for each edge (u,v) and each color c in {0,1,2}, add clause that
        # ¬(u has color c) ∨ ¬(v has color c).

        # u has color 0 : (¬x_u ∨ ¬y_u)  -- wait we already have clause (¬x_u ∨ ¬y_u) per vertex.
        # Actually we want exactly one color per vertex. We'll enforce:
        #   (x_u ∨ y_u)   at least one of x_u,y_u true? No, color 0 is both false.
        # Let's redesign mapping to make exactly-one easier.

        # New mapping (more standard):
        #   color 0 : p_i = False, q_i = False
        #   color 1 : p_i = True,  q_i = False
        #   color 2 : p_i = False, q_i = True
        #   (p_i=True, q_i=True excluded by clause (¬p_i ∨ ¬q_i) )
        # Exactly-one per vertex is enforced by (¬p_i ∨ ¬q_i) plus we don't care about the
        # (True,True) case because it will never be chosen if we forbid it.

        # For an edge (u,v) and color c:
        #   if c == 0:  we cannot have (¬p_u ∧ ¬q_u) ∧ (¬p_v ∧ ¬q_v)
        #               i.e. clause (p_u ∨ q_u ∨ p_v ∨ q_v) – not 2-CNF directly.
        # But we can convert using auxiliary variables or use pairwise exclusion.
        # Simpler: for each edge (u,v), for each color c, add two 2-clauses that forbid
        # the specific literals.
        #   color 0:  (p_u ∨ p_v)  and  (p_u ∨ q_v)  and  (q_u ∨ p_v)  and  (q_u ∨ q_v)
        #           Wait: if we ensure that at least one of p,q is true for each vertex? No.
        # Let's step back.

        # Standard reduction for graph 3-coloring to 2-SAT does NOT work in general because
        # 3-coloring is NP-com