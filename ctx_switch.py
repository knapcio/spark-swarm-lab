#!/usr/bin/env python3
"""Long-context Nemotron serving for the context-gap experiments (owner: the fleet is ours on Nemotron).

The 16K serving containers (`swarm-lightning`, ids pinned in ds_switch.CONTAINERS) are never modified or
removed. `create` clones each one into a sibling `swarm-lightning-128k` with the SAME local image id, mounts,
host networking, IPC and every vLLM argument except --max-model-len 131072 (the model's native context is
1,048,576). Only one of the two runs per node; both bind the same local port, so the owned SSH tunnels
18081-18084 keep working unchanged. Head guards are checked before every switch and never touched.

Usage: ctx_switch.py create | to-128k | to-16k | status      (prints a JSON receipt per step)
"""
import json
import shlex
import sys
import time
import urllib.request

from ds_switch import CONTAINERS, NODES, gpu_apps, guards_ok, record, fail, ssh

LONG = 'swarm-lightning-128k'
SHORT = 'swarm-lightning'
MAX_LEN = '131072'


def inspect(node, name):
    out = ssh(node, f'docker inspect {name}')
    return json.loads(out.stdout)[0] if out.returncode == 0 else None


def create():
    for node in NODES:
        base = inspect(node, SHORT)
        if base is None or not base['Id'].startswith(CONTAINERS[node]):
            fail('create', 'unexpected base container on ' + node)
        if inspect(node, LONG) is not None:
            record('create', node=node, skipped='exists')
            continue
        args = list(base['Config']['Cmd'])
        i = args.index('--max-model-len')
        require_old = args[i + 1] == '16384'
        if not require_old or base['Config']['Entrypoint'] != ['vllm', 'serve']:
            fail('create', 'base arguments differ from the reviewed 16K config on ' + node)
        args[i + 1] = MAX_LEN
        mounts = ' '.join(f"-v {m['Source']}:{m['Destination']}{'' if m['RW'] else ':ro'}" for m in base['Mounts'])
        command = (f"docker create --name {LONG} --network host --ipc host --gpus all {mounts} "
                   f"--label swarm-lab.owner=swarm-lab-20261115 --label swarm-lab.clone-of={base['Id'][:12]} "
                   f"--entrypoint vllm {base['Image']} serve " + ' '.join(shlex.quote(a) for a in args))
        out = ssh(node, command)
        record('create', node=node, rc=out.returncode, id=out.stdout.strip()[:12], err=out.stderr.strip()[-200:])
        if out.returncode != 0:
            fail('create', 'docker create failed on ' + node)


def healthy_all():
    ok = 0
    for port in range(18081, 18085):
        try:
            ok += urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5).status == 200
        except OSError:
            pass
    return ok == 4


def max_len(port=18081):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=10) as r:
        return json.load(r)['data'][0].get('max_model_len')


def switch(stop, start, step):
    if not guards_ok():
        fail(step, 'head guards changed')
    for node in NODES:
        out = ssh(node, f'docker stop -t 60 {stop}', timeout=120)
        record(step + '-stop', node=node, name=stop, rc=out.returncode)
    for node in NODES:
        for _ in range(30):
            if not gpu_apps(node):
                break
            time.sleep(5)
        else:
            fail(step, 'GPU still busy on ' + node, apps=gpu_apps(node))
        out = ssh(node, f'docker start {start}')
        record(step + '-start', node=node, name=start, rc=out.returncode)
    for _ in range(90):
        if healthy_all():
            lens = [max_len(p) for p in range(18081, 18085)]
            return record(step + '-healthy', ok=True, max_model_len=lens, guards=guards_ok())
        time.sleep(10)
    fail(step, 'not healthy within 15 minutes')


def status():
    for node in NODES:
        out = ssh(node, f"docker ps -a --filter name=swarm-lightning --format '{{{{.Names}}}} {{{{.ID}}}} {{{{.Status}}}}'")
        record('status', node=node, containers=out.stdout.strip().splitlines())


if __name__ == '__main__':
    {'create': create, 'to-128k': lambda: switch(SHORT, LONG, 'to-128k'),
     'to-16k': lambda: switch(LONG, SHORT, 'to-16k'), 'status': status}[sys.argv[1]]()
