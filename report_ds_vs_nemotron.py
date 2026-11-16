#!/usr/bin/env python3
"""DeepSeek reference vs Nemotron agents/swarms on the same fresh tasks (arithmetic-v2, arithmetic-hard-v1).

Expected any-of-k values average over all k-subsets of the agents of one type in a run.
Different runs share tasks and seeds; server, model and serving engine differ (bundled comparison).
"""
import argparse
import collections
import json
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cases(path, corpus=None):
    rows = json.loads((HERE / path / 'summary.json').read_text())
    out = collections.defaultdict(dict)
    for r in rows:
        if corpus is None or r.get('corpus') == corpus:
            out[(r['task_id'], r['seed'])][r['agent']] = r
    return out


def expected(cs, agents, k):
    subs = list(combinations(agents, k))
    full = [c for c in cs.values() if all(a in c for a in agents)]
    return sum(any(bool(c[a]['solved']) for a in s) for c in full for s in subs) / len(subs), len(full)


def tokens(cs, agents):
    vals = [c[a]['completion_tokens'] or 0 for c in cs.values() for a in agents if a in c]
    return sum(vals) / max(1, len(vals))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    rows = []
    sources = {
        'v2': [('DeepSeek V4.1 (1 call, 8K)', cases('runs/deepseek-fresh-v1', 'v2'), [0, 1]),
               ('Nemotron original single call (8K)', cases('runs/confirm-v2-v1'), [0, 1, 2, 3]),
               ('Nemotron budget-forced agent (8K)', cases('runs/confirm-v2-v1'), list(range(4, 12)))],
        'hard': [('DeepSeek V4.1 (1 call, 8K)', cases('runs/deepseek-hard-stream-v1', 'hard'), [0, 1]),
                 ('Nemotron original single call (8K)', cases('runs/confirm-hard-v1'), [0, 1, 2, 3]),
                 ('Nemotron budget-forced agent (8K)', cases('runs/confirm-hard-v1'), list(range(4, 12))),
                 ('Nemotron deep agent (16K)', cases('runs/confirm-hard-long-v1'), [0, 1, 2, 3])]}
    lines = ['# DeepSeek V4.1 reference vs Nemotron agents on fresh tasks', '',
             'Same fresh tasks and seeds (48 evaluation tasks x 3 seeds per corpus). Every success passes the exact verifier. '
             'Values are expected solved cases out of 144 for k independent attempts (average over all k-subsets). '
             'Bundled comparison: different model, checkpoint (DeepSeek is a custom abliterated checkpoint) and serving engine; '
             'DeepSeek uses all four Sparks for one TP4 model, Nemotron one Spark per replica. No wall-clock cutoffs.', '']
    for corpus, entries in sources.items():
        lines += [f'## {"arithmetic-v2 (normal difficulty)" if corpus == "v2" else "arithmetic-hard-v1"}', '',
                  '| Method | k=1 | k=2 | k=4 | k=8 | Mean completion tokens per attempt |', '|---|---:|---:|---:|---:|---:|']
        for name, cs, agents in entries:
            cells = []
            for k in (1, 2, 4, 8):
                cells.append(f'{expected(cs, agents, k)[0]:.1f}' if k <= len(agents) else '—')
            n = expected(cs, agents, 1)[1]
            lines.append(f'| {name} | ' + ' | '.join(cells) + f' | {tokens(cs, agents):,.0f} |')
            rows.append(dict(corpus=corpus, method=name, cases=n, any_of={k: expected(cs, agents, k)[0] for k in (1, 2, 4, 8) if k <= len(agents)},
                             mean_completion_tokens=tokens(cs, agents)))
        lines.append('')
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    (a.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
