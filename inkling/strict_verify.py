"""Exact verification of an arithmetic plan, strict and lenient (sol review of the idea #1 screen, 2026-11-27).

lenient  direct_solver.replay_plan's rule (the shared verifier of the arithmetic reports so far): apply the moves in
         order and stop at the first move that reaches the target or the first illegal move; solved if the target is
         then in the state. A plan that reaches the target and then makes an illegal move is credited.
strict   every submitted move is applied and must be legal; solved if the target appeared after some move. A plan with
         any illegal move is not solved.
Both require {"moves": [...]} only, with 1..min(rounds, len(numbers) - 1) moves.
"""
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness import apply_action  # noqa: E402


def moves_of(plan, numbers, rounds=5):
    moves = plan.get('moves') if isinstance(plan, dict) and set(plan) == {'moves'} else None
    if not isinstance(moves, list) or not 1 <= len(moves) <= min(rounds, len(numbers) - 1):
        return None
    return moves


def lenient_solved(numbers, target, plan, rounds=5):
    moves = moves_of(plan, numbers, rounds)
    state = tuple(Fraction(n) for n in numbers)
    for action in moves or []:
        try:
            state = apply_action(state, action, False)
        except (ValueError, TypeError):
            break
        if Fraction(target) in state:
            break
    return moves is not None and Fraction(target) in state


def strict_solved(numbers, target, plan, rounds=5):
    moves = moves_of(plan, numbers, rounds)
    if moves is None:
        return False
    state, appeared = tuple(Fraction(n) for n in numbers), False
    for action in moves:
        try:
            state = apply_action(state, action, False)
        except (ValueError, TypeError):
            return False  # an illegal move anywhere: not solved
        appeared = appeared or Fraction(target) in state
    return appeared
