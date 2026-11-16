"""Offline tests for the hard arithmetic corpus generator and difficulty DP; no model calls."""
import itertools
import random
import unittest
from fractions import Fraction

import arith_difficulty as d
import make_arithmetic_hard as m
from harness import InvalidMove, apply_action


def brute_min_moves(numbers, target, limit=5):
    """Independent move-level BFS with the frozen harness rules."""
    frontier = {tuple(sorted(map(Fraction, numbers)))}
    for depth in range(limit + 1):
        if any(target in state for state in frontier) and depth > 0:
            return depth
        nxt = set()
        for state in frontier:
            for i, j in itertools.permutations(range(len(state)), 2):
                for op in '+-*/':
                    try:
                        nxt.add(tuple(sorted(apply_action(state, dict(i=i, j=j, op=op)))))
                    except InvalidMove:
                        pass
        frontier = nxt
    return None


class HardTests(unittest.TestCase):
    def test_dp_matches_bruteforce_min_moves(self):
        rng = random.Random(5)
        for _ in range(60):
            numbers = [rng.randint(1, 10) for _ in range(2)] + rng.sample([25, 50, 75, 100], 2)
            target = rng.randint(10, 999)
            if target in numbers:
                continue
            stats = d.stats(numbers, target)
            self.assertEqual(stats['min_moves'], brute_min_moves(numbers, target, 3))

    def test_witness_replays_with_minimal_moves(self):
        rng = random.Random(7)
        checked = 0
        while checked < 40:
            size = rng.choice((4, 6))
            numbers = [rng.randint(1, 10) for _ in range(size - 2)] + rng.sample([25, 50, 75, 100], 2)
            target = rng.randint(100, 999)
            stats = d.stats(numbers, target)
            if stats['min_numbers'] is None:
                continue
            moves = d.witness(numbers, target)
            self.assertEqual(len(moves), stats['min_moves'])
            state = tuple(map(Fraction, numbers))
            for move in moves:
                state = apply_action(state, move)
            self.assertIn(target, state)
            checked += 1

    def test_known_unique_task(self):
        self.assertEqual(d.stats([100, 75, 4, 8], 357)['derivations_total'], 1)
        self.assertIsNotNone(m.hard([100, 75, 4, 8], 357))

    def test_generation_is_deterministic_balanced_and_verified(self):
        first = m.generate(m.SEED, set())
        second = m.generate(m.SEED, set())
        self.assertEqual(first[0], second[0])
        m.verify(first[0], first[1], set())

    def test_exclusion_is_respected(self):
        tasks, _, _ = m.generate(m.SEED, set())
        banned = {m.key(tasks[0]['numbers'], tasks[0]['target'])}
        again, private, _ = m.generate(m.SEED, banned)
        self.assertNotIn(tasks[0]['id'], [t['id'] for t in again])
        m.verify(again, private, banned)


if __name__ == '__main__':
    unittest.main()
