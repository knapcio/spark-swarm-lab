#!/usr/bin/env python3
"""Fresh read-only admission for an Inkling-2-Mini Swarm Lab run.

Same receipt contract as admit_known72.py (``verified``, ``verified_utc``), for the Inkling serving stack:
on each of the four Sparks an SGLang ``swarm-inkling`` container plus the vLLM-dialect adapter
``swarm-inkling-shim`` (inkling/shim.py) must run from the same image digest, with the same launch
arguments, no OOM, no restarts, the expected shim source hash, health 200 through the local tunnel and
(unless --allow-busy) zero running/waiting requests.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import run_agents72 as runner  # noqa: E402

def metric(text, name):
    m = re.search(rf'^vllm:{name}{{[^}}]*}} (\S+)', text, re.M)
    return float(m.group(1)) if m else None


def inspect(node, name):
    raw = subprocess.check_output(['ssh', '-o', 'BatchMode=yes', 'Spark_' + node,
                                   f'hostname; docker inspect {name}'], text=True)
    host, body = raw.split('\n', 1)
    c = json.loads(body)[0]
    return dict(hostname=host.strip(), container_id=c['Id'][:12], image=c['Image'], running=c['State']['Running'],
                started_at=c['State']['StartedAt'], oom=c['State']['OOMKilled'], restarts=c['RestartCount'],
                cmd=c['Config']['Cmd'], entrypoint=c['Config']['Entrypoint'],
                env=sorted(e for e in c['Config']['Env'] if e.startswith(('SGLANG_', 'MAX_JOBS', 'THINK', 'NOTHINK'))))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--note', default='')
    p.add_argument('--allow-busy', action='store_true')
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    runner.validate_source(a.source.resolve(), plan['source_revision'])
    shim_sha = hashlib.sha256((HERE / 'shim.py').read_bytes()).hexdigest()
    expected = plan.get('serving', {})
    nodes, ok_all, reference = [], True, None
    for i, n in enumerate(['01', '02', '03', '04']):
        server, shim = inspect(n, 'swarm-inkling'), inspect(n, 'swarm-inkling-shim')
        remote_sha = subprocess.check_output(['ssh', '-o', 'BatchMode=yes', 'Spark_' + n,
                                              'sha256sum ~/swarm-lab/inkling/shim.py'], text=True).split()[0]
        base = f'http://127.0.0.1:{18081 + i}'
        text = urllib.request.urlopen(base + '/metrics', timeout=10).read().decode()
        health = urllib.request.urlopen(base + '/health', timeout=10).status
        signature = dict(image=server['image'], cmd=server['cmd'], env=server['env'])
        reference = reference or signature
        node = dict(node=n, server=server, shim=shim, shim_sha256=remote_sha, health=health,
                    running_requests=metric(text, 'num_requests_running'),
                    waiting_requests=metric(text, 'num_requests_waiting'))
        node['ok'] = (server['hostname'] == f'spark-{n}' and server['running'] and shim['running']
                      and not server['oom'] and not shim['oom'] and server['restarts'] == shim['restarts'] == 0
                      and shim['image'] == server['image'] and remote_sha == shim_sha and health == 200
                      and signature == reference
                      and (not expected.get('image_id') or server['image'] == expected['image_id'])
                      and (a.allow_busy or node['running_requests'] == node['waiting_requests'] == 0))
        ok_all &= node['ok']
        nodes.append(node)
    receipt = dict(protocol='inkling-agent-run-admission', verified=ok_all, allow_busy=a.allow_busy,
                   verified_utc=datetime.now(timezone.utc).isoformat(), plan=str(a.plan),
                   plan_status=plan['status'], source_revision=plan['source_revision'], shim_sha256=shim_sha,
                   serving_signature=reference, nodes=nodes, note=a.note)
    a.output.write_text(json.dumps(receipt, indent=1) + '\n')
    print(json.dumps(dict(verified=ok_all, nodes=[(x['node'], x['ok']) for x in nodes])))
    return 0 if ok_all else 1


if __name__ == '__main__':
    raise SystemExit(main())
