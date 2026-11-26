#!/usr/bin/env python3
"""OFFLINE upper-bound screen of idea #5 (astra, IDEAS 2026-11-26): suspend sibling generation while a candidate's
acceptance is pending (keep the siblings' KV, position and RNG; commit cancellation on acceptance, resume on
rejection). Zero fleet: it replays the recorded timestamps of default-policy runs.

Saving (both bounds): sibling generation that overlaps the pending verification of a candidate that was later
ACCEPTED (those siblings were cancelled at the acceptance anyway, so suspending them loses nothing). Charges:
  optimistic   none (suspension and resume free, capacity lent elsewhere, nothing recomputed);
  pessimistic  for every pending verification that ended in a REJECTION, every sibling in flight during it is suspended
               and its retained KV is assumed evicted: its whole context (prompt + tokens generated so far) is
               recomputed on resume, charged at PREFILL_WEIGHT decode-equivalent tokens per token (1.0: as expensive as
               generation, deliberately pessimistic); the resume delay (seconds siblings stand still) is reported, not
               converted to tokens (the freed capacity is lent to other cases).
Shares are of the run's server generation tokens (arm_accounting.json); the energy proxy is that share of the run's
GPU energy (Wh) (decode dominates; prefill compute is a few percent of the tokens and cheaper per token).

Pending verification windows:
  arithmetic roll12fair   [worker exit, judge verdict] of an agent (cases.jsonl: finished_s, judged_s); accepted =
                          the case's selected slot with verdict true;
  coding judge-only       [judge_start, acceptance] in the agent's trace (acceptance.accepted);
  coding R2 (public)      [feedback evaluation_start, worker exit] of the winner (the case ends at its exit); rejected
                          windows: [feedback evaluation_start, evaluation_end] of agents whose public grade failed.
Sibling generation inside a window: arithmetic from each agent's tokens over its [started_s, finished_s]; coding from
each request's [request_start, request_end] and completion tokens; a stream without a recorded end or token count (a
cancelled agent) generates at the run's median per-stream rate (a stated estimate).

Frozen rule (coordinator, 2026-11-27): REJECT the idea if even the optimistic bound saves < 2 % (per family, pooled
over its runs); otherwise it survives to a live validation.

usage: screen_suspend_siblings.py [--runs-root runs] [--out results/screen-suspend-siblings]
"""
import argparse
import glob
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ARITH_RUNS = ('swarm-fair-hard22-v1-roll12fair', 'swarm-fair-hard23-v1-roll12fair', 'swarm-baseline-hard26-v1-roll12fair')
JUDGE_RUNS = ('coding-notests-v1-judge',)
R2_RUNS = ('coding-elastic-v2-a', 'coding-elastic-v2-p')
PREFILL_WEIGHT = 1.0
ARITH_PROMPT_TOKENS = 600  # approximate prompt of an arithmetic agent (pessimistic recompute context)
THRESHOLD = 0.02


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def ts(e):
    return datetime.fromisoformat(e['timestamp']).timestamp()


def accounting(d):
    rec = json.loads((Path(d) / 'arm_accounting.json').read_text())
    total = (rec.get('server') or {}).get('total') or {}
    return total.get('generation_tokens'), (rec.get('energy') or {}).get('total_wh')


# ---------------------------------------------------------------- arithmetic (roll12fair)

def arith_run(d):
    rows = [json.loads(line) for line in (Path(d) / 'cases.jsonl').read_text().splitlines() if line.strip()]
    rates = [a['tokens'] / (a['finished_s'] - a['started_s']) for r in rows for a in r['agents']
             if a.get('started') and not a.get('cancelled') and a.get('tokens') and a.get('finished_s')
             and a['finished_s'] > a.get('started_s', 0)]
    rate = statistics.median(rates) if rates else 0.0
    saved = recompute = delay = 0.0
    accepted_windows = rejected_windows = 0
    for r in rows:
        agents = [a for a in r['agents'] if a.get('started') and a.get('started_s') is not None
                  and a.get('finished_s') is not None]

        def gen(a, w0, w1):
            dur = a['finished_s'] - a['started_s']
            per = a['tokens'] / dur if (a.get('tokens') and not a.get('cancelled') and dur > 0) else rate
            return per * overlap(a['started_s'], a['finished_s'], w0, w1), per
        for a in agents:
            if a.get('judged_s') is None or a.get('verdict') is None or a.get('judge_skipped'):
                continue
            w0, w1 = a['finished_s'], a['judged_s']
            siblings = [b for b in agents if b is not a]
            if a['verdict'] is True and r.get('selected_slot') == a['slot']:
                accepted_windows += 1
                saved += sum(gen(b, w0, w1)[0] for b in siblings)
            elif a['verdict'] is False:
                rejected_windows += 1
                for b in siblings:
                    if overlap(b['started_s'], b['finished_s'], w0, w1) > 0:
                        _, per = gen(b, w0, w1)
                        recompute += ARITH_PROMPT_TOKENS + per * max(0.0, w0 - b['started_s'])
                        delay += overlap(b['started_s'], b['finished_s'], w0, w1)
    return dict(saved=saved, recompute=recompute, delay_s=delay, accepted_windows=accepted_windows,
                rejected_windows=rejected_windows, median_stream_rate=rate)


# ---------------------------------------------------------------- coding (traces)

def trace_streams(path):
    """(start ts, generation intervals [(t0, t1, tokens or None)], events) of one agent trace."""
    events = []
    for line in Path(path).read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    open_req, streams = {}, []
    end_ts = max((ts(e) for e in events if 'timestamp' in e), default=None)
    for e in events:
        if e.get('type') == 'request_start':
            open_req[e.get('request_id')] = ts(e)
        elif e.get('type') == 'request_end' and e.get('request_id') in open_req:
            tok = (e.get('usage') or {}).get('completion_tokens')
            streams.append((open_req.pop(e['request_id']), ts(e), tok))
    for _, t0 in open_req.items():  # cancelled mid-stream: until the trace's last event, tokens unknown
        streams.append((t0, end_ts, None))
    return streams, events


def coding_run(d, mode):
    d = Path(d)
    summary = json.loads((d / 'summary.json').read_text())
    by_case = defaultdict(list)
    for row in summary:
        by_case[(row['task_id'], row['seed'])].append(row)
    traces = {}
    for row in summary:
        traces[(row['task_id'], row['seed'], row['agent'])] = trace_streams(row['events'] if Path(row['events']).exists()
                                                                            else d / Path(row['events']).name)
    rates = [tok / (t1 - t0) for streams, _ in traces.values() for t0, t1, tok in streams if tok and t1 > t0]
    rate = statistics.median(rates) if rates else 0.0

    def gen(key, w0, w1):
        total = 0.0
        for t0, t1, tok in traces[key][0]:
            if t1 is None or t1 <= t0:
                continue
            per = tok / (t1 - t0) if tok else rate
            total += per * overlap(t0, t1, w0, w1)
        return total

    def generated_before(key, t):
        return sum((tok / (t1 - t0) if tok else rate) * overlap(t0, t1, float('-inf'), t)
                   for t0, t1, tok in traces[key][0] if t1 and t1 > t0)

    def busy(key, w0, w1):
        return sum(overlap(t0, t1, w0, w1) for t0, t1, _ in traces[key][0] if t1)
    saved = recompute = delay = 0.0
    accepted_windows = rejected_windows = 0
    for (task, seed), rows in by_case.items():
        for row in rows:
            key = (task, seed, row['agent'])
            events = traces[key][1]
            windows = []  # (w0, w1, accepted)
            if mode == 'judge':
                start = next((ts(e) for e in events if e.get('type') == 'judge_start'), None)
                dec = next((e for e in events if e.get('type') == 'acceptance'), None)
                if start is not None and dec is not None:
                    windows.append((start, ts(dec), bool(dec.get('accepted')) and bool(row.get('winner'))))
            else:
                fb0 = next((ts(e) for e in events if e.get('type') == 'evaluation_start'
                            and e.get('phase') == 'feedback'), None)
                fb1 = next((ts(e) for e in events if e.get('type') == 'evaluation_end' and e.get('phase') == 'feedback'),
                           None)
                end = max((ts(e) for e in events if 'timestamp' in e), default=None)
                if fb0 is not None and row.get('winner'):
                    windows.append((fb0, end, True))
                elif fb0 is not None and fb1 is not None and not row.get('feedback_pass'):
                    windows.append((fb0, fb1, False))
            for w0, w1, accepted in windows:
                siblings = [(task, seed, r['agent']) for r in rows if r['agent'] != row['agent']]
                if accepted:
                    accepted_windows += 1
                    saved += sum(gen(k, w0, w1) for k in siblings)
                else:
                    rejected_windows += 1
                    for k in siblings:
                        if busy(k, w0, w1) > 0:
                            recompute += 500 + generated_before(k, w0)  # prompt (~500) + generated so far
                            delay += busy(k, w0, w1)
    return dict(saved=saved, recompute=recompute, delay_s=delay, accepted_windows=accepted_windows,
                rejected_windows=rejected_windows, median_stream_rate=rate)


# ---------------------------------------------------------------- screen

def screen(runs_root):
    runs_root = Path(runs_root)
    out = dict(rule=f'REJECT if even the optimistic bound saves < {THRESHOLD:.0%} (per family, pooled)',
               prefill_weight=PREFILL_WEIGHT, families={}, runs={})
    families = dict(arithmetic=[(r, 'arith') for r in ARITH_RUNS], coding_judge_only=[(r, 'judge') for r in JUDGE_RUNS],
                    coding_r2=[(r, 'r2') for r in R2_RUNS])
    for family, runs in families.items():
        pooled = defaultdict(float)
        for name, mode in runs:
            d = runs_root / name
            if not (d / 'arm_accounting.json').exists():
                out['runs'][name] = dict(missing=True)
                continue
            gen_total, wh = accounting(d)
            r = arith_run(d) if mode == 'arith' else coding_run(d, mode)
            opt = r['saved']
            pes = r['saved'] - PREFILL_WEIGHT * r['recompute']
            r.update(generation_tokens=gen_total, wh=wh, optimistic_saved_tokens=round(opt),
                     pessimistic_saved_tokens=round(pes), optimistic_share=opt / gen_total,
                     pessimistic_share=pes / gen_total, optimistic_wh=(opt / gen_total) * wh if wh else None,
                     pessimistic_wh=(pes / gen_total) * wh if wh else None)
            out['runs'][name] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
            for k in ('saved', 'recompute', 'delay_s', 'accepted_windows', 'rejected_windows'):
                pooled[k] += r[k]
            pooled['generation_tokens'] += gen_total
            pooled['wh'] += wh or 0.0
        if pooled['generation_tokens']:
            opt = pooled['saved'] / pooled['generation_tokens']
            pes = (pooled['saved'] - PREFILL_WEIGHT * pooled['recompute']) / pooled['generation_tokens']
            out['families'][family] = dict(
                runs=[n for n, _ in runs], optimistic_share=round(opt, 4), pessimistic_share=round(pes, 4),
                optimistic_wh=round(opt * pooled['wh'], 2), pessimistic_wh=round(pes * pooled['wh'], 2),
                resume_delay_s=round(pooled['delay_s'], 1), accepted_windows=int(pooled['accepted_windows']),
                rejected_windows=int(pooled['rejected_windows']),
                verdict='REJECT' if opt < THRESHOLD else 'SURVIVES (live validation needed)')
    out['verdict'] = ('REJECT' if all(f['verdict'] == 'REJECT' for f in out['families'].values())
                      else 'SURVIVES in ' + ', '.join(k for k, f in out['families'].items() if f['verdict'] != 'REJECT'))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--runs-root', type=Path, default=ROOT / 'runs')
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'screen-suspend-siblings')
    a = p.parse_args(argv)
    r = screen(a.runs_root)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(r, indent=1) + '\n')
    print(json.dumps(dict(verdict=r['verdict'], families=r['families']), indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
