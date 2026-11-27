#!/usr/bin/env python3
"""The frozen fleet plan of the differential gate's generator calls (DIFFGATE_GEN_PLAN.json): one call per frozen
population item (DIFFGATE_POPULATION.json), the generic prompts of DIFFGATE_PLAN.json, driver diffgate_gen.py at the
given research/diffgate-v1 revision, <= 20 requests per node on the canonical four nodes.

usage: diffgate_gen_plan.py --source-revision REV --output DIFFGATE_GEN_PLAN.json
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import collab_plans  # noqa: E402  (fleet and serving identity)

THINK, TOTAL, PER_NODE = 8192, 10240, 20
PINNED = ('inkling/fleet_lease.py', 'inkling/admit.py')  # loaded by the driver from the main tree


def make(revision, root=ROOT):
    plan = json.loads((Path(root) / 'DIFFGATE_PLAN.json').read_text())
    pop_path = Path(root) / 'DIFFGATE_POPULATION.json'
    pop = json.loads(pop_path.read_text())
    gen = plan['generator_call']
    return dict(protocol='diffgate-gen-v1', study='diffgate-gen-v1', status='FROZEN', screen='diffgate',
                source_revision=revision, source_path='.runtime/diffgate-source', driver='diffgate_gen.py',
                system=gen['system'], user=gen['user'], think_tokens=THINK, total_tokens=TOTAL,
                per_node=PER_NODE, nodes=4, fleet=collab_plans.FLEET, serving=collab_plans.serving(root),
                judge_code_sha256={n: hashlib.sha256((Path(root) / n).read_bytes()).hexdigest() for n in PINNED},
                population_sha256=hashlib.sha256(pop_path.read_bytes()).hexdigest(),
                items=[dict(item_id=i['item_id'], payload=i['payload']) for i in pop['items']],
                execution='diffgate_gen.py --plan DIFFGATE_GEN_PLAN.json --run --output runs/diffgate-gen-v1 from a '
                          'clean worktree of the source revision (lease, admission, raw idle gauges, fenced drain)',
                estimate=f"{len(pop['items'])} calls x <= {TOTAL} generated tokens, <= {PER_NODE} per node")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source-revision', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', a.source_revision):
        p.error('--source-revision must be a full commit hash')
    if a.output.exists():
        p.error('output exists')
    plan = make(a.source_revision)
    a.output.write_text(json.dumps(plan, indent=1) + '\n')
    print(json.dumps(dict(items=len(plan['items']), source_revision=a.source_revision)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
