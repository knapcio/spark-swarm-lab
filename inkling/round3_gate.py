#!/usr/bin/env python3
"""Gates and case lists of study swarm-round3-hard17-v1 (offline; no model, no fleet).

screen PATH
    Gate of a dev screen on recorded abstentions. PATH is a closer_replay output directory (its cases.jsonl) or a
    tail_replay cases file (OUTPUT.cases.jsonl, or a directory holding exactly one *.cases.jsonl). Prints
    {cases, rescued, wrong, faults, pass}; exit 0 if pass, 10 if not. rescued = the case's judge-accepted answer is
    verifier-correct; wrong = a judge-accepted answer is verifier-wrong; pass = rescued >= 4 and wrong == 0.
      closer_replay rows: the case answer is the first accepted closer plan in time: rescued = solved, wrong = wrong.
      tail_replay rows: replays are independent (no first-accept order), so a case counts as wrong if ANY accepted
      replay plan is verifier-wrong, and as rescued only if it was an abstention (outcome case_rescue), at least one
      accepted plan is verifier-correct and none is wrong. Rows whose case was already answered are not counted.
    faults = rows with infra/replay errors, or (recall) a replay or judge error / judge infra in the replay records
    file next to the cases file (X.jsonl), or no such records file (reported; the gate is the frozen rule above).

abstentions --run RUN_DIR [--output FILE]
    D's clean abstentions under the frozen resume rule (run_variants.arm_latest: latest clean row per case, resume
    segments merged) in the case_list format esc_extra expects ({"cases": [[task_id, seed], ...]}). Refuses if the
    run still has unresolved infra cases or the output exists.
    Default output: results/swarm-round3-hard17-v1/d_abstentions.json.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import run_variants  # noqa: E402

STUDY = 'swarm-round3-hard17-v1'
RESCUE_GATE = 4
DEFAULT_ABSTENTIONS = Path('results') / STUDY / 'd_abstentions.json'


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def screen_file(path):
    path = Path(path)
    if path.is_dir():
        if (path / 'cases.jsonl').exists():
            return path / 'cases.jsonl'
        found = sorted(path.glob('*.cases.jsonl'))
        if len(found) != 1:
            raise SystemExit(f'{path}: expected cases.jsonl or exactly one *.cases.jsonl, found {len(found)}')
        return found[0]
    return path


def recall_faults(cases_path):
    """Judge or replay faults per case from the replay records next to a tail_replay cases file (X.cases.jsonl ->
    X.jsonl): {(run, task_id, seed): True} for every case with a replay error, a judge error or judge infra. Returns
    None if the records file is missing (then every case counts as faulted: its judge outcome is unverifiable)."""
    cases_path = Path(cases_path)
    records = cases_path.with_name(cases_path.name.removesuffix('.cases.jsonl') + '.jsonl')
    if not records.exists() or records == cases_path:
        return None
    faults = {}
    for r in read_rows(records):
        if r.get('error') or r.get('judge_error') or (r.get('judge_infra') or 0) > 0:
            faults[(r.get('run'), r['task_id'], r['seed'])] = True
    return faults


def case_outcome(row, judge_faults=None):
    """(kind, rescued, wrong, fault) of one screen row; kind 'closer' or 'recall'; rescued/wrong None if not counted.
    judge_faults: recall_faults() of the screen (None: records missing -> every recall row faulted)."""
    if 'closers' in row or 'rescue' in row:
        return 'closer', bool(row.get('solved')), bool(row.get('wrong')), bool(row.get('infra'))
    if 'outcome' in row and 'judge_accepted' in row:
        fault = bool(row.get('replay_errors')) or judge_faults is None or \
            judge_faults.get((row.get('run'), row['task_id'], row['seed']), False)
        if row.get('recorded_answered') is not False:
            return 'recall', None, None, fault
        wrong = (row.get('judge_accepted_wrong') or 0) > 0
        rescued = row['outcome'] == 'case_rescue' and not wrong and (row.get('judge_accepted_verifier_solved') or 0) > 0
        return 'recall', rescued, wrong, fault
    raise ValueError(f'unknown screen row: {sorted(row)[:8]}')


def screen(path):
    cases_file = screen_file(path)
    rows = read_rows(cases_file)
    judge_faults = recall_faults(cases_file)
    kinds, cases, rescued, wrong, faults, rescued_cases = set(), 0, 0, 0, 0, []
    for row in rows:
        kind, r, w, f = case_outcome(row, judge_faults)
        kinds.add(kind)
        faults += f
        if r is None:
            continue
        cases += 1
        rescued += r
        wrong += w
        if r:
            rescued_cases.append([row.get('run'), row['task_id'], row['seed']])
    if len(kinds) > 1:
        raise SystemExit('mixed closer and recall rows')
    return dict(kind=next(iter(kinds), None), file=str(screen_file(path)), cases=cases, rescued=rescued, wrong=wrong,
                faults=faults, rescued_cases=rescued_cases, rule=f'rescued >= {RESCUE_GATE} and wrong == 0',
                **{'pass': rescued >= RESCUE_GATE and wrong == 0})


def abstentions(run_dir, root=ROOT, policy='roll12strategy'):
    arm = run_variants.arm_latest(run_dir, root, policy=policy)
    if arm['unresolved']:
        raise SystemExit(f"{arm['base'].name}: unresolved infra cases {arm['unresolved'][:3]}; resume the arm first")
    keys = sorted((k for k in arm['clean'] if not arm['latest'][k][1]['answered']), key=lambda k: arm['index'][k])
    return dict(protocol='swarm-clean-abstentions-v1', study=STUDY, run=str(arm['base']),
                segments=[s.name for s in arm['segments']], policy=policy,
                rule='latest clean row per (task, seed) over the arm and its -resumeN segments; answered == false',
                superseded=arm['superseded'], cases=[[k[0], k[1]] for k in keys])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('screen')
    s.add_argument('path', type=Path)
    b = sub.add_parser('abstentions')
    b.add_argument('--run', type=Path, required=True)
    b.add_argument('--output', type=Path, default=DEFAULT_ABSTENTIONS)
    b.add_argument('--root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.cmd == 'screen':
        result = screen(a.path)
        print(json.dumps(result))
        return 0 if result['pass'] else 10
    out = a.output if a.output.is_absolute() else a.root / a.output
    if out.exists():
        raise SystemExit(f'{out} exists')
    result = abstentions(a.run if a.run.is_absolute() else a.root / a.run, a.root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps(dict(output=str(out), cases=len(result['cases']), segments=result['segments'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
