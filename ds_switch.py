#!/usr/bin/env python3
"""Owner-authorized fleet switch for DeepSeek MEASUREMENT only, and back to Nemotron.

Implements the reviewed procedure (diagnostics/swarm-prototype-20261115/
nemotron72-followup-operations-plan-20261116.json and deepseek-reference-exclusive-procedure.md,
sha 0b9999...): both head guards stay in place throughout; Nemotron containers are only stopped
and started (never removed/recreated); native DeepSeek starts with the exact saved script
(sha 4ac01755...) sent as a remote `bash -c` argument with local stdin=DEVNULL; native stop uses
service.sh stop. Never fleet.sh restore / window.sh prod. Each step re-checks state first.

Usage: ds_switch.py precheck | to-deepseek | to-nemotron     (prints a JSON receipt per step)
"""
import hashlib
import json
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
NODES = ['Spark_01', 'Spark_02', 'Spark_03', 'Spark_04']
CONTAINERS = {'Spark_01': '2852bbfaa4ae', 'Spark_02': 'fb233e4057cf', 'Spark_03': '94155d2ac1f7', 'Spark_04': 'd59fa32fef85'}
START_SCRIPT = HERE / '.runtime/start-native-reference-exact-v1.sh'
START_SHA = '4ac017501254e826406ea97232ff5d5b99591159102f985a481bd48fd3048f36'
SERVICE = '/home/knapcio/dsgb10/pico-dgx-ds4/ds41f-4xgx10-switchless/engine/server/service.sh'
OWNER = 'swarm-lab-20261115'
LOG = HERE / '.runtime/ds-switch-20261116.jsonl'


def ssh(node, command, timeout=120):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', node, command],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


def record(step, **fields):
    entry = dict(utc=datetime.now(timezone.utc).isoformat(), step=step, **fields)
    with LOG.open('a') as stream:
        stream.write(json.dumps(entry) + '\n')
    print(json.dumps(entry))
    return entry


def fail(step, message, **fields):
    record(step, ok=False, error=message, **fields)
    raise SystemExit(message)


def guards_ok():
    out = ssh('Spark_01', 'for p in ~/dsgb10/no-autostart ~/fleet_busy; do [ -f "$p" ] && [ ! -L "$p" ] && [ -O "$p" ] && cat "$p" || echo BAD; done')
    return out.returncode == 0 and out.stdout.split() == [OWNER, OWNER]


def gpu_apps(node):
    out = ssh(node, 'nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader')
    return [line for line in out.stdout.splitlines() if line.strip()]


def container(node):
    out = ssh(node, 'docker inspect swarm-lightning --format "{{.Id}} {{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}}"')
    cid, running, oom, restarts = out.stdout.split()
    return dict(id=cid, running=running == 'true', oom=oom, restarts=int(restarts))


def nemo_idle():
    idle = True
    for port in range(18081, 18085):
        try:
            text = urllib.request.urlopen(f'http://127.0.0.1:{port}/metrics', timeout=5).read().decode()
            for line in text.splitlines():
                if line.startswith(('vllm:num_requests_running{', 'vllm:num_requests_waiting{')):
                    idle &= float(line.split()[-1]) == 0
        except OSError:
            idle = False
    return idle


def native_state():
    out = ssh('Spark_01', 'cat ~/dsgb10/service/run/state 2>/dev/null; curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/health')
    return out.stdout.strip()


def precheck():
    nodes = {n: dict(container=container(n), gpu=gpu_apps(n)) for n in NODES}
    ok = guards_ok() and all(v['container']['id'].startswith(CONTAINERS[n]) for n, v in nodes.items())
    return record('precheck', ok=ok, guards=guards_ok(), nemo_idle=nemo_idle(), native=native_state(), nodes=nodes)


def to_deepseek():
    pre = precheck()
    if not pre['ok'] or not pre['nemo_idle']:
        fail('to-deepseek', 'precheck failed or Nemotron not idle')
    if hashlib.sha256(START_SCRIPT.read_bytes()).hexdigest() != START_SHA:
        fail('to-deepseek', 'start script hash differs')
    for node in NODES:
        if not container(node)['id'].startswith(CONTAINERS[node]):
            fail('to-deepseek', 'unexpected container on ' + node)
        out = ssh(node, 'docker stop -t 60 swarm-lightning', timeout=120)
        record('nemo-stop', node=node, rc=out.returncode, out=out.stdout.strip()[-80:])
    for node in NODES:
        apps = gpu_apps(node)
        if apps or container(node)['running']:
            fail('to-deepseek', 'GPU or container still busy on ' + node, apps=apps)
    if not guards_ok():
        fail('to-deepseek', 'head guards changed')
    script = START_SCRIPT.read_text()
    out = ssh('Spark_01', 'bash -c ' + shlex.quote(script), timeout=900)
    record('native-start', rc=out.returncode, stdout_tail=out.stdout[-400:], stderr_tail=out.stderr[-400:])
    if out.returncode != 0:
        fail('to-deepseek', 'native start returned nonzero')
    for _ in range(90):
        state = native_state()
        if state.endswith('200'):
            return record('native-healthy', ok=True, state=state, guards=guards_ok())
        time.sleep(10)
    fail('to-deepseek', 'native did not become healthy within 15 minutes', state=native_state())


def to_nemotron():
    if not guards_ok():
        fail('to-nemotron', 'head guards changed')
    out = ssh('Spark_01', f'env FLEET=/home/knapcio/dsgb10/fleet.conf {SERVICE} stop', timeout=300)
    record('native-stop', rc=out.returncode, stdout_tail=out.stdout[-300:], stderr_tail=out.stderr[-300:])
    for _ in range(30):
        if not any(gpu_apps(n) for n in NODES):
            break
        time.sleep(10)
    else:
        fail('to-nemotron', 'GPU still busy after native stop', apps={n: gpu_apps(n) for n in NODES})
    for node in NODES:
        if not container(node)['id'].startswith(CONTAINERS[node]):
            fail('to-nemotron', 'unexpected container on ' + node)
        out = ssh(node, 'docker start swarm-lightning')
        record('nemo-start', node=node, rc=out.returncode)
    for _ in range(90):
        healthy = 0
        for port in range(18081, 18085):
            try:
                healthy += urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5).status == 200
            except OSError:
                pass
        if healthy == 4:
            return record('nemo-healthy', ok=True, nodes={n: container(n) for n in NODES}, guards=guards_ok())
        time.sleep(10)
    fail('to-nemotron', 'Nemotron not healthy within 15 minutes')


if __name__ == '__main__':
    {'precheck': precheck, 'to-deepseek': to_deepseek, 'to-nemotron': to_nemotron}[sys.argv[1]]()
