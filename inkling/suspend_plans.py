#!/usr/bin/env python3
"""Frozen A/B plans of the idea #5 LIVE validation (astra IDEAS 2026-11-26 #5; coordinator 2026-11-27) for the only
family that survived the offline bound, judge-only coding (results/screen-suspend-siblings: optimistic 22.2 %,
pessimistic 13.9 % of server generation tokens).

Mechanism (what this server allows): hold_dispatch. True pausing of an in-flight stream is not possible here (SGLang has
no per-request pause, a stopped client does not stop decoding, and per-request seeds are not honoured, so an aborted
stream cannot be resumed token-exactly). One judge per case at a time (an atomic ownership file taken before the
first judge call). While a candidate's judge verdict is PENDING, its case siblings hold their NEXT model dispatch and no
new agent of the case starts; streams already in flight continue. On an acceptance the siblings are terminated (as
today); on a rejection they resume. The frozen wall deadline is the same in both arms (no credit for held time). Offline bound of this mechanism on coding-notests-v1-judge:
12.3 % of server generation tokens (dispatches that started inside accepted pending windows; median window 576 s),
against 22.2 % for true suspension; a rejection costs delay only (nothing is recomputed).

Arms (each alone on the fleet via inkling/suspend_arms.py; arm_order control, hold):
  control  the production no-provided-tests judge path of coding-notests-v1-judge (run_coding_earlystop.py, acceptance
           judge, early stop first_accepted_in_time, R2 rolling width 2 up to 8 agents, judge 16,384 + 2,048 tokens,
           2 calls, per-agent 32,768 tokens, 20 agents per node);
  hold     the same plus suspend_siblings = hold_dispatch.
Both use the same worker revision (research/coding-suspend-v1; without --hold-file it is the 9d60b36 worker), the same
72 fresh cases (coding-hard-v1 evaluation split, 24 tasks x seeds 58-60, never used before on this corpus), the same
judge and budgets.

Pre-registered rule (inkling/report_suspend_ab.py): PASS only if (1) the hold arm has no additional wrong answers
(answered but not solved: wrong(hold) <= wrong(control)), (2) solved(hold) >= solved(control) - 1, and (3) GPU energy
per solved case (inkling/energy.py, the arm's window) <= 0.90 x control; otherwise STOP. Server generated tokens, wall,
pending windows and holds are reported. Both arms must be complete (no runner errors, all 72 cases, runner exit 0,
confirmed drain, energy covered on every node) or the report says INCOMPLETE.

usage: suspend_plans.py --source-revision REV [--root DIR]   (writes CODING_SUSPEND_CONTROL_PLAN.json and
                                                               CODING_SUSPEND_HOLD_PLAN.json next to this repository)
"""
import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import collab_plans  # noqa: E402  (serving identity)
import screen_suspend_siblings as screen  # noqa: E402  (trace streams of the offline screen)

BASE_PLAN = 'CODING_NOTESTS_JUDGE_PLAN.json'
SEEDS = [58, 59, 60]
SOURCE_PATH = '.runtime/coding-suspend-source'
ARMS = ('control', 'hold')
FILES = {'control': 'CODING_SUSPEND_CONTROL_PLAN.json', 'hold': 'CODING_SUSPEND_HOLD_PLAN.json'}
PINNED = ('run_coding_earlystop.py', 'run_coding_agents.py', 'run_benchmark.py', 'run_agents72.py',
          'inkling/suspend_arms.py', 'inkling/admit.py', 'inkling/fleet_lease.py', 'inkling/arms.py',
          'inkling/energy.py', 'inkling/report_suspend_ab.py')
WORKER_FILES = ('coding_forced.py', 'coding_forced_worker.py', 'forced72.py', 'harness.py', 'sandbox_code.py',
                'coding_harness.py')
RULE = dict(wrong='wrong(hold) <= wrong(control): no additional wrong answers (answered but not solved)',
            solved='solved(hold) >= solved(control) - 1',
            energy='GPU Wh per solved case (inkling/energy.py over the arm window) <= 0.90 x control',
            decision='PASS only if all three hold; otherwise STOP',
            reported='server generated tokens, wall, energy, pending windows and holds per arm')


BOUND_RUN = 'coding-notests-v1-judge'


def hold_bound(root, run=BOUND_RUN):
    """Offline bound of hold_dispatch on a recorded judge-only run: the generation of sibling streams DISPATCHED inside
    a pending window that ended in the case's acceptance (a hold would have kept them from starting; the siblings were
    terminated at the acceptance), as a share of the run's server generation tokens. In-flight streams (the true
    suspension bound of the screen) are reported beside it."""
    from collections import defaultdict
    import statistics
    d = Path(root) / 'runs' / run
    summary = json.loads((d / 'summary.json').read_text())
    traces = {(r['task_id'], r['seed'], r['agent']): screen.trace_streams(r['events'] if Path(r['events']).exists()
                                                                          else d / Path(r['events']).name)
              for r in summary}
    rates = [tok / (t1 - t0) for streams, _ in traces.values() for t0, t1, tok in streams if tok and t1 > t0]
    rate = statistics.median(rates) if rates else 0.0
    by_case = defaultdict(list)
    for r in summary:
        by_case[(r['task_id'], r['seed'])].append(r)
    held = inflight = 0.0
    windows = []
    for (task, seed), rows in by_case.items():
        for row in rows:
            events = traces[(task, seed, row['agent'])][1]
            w0 = next((screen.ts(e) for e in events if e.get('type') == 'judge_start'), None)
            dec = next((e for e in events if e.get('type') == 'acceptance'), None)
            if w0 is None or dec is None or not (dec.get('accepted') and row.get('winner')):
                continue
            w1 = screen.ts(dec)
            windows.append(w1 - w0)
            for other in rows:
                if other['agent'] == row['agent']:
                    continue
                for t0, t1, tok in traces[(task, seed, other['agent'])][0]:
                    if t1 is None or t1 <= t0:
                        continue
                    gen = (tok / (t1 - t0) if tok else rate) * screen.overlap(t0, t1, w0, w1)
                    inflight += gen
                    if w0 <= t0 < w1:
                        held += gen
    total, wh = screen.accounting(d)
    return dict(run=run, accepted_windows=len(windows),
                median_window_seconds=round(statistics.median(windows), 1) if windows else None,
                hold_dispatch_share=round(held / total, 4) if total else None,
                true_suspension_share=round(inflight / total, 4) if total else None,
                generation_tokens=total, energy_wh=wh)


def used_seeds(root):
    """Every seed any committed plan or recorded run used on coding-hard-v1."""
    seen = set()
    paths = [p for p in Path(root).glob('*.json')] + list((Path(root) / 'runs').glob('*/metadata.json'))
    for path in paths:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                m = o.get('matrix')
                if isinstance(m, dict) and 'coding-hard-v1/' in str(m.get('tasks', '')):
                    seen.update(s for s in m.get('seeds', []) if type(s) is int)
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return seen


def worker_hashes(root, revision):
    out = {}
    for name in WORKER_FILES:
        blob = subprocess.run(['git', '-C', str(Path(root) / SOURCE_PATH), 'show', f'{revision}:{name}'],
                              capture_output=True, check=True).stdout
        out[f'{SOURCE_PATH}/{name}'] = hashlib.sha256(blob).hexdigest()
    return out


def make(root, revision, generator_root=ROOT):
    base = json.loads((Path(root) / BASE_PLAN).read_text())
    clash = sorted(set(SEEDS) & used_seeds(root))
    if clash:
        raise ValueError(f'seeds already used on coding-hard-v1: {clash}')
    pins = {name: hashlib.sha256((Path(generator_root) / name).read_bytes()).hexdigest() for name in PINNED}
    pins.update(worker_hashes(root, revision))
    bound = hold_bound(root)
    plans = {}
    for arm in ARMS:
        plan = {k: copy.deepcopy(v) for k, v in base.items()
                if k in ('protocol', 'limits', 'scheduling', 'runner', 'agent_variants', 'agent_seed_offset',
                         'early_stop', 'selection', 'rolling', 'acceptance', 'judge', 'arm')}
        plan['matrix'] = dict(base['matrix'], seeds=SEEDS)
        plan.update(status='FROZEN', study=f'coding-suspend-v1-{arm}', study_group='coding-suspend-v1',
                    screen='idea-5-live', ab_arm=arm, arm_order=list(ARMS), source_revision=revision,
                    source_path=SOURCE_PATH, serving=collab_plans.serving(generator_root), code_sha256=pins,
                    question=__doc__.split('\n\n')[0], mechanism=__doc__.split('\n\n')[1],
                    arms_text=__doc__.split('\n\n')[2], decision_rule=RULE, offline_bound=bound,
                    base_plan=BASE_PLAN, base_plan_sha256=hashlib.sha256((Path(root) / BASE_PLAN).read_bytes())
                    .hexdigest(),
                    execution=(f'python inkling/suspend_arms.py --plan {FILES[arm]} --output '
                               f'runs/coding-suspend-v1-{arm} (alone on the fleet: lease, admission, raw idle gauges, '
                               'fenced drain), in arm_order'),
                    report='inkling/report_suspend_ab.py --control CODING_SUSPEND_CONTROL_PLAN.json --hold '
                           'CODING_SUSPEND_HOLD_PLAN.json',
                    frozen_note='Frozen before any call with seeds 58-60 on coding-hard-v1 (no earlier plan or run '
                                'used them).')
        if arm == 'hold':
            plan['suspend_siblings'] = 'hold_dispatch'
        plans[arm] = plan
    return plans


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT, help='repository with runs/ and the base plan')
    p.add_argument('--source-revision', required=True)
    p.add_argument('--out-dir', type=Path, default=ROOT)
    a = p.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', a.source_revision):
        p.error('--source-revision must be a full commit hash')
    plans = make(a.root, a.source_revision)
    for arm, plan in plans.items():
        path = a.out_dir / FILES[arm]
        if path.exists():
            p.error(f'{path} exists')
        path.write_text(json.dumps(plan, indent=1) + '\n')
    print(json.dumps({arm: FILES[arm] for arm in plans}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
