"""Differential-consensus gate (DIFFGATE_PLAN.json): run model-written code ONLY in the CPU-only sandbox container of
sandbox_code.py (same image, same docker flags: no network, read-only, 256 MB, 1 CPU, pids 64, user 65534, tmpfs /tmp)
on a fleet host over ssh, never on the controller host. Two modes, both through a static trusted runner fed by stdin:

  generate  exec the generator code and call generate_inputs(); the result must be a non-empty list of dicts with an
            'args' list and an optional 'kwargs' dict of JSON values (first 64 kept); else status error
  outputs   exec a candidate and call its function on every input (fresh deep copy per call, per-input timer); each
            outcome is the type-tagged canonical encoding of the return value (bool, int, float, str, None, list,
            dict with sorted keys; any other type by its type name and repr), 'exception:<type name>' or 'timeout',
            returned as sha256 plus a short preview; a candidate that cannot be loaded, has no callable of that
            name, or exceeds the total time is status error / timeout (unavailable)

Hosts (sol review): only the frozen fleet hosts FLEET (Spark_01..04). Before any code is sent, the host's hostname and
its Docker daemon's name must be the expected spark-0N (never the controller's hostname); the daemon ID read then is
re-checked on the host in the same session that receives the code. The host itself enforces the deadline (coreutils
timeout around docker run), caps the runner output (head -c OUTPUT_CAP) before anything reaches the controller, and
removes the container under a trap that verifies both ownership labels (no reconnect needed for cleanup). The runner's
timers stay armed through result encoding and serialization.

Importing this module never contacts a host or executes candidate code.
"""
import json
import shlex
import socket
import subprocess
import threading
import uuid

import sandbox_code as sc

FLEET = {'Spark_01': 'spark-01', 'Spark_02': 'spark-02', 'Spark_03': 'spark-03', 'Spark_04': 'spark-04'}
MAX_INPUTS = 64
MAX_INPUTS_BYTES = 200_000
OUTPUT_CAP = 262_144
STATE_MARK = '\n@@SWARM_STATE@@'
CLEAN_MARK = '\n@@SWARM_CLEAN@@'
IDENTITY_EXIT = (96, 97)

RUNNER = r'''
import copy, hashlib, io, json, os, signal, sys, time, contextlib
class Deadline(BaseException): pass
def deadline(*_): raise Deadline()
def encode(v):
    t = type(v)
    if v is None: return 'N'
    if t is bool: return 'B:' + ('true' if v else 'false')
    if t is int: return 'I:' + str(v)
    if t is float: return 'F:' + repr(v)
    if t is str: return 'S:' + json.dumps(v)
    if t is list: return 'L[' + ','.join(encode(x) for x in v) + ']'
    if t is dict:
        return 'D{' + ','.join(sorted(encode(k) + ':' + encode(x) for k, x in v.items())) + '}'
    return 'O:' + t.__name__ + ':' + repr(v)
class Capture(io.TextIOBase):
    def write(self, text): return len(text)
    def flush(self): pass
payload = json.load(sys.stdin)
protocol = os.dup(1)
null = os.open(os.devnull, os.O_WRONLY)
os.dup2(null, 1)
os.dup2(null, 2)
signal.signal(signal.SIGALRM, deadline)
start = time.monotonic()
def remaining():
    return payload['total_timeout'] - (time.monotonic() - start)
result = {}
try:
    with contextlib.redirect_stdout(Capture()), contextlib.redirect_stderr(Capture()):
        signal.setitimer(signal.ITIMER_REAL, max(0.01, remaining()))
        namespace = {}
        exec(compile(payload['code'], '<candidate>', 'exec'), namespace)
        function = namespace.get(payload['function_name'])
        if not callable(function): raise TypeError('Named function is not callable')
        if payload['mode'] == 'generate':
            value = function()  # the total timer stays armed through validation and serialization
            if not isinstance(value, list) or not value:
                raise ValueError('generate_inputs must return a non-empty list')
            inputs, size = [], 0
            for case in value[:payload['max_inputs']]:
                if not isinstance(case, dict) or not isinstance(case.get('args'), list) \
                        or not isinstance(case.get('kwargs', {}), dict) or set(case) - {'args', 'kwargs'}:
                    raise ValueError('each input needs args:list and optional kwargs:dict')
                text = json.dumps(case, allow_nan=False)
                size += len(text)
                if size > payload['max_inputs_bytes']: raise ValueError('generated inputs exceed the size cap')
                inputs.append(json.loads(text))
            signal.setitimer(signal.ITIMER_REAL, 0)
            result = {'status': 'ok', 'inputs': inputs}
        else:
            signal.setitimer(signal.ITIMER_REAL, 0)
            outcomes = []
            for case in payload['inputs']:
                left = remaining()
                if left <= 0: raise Deadline()
                args, kwargs = copy.deepcopy(case['args']), copy.deepcopy(case.get('kwargs', {}))
                try:
                    signal.setitimer(signal.ITIMER_REAL, min(payload['per_input'], left))
                    try:
                        value = function(*args, **kwargs)
                        try:
                            text = encode(value)  # the per-input timer covers encoding too
                        except Deadline:
                            raise
                        except BaseException as exc:
                            text = 'unencodable:' + type(exc).__name__
                        digest = hashlib.sha256(text.encode()).hexdigest()
                    finally:
                        signal.setitimer(signal.ITIMER_REAL, 0)
                except Deadline:
                    if remaining() <= 0: raise
                    text = 'timeout'
                    digest = hashlib.sha256(text.encode()).hexdigest()
                except Exception as exc:
                    text = 'exception:' + type(exc).__name__
                    digest = hashlib.sha256(text.encode()).hexdigest()
                outcomes.append({'sha256': digest, 'preview': text[:120]})
            result = {'status': 'ok', 'outcomes': outcomes}
except Deadline:
    result = {'status': 'timeout', 'error': 'Execution deadline exceeded'}
except BaseException as exc:
    result = {'status': 'error', 'error': type(exc).__name__ + ': ' + str(exc)[:500]}
signal.setitimer(signal.ITIMER_REAL, 0)
result['seconds'] = round(time.monotonic() - start, 3)
os.write(protocol, json.dumps(result, allow_nan=False).encode())
'''


def check_host(host):
    """Only the frozen fleet hosts; anything else (an alias that could resolve to the controller) is refused."""
    if host not in FLEET:
        raise ValueError(f'host must be one of the frozen fleet hosts {sorted(FLEET)}')


_IDENTITY, _IDENTITY_LOCK = {}, threading.Lock()


def verify_host(host):
    """The host's hostname and its Docker daemon's name must be FLEET[host] (and not the controller); returns the
    daemon ID (cached per host). Raises HostIdentityError otherwise; nothing is sent before this passes."""
    check_host(host)
    with _IDENTITY_LOCK:
        if host in _IDENTITY:
            return _IDENTITY[host]
        out = sc._ssh(host, ['sh', '-c', 'hostname; docker info --format "{{.Name}} {{.ID}}"'], timeout=20)
        lines = (out.stdout or '').strip().splitlines() if out.returncode == 0 else []
        expected = FLEET[host]
        parts = lines[1].split() if len(lines) == 2 else []
        if len(parts) != 2 or lines[0].strip() != expected or parts[0] != expected \
                or expected == socket.gethostname().split('.')[0].lower():
            raise HostIdentityError(f'{host}: identity {lines!r} is not {expected}')
        _IDENTITY[host] = parts[1]
        return parts[1]


class HostIdentityError(RuntimeError):
    pass


def host_script(host, daemon_id, name, task, total_timeout):
    """The host-side wrapper: identity re-check, coreutils timeout around docker run, output cap, label-verified
    cleanup under a trap, then the container state (capped) after STATE_MARK."""
    q = shlex.quote
    docker = ['docker', 'run', '--pull', 'never', '--runtime', 'runc', '-i', '--name', name,
              '--label', 'swarm-lab.code-owner=' + sc.OWNER, '--label', 'swarm-lab.code-task=' + task,
              '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
              '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
              '--user', '65534:65534', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=16m', '--workdir', '/tmp',
              '--env', 'NVIDIA_VISIBLE_DEVICES=void',
              '--stop-timeout', '1', '--entrypoint', 'python3', sc.IMAGE, '-I', '-S', '-c', RUNNER]
    label = 'docker inspect --format {fmt} {name} 2>/dev/null'
    owner = label.format(fmt=q('{{index .Config.Labels "swarm-lab.code-owner"}}'), name=q(name))
    ident = label.format(fmt=q('{{index .Config.Labels "swarm-lab.code-task"}}'), name=q(name))
    return '\n'.join([
        f'[ "$(hostname)" = {q(FLEET[host])} ] || exit 96',
        f'[ "$(docker info --format {q("{{.ID}}")})" = {q(daemon_id)} ] || exit 97',
        f'cleanup() {{ if [ "$({owner})" = {q(sc.OWNER)} ] && [ "$({ident})" = {q(task)} ]; then '
        f'docker rm -f {q(name)} >/dev/null 2>&1; fi; }}',
        'trap cleanup EXIT HUP INT TERM',
        f'timeout -k 5 {int(total_timeout) + 5} {shlex.join(docker)} | head -c {OUTPUT_CAP}',
        f'printf %s {q(STATE_MARK)}',
        f'docker inspect --format {q("{{json .State}}")} {q(name)} 2>/dev/null | head -c 4096',
        'cleanup',  # explicitly, then verified: the number of containers left with this task's label
        f'printf %s {q(CLEAN_MARK)}',
        f'docker ps -aq --filter {q("label=swarm-lab.code-task=" + task)} | wc -l',
    ])


def sweep_script(host):
    """Remove every container with the sandbox owner label on the host (label filter only), then print how many are
    left."""
    q = shlex.quote
    flt = q('label=swarm-lab.code-owner=' + sc.OWNER)
    return '\n'.join([
        f'[ "$(hostname)" = {q(FLEET[host])} ] || exit 96',
        f'ids=$(docker ps -aq --filter {flt})',
        '[ -z "$ids" ] || docker rm -f $ids >/dev/null 2>&1',
        f'docker ps -aq --filter {flt} | wc -l',
    ])


def sweep(hosts=None):
    """{host: containers left with the sandbox owner label (0 = verified clean), or None if the host could not be
    checked}. Used before the fleet lease is released."""
    out = {}
    for host in hosts or sorted(FLEET):
        try:
            verify_host(host)
            proc = sc._ssh(host, ['sh', '-c', sweep_script(host)], timeout=60)
            out[host] = int(proc.stdout.strip()) if proc.returncode == 0 else None
        except (HostIdentityError, ValueError, OSError, subprocess.TimeoutExpired):
            out[host] = None
    return out


def parse_host_output(stdout):
    """(runner text, container state or None, containers left after cleanup or None)."""
    head, mark, left = (stdout or '').rpartition(CLEAN_MARK)
    remaining = None
    if mark:
        try:
            remaining = int(left.strip())
        except ValueError:
            remaining = None
    else:
        head = stdout or ''
    text, mark, state = head.rpartition(STATE_MARK)
    if not mark:
        return head, None, remaining
    try:
        return text, json.loads(state), remaining
    except ValueError:
        return text, None, remaining


def run(mode, code, function_name, host, inputs=None, per_input=2.0, total_timeout=60.0):
    """Execute in the sandbox on a verified fleet host; returns the runner's result plus container_seconds."""
    check_host(host)
    if mode not in ('generate', 'outputs') or not isinstance(code, str) or len(code) > 65536:
        raise ValueError('bad mode or code')
    payload = json.dumps(dict(mode=mode, code=code, function_name=function_name, inputs=inputs or [],
                              per_input=per_input, total_timeout=total_timeout, max_inputs=MAX_INPUTS,
                              max_inputs_bytes=MAX_INPUTS_BYTES), allow_nan=False)
    if len(payload.encode()) > 1_000_000:
        raise ValueError('payload exceeds 1 MB')
    daemon = verify_host(host)  # raises before any code is sent
    task = uuid.uuid4().hex
    script = host_script(host, daemon, 'swarm-code-' + task, task, total_timeout)
    try:
        process = sc._ssh(host, ['sh', '-c', script], payload, timeout=total_timeout + 30)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return dict(status='error', infrastructure=True, error=f'{type(exc).__name__}: {str(exc)[:300]}',
                    container_seconds=None)
    if process.returncode in IDENTITY_EXIT:
        return dict(status='error', infrastructure=True, error='host identity changed', container_seconds=None)
    text, state, remaining = parse_host_output(process.stdout)
    result = dict(status='error')
    if remaining != 0:
        result.update(error='sandbox container not verified removed', infrastructure=True)
    elif state is None:
        result.update(error='no container state', infrastructure=True)
    elif len(text) >= OUTPUT_CAP:
        result.update(error='runner output over the cap')
    elif state.get('Running'):
        result.update(status='timeout', error='host deadline exceeded')
    elif state.get('OOMKilled'):
        result.update(error='out of memory')
    else:
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict) or parsed.get('status') not in ('ok', 'error', 'timeout'):
                raise ValueError('invalid runner response')
            result = parsed
        except (ValueError, TypeError) as exc:
            if state.get('ExitCode') in (124, 137):
                result.update(status='timeout', error='host deadline exceeded')
            else:
                result.update(error=f'invalid runner protocol: {str(exc)[:300]}', infrastructure=True)
    result['container_seconds'] = container_seconds(state)
    return result


def container_seconds(state):
    from datetime import datetime
    try:
        t0 = datetime.fromisoformat(state['StartedAt'][:26].rstrip('Z'))
        t1 = datetime.fromisoformat(state['FinishedAt'][:26].rstrip('Z'))
        return max(0.0, (t1 - t0).total_seconds())
    except (TypeError, KeyError, ValueError, AttributeError):
        return None
