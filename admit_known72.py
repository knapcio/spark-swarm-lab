#!/usr/bin/env python3
"""Fresh read-only admission for a known72 agent run: source checks, four retained containers, idle endpoints."""
import argparse
import json
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import run_agents72 as runner

IMAGE = '6ff5ff0ddf3658d2c2d677dac5ca2d4726ce0156b4371166d918181b210bd4bc'
CONTAINERS = {'spark-01': '2852bbfaa4ae', 'spark-02': 'fb233e4057cf', 'spark-03': '94155d2ac1f7', 'spark-04': 'd59fa32fef85'}
# 128K serving clones (ctx_switch.py): same local image as the original on each node, only --max-model-len differs.
CLONES = {'spark-01': 'c55680db5c3c', 'spark-02': 'af24362acd78', 'spark-03': '43faffa72b36', 'spark-04': '34e7cef7a0fd'}


def metric(text, name):
    return float(re.search(rf'^vllm:{name}{{[^}}]*}} (\S+)', text, re.M).group(1))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--note', default='')
    p.add_argument('--allow-busy', action='store_true',
                   help='concurrent owned runs allowed (no wall-clock limits): identity/health still required, load recorded')
    p.add_argument('--long-context', action='store_true', help='admit the 128K clones instead of the 16K originals')
    a = p.parse_args(argv)
    name = 'swarm-lightning-128k' if a.long_context else 'swarm-lightning'
    plan = json.loads(a.plan.read_text())
    source = a.source.resolve()
    runner.validate_source(source, plan['source_revision'])
    endpoints = [f'http://127.0.0.1:{port}/v1' for port in range(18081, 18085)]
    nodes, ok_all = [], True
    for i, n in enumerate(['01', '02', '03', '04']):
        host, cid, image, running, started, oom, restarts = subprocess.check_output(
            ['ssh', '-o', 'BatchMode=yes', 'Spark_' + n, 'hostname; docker inspect ' + name + ' --format '
             '"{{.Id}} {{.Config.Image}} {{.State.Running}} {{.State.StartedAt}} {{.State.OOMKilled}} {{.RestartCount}}"'],
            text=True).split()
        if a.long_context:  # clone must run the original's exact local image
            images = subprocess.check_output(['ssh', '-o', 'BatchMode=yes', 'Spark_' + n,
                                              'docker inspect --format "{{.Image}}" swarm-lightning swarm-lightning-128k'],
                                             text=True).split()
            image = IMAGE if len(images) == 2 and images[0] == images[1] else 'MISMATCH'
        text = urllib.request.urlopen(endpoints[i].replace('/v1', '/metrics'), timeout=5).read().decode()
        health = urllib.request.urlopen(endpoints[i].replace('/v1', '/health'), timeout=5).status
        node = dict(hostname=host, container_id=cid, image=image, started_at=started, oom=oom, restarts=int(restarts),
                    running_requests=metric(text, 'num_requests_running'), waiting_requests=metric(text, 'num_requests_waiting'),
                    health=health)
        node['ok'] = (running == 'true' and oom == 'false' and restarts == '0' and health == 200 and image.endswith(IMAGE)
                      and cid.startswith((CLONES if a.long_context else CONTAINERS)[host])
                      and (a.allow_busy or node['running_requests'] == node['waiting_requests'] == 0))
        ok_all &= node['ok']
        nodes.append(node)
    receipt = dict(protocol='known72-agent-run-admission', verified=ok_all, all_four_owned_healthy_idle=ok_all and not a.allow_busy,
                   allow_busy=a.allow_busy, container_name=name,
                   verified_utc=datetime.now(timezone.utc).isoformat(), plan=str(a.plan), plan_status=plan['status'],
                   source_revision=plan['source_revision'], source_sha256=runner.hashes(source), endpoints=endpoints,
                   runner_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), nodes=nodes, note=a.note)
    with a.output.open('x') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(verified=ok_all, nodes=[n['ok'] for n in nodes])))
    return 0 if ok_all else 1


if __name__ == '__main__':
    raise SystemExit(main())
