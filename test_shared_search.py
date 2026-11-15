"""Offline policy checks using the existing verifier and a fake model client."""
from fractions import Fraction as F
import argparse
import threading
import unittest
from unittest.mock import patch

import harness as h
from shared_search import run_rounds


class Log:
    def __init__(self):
        self.rows = []
        self.lock = threading.Lock()

    def emit(self, kind, **fields):
        with self.lock:
            row = dict(type=kind, **fields)
            self.rows.append(row)
            return row


class FakeClient:
    def __init__(self, events, action, initial_size, max_calls=1000):
        self.events, self.action, self.initial_size = events, action, initial_size
        self.budget = h.Budget(max_calls, 10000)
        self.calls = []
        self.lock = threading.Lock()

    def call(self, agent, stage, prompt, **context):
        with self.events.lock:
            node = next(r for r in self.events.rows
                        if r["type"] == "node" and r["node_id"] == context["node_id"])
        state = tuple(map(F, node["state"]))
        depth = self.initial_size - len(state)
        with self.lock:
            self.calls.append((agent, depth, state))
        if not self.budget.reserve(4):
            return None
        self.budget.settle(4, 1)
        return self.action(agent, state, depth)


class RoundSearchTests(unittest.TestCase):
    def run_policy(self, shared, numbers=(2, 3, 7, 11), target=999, agents=6,
                   rounds=2, action=None, max_calls=1000, seed=7):
        events = Log()
        args = argparse.Namespace(agents=agents, rounds=rounds, target=target,
                                  seed=seed, allow_fractions=False)
        client = FakeClient(events, action or (lambda a, s, d: dict(i=0, j=1, op="+")),
                            len(numbers), max_calls)
        experiment = h.Experiment(args, client, events)
        try:
            result = run_rounds(experiment, tuple(map(F, numbers)), "offline", shared)
        finally:
            experiment.pool.shutdown(wait=True)
        return result, events.rows, client

    def test_barrier_publishes_after_all_verified_proposals(self):
        result, rows, client = self.run_policy(True)
        self.assertEqual(len(client.calls), 12)
        for depth in (0, 1):
            verified = [i for i, row in enumerate(rows)
                        if row["type"] == "proposal" and row["depth"] == depth]
            writes = [i for i, row in enumerate(rows)
                      if row["type"] == "memory_write" and row["round"] == depth]
            self.assertEqual(len(verified), 6)
            self.assertGreater(min(writes), max(verified))
            self.assertTrue(all(rows[i]["verified_transition"] for i in writes))
        self.assertEqual(result["policy"], "shared_frontier_search")

    def test_independent_keeps_own_paths_and_uses_same_round_barrier(self):
        result, rows, client = self.run_policy(False)
        self.assertEqual(len(result["outcomes"]), 6)
        self.assertEqual([depth for _, depth, _ in client.calls], [0] * 6 + [1] * 6)
        first_round_nodes = {r["agent_id"]: r["node_id"] for r in rows
                             if r["type"] == "chosen" and r["reason"] == "independent_round_transition"
                             and len(next(n for n in rows if n["type"] == "node"
                                          and n["node_id"] == r["node_id"])["state"]) == 3}
        for row in (r for r in rows if r["type"] == "proposal" and r["depth"] == 1):
            self.assertEqual(row["parent_id"], first_round_nodes[row["agent_id"]])
        self.assertFalse(any(r["type"].startswith("memory_") for r in rows))

    def test_shared_deduplicates_and_hands_verified_states_to_other_workers(self):
        result, rows, client = self.run_policy(True)
        self.assertEqual(len(result["frontier"]), 1)
        self.assertEqual(result["memory_states"], 3)  # root plus one unique state per round
        duplicates = [r for r in rows if r["type"] == "pruned"]
        self.assertEqual(len(duplicates), 10)
        self.assertEqual({r["reason"] for r in duplicates}, {"duplicate_state"})
        self.assertTrue(all(not r.get("proven_wrong", False) for r in duplicates))
        second = next(r for r in rows if r["type"] == "memory_snapshot" and r["round"] == 1)
        self.assertEqual(len(second["frontier"]), 1)
        self.assertEqual(len({state for _, depth, state in client.calls if depth == 1}), 1)

    def test_beam_limit_and_selection_ignore_distance_to_target(self):
        pairs = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        action = lambda a, s, d: dict(i=pairs[a][0], j=pairs[a][1], op="+")
        left, rows, _ = self.run_policy(True, rounds=1, action=action, target=999)
        right, _, _ = self.run_policy(True, rounds=1, action=action, target=1000)
        self.assertEqual(len(left["frontier"]), 4)
        self.assertEqual([r["state"] for r in left["frontier"]],
                         [r["state"] for r in right["frontier"]])
        self.assertEqual(sum(r.get("reason") == "frontier_limit" for r in rows), 2)
        self.assertTrue(all(not r.get("proven_wrong", False) for r in rows))

    def test_shared_round_reads_other_agents_states_without_extra_arithmetic_search(self):
        pairs = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        action = lambda a, s, d: dict(i=pairs[a][0], j=pairs[a][1], op="+") if d == 0 else dict(i=0, j=1, op="+")
        with patch.object(h, "apply_action", wraps=h.apply_action) as verify:
            _, rows, client = self.run_policy(True, action=action)
        self.assertEqual(verify.call_count, len(client.calls))
        own = {r["agent_id"]: tuple(map(F, r["child_state"])) for r in rows
               if r["type"] == "proposal" and r["depth"] == 0}
        inherited = [(agent, state) for agent, depth, state in client.calls if depth == 1]
        self.assertEqual(len(inherited), 6)
        self.assertLessEqual(len({tuple(sorted(state)) for _, state in inherited}), 4)
        self.assertTrue(any(state != own[agent] for agent, state in inherited))

    def test_every_generated_independent_solution_receives_truthful_reward(self):
        action = lambda a, s, d: dict(i=0, j=3, op="*")
        result, rows, _ = self.run_policy(False, numbers=(3, 4, 6, 8), target=24, action=action)
        self.assertEqual(sum(row["solved"] for row in result["outcomes"]), 6)
        self.assertEqual(sum(row["reward"] for row in rows if row["type"] == "reward"), 6)

    def test_invalid_proposals_do_not_become_shared_facts(self):
        for shared in (False, True):
            result, rows, client = self.run_policy(shared, action=lambda a, s, d: dict(i=0, j=0, op="+"))
            self.assertFalse(result["solved"])
            self.assertEqual(len(client.calls), 6)
            self.assertFalse(any(row["type"] == "memory_write" for row in rows))
            self.assertTrue(all(not row["solved"] for row in rows if row["type"] == "reward"))

    def test_verified_solution_stops_both_policies_before_beam_or_next_round(self):
        action = lambda a, s, d: dict(i=0, j=3, op="*") if a == 1 else dict(i=0, j=1, op="+")
        for shared in (False, True):
            with self.subTest(shared=shared):
                result, rows, client = self.run_policy(shared, numbers=(3, 4, 6, 8),
                    target=24, action=action, rounds=4)
                self.assertTrue(result["solved"])
                self.assertEqual(len(client.calls), 6)
                chosen = [r for r in rows if r["type"] == "chosen"]
                self.assertEqual(len(chosen), 1)
                self.assertEqual(chosen[0]["reason"], "exact_target_verified")
                self.assertEqual(chosen[0]["agent_id"], 1)
                self.assertEqual(sum(r["reward"] for r in rows if r["type"] == "reward"), 1)
                self.assertTrue(all(r["reason"] == "verified_solution_found"
                                    for r in rows if r["type"] == "pruned"))

    def test_initial_solution_needs_no_model_call_and_client_budget_is_respected(self):
        for shared in (False, True):
            result, _, client = self.run_policy(shared, target=7)
            self.assertTrue(result["solved"])
            self.assertEqual(client.calls, [])
            result, _, client = self.run_policy(shared, max_calls=3)
            self.assertFalse(result["solved"])
            self.assertEqual(client.budget.snapshot()["calls"], 3)
            self.assertLessEqual(len(client.calls), 12)


if __name__ == "__main__":
    unittest.main()
