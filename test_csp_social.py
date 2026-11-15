from fractions import Fraction
import itertools
import threading
import unittest

from csp_tasks import verify_assignment
from csp_social import SOCIAL_ARMS, align_colors, color_consensus, run_social_search
from harness import Budget


TASK = dict(id="tiny", vertex_count=3, color_count=2, edges=[[0, 1], [0, 2], [1, 2]])
BASE = 'Return ONLY {"assignment":[color_for_vertex_0,...]}. TASK PLACEHOLDER'


class Events:
    def __init__(self): self.rows = []
    def emit(self, kind, **fields): self.rows.append(dict(type=kind, **fields))


class Client:
    def __init__(self, answer=None, max_calls=16):
        self.calls, self.lock = [], threading.Lock()
        self.budget = Budget(max_calls, max_calls * 512)
        self.answer = answer or (lambda stage: {"critique": "Check conflicting public edges."}
                                 if stage.startswith("review-") else {"assignment": [0, 0, 0]})
    def call(self, agent, stage, prompt, **context):
        if not self.budget.reserve(512):
            raise AssertionError("unexpected exhausted fake budget")
        with self.lock:
            self.calls.append(dict(agent=agent, stage=stage, prompt=prompt, **context))
        payload = self.answer(stage)
        self.budget.settle(512, 10)
        return payload


def candidate(task, values, index):
    payload = {"assignment": values}
    return dict(id=f"c{index}", index=index, payload=payload,
                verification=verify_assignment(task, payload))


class CSPSocialTests(unittest.TestCase):
    def test_default_and_extended_call_accounting(self):
        for limit in (4, 16, 64):
            for arm in SOCIAL_ARMS:
                with self.subTest(limit=limit, arm=arm):
                    client, events = Client(max_calls=limit), Events()
                    result = run_social_search(TASK, arm, client, events, BASE, max_calls=limit)
                    self.assertFalse(result["solved"])
                    self.assertEqual(len(client.calls), limit)
                    self.assertEqual(result["model_call_count"], limit)
                    self.assertEqual(result["attempted_model_calls"], limit)
                    self.assertEqual(client.budget.snapshot()["completion_tokens_reserved"], 0)
                    if arm == "review_elites4":
                        self.assertEqual(result["candidate_count"], 4 + (limit - 4) // 2)
                        self.assertEqual(result["review_count"], (limit - 4) // 2)
                        self.assertEqual(result["derived_count"], 0)
                    else:
                        self.assertEqual(result["candidate_count"], limit)
                        self.assertEqual(result["review_count"], 0)
                        self.assertEqual(result["derived_count"], limit // 4)
                    self.assertEqual(result["candidate_count"] + result["review_count"], limit)

    def test_reviews_are_delegated_to_worse_sources_and_ancestry_precedes_use(self):
        client, events = Client(), Events()
        run_social_search(TASK, "review_elites4", client, events, BASE)
        known, review_ids = {}, set()
        for row in events.rows:
            if row["type"] == "candidate":
                self.assertTrue(set(row["parents"]) <= set(known))
                self.assertTrue(set(row["review_ids"]) <= review_ids)
                self.assertGreaterEqual(row["verified_elapsed_seconds"], 0)
                known[row["id"]] = row
            elif row["type"] == "review_delegation":
                self.assertFalse(set(row["elite_ids"]) & set(row["reviewer_candidate_ids"]))
                self.assertEqual(len(row["elite_ids"]), 2)
                self.assertEqual(len(row["reviewer_candidate_ids"]), 2)
                self.assertTrue(set(row["elite_ids"] + row["reviewer_candidate_ids"]) <= set(known))
            elif row["type"] == "review":
                self.assertIn(row["reviewer_candidate_id"], known)
                self.assertTrue(set(row["target_ids"]) <= set(known))
                self.assertFalse(row["verified_fact"])
                review_ids.add(row["id"])
        self.assertEqual(len(review_ids), 6)
        for call in client.calls:
            if call["stage"].startswith("review-"):
                self.assertNotIn(BASE, call["prompt"])
                self.assertIn("one key critique", call["prompt"])
                self.assertNotIn('Return ONLY {"assignment"', call["prompt"])

    def test_invalid_reviews_are_charged_but_not_forwarded(self):
        def answer(stage):
            return {"assignment": [0, 0, 0]}
        client, events = Client(answer), Events()
        result = run_social_search(TASK, "review_elites4", client, events, BASE)
        self.assertEqual(result["review_count"], 6)
        self.assertEqual(result["model_call_count"], 16)
        self.assertTrue(all(not r["valid_schema"] for r in events.rows if r["type"] == "review"))
        self.assertTrue(all(not r["review_ids"] for r in events.rows if r["type"] == "candidate"))

    def test_no_valid_ballot_restarts_fresh_without_derived_candidate(self):
        for arm in ("democracy4", "weighted_democracy4"):
            client, events = Client(lambda stage: None), Events()
            result = run_social_search(TASK, arm, client, events, BASE)
            self.assertEqual(result["model_call_count"], 16)
            self.assertEqual(result["derived_count"], 0)
            self.assertTrue(all(call["operation"] == "fresh" and call["parent_ids"] == [] for call in client.calls))

    def test_initial_solved_candidate_still_charges_entire_batch(self):
        task = dict(id="edge", vertex_count=2, color_count=2, edges=[[0, 1]])
        for arm in SOCIAL_ARMS:
            client, events = Client(lambda stage: {"assignment": [0, 1]}), Events()
            result = run_social_search(task, arm, client, events, BASE)
            self.assertTrue(result["solved"])
            self.assertEqual(result["candidate_count"], 4)
            self.assertEqual(result["model_call_count"], 4)
            self.assertEqual(result["review_count"], 0)
            self.assertEqual(result["derived_count"], 0)

    def test_consensus_solution_is_derived_and_not_claimed_as_model_sample(self):
        task = dict(id="derived", vertex_count=5, color_count=3,
                    edges=[[0, 1], [1, 2], [2, 3], [3, 4], [0, 4], [0, 2]])
        rows = [[1, 2, 1, 2, 0], [2, 0, 1, 0, 0], [2, 2, 0, 1, 0], [2, 0, 0, 2, 0]]
        self.assertTrue(all(not verify_assignment(task, {"assignment": row})["solved"] for row in rows))
        client = Client(lambda stage: {"assignment": rows[int(stage.split("-")[-1])]})
        events = Events()
        result = run_social_search(task, "democracy4", client, events, BASE)
        self.assertTrue(result["solved"])
        self.assertEqual(result["candidate_count"], 4)
        self.assertEqual(result["derived_count"], 1)
        self.assertEqual(result["model_call_count"], 4)
        self.assertEqual(result["best_candidate_origin"], "derived")
        derived = next(row for row in events.rows if row["type"] == "derived_candidate")
        self.assertEqual(derived["model_calls"], 0)
        self.assertEqual(set(derived["parents"]), {f"candidate-{i}" for i in range(4)})
        self.assertTrue(verify_assignment(task, derived["payload"])["solved"])

    def test_alignment_matches_independent_brute_permutation(self):
        for anchor in ([0, 1, 2, 0], [0, 0, 0, 0], [2, 1, 1, 0]):
            for colors in itertools.product(range(3), repeat=4):
                options = []
                for mapping in itertools.permutations(range(3)):
                    output = [mapping[v] for v in colors]
                    options.append((-sum(v == anchor[i] for i, v in enumerate(output)), mapping, output))
                expected = min(options)
                actual = align_colors(list(colors), anchor, 3)
                self.assertEqual(actual["permutation"], list(expected[1]))
                self.assertEqual(actual["assignment"], expected[2])
                self.assertEqual(actual["agreement"], -expected[0])

    def test_weighted_votes_are_exact_and_match_independent_reference(self):
        task = dict(id="votes", vertex_count=4, color_count=3, edges=[[0, 1], [1, 2], [2, 3]])
        population = [candidate(task, row, i) for i, row in enumerate(
            ([0, 0, 1, 2], [1, 1, 1, 2], [2, 0, 0, 1], [0, 0, 0, 0]))]
        population.append(candidate(task, [True, 0, 1, 2], 4))
        result = color_consensus(population, 3, weighted=True)
        anchor = population[0]["payload"]["assignment"]
        expected = [[Fraction(0) for _ in range(3)] for _ in range(4)]
        for item in population[:4]:
            values = item["payload"]["assignment"]
            mapping = min(itertools.permutations(range(3)),
                          key=lambda m: (-sum(m[v] == a for v, a in zip(values, anchor)), m))
            weight = Fraction(1, 1 + sum(values[u] == values[v] for u, v in task["edges"]))
            for index, value in enumerate(values): expected[index][mapping[value]] += weight
        self.assertEqual(result["votes"], [[[v.numerator, v.denominator] for v in row] for row in expected])
        self.assertNotIn("c4", result["source_ids"])
        answer = []
        for index, row in enumerate(expected):
            tied = [color for color, value in enumerate(row) if value == max(row)]
            answer.append(anchor[index] if anchor[index] in tied else min(tied))
        self.assertEqual(result["payload"]["assignment"], answer)
        self.assertTrue(all(type(n) is int for row in result["votes"] for rational in row for n in rational))

    def test_color_permuted_identical_assignments_align_to_anchor(self):
        task = dict(id="symmetry", vertex_count=4, color_count=3, edges=[[0, 1]])
        population = [candidate(task, row, i) for i, row in enumerate(
            ([0, 1, 2, 0], [2, 0, 1, 2], [1, 2, 0, 1]))]
        result = color_consensus(population, 3)
        self.assertEqual(result["payload"], population[0]["payload"])
        self.assertTrue(all(row["agreement"] == 4 for row in result["alignments"]))

    def test_all_parent_references_exist_before_consensus_repairs(self):
        client, events = Client(), Events()
        run_social_search(TASK, "weighted_democracy4", client, events, BASE)
        known = set()
        for row in events.rows:
            if row["type"] in ("candidate", "derived_candidate"):
                self.assertTrue(set(row["parents"]) <= known)
                known.add(row["id"])
        repair_calls = [call for call in client.calls if call["operation"] == "consensus_guided_repair"]
        self.assertEqual(len(repair_calls), 12)
        self.assertTrue(all(len(call["parent_ids"]) == 2 for call in repair_calls))

    def test_invalid_call_limits_rejected_before_dispatch(self):
        for value in (0, 3, 5, -4, True, 16.0):
            client = Client()
            with self.assertRaises(ValueError):
                run_social_search(TASK, "democracy4", client, Events(), BASE, max_calls=value)
            self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
