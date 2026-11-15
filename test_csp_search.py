import unittest

from csp_search import CORE_ARMS as ARMS, classical_search, run_search
from csp_tasks import verify_assignment


TASK = dict(id="triangle", vertex_count=3, color_count=3,
            edges=[[0, 1], [0, 2], [1, 2]])


class Recorder:
    def __init__(self):
        self.records = []

    def emit(self, kind, **fields):
        self.records.append(dict(type=kind, **fields))


class FakeClient:
    def __init__(self, successful_at=None):
        self.successful_at = successful_at
        self.requests = []

    def call(self, agent, stage, prompt, **context):
        index = context["candidate_index"]
        self.requests.append(dict(agent=agent, prompt=prompt, **context))
        return {"assignment": [0, 1, 2] if index == self.successful_at else [0, 0, 0]}


class SearchTests(unittest.TestCase):
    def test_every_unsolved_arm_dispatches_exactly_sixteen(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                client, events = FakeClient(), Recorder()
                result = run_search(TASK, arm, client, events)
                self.assertFalse(result["solved"])
                self.assertEqual(len(client.requests), 16)
                self.assertEqual(result["candidate_count"], 16)
                self.assertEqual(result["unique_candidates"], 1)
                self.assertEqual(result["best_verification"]["conflicts"], 3)

    def test_success_finishes_current_batch_without_new_generation(self):
        for arm in ARMS:
            client, events = FakeClient(successful_at=0), Recorder()
            result = run_search(TASK, arm, client, events)
            self.assertTrue(result["solved"])
            self.assertEqual(result["candidate_count"], 1 if arm == "sequential" else 4)
            self.assertTrue(verify_assignment(TASK, result["best_payload"])["solved"])

    def test_budget_extension_preserves_balanced_rounds(self):
        for arm in ARMS:
            client = FakeClient()
            result = run_search(TASK, arm, client, Recorder(), max_calls=64)
            self.assertEqual(result["candidate_count"], 64)
            self.assertEqual(len(client.requests), 64)
        for limit in (0, 3, 5, True):
            with self.assertRaises(ValueError):
                run_search(TASK, ARMS[0], FakeClient(), Recorder(), max_calls=limit)

    def test_resampling_receives_no_prior_feedback(self):
        client = FakeClient()
        run_search(TASK, "resample", client, Recorder())
        self.assertTrue(all(not r["parent_ids"] for r in client.requests))
        self.assertEqual(len({r["prompt"] for r in client.requests}), 1)

    def test_parallel_chains_never_receive_peer_candidates(self):
        client = FakeClient()
        run_search(TASK, "parallel_repair4", client, Recorder())
        for request in client.requests:
            index = request["candidate_index"]
            self.assertEqual(request["parent_ids"], [] if index < 4 else [f"candidate-{index - 4}"])
            self.assertEqual(request["agent"], index % 4)

    def test_sequential_chain_only_receives_own_last_candidate(self):
        client = FakeClient()
        run_search(TASK, "sequential", client, Recorder())
        for request in client.requests:
            index = request["candidate_index"]
            self.assertEqual(request["parent_ids"], [] if not index else [f"candidate-{index - 1}"])

    def test_evolution_immigration_crossover_elitism_are_explicit(self):
        client, events = FakeClient(), Recorder()
        run_search(TASK, "evolution4", client, events)
        requests = {r["candidate_index"]: r for r in client.requests}
        for offset in (4, 8, 12):
            # All scripted assignments are identical: crossover must fall back
            # to mutation instead of claiming two distinct parents.
            self.assertEqual(requests[offset + 2]["operation"], "mutation")
            self.assertEqual(requests[offset + 2]["parent_ids"], ["candidate-0"])
            self.assertEqual(requests[offset + 3]["operation"], "immigrant")
            self.assertFalse(requests[offset + 3]["parent_ids"])
        selections = [e for e in events.records if e["type"] == "selection"]
        self.assertEqual(len(selections), 3)
        self.assertTrue(all(e["survivor_ids"] == [f"candidate-{i}" for i in range(4)] for e in selections))

    def test_classical_baseline_is_deterministic_and_independently_verified(self):
        a = classical_search(TASK, 19, generations=8, population_size=8)
        self.assertEqual(a, classical_search(TASK, 19, generations=8, population_size=8))
        self.assertEqual(a["model_calls"], 0)
        self.assertLessEqual(a["evaluations"], 8 + 8 * 4)
        self.assertEqual(a["solved"], verify_assignment(TASK, {"assignment": a["assignment"]})["solved"])

    def test_classical_rejects_invalid_search_budgets(self):
        for kwargs in ({"generations": -1}, {"generations": True}, {"population_size": 4}, {"population_size": 5.5}):
            with self.assertRaises(ValueError):
                classical_search(TASK, 1, **kwargs)


if __name__ == "__main__":
    unittest.main()
