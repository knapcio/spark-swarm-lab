#!/usr/bin/env python3
"""The two frozen arm plans of the live differential-gate A/B (DIFFGATE_LIVE_PLAN.json): the production coding default
(CODING_BASELINE_S64_PLAN.json's path) on 216 fresh cases, control vs gate. The plans differ only in ARM_FIELDS.

usage: diffgate_live_plans.py --gate-revision REV [--out-dir DIR]
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

BASE_PLAN, DESIGN, GATE_PROMPTS = 'CODING_BASELINE_S64_PLAN.json', 'DIFFGATE_LIVE_PLAN.json', 'DIFFGATE_PLAN.json'
SEEDS, OFFSET = list(range(70, 79)), 70700
ARMS = ('control', 'gate')
FILES = {'control': 'CODING_DIFFGATE_CONTROL_PLAN.json', 'gate': 'CODING_DIFFGATE_GATE_PLAN.json'}
ARM_FIELDS = ('study', 'ab_arm', 'runner', 'differential_gate', 'execution')
GATE_SOURCE = '.runtime/diffgate-source'
PINNED = ('run_coding_earlystop.py', 'run_coding_diffgate.py', 'run_coding_agents.py', 'run_benchmark.py',
          'run_agents72.py', 'run_variants.py', 'sandbox_code.py', 'inkling/diffgate_arms.py',
          'inkling/suspend_arms.py',
          'inkling/admit.py', 'inkling/fleet_lease.py', 'inkling/arms.py', 'inkling/energy.py',
          'inkling/sandbox_outputs.py', 'inkling/diffgate_exec.py', 'inkling/report_diffgate_live.py',
          'inkling/report_suspend_ab.py')
GATE_FILES = ('diffgate_gen.py', 'forced72.py', 'harness.py', 'tail_replay.py', 'extend_replay.py', 'followup72.py')


def blob_sha(tree, revision, name):
    data = subprocess.run(['git', '-C', str(tree), 'show', f'{revision}:{name}'], capture_output=True,
                          check=True).stdout
    return hashlib.sha256(data).hexdigest()


def make(gate_revision, root=ROOT):
    base = json.loads((Path(root) / BASE_PLAN).read_text())
    design = json.loads((Path(root) / DESIGN).read_text())
    prompts = json.loads((Path(root) / GATE_PROMPTS).read_text())['generator_call']
    pins = {n: hashlib.sha256((Path(root) / n).read_bytes()).hexdigest() for n in PINNED}
    for name in ('coding_forced.py', 'coding_forced_worker.py', 'forced72.py', 'harness.py', 'sandbox_code.py',
                 'coding_harness.py'):
        pins[f"{base['source_path']}/{name}"] = blob_sha(root, base['source_revision'], name)  # shared object store
    for name in GATE_FILES:
        pins[f'{GATE_SOURCE}/{name}'] = blob_sha(root, gate_revision, name)
    plans = {}
    for arm in ARMS:
        plan = copy.deepcopy(base)
        plan['matrix'] = dict(base['matrix'], seeds=SEEDS)
        plan.update(status='FROZEN', study=f'coding-diffgate-v1-{arm}', study_group='coding-diffgate-v1',
                    ab_arm=arm, arm_order=list(ARMS), agent_seed_offset=OFFSET, code_sha256=pins,
                    design=DESIGN, design_sha256=hashlib.sha256((Path(root) / DESIGN).read_bytes()).hexdigest(),
                    question=design['question'], decision_rule=design['decision_rule'], cases=design['cases'],
                    frozen_note=('Frozen before any call with fresh seeds 70-78 (coding-hard-v1 used <= 66) and '
                                 'offset 70700 (unused); the arms differ only in ' + ', '.join(ARM_FIELDS) + '.'),
                    report='inkling/report_diffgate_live.py',
                    execution=(f'python inkling/diffgate_arms.py --plan {FILES[arm]} --output '
                               f'runs/coding-diffgate-v1-{arm} (alone on the fleet; arm order control, gate)'))
        for stale in ('arms_order', 'primary_outcomes', 'secondary_outcomes', 'arm'):
            plan.pop(stale, None)
        if arm == 'control':
            plan['runner'] = 'run_coding_earlystop.py'
        else:
            plan['runner'] = 'run_coding_diffgate.py'
            plan['differential_gate'] = dict(rule='differential_v1', system=prompts['system'], user=prompts['user'],
                                             think_tokens=8192, total_tokens=10240, source_path=GATE_SOURCE,
                                             source_revision=gate_revision, design=design['gate'])
        plans[arm] = plan
    return plans


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--gate-revision', required=True)
    p.add_argument('--out-dir', type=Path, default=ROOT)
    a = p.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', a.gate_revision):
        p.error('--gate-revision must be a full commit hash')
    plans = make(a.gate_revision)
    for arm, plan in plans.items():
        path = a.out_dir / FILES[arm]
        if path.exists():
            p.error(f'{path} exists')
        path.write_text(json.dumps(plan, indent=1) + '\n')
    print(json.dumps(FILES))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
