#!/usr/bin/env python3
"""Owner-authorized fleet switch for DeepSeek MEASUREMENT only, and back to Inkling (ds_switch.py adapted).

Same reviewed procedure as ds_switch.py; the Swarm Lab containers are now `swarm-inkling` (SGLang) and
`swarm-inkling-shim` (adapter), stopped and started, never removed or recreated.


Implements the reviewed procedure (diagnostics/swarm-prototype-20261115/
nemotron72-followup-operations-plan-20261116.json and deepseek-reference-exclusive-procedure.md,
sha 0b9999...): both head guards stay in place throughout; Nemotron containers are only stopped
and started (never removed/recreated); native DeepSeek starts with the exact saved script
(sha 4ac01755...) sent as a remote `bash -c` argument with local stdin=DEVNULL; native stop uses
service.sh stop. Never fleet.sh restore / window.sh prod. Each step re-checks state first.

stop-deepseek = exactly the first half of to-inkling (guards, native `service.sh stop` over the same ssh, wait until no
GPU apps on all four nodes) WITHOUT starting swarm-inkling / swarm-inkling-shim; its final receipt lists every node's
GPU apps (empty) and container states (stopped) and guards_ok.

start-deepseek = to-deepseek's native start (pinned script; the bytes executed are the bytes hashed, sha in the
receipt) and health wait (explicit: run/state serving AND /health 200) WITHOUT stopping any
swarm container: it runs only on a fleet whose swarm is already stopped. Its preflight (nothing started on any
failure) requires the head guards, the start script hash, a successful GPU query with no compute apps and no
dsgb10_rank/dsfront process (/proc scan) on all four nodes, and none of
swarm-inkling, swarm-recipe, swarm-inkling-shim running on any node (a container counts as absent only on docker's
exact "No such object/container" error; any other inspection failure fails the preflight).

stop-native = the native stop for start-deepseek: service.sh stop, then confirmed shutdown (run/state stopped,
/health not 200, no dsgb10_rank/dsfront process on any node by a /proc scan) and a successful idle GPU query on all
four nodes; it touches no container and needs no container manifest.

start-deepseek --official runs .runtime/start-native-official-v1.sh instead (pinned START_SHA_OFFICIAL: the same
bytes as the ablit launcher except the front-end tokenizer path, which is the official 1017 checkpoint's); without
the flag the ablit launcher (START_SHA) runs, as before.

Usage: inkling/ds_switch_inkling.py precheck | to-deepseek | to-inkling | stop-deepseek | start-deepseek [--official]
       | stop-native
       (a JSON receipt per step)
"""
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
NODES = ['Spark_01', 'Spark_02', 'Spark_03', 'Spark_04']
_CONTAINERS = HERE / '.runtime/INKLING_CONTAINERS.json'  # recorded before the first switch
CONTAINERS = json.loads(_CONTAINERS.read_text()) if _CONTAINERS.exists() else None  # None only outside the fleet tree
START_SCRIPT = HERE / '.runtime/start-native-reference-exact-v1.sh'
START_SHA = '4ac017501254e826406ea97232ff5d5b99591159102f985a481bd48fd3048f36'
# start-deepseek --official: the same bytes except the front-end tokenizer path (the official 1017 checkpoint's)
START_SCRIPT_OFFICIAL = HERE / '.runtime/start-native-official-v1.sh'
START_SHA_OFFICIAL = '524e8376bfed84e6fea0dee86bc1c3a38fc32547dc3208998f76dc913a91f92f'
SERVICE = '/home/knapcio/dsgb10/pico-dgx-ds4/ds41f-4xgx10-switchless/engine/server/service.sh'
OWNER = 'swarm-lab-20261115'
LOG = HERE / '.runtime/ds-switch-inkling-20261121.jsonl'


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
    out = ssh(node, 'for c in swarm-inkling swarm-inkling-shim; do docker inspect $c --format "{{.Id}} {{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}}"; done')
    (cid, running, oom, restarts), (sid, srunning, _, _) = [line.split() for line in out.stdout.splitlines()]
    return dict(id=cid, shim_id=sid, running=running == 'true' or srunning == 'true', oom=oom, restarts=int(restarts))


def inkling_idle():
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
    ok = guards_ok() and all(v['container']['id'].startswith(CONTAINERS[n][0]) and v['container']['shim_id'].startswith(CONTAINERS[n][1]) for n, v in nodes.items())
    return record('precheck', ok=ok, guards=guards_ok(), inkling_idle=inkling_idle(), native=native_state(), nodes=nodes)


def to_deepseek():
    pre = precheck()
    if not pre['ok'] or not pre['inkling_idle']:
        fail('to-deepseek', 'precheck failed or Inkling not idle')
    if hashlib.sha256(START_SCRIPT.read_bytes()).hexdigest() != START_SHA:
        fail('to-deepseek', 'start script hash differs')
    for node in NODES:
        if not container(node)['id'].startswith(CONTAINERS[node][0]):
            fail('to-deepseek', 'unexpected container on ' + node)
        out = ssh(node, 'docker stop -t 60 swarm-inkling-shim swarm-inkling', timeout=180)
        record('inkling-stop', node=node, rc=out.returncode, out=out.stdout.strip()[-80:])
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


def to_inkling():
    if not guards_ok():
        fail('to-inkling', 'head guards changed')
    out = ssh('Spark_01', f'env FLEET=/home/knapcio/dsgb10/fleet.conf {SERVICE} stop', timeout=300)
    record('native-stop', rc=out.returncode, stdout_tail=out.stdout[-300:], stderr_tail=out.stderr[-300:])
    for _ in range(30):
        if not any(gpu_apps(n) for n in NODES):
            break
        time.sleep(10)
    else:
        fail('to-inkling', 'GPU still busy after native stop', apps={n: gpu_apps(n) for n in NODES})
    for node in NODES:
        if not container(node)['id'].startswith(CONTAINERS[node][0]):
            fail('to-inkling', 'unexpected container on ' + node)
        out = ssh(node, 'docker start swarm-inkling swarm-inkling-shim')
        record('inkling-start', node=node, rc=out.returncode)
    for _ in range(90):
        healthy = 0
        for port in range(18081, 18085):
            try:
                healthy += urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5).status == 200
            except OSError:
                pass
        if healthy == 4:
            return record('inkling-healthy', ok=True, nodes={n: container(n) for n in NODES}, guards=guards_ok())
        time.sleep(10)
    fail('to-inkling', 'Inkling not healthy within 15 minutes')


GPU_QUERY_TRIES = 3


def gpu_query(node):
    """(ok, apps): ok only if the ssh + nvidia-smi query exited 0 and every output line parses as 'pid, name'; a failed
    or unparsable query is NOT idle (stop-deepseek only)."""
    try:
        out = ssh(node, 'nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader')
    except Exception as exc:  # ssh timeout or launch failure
        return False, [f'{type(exc).__name__}: {exc}'[:120]]
    if out.returncode != 0:
        return False, [f'query exit {out.returncode}: {out.stderr.strip()[:120]}']
    apps = [line for line in out.stdout.splitlines() if line.strip()]
    if any(not line.split(',')[0].strip().isdigit() for line in apps):
        return False, apps
    return True, apps


def gpu_idle_everywhere():
    """{node: (ok, apps)} with every failed query retried GPU_QUERY_TRIES times."""
    state = {}
    for n in NODES:
        for _ in range(GPU_QUERY_TRIES):
            state[n] = gpu_query(n)
            if state[n][0]:
                break
    return state


def stop_preflight():
    """Local inputs of every later stop-deepseek step: the recorded container manifest (.runtime/INKLING_CONTAINERS.json,
    readable, a [server id, shim id] pair per node) used by the final receipt check."""
    problems = []
    if not isinstance(CONTAINERS, dict):
        problems.append(f'container manifest {_CONTAINERS} missing or unreadable')
    else:
        for n in NODES:
            ids = CONTAINERS.get(n)
            if not (isinstance(ids, (list, tuple)) and len(ids) == 2 and all(isinstance(x, str) and x for x in ids)):
                problems.append(f'container manifest has no [server id, shim id] for {n}')
    return problems


def stop_deepseek():
    """The first half of to_inkling (guards, native stop, wait for free GPUs), then a receipt instead of starting
    Inkling: every node's GPU apps (a successful query with no compute apps), its swarm containers (recorded ids, not
    running) and guards_ok. Stricter than to_inkling where only this step is concerned: the receipt log is written
    before the stop is issued (fail early if it cannot be), a non-zero native stop fails the step, and a failed or
    unparsable GPU query never counts as idle. The fleet is left with nothing serving."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        record('stop-deepseek-start', guards=guards_ok())
    except OSError as exc:
        raise SystemExit(f'stop-deepseek: receipt log {LOG} cannot be written ({exc}); nothing was stopped')
    problems = stop_preflight()
    if problems:  # every later step's local inputs must exist before anything is stopped
        fail('stop-deepseek', 'preflight failed; nothing was stopped: ' + '; '.join(problems))
    if not guards_ok():
        fail('stop-deepseek', 'head guards changed')
    out = ssh('Spark_01', f'env FLEET=/home/knapcio/dsgb10/fleet.conf {SERVICE} stop', timeout=300)
    record('native-stop', rc=out.returncode, stdout_tail=out.stdout[-300:], stderr_tail=out.stderr[-300:])
    if out.returncode != 0:
        record('deepseek-stopped', ok=False, guards_ok=guards_ok(), error=f'native stop exited {out.returncode}')
        raise SystemExit(f'stop-deepseek: native stop exited {out.returncode}')
    for _ in range(30):
        state = gpu_idle_everywhere()
        if all(ok and not apps for ok, apps in state.values()):
            break
        time.sleep(10)
    else:
        fail('stop-deepseek', 'GPU still busy or GPU query failing after native stop',
             gpus={n: dict(query_ok=ok, apps=apps) for n, (ok, apps) in state.items()})
    nodes = {n: dict(gpu=apps, gpu_query_ok=ok, container=container(n)) for n, (ok, apps) in gpu_idle_everywhere().items()}
    guards = guards_ok()
    ok = (guards and all(v['gpu_query_ok'] and not v['gpu'] for v in nodes.values())
          and all(not v['container']['running'] and v['container']['id'].startswith(CONTAINERS[n][0])
                  and v['container']['shim_id'].startswith(CONTAINERS[n][1]) for n, v in nodes.items()))
    receipt = record('deepseek-stopped', ok=ok, guards_ok=guards, nodes=nodes)
    if not ok:
        raise SystemExit('stop-deepseek: GPU apps, swarm containers or guards not as expected')
    return receipt


SWARM_CONTAINERS = ('swarm-inkling', 'swarm-recipe', 'swarm-inkling-shim')


def _docker_absent(name, out):
    """True only for docker's exact not-found error for this name (exit 1, nothing usable on stdout)."""
    return (out.returncode == 1 and not out.stdout.strip()
            and re.fullmatch(r'(?i:error: no such (?:object|container)): ' + re.escape(name), out.stderr.strip()) is not None)


def swarm_containers(node):
    """(ok, {name: True running | False stopped | None absent}); ok only if every container was inspected or is
    absent by docker's exact error text (start-deepseek only)."""
    state = {}
    for name in SWARM_CONTAINERS:
        try:
            out = ssh(node, f'docker inspect --format "{{{{.State.Running}}}}" {name}')
        except Exception as exc:  # ssh timeout or launch failure
            return False, {name: f'{type(exc).__name__}: {exc}'[:120]}
        value = out.stdout.strip()
        if out.returncode == 0 and value in ('true', 'false'):
            state[name] = value == 'true'
        elif _docker_absent(name, out):
            state[name] = None
        else:
            return False, {name: f'inspect exit {out.returncode}: {(out.stderr.strip() or value)[:120]}'}
    return True, state


def launcher(official=False):
    """(path, pinned sha) of the native start script: the ablit-tokenizer one (default) or the official one."""
    return (START_SCRIPT_OFFICIAL, START_SHA_OFFICIAL) if official else (START_SCRIPT, START_SHA)


def start_preflight(official=False):
    """(problems, observed): head guards, start script hash, GPUs idle (a failed or unparsable query is not idle)
    and no swarm container running, on all four nodes."""
    script_path, pinned = launcher(official)
    problems, observed = [], dict(guards=guards_ok(), nodes={}, launcher=str(script_path.name))
    if not observed['guards']:
        problems.append('head guards changed')
    try:
        sha = hashlib.sha256(script_path.read_bytes()).hexdigest()
    except OSError as exc:
        sha = f'unreadable: {exc}'
    if sha != pinned:
        problems.append('start script hash differs')
    for n, (ok, apps) in gpu_idle_everywhere().items():
        ok_c, containers = swarm_containers(n)
        ok_p, procs = native_procs(n)
        observed['nodes'][n] = dict(gpu_query_ok=ok, gpu=apps, containers_ok=ok_c, containers=containers,
                                    procs_ok=ok_p, procs=procs)
        if not ok_p:
            problems.append(f'{n}: process scan failed')
        elif procs:
            problems.append(f'{n}: native process already running')
        if not ok:
            problems.append(f'{n}: GPU query failed')
        elif apps:
            problems.append(f'{n}: GPU compute apps present')
        if not ok_c:
            problems.append(f'{n}: container inspection failed')
        elif any(containers.values()):
            problems.append(f'{n}: swarm container running: ' + ','.join(k for k, v in containers.items() if v))
    return problems, observed


def start_deepseek(official=False):
    """to_deepseek's native start and health wait, without stopping anything: the swarm must already be stopped."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        record('start-deepseek-start')
    except OSError as exc:
        raise SystemExit(f'start-deepseek: receipt log {LOG} cannot be written ({exc}); nothing was started')
    script_path, pinned = launcher(official)
    problems, observed = start_preflight(official)
    record('start-preflight', ok=not problems, problems=problems, **observed)
    if problems:
        fail('start-deepseek', 'preflight failed; nothing was started: ' + '; '.join(problems))
    data = script_path.read_bytes()  # the exact bytes executed below, hashed once more right before the start
    launcher_sha = hashlib.sha256(data).hexdigest()
    if launcher_sha != pinned:
        fail('start-deepseek', 'start script hash differs; nothing was started', launcher_sha=launcher_sha)
    out = ssh('Spark_01', 'bash -c ' + shlex.quote(data.decode()), timeout=900)
    record('native-start', rc=out.returncode, launcher=script_path.name, launcher_sha=launcher_sha, stdout_tail=out.stdout[-400:],
           stderr_tail=out.stderr[-400:])
    if out.returncode != 0:
        fail('start-deepseek', 'native start returned nonzero')
    for _ in range(90):
        state = native_state()
        if native_healthy(state):
            return record('native-healthy', ok=True, state=state, launcher=script_path.name, launcher_sha=launcher_sha,
                          guards=guards_ok())
        time.sleep(10)
    fail('start-deepseek', 'native did not become healthy within 15 minutes', state=native_state())


def _state_parts(state):
    """(service state word, /health HTTP code) from native_state()'s two parts; ('', '') when malformed."""
    lines = [line.strip() for line in state.splitlines() if line.strip()]
    if len(lines) != 2 or not lines[0].split():
        return '', ''
    return lines[0].split()[0], lines[1]


def native_healthy(state):
    """Explicit success only: run/state says serving AND /health answered exactly 200."""
    return _state_parts(state) == ('serving', '200')


NATIVE_PROCS = ('dsgb10_rank', 'dsfront')


def native_procs(node):
    """(ok, ['pid comm', ...]) of the native engine's processes, by /proc/<pid>/comm (never matches the checking
    shell); ok only if the scan ran to its end marker."""
    cmd = ('for d in /proc/[0-9]*; do c=$(cat "$d/comm" 2>/dev/null) || continue; case "$c" in '
           + '|'.join(NATIVE_PROCS) + ') echo "${d#/proc/} $c";; esac; done; echo END-OF-SCAN')
    try:
        out = ssh(node, cmd)
    except Exception as exc:  # ssh timeout or launch failure
        return False, [f'{type(exc).__name__}: {exc}'[:120]]
    lines = out.stdout.splitlines()
    if out.returncode != 0 or not lines or lines[-1] != 'END-OF-SCAN':
        return False, [f'scan exit {out.returncode}: {out.stderr.strip()[:120]}']
    return True, lines[:-1]


def stop_native():
    """Native stop with confirmed shutdown: service.sh stop exits 0, then (polled) run/state says stopped and
    /health is not 200, no dsgb10_rank/dsfront process on any node (/proc scan), and a successful GPU query with no
    compute apps on all four nodes. Touches no container and needs no container manifest. Receipts:
    stop-native-start, native-stop, native-stopped."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        record('stop-native-start')
    except OSError as exc:
        raise SystemExit(f'stop-native: receipt log {LOG} cannot be written ({exc}); nothing was stopped')
    if not guards_ok():
        fail('stop-native', 'head guards changed; nothing was stopped')
    out = ssh('Spark_01', f'env FLEET=/home/knapcio/dsgb10/fleet.conf {SERVICE} stop', timeout=300)
    record('native-stop', rc=out.returncode, stdout_tail=out.stdout[-300:], stderr_tail=out.stderr[-300:])
    if out.returncode != 0:
        fail('stop-native', f'native stop exited {out.returncode}')
    observed = {}
    for _ in range(30):
        state = native_state()
        word, code = _state_parts(state)
        procs = {n: native_procs(n) for n in NODES}
        gpus = gpu_idle_everywhere()
        observed = dict(state=state, nodes={n: dict(procs_ok=procs[n][0], procs=procs[n][1], gpu_query_ok=gpus[n][0],
                                                     gpu=gpus[n][1]) for n in NODES})
        if (word == 'stopped' and code != '200' and all(ok and not p for ok, p in procs.values())
                and all(ok and not apps for ok, apps in gpus.values())):
            return record('native-stopped', ok=True, guards=guards_ok(), **observed)
        time.sleep(10)
    fail('stop-native', 'native shutdown not confirmed (state, processes or GPUs)', **observed)

if __name__ == '__main__':
    if sys.argv[1:] == ['start-deepseek', '--official']:
        start_deepseek(official=True)
    elif len(sys.argv) == 2:
        {'precheck': precheck, 'to-deepseek': to_deepseek, 'to-inkling': to_inkling,
         'stop-deepseek': stop_deepseek, 'start-deepseek': start_deepseek, 'stop-native': stop_native}[sys.argv[1]]()
    else:
        raise SystemExit('usage: ds_switch_inkling.py precheck | to-deepseek | to-inkling | stop-deepseek | '
                         'start-deepseek [--official] | stop-native')
