#!/usr/bin/env python3
"""Offline replay of the L loop watchdog (zlib ratio < 0.06 on 2,000-character windows, every 500 characters, 2 hits)
on the completed plan-stream thinking texts of arms that ran WITHOUT it. Answers: how many streams it would stop, how many
of those went on to an accepted (judge valid) answer in the real run, whether a longer trigger would spare them, and the
share of completed plan-stream characters after the stop point. Writes results/swarm-loop-hard15-v1/replay.json."""
import glob, json, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / 'runs'
W, STEP, RATIO = 2000, 500, 0.06
ARMS = ['swarm-loop-hard15-v1-d-roll12strategy', 'swarm-cap12-hard14-v1-roll8strategy', 'swarm-cap12-hard14-v1-roll12strategy',
        'swarm-cap12-hard12-v1-roll8strategy', 'swarm-cap12-hard12-v1-roll12strategy', 'swarm-width3-hard11-v1-roll8strategy',
        'swarm-width3-hard11-v1-roll3strategy', 'swarm-strategy-hard10-v1-roll8cancel', 'swarm-strategy-hard10-v1-roll8strategy',
        'swarm-repair-hard9-v1-roll8cancel', 'swarm-repair-hard9-v1-roll8repair', 'swarm-burst-hard8-v1-roll8cancel',
        'swarm-burst-hard8-v1-roll12burst']


def ratio(w):
    b = w.encode()
    return len(zlib.compress(b)) / max(1, len(b))


def scan(text):
    """Longest run of consecutive low-ratio checks while thinking is open, and the character offset of the 2nd hit."""
    e = text.find('</think>')
    text = text if e < 0 else text[:e]
    best = cur = 0
    stop = None
    for n in range(W, len(text) + 1, STEP):
        cur = cur + 1 if ratio(text[n - W:n]) < RATIO else 0
        best = max(best, cur)
        if cur >= 2 and stop is None:
            stop = n
    return best, stop


def main():
    per_arm, streams = {}, []
    for run in ARMS:
        segs = [run] + [f'{run}-resume{i}' for i in range(1, 10) if (RUNS / f'{run}-resume{i}').exists()]
        cases = {(r['task_id'], r['seed']): r for d in segs for r in map(json.loads, open(RUNS / d / 'cases.jsonl'))}
        a = dict(would_stop=0, recovered=0, chars=0, chars_after_stop=0)
        for d in segs:
            for f in glob.glob(str(RUNS / d / 'agents' / '*.jsonl')):
                recs = [json.loads(l) for l in open(f)]
                t = next((r.get('reasoning') for r in recs if r.get('type') == 'request_end'
                          and r.get('stage') in (None, 'plan') and r.get('reasoning')), None)
                if not t:
                    continue
                best, stop = scan(t)
                a['chars'] += len(t)
                if stop is None:
                    continue
                name = Path(f).name[:-6]
                task, seed, slot = name.split('-s')[0], int(name.split('-s')[1].split('-')[0]), int(name.rsplit('-a', 1)[1])
                ag = next((x for x in cases[(task, seed)]['agents'] if x.get('slot') == slot), {})
                ok = ag.get('verdict') is True
                a['would_stop'] += 1
                a['recovered'] += ok
                a['chars_after_stop'] += len(t) - stop
                streams.append(dict(run=run, agent=name, longest_run=best, recovered=ok,
                                    case_solved_by_it=ok and cases[(task, seed)].get('selected_slot') == slot and cases[(task, seed)].get('solved')))
        per_arm[run] = a
    rec = [s for s in streams if s['recovered']]
    out = dict(arms=per_arm, would_stop=len(streams), recovered=len(rec),
               recovered_solved_case=sum(bool(s['case_solved_by_it']) for s in rec),
               recovered_longest_runs=sorted(s['longest_run'] for s in rec),
               by_trigger={h: dict(stops=sum(s['longest_run'] >= h for s in streams), recoveries_lost=sum(s['longest_run'] >= h and s['recovered'] for s in streams))
                           for h in (2, 4, 8, 12, 20)})
    out_dir = ROOT / 'results' / 'swarm-loop-hard15-v1'
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'replay.json').write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k != 'arms'}))


if __name__ == '__main__':
    main()
