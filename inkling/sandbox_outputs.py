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

Importing this module never contacts a host or executes candidate code.
"""
import json
import re
import subprocess
import uuid

import sandbox_code as sc

LOCAL = {'localhost', '127.0.0.1', '::1'}
MAX_INPUTS = 64

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
            value = function()
            signal.setitimer(signal.ITIMER_REAL, 0)
            if not isinstance(value, list) or not value:
                raise ValueError('generate_inputs must return a non-empty list')
            inputs = []
            for case in value[:payload['max_inputs']]:
                if not isinstance(case, dict) or not isinstance(case.get('args'), list) \
                        or not isinstance(case.get('kwargs', {}), dict) or set(case) - {'args', 'kwargs'}:
                    raise ValueError('each input needs args:list and optional kwargs:dict')
                inputs.append(json.loads(json.dumps(case, allow_nan=False)))
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
                    finally:
                        signal.setitimer(signal.ITIMER_REAL, 0)
                    try:
                        text = encode(value)
                    except BaseException as exc:
                        text = 'unencodable:' + type(exc).__name__
                except Deadline:
                    if remaining() <= 0: raise
                    text = 'timeout'
                except Exception as exc:
                    text = 'exception:' + type(exc).__name__
                outcomes.append({'sha256': hashlib.sha256(text.encode()).hexdigest(), 'preview': text[:120]})
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
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9][A-Za-z0-9_.-]*)?',
                                                     host) or host.split('@')[-1].lower() in LOCAL:
        raise ValueError('host must be a remote SSH alias (never the controller host)')


def run(mode, code, function_name, host, inputs=None, per_input=2.0, total_timeout=60.0):
    """Execute in the sandbox on `host`; returns the runner's result plus container_seconds and failure fields."""
    check_host(host)
    if mode not in ('generate', 'outputs') or not isinstance(code, str) or len(code) > 65536:
        raise ValueError('bad mode or code')
    payload = json.dumps(dict(mode=mode, code=code, function_name=function_name, inputs=inputs or [],
                              per_input=per_input, total_timeout=total_timeout, max_inputs=MAX_INPUTS),
                         allow_nan=False)
    if len(payload.encode()) > 1_000_000:
        raise ValueError('payload exceeds 1 MB')
    task = uuid.uuid4().hex
    name = 'swarm-code-' + task
    command = ['docker', 'run', '--pull', 'never', '--runtime', 'runc', '-i', '--name', name,
               '--label', 'swarm-lab.code-owner=' + sc.OWNER, '--label', 'swarm-lab.code-task=' + task,
               '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
               '--user', '65534:65534', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=16m', '--workdir', '/tmp',
               '--env', 'NVIDIA_VISIBLE_DEVICES=void',
               '--stop-timeout', '1', '--entrypoint', 'python3', sc.IMAGE, '-I', '-S', '-c', RUNNER]
    process, error = None, None
    try:
        process = sc._ssh(host, command, payload, timeout=total_timeout + 20)
    except (subprocess.TimeoutExpired, OSError) as exc:
        error = exc
    state, inspect_error = sc._inspect_owned(host, name, task)
    cleanup_ok = sc._cleanup(host, name, task)
    result = dict(status='error')
    if isinstance(error, subprocess.TimeoutExpired):
        result.update(status='timeout', error='Controller deadline exceeded')
    elif error is not None:
        result.update(error=f'{type(error).__name__}: {str(error)[:500]}', infrastructure=True)
    elif process.returncode:
        result.update(error=(process.stderr or '')[-1000:] or f'exit {process.returncode}',
                      infrastructure=process.returncode in (125, 126, 127, 255),
                      oom=bool(state and state.get('OOMKilled')))
    else:
        try:
            parsed = json.loads(process.stdout)
            if not isinstance(parsed, dict) or parsed.get('status') not in ('ok', 'error', 'timeout'):
                raise ValueError('invalid runner response')
            result = parsed
        except (ValueError, TypeError) as exc:
            result.update(error=f'invalid runner protocol: {str(exc)[:300]}', infrastructure=True)
    result.update(cleanup_ok=cleanup_ok, container_seconds=container_seconds(state))
    if inspect_error or not cleanup_ok:
        result['infrastructure'] = True
    return result


def container_seconds(state):
    from datetime import datetime
    try:
        t0 = datetime.fromisoformat(state['StartedAt'][:26].rstrip('Z'))
        t1 = datetime.fromisoformat(state['FinishedAt'][:26].rstrip('Z'))
        return max(0.0, (t1 - t0).total_seconds())
    except (TypeError, KeyError, ValueError):
        return None
