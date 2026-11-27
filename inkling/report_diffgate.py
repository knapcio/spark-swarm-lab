#!/usr/bin/env python3
"""Report of the differential-consensus gate (DIFFGATE_PLAN.json, amended): per item the accepted program against its
frozen cross-case references on the generated inputs.

Per item: gate unavailable if no usable inputs or < MIN_REFERENCES available references (status ok); otherwise a
reference disagrees if any input's outcome differs from the accepted program's; FLAG if more than half of the available
references disagree or the accepted program is unavailable; else PASS. Secondary (reported only): the any-reference
variant. KILL if the gate flags < 40 % of the wrong items or > 10 % of the correct items (items with an available
gate; a class without any such item fails its condition); otherwise SURVIVES. INCOMPLETE (no decision) unless the
generator run embeds the frozen generator plan, is complete and holds exactly one unfaulted record per item, the
sandbox run is complete, and every population item has exactly one sandbox record whose bindings (plan, population,
generator plan and generation record sha256) match the artifacts read here. A missing generator record is INCOMPLETE,
never an unavailable gate.

usage: report_diffgate.py --generations runs/diffgate-gen-v1 --exec runs/diffgate-exec-v1 [--out DIR]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from diffgate_exec import bindings, file_sha, generation_problems  # noqa: E402
MIN_REFERENCES = 3
KILL_WRONG, KILL_CORRECT = 0.40, 0.10


def read_jsonl(path):
    out = []
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def gate(rec):
    """(status, disagreeing, available, any_disagree) with status flag | pass | unavailable."""
    if not rec or rec.get('inputs_status') != 'ok':
        return 'unavailable', 0, 0, False
    accepted = next((p for p in rec['programs'] if p['role'] == 'accepted'), None)
    refs = [p for p in rec['programs'] if p['role'] == 'reference' and p.get('status') == 'ok']
    if len(refs) < MIN_REFERENCES:
        return 'unavailable', 0, len(refs), False
    if accepted is None or accepted.get('status') != 'ok':
        return 'flag', len(refs), len(refs), True
    disagree = sum(r['outcomes'] != accepted['outcomes'] for r in refs)
    return ('flag' if disagree * 2 > len(refs) else 'pass'), disagree, len(refs), disagree > 0


def rate(n, d):
    return round(n / d, 4) if d else None


def build(pop, gen_dir, exec_dir, plan_path=ROOT / 'DIFFGATE_PLAN.json',
          gen_plan_path=ROOT / 'DIFFGATE_GEN_PLAN.json', pop_path=ROOT / 'DIFFGATE_POPULATION.json'):
    plan_sha, pop_sha, gen_plan_sha = file_sha(plan_path), file_sha(pop_path), file_sha(gen_plan_path)
    problems, gens = generation_problems(gen_dir, gen_plan_sha, pop)
    if json.loads(Path(gen_plan_path).read_text()).get('population_sha256') != pop_sha:
        problems.append('the generator plan is not bound to this population')
    ex_summary = json.loads((Path(exec_dir) / 'summary.json').read_text()) \
        if (Path(exec_dir) / 'summary.json').exists() else {}
    if ex_summary.get('complete') is not True:
        problems.append('the sandbox run is not complete')
    records = read_jsonl(Path(exec_dir) / 'records.jsonl')
    by_item = defaultdict(list)
    for r in records:
        by_item[r['item']].append(r)
    ids = {i['item_id'] for i in pop['items']}
    if set(by_item) != ids or any(len(v) != 1 for v in by_item.values()):
        problems.append('sandbox records are not exactly one per population item')
    unbound = [i for i in sorted(ids) if len(by_item.get(i, [])) == 1 and i in gens
               and by_item[i][0].get('bindings') != bindings(plan_sha, pop_sha, gen_plan_sha, gens[i])]
    if unbound:
        problems.append(f'sandbox records not bound to these artifacts: {unbound[:3]}')
    out = dict(study='diffgate-v1', problems=problems)
    if problems:
        return dict(out, decision='INCOMPLETE (no decision)')
    items, counts = [], defaultdict(lambda: defaultdict(int))
    for item in pop['items']:
        rec = by_item[item['item_id']][0]
        status, disagree, available, any_dis = gate(rec)
        refs_wrong = sum(not r['holdout_pass'] for r in item['references'])
        items.append(dict(item=item['item_id'], run=item['run'], task_id=item['task_id'], seed=item['seed'],
                          kind=item['kind'], gate=status, disagreeing=disagree, available_references=available,
                          any_reference_disagrees=any_dis, references_hidden_wrong=refs_wrong,
                          inputs=len(rec.get('inputs') or []), sandbox_seconds=rec.get('sandbox_seconds')))
        c = counts[item['kind']]
        c['items'] += 1
        c[status] += 1
        c['any_flag'] += status != 'unavailable' and any_dis
    wrong, correct = counts['wrong'], counts['correct']
    wrong_avail, correct_avail = wrong['flag'] + wrong['pass'], correct['flag'] + correct['pass']
    flag_wrong, flag_correct = rate(wrong['flag'], wrong_avail), rate(correct['flag'], correct_avail)
    kill = (wrong_avail == 0 or correct_avail == 0 or wrong['flag'] < KILL_WRONG * wrong_avail
            or correct['flag'] > KILL_CORRECT * correct_avail)
    per_task, per_run = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    for i in items:
        per_task[i['task_id']][f"{i['kind']}_{i['gate']}"] += 1
        per_run[i['run']][f"{i['kind']}_{i['gate']}"] += 1
        per_run[i['run']]['sandbox_seconds'] += i['sandbox_seconds'] or 0
    return dict(out, items=items, counts={k: dict(v) for k, v in counts.items()},
                flagged_wrong=dict(flagged=wrong['flag'], available=wrong_avail, rate=flag_wrong),
                flagged_correct=dict(flagged=correct['flag'], available=correct_avail, rate=flag_correct),
                any_reference_variant=dict(wrong=rate(wrong['any_flag'], wrong_avail),
                                           correct=rate(correct['any_flag'], correct_avail)),
                gate_unavailable_share=rate(wrong['unavailable'] + correct['unavailable'], len(pop['items'])),
                generator_tokens=sum(r.get('tokens_generated') or 0 for r in gens.values()),
                sandbox_seconds=round(sum(i['sandbox_seconds'] or 0 for i in items), 1),
                per_task={k: dict(v) for k, v in per_task.items()},
                per_run={k: dict(v) for k, v in per_run.items()},
                caveat='references can be wrong themselves and can share a common bug with the accepted program',
                decision='KILL' if kill else 'SURVIVES (a live validation would follow)')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--population', type=Path, default=ROOT / 'DIFFGATE_POPULATION.json')
    p.add_argument('--plan', type=Path, default=ROOT / 'DIFFGATE_PLAN.json')
    p.add_argument('--gen-plan', type=Path, default=ROOT / 'DIFFGATE_GEN_PLAN.json')
    p.add_argument('--generations', type=Path, required=True)
    p.add_argument('--exec', dest='exec_dir', type=Path, required=True)
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'diffgate-v1')
    a = p.parse_args(argv)
    r = build(json.loads(a.population.read_text()), a.generations, a.exec_dir, a.plan, a.gen_plan, a.population)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(r, indent=1) + '\n')
    print(json.dumps(dict(decision=r['decision'], flagged_wrong=r.get('flagged_wrong'),
                          flagged_correct=r.get('flagged_correct'), problems=r['problems'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
