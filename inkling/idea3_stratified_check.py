#!/usr/bin/env python3
"""Idea #3 CPU distribution check (astra, IDEAS 2026-11-26: couple sampling randomness across siblings). Offline, no
model, no fleet, standard library only.

Scheme. N sibling agents sample position t of their own sequences by inverse CDF over their OWN next-token
distribution (after temperature / truncation, any fixed token order) with coupled uniforms
    u[k, t] = (pi_t(k) + V[k, t]) / N,
pi_t a uniformly random permutation of 0..N-1 drawn afresh per position, V[k, t] iid Uniform(0, 1) (randomized
stratified sampling: one sibling per stratum [m/N, (m+1)/N) at every position).

Claims checked:
  1  exact single-position marginal: for any categorical p and any sibling k, P(token c) = p_c (exact rationals);
  2  exact sequence marginal: on toy autoregressive models (context-dependent, rational probabilities) every
     sibling's full-sequence distribution equals the model's (exact enumeration over strata; this needs only that
     u[k, .] is iid Uniform(0, 1) for a fixed k, which holds because pi_t and V are drawn afresh per position);
  3  Monte Carlo cross-check of 1-2 (chi-square) and the coupling's effect: duplicate first tokens / duplicate whole
     sequences between siblings, coupled vs independent;
  control  a wrong coupling (fixed strata u[k] = (k + V) / N, no permutation) must FAIL check 1 (the check has power);
  speculative  the serving stack samples through speculative verification (rejection sampling: accept a draft token
     with coin u < p / q, else sample the residual with a second coin). Feeding the coupled uniforms in as coins keeps
     the marginals but is not inverse-CDF stratification: the duplicate rate is measured on that path too.
The check says nothing about acceptance quality; see the report's notes on what a fleet screen would need.

usage: idea3_stratified_check.py [--out results/idea3-stratified-check] [--draws 200000] [--seed 2026112703]
"""
import argparse
import itertools
import json
import random
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cdf_intervals(p):
    """Token c occupies [sum p[:c], sum p[:c+1]) of [0, 1) (inverse CDF in a fixed token order)."""
    out, lo = [], Fraction(0)
    for q in p:
        out.append((lo, lo + q))
        lo += q
    assert lo == 1, 'probabilities must sum to 1'
    return out


def stratum_token_prob(p, m, n):
    """P(token c | u uniform on stratum [m/n, (m+1)/n)) for every c (exact)."""
    a, b = Fraction(m, n), Fraction(m + 1, n)
    return [max(Fraction(0), min(b, hi) - max(a, lo)) * n for lo, hi in cdf_intervals(p)]


def exact_marginal(p, n, k):
    """P(sibling k draws token c) under the coupling: the stratum pi(k) is uniform on 0..n-1 (any k)."""
    out, total = [Fraction(0)] * len(p), 0
    for perm in itertools.permutations(range(n)):  # pi uniform over all permutations
        total += 1
        for c, q in enumerate(stratum_token_prob(p, perm[k], n)):
            out[c] += q
    return [q / total for q in out]


class ToyModel:
    """A context-dependent autoregressive model with rational next-token probabilities (vocab V, length T)."""

    def __init__(self, vocab, length, rng):
        self.vocab, self.length, self.table = vocab, length, {}
        for t in range(length):
            for prefix in itertools.product(range(vocab), repeat=t):
                weights = [rng.randint(1, 9) for _ in range(vocab)]
                if rng.random() < 0.3:
                    weights[rng.randrange(vocab)] = 0  # truncated tokens (as after top-p / top-k)
                    if sum(weights) == 0:
                        weights[0] = 1
                s = sum(weights)
                self.table[prefix] = [Fraction(w, s) for w in weights]

    def prob(self, seq):
        out = Fraction(1)
        for t in range(len(seq)):
            out *= self.table[tuple(seq[:t])][seq[t]]
        return out

    def sample(self, uniforms):
        seq = []
        for u in uniforms:
            p = self.table[tuple(seq)]
            acc = 0.0
            for c, q in enumerate(p):
                acc += float(q)
                if u < acc:
                    break
            else:
                c = max(i for i, q in enumerate(p) if q > 0)
            seq.append(c)
        return tuple(seq)


def fixed_strata_marginal(p, n, k):
    """The wrong coupling: sibling k always draws from stratum k."""
    return stratum_token_prob(p, k, n)


def speculative_token(p, q, draft_u, coin, residual_u):
    """One speculative-verify step (chain of one draft token): draft x ~ q by draft_u; accept if coin < p(x) / q(x),
    else sample the residual max(p - q, 0) by residual_u. The output is distributed as p for any iid uniforms."""
    def inverse(dist, u):
        acc = 0.0
        for c, w in enumerate(dist):
            acc += w
            if u < acc:
                return c
        return max(i for i, w in enumerate(dist) if w > 0)
    x = inverse(q, draft_u)
    if coin < p[x] / q[x]:
        return x
    residual = [max(a - b, 0.0) for a, b in zip(p, q)]
    total = sum(residual)
    return inverse([r / total for r in residual], residual_u)


def exact_sequence_marginal(model, n):
    """P(sibling's sequence = s) for every s, by enumerating the sibling's stratum at each position (each stratum has
    probability 1/n at every position, independently across positions); compared with model.prob."""
    out = {}
    for seq in itertools.product(range(model.vocab), repeat=model.length):
        total = Fraction(0)
        for strata in itertools.product(range(n), repeat=model.length):
            q = Fraction(1, n ** model.length)
            for t, m in enumerate(strata):
                q *= stratum_token_prob(model.table[tuple(seq[:t])], m, n)[seq[t]]
                if q == 0:
                    break
            total += q
        out[seq] = total
    return out


def stratified_duplicate(p, n):
    """Exact P(siblings 0 and 1 draw the same token) under inverse-CDF stratification of one position (float p)."""
    exact = [Fraction(x).limit_denominator(1000) for x in p]
    total, perms = Fraction(0), list(itertools.permutations(range(n)))
    for perm in perms:
        a, b = stratum_token_prob(exact, perm[0], n), stratum_token_prob(exact, perm[1], n)
        total += sum(x * y for x, y in zip(a, b))
    return float(total / len(perms))


def coupled_uniforms(n, length, rng):
    """u[k][t] for n siblings."""
    out = [[0.0] * length for _ in range(n)]
    for t in range(length):
        perm = list(range(n))
        rng.shuffle(perm)
        for k in range(n):
            out[k][t] = (perm[k] + rng.random()) / n
    return out


def chi_square(counts, probs, draws):
    stat, dof = 0.0, -1
    for key, p in probs.items():
        if p == 0:
            if counts.get(key):
                return float('inf'), dof
            continue
        e = draws * float(p)
        stat += (counts.get(key, 0) - e) ** 2 / e
        dof += 1
    return stat, dof


def chi_square_p(stat, dof):
    """Upper tail of the chi-square distribution (Wilson-Hilferty normal approximation; dof >= 3)."""
    from math import erf, sqrt
    if dof <= 0:
        return 1.0
    z = ((stat / dof) ** (1 / 3) - (1 - 2 / (9 * dof))) / sqrt(2 / (9 * dof))
    return 0.5 * (1 - erf(z / sqrt(2)))


FLEET_SCREEN = dict(
    implementable_without_server_change=False,
    stop='a fleet screen needs an SGLang change; stopped here (coordinator 2026-11-27, item 3)',
    evidence=[
        'serving: swarm-recipe (Inkling-2-Mini-1x-DGX-Spark v2.9.2) samples through DFLASH speculative decoding '
        '(--speculative-algorithm DFLASH, block verification); the plan serving block and admission receipts record '
        'the launch command, without --enable-custom-logit-processor and without --enable-deterministic-inference',
        'SGLang source read (repos/external/sglang-v3-survey-20261027 @7fe5b127e4, not the serving image itself): the '
        'DFLASH verify step draws its accept and final-sampling coins with torch.rand inside the server '
        '(speculative/dflash_utils.py ~982-990); no request field carries per-position uniforms',
        'per-request seed (the shim maps seed -> sampling_seed) is only used when deterministic inference is enabled '
        '(sampling/sampling_batch_info.py ~157-171); otherwise sampling is global torch randomness, so sibling '
        'coupling through request seeds is impossible on this launch',
        'a custom logit processor could force each position to the coupled inverse-CDF choice (one-hot target, exact '
        'under rejection sampling) but needs --enable-custom-logit-processor (a relaunch) and a per-position processor '
        'over the full vocabulary inside the verify block (DFLASH fast paths disabled): a server change',
        'feeding coupled coins into the existing rejection-sampling path keeps the marginals but barely couples the '
        'tokens (speculative_path: duplicate rate 0.276 vs 0.324 independent, against 0.05 for inverse-CDF '
        'stratification on the same distribution)'])


def run(draws=200_000, seed=2026112703):
    rng = random.Random(seed)
    report = dict(protocol='idea3-stratified-check-v1', seed=seed, draws=draws, checks=[])

    # 1 exact single-position marginals
    single = []
    for case in range(200):
        n = rng.choice([2, 3, 4, 5])
        weights = [rng.randint(0, 12) for _ in range(rng.randint(2, 9))]
        if sum(weights) == 0:
            weights[0] = 1
        p = [Fraction(w, sum(weights)) for w in weights]
        ok = all(exact_marginal(p, n, k) == p for k in range(n))
        single.append(ok)
    report['checks'].append(dict(name='exact single-position marginal', cases=len(single), passed=sum(single)))
    p, n = [Fraction(1, 2), Fraction(1, 3), Fraction(1, 6)], 3
    report['control'] = dict(name='wrong coupling (fixed strata) is detected',
                             detected=any(fixed_strata_marginal(p, n, k) != p for k in range(n)))

    # 2 exact sequence marginals on toy models
    seqs = []
    for case in range(6):
        model = ToyModel(vocab=3, length=3, rng=rng)
        for n in (2, 4):
            exact = exact_sequence_marginal(model, n)
            seqs.append(all(exact[s] == model.prob(s) for s in exact) and sum(exact.values()) == 1)
    report['checks'].append(dict(name='exact full-sequence marginal (toy models, vocab 3, length 3, n = 2 and 4)',
                                 cases=len(seqs), passed=sum(seqs)))

    # 3 Monte Carlo: marginal of each sibling, and the coupling's duplicate rates
    model, n = ToyModel(vocab=4, length=3, rng=rng), 4
    probs = {s: model.prob(s) for s in itertools.product(range(4), repeat=3)}
    counts = [dict() for _ in range(n)]
    dup_first = dup_seq = ind_first = ind_seq = 0
    for _ in range(draws):
        us = coupled_uniforms(n, 3, rng)
        out = [model.sample(u) for u in us]
        for k in range(n):
            counts[k][out[k]] = counts[k].get(out[k], 0) + 1
        dup_first += out[0][0] == out[1][0]
        dup_seq += out[0] == out[1]
        a, b = model.sample([rng.random() for _ in range(3)]), model.sample([rng.random() for _ in range(3)])
        ind_first += a[0] == b[0]
        ind_seq += a == b
    mc = []
    for k in range(n):
        stat, dof = chi_square(counts[k], probs, draws)
        mc.append(dict(sibling=k, chi_square=round(stat, 2), dof=dof, p_value=round(chi_square_p(stat, dof), 4)))
    report['checks'].append(dict(name='Monte Carlo sibling marginals (vocab 4, length 3, n = 4)', siblings=mc,
                                 passed=sum(1 for m in mc if m['p_value'] > 0.001), cases=n))
    report['coupling_effect'] = dict(
        duplicate_first_token=dict(coupled=round(dup_first / draws, 4), independent=round(ind_first / draws, 4)),
        duplicate_whole_sequence=dict(coupled=round(dup_seq / draws, 4), independent=round(ind_seq / draws, 4)))
    # speculative path: coupled coins in the accept test and the residual draw, independent draft samples
    p_f, q_f = [0.45, 0.3, 0.15, 0.1], [0.25, 0.25, 0.25, 0.25]
    counts, dup_spec, dup_ind = [0] * 4, 0, 0
    for _ in range(draws):
        coins, residual = coupled_uniforms(2, 1, rng), coupled_uniforms(2, 1, rng)
        a = speculative_token(p_f, q_f, rng.random(), coins[0][0], residual[0][0])
        b = speculative_token(p_f, q_f, rng.random(), coins[1][0], residual[1][0])
        counts[a] += 1
        dup_spec += a == b
        dup_ind += (speculative_token(p_f, q_f, rng.random(), rng.random(), rng.random())
                    == speculative_token(p_f, q_f, rng.random(), rng.random(), rng.random()))
    stat, dof = chi_square({c: counts[c] for c in range(4)}, {c: Fraction(p_f[c]).limit_denominator(100)
                                                             for c in range(4)}, draws)
    report['speculative_path'] = dict(
        target=p_f, draft=q_f, marginal_chi_square=round(stat, 2), dof=dof, p_value=round(chi_square_p(stat, dof), 4),
        duplicate_token=dict(coupled_coins=round(dup_spec / draws, 4), independent=round(dup_ind / draws, 4),
                             inverse_cdf_stratified=round(stratified_duplicate(p_f, 2), 4),
                             iid=round(sum(x * x for x in p_f), 4)))
    report['fleet_screen'] = FLEET_SCREEN
    report['verdict'] = ('marginals preserved exactly' if all(c['passed'] == c['cases'] for c in report['checks'])
                         and report['control']['detected'] else 'MARGINAL CHECK FAILED')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'idea3-stratified-check')
    p.add_argument('--draws', type=int, default=200_000)
    p.add_argument('--seed', type=int, default=2026112703)
    a = p.parse_args(argv)
    r = run(a.draws, a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(r, indent=1) + '\n')
    print(json.dumps(dict(verdict=r['verdict'], checks=[(c['name'], c['passed'], c['cases']) for c in r['checks']],
                          coupling_effect=r['coupling_effect'])))
    return 0 if r['verdict'] == 'marginals preserved exactly' else 1


if __name__ == '__main__':
    raise SystemExit(main())
