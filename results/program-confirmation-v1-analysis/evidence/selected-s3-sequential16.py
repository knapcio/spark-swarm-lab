#!/usr/bin/env python3
"""
Graph k-coloring solver (k=3 or k=4).

solve(n, k, edges) -> dict with exactly {'assignment': [color0, ..., color_{n-1}]}
or raises an exception if the graph cannot be colored within limits.

Constraints:
    * vertices 0 .. n-1
    * colors 0 .. k-1
    * edge endpoints must have different colors
    * n <= 64
    * k in {3, 4}
    * edges are undirected; each edge appears once, endpoints differ
    * input edges must not be mutated
    * Python standard library only
    * each graph runs in a fresh process with 10 s and 256 MiB
"""

from __future__ import annotations
from typing import List, Dict, Any
import sys
import time


# ---------- small utilities ----------
def _build_adj(n: int, edges: List[List[int]]) -> List[List[int]]:
    """Return adjacency lists; does not modify *edges*."""
    adj: List[List[int]] = [[] for _ in range(n)]
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)
    return adj


def _order_vertices(adj: List[List[int]]) -> List[int]:
    """Heuristic ordering: largest degree first (static)."""
    return sorted(range(len(adj)), key=lambda v: len(adj[v]), reverse=True)


# ---------- backtracking engine ----------
def _solve_core(n: int, k: int, adj: List[List[int]]) -> List[int] | None:
    """
    Return a valid color assignment (list of length n, colors 0..k-1) or None.
    Uses forward checking + smallest-domain heuristic.
    """
    order = _order_vertices(adj)
    # domain[v] = set of still-allowed colors for v
    domain: List[set[int]] = [set(range(k)) for _ in range(n)]
    assignment: List[int | None] = [None] * n

    # forbid_count[v][c] = how many already-colored neighbours of v have color c
    forbid_count: List[List[int]] = [[0] * k for _ in range(n)]

    def _remove_color(v: int, c: int) -> bool:
        """Forcefully remove color c from v's domain. Returns True if domain becomes empty."""
        if c not in domain[v]:
            return False
        domain[v].remove(c)
        forbid_count[v][c] += 1
        return domain[v] == set()

    def _restore_color(v: int, c: int) -> None:
        """Undo _remove_color."""
        forbid_count[v][c] -= 1
        domain[v].add(c)

    def _assign(v: int, c: int) -> None:
        """Assign color c to vertex v (v must be unassigned)."""
        assignment[v] = c
        # propagate to unassigned neighbours
        for u in adj[v]:
            if assignment[u] is not None:
                continue
            _remove_color(u, c)

    def _unassign(v: int) -> None:
        """Revert assignment of v and restore domains."""
        c = assignment[v]
        assignment[v] = None
        for u in adj[v]:
            if assignment[u] is not None:
                continue
            _restore_color(u, c)

    def _select_unassigned() -> int | None:
        """Choose unassigned vertex with smallest domain (ties broken by degree)."""
        best = None
        best_size = k + 1
        for v in order:
            if assignment[v] is not None:
                continue
            d = len(domain[v])
            if d < best_size or (d == best_size and (best is None or len(adj[v]) > len(adj[best]))):
                best = v
                best_size = d
                if d == 1:
                    break
        return best

    def _dfs() -> bool:
        """Depth‑first search with forward checking."""
        v = _select_unassigned()
        if v is None:
            return True  # all vertices assigned

        # try colors; sorted for determinism, but we iterate over the current domain
        for c in sorted(domain[v]):
            # tentatively assign
            _assign(v, c)
            # check for empty domain immediately
            empty = False
            for u in adj[v]:
                if assignment[u] is None and domain[u] == set():
                    empty = True
                    break
            if not empty:
                if _dfs():
                    return True
            # backtrack
            _unassign(v)
        return False

    # Quick check: if any vertex has degree >= k and no color can be assigned without
    # conflict from already colored neighbours, we still let the solver handle it.
    if _dfs():
        return assignment  # type: ignore[return-value]
    return None


# ---------- public API ----------
def solve(n: int, k: int, edges: List[List[int]]) -> Dict[str, List[int]]:
    """
    Return exactly {'assignment': [color0, ..., color_{n-1}]} for a k‑colorable
    undirected graph.  Edges are not mutated.

    Raises:
        ValueError if the graph cannot be colored (should not happen for valid inputs
        provided in the test data).
    """
    if not (1 <= k <= 4 and n <= 64):
        raise ValueError("unsupported n or k")
    # ensure we work on a copy of the edge list so the caller's list is not mutated
    edges_copy = [list(e) for e in edges]
    adj = _build_adj(n, edges_copy)
    assignment = _solve_core(n, k, adj)
    if assignment is None:
        raise ValueError("graph cannot be k‑colored")
    # guarantee the returned list has exactly n ints (0..k-1)
    return {"assignment": assignment}


# ---------- tiny CLI for manual testing ----------
if __name__ == "__main__":
    # Minimal example: 3‑color a triangle
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # sample from the dev set
        n, k, dev_edges = 24, 3, [
            [0, 7], [0, 8], [0, 12], [0, 15], [0, 22], [0, 23],
            [1, 2], [1, 11], [1, 19], [2, 17], [2, 19],
            [3, 9], [3, 10], [4, 16], [4, 20], [4, 21],
            [5, 6], [5, 9], [5, 13], [5, 15], [6, 17], [6, 20],
            [7, 16], [7, 19], [8, 12], [8, 14], [8, 16], [8, 19],
            [9, 12], [10, 13], [10, 14], [14, 18], [17, 19],
            [18, 19], [18, 20], [18, 21], [18, 23], [19, 20]
        ]
        result = solve(n, k, dev_edges)
        print(result)
    else:
        print("Usage: python solver.py test")