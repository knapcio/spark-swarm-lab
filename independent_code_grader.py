"""Independent confirmation grading: oracle values never enter the candidate container.

Only authored fixtures may run CHILD locally in tests. Real candidate evaluation
uses the pinned CPU-only container on the named Spark. The outer parent alone
compares expected values. Child-reported results/input postconditions are
observations, not authenticated provenance against arbitrary interpreter tampering.
"""
import copy
import hashlib
import json
import keyword
import math
import os
import re
import selectors
import shlex
import subprocess
import time
from types import SimpleNamespace
import uuid

IMAGE = 'python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd'
OWNER = 'swarm-lab-independent-code-eval'
MAX_OUTPUT = 1_048_576

# No expected values, test metadata, comparisons or grade fields exist here.
CHILD = r'''
import copy,json,os,signal,sys
_type, _str, _int, _float, _bool, _list, _dict = type,str,int,float,bool,list,dict
_dumps, _write = json.dumps, os.write
class Deadline(BaseException): pass
def expired(*_): raise Deadline()
def plain(value):
    t = _type(value)
    if value is None or t in (_str,_int,_float,_bool): return value
    if t is _list: return [plain(x) for x in value]
    if t is _dict and all(_type(k) is _str for k in value): return {k:plain(v) for k,v in value.items()}
    raise TypeError('Return/input contains unsupported Python type: '+t.__name__)
payload = json.load(sys.stdin)
protocol = os.dup(1)
null = os.open(os.devnull,os.O_WRONLY)
os.dup2(null,1); os.dup2(null,2)
result = {'version':1,'results':[]}
signal.signal(signal.SIGALRM,expired)
signal.setitimer(signal.ITIMER_REAL,payload['timeout'])
try:
    ns = {}
    exec(compile(payload['code'],'<candidate>','exec'),ns)
    function = ns.get(payload['function_name'])
    if not callable(function): raise TypeError('Named function is not callable')
except Deadline:
    result['interrupted'] = 'timeout'
except BaseException as exc:
    result['setup_error'] = {'type':_type(exc).__name__,'message':_str(exc)[:1000]}
else:
    try:
        for call in payload['calls']:
            args,kwargs = copy.deepcopy(call['args']),copy.deepcopy(call['kwargs'])
            try:
                value = function(*args,**kwargs)
            except Deadline: raise
            except BaseException as exc:
                observation = {'kind':'exception','exception_type':_type(exc).__name__,'message':_str(exc)[:1000]}
            else:
                try:
                    observation = {'kind':'value','value':plain(value)}
                    _dumps(observation,allow_nan=False)
                except Deadline: raise
                except BaseException as exc:
                    observation = {'kind':'serialization_error','message':_type(exc).__name__+': '+_str(exc)[:1000]}
            try:
                observation.update(args_after=plain(args),kwargs_after=plain(kwargs))
                _dumps(observation,allow_nan=False)
            except Deadline: raise
            except BaseException as exc:
                observation = {'kind':'serialization_error','message':_type(exc).__name__+': '+_str(exc)[:1000]}
            result['results'].append(observation)
    except Deadline:
        result['interrupted'] = 'timeout'
signal.setitimer(signal.ITIMER_REAL,0)
try: wire = _dumps(result,allow_nan=False).encode()
except BaseException: wire = b'{"version":1,"results":[],"setup_error":{"type":"SerializationError","message":"Cannot serialize observations"}}'
_write(protocol,wire)
'''


def json_equal(actual, expected, ordered_dict=False):
    """Exact JSON types; int/float/bool differ, dictionary order is opt-in."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return (actual.keys() == expected.keys() and (not ordered_dict or list(actual) == list(expected))
                and all(json_equal(actual[k], v, ordered_dict) for k, v in expected.items()))
    if type(expected) is list:
        return len(actual) == len(expected) and all(json_equal(a, b, ordered_dict) for a, b in zip(actual, expected))
    return type(expected) in (str, int, float, bool, type(None)) and actual == expected


def _strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError('Duplicate JSON key')
            out[key] = value
        return out
    def constant(_): raise ValueError('Non-finite JSON number')
    def floating(text):
        value=float(text)
        if not math.isfinite(value):raise ValueError('Non-finite JSON number')
        return value
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)


def _preview(value):
    text = json.dumps(value, allow_nan=False)
    return value if len(text) <= 1200 else {'truncated': True, 'preview': text[:1200]}


def compare_observations(tests, raw):
    """Trusted parent only. Candidate-supplied grades or unknown fields are rejected."""
    data = _strict_json(raw)
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1 or set(data) - {'version','results','setup_error','interrupted'}:
        raise ValueError('Invalid observation envelope')
    observations = data.get('results')
    if not isinstance(observations, list) or len(observations) > len(tests): raise ValueError('Invalid observation count')
    if data.get('interrupted') not in (None, 'timeout'): raise ValueError('Invalid interruption')
    if 'setup_error' in data:
        error = data['setup_error']
        if observations or not isinstance(error, dict) or set(error) != {'type','message'} or not all(type(x) is str for x in error.values()):
            raise ValueError('Invalid setup error')
        return dict(status='error', passed=0, failed=len(tests), tests_run=0, total=len(tests),
                    error=error['type']+': '+error['message'][:1000], failure_kind='candidate_runtime')
    if not data.get('interrupted') and len(observations) != len(tests): raise ValueError('Missing observations')
    passed, first = 0, None
    for index, (case, observation) in enumerate(zip(tests, observations)):
        if not isinstance(observation, dict): raise ValueError('Invalid observation')
        kind = observation.get('kind')
        required = {'value': {'kind','value','args_after','kwargs_after'},
                    'exception': {'kind','exception_type','message','args_after','kwargs_after'},
                    'serialization_error': {'kind','message'}}.get(kind)
        if kind == 'serialization_error' and set(observation) == {'kind','message','args_after','kwargs_after'}:
            required=set(observation)
        if required is None or set(observation) != required: raise ValueError('Invalid observation fields')
        if kind == 'serialization_error' and not isinstance(observation['message'],str):raise ValueError('Invalid serialization observation')
        if kind == 'exception' and (not isinstance(observation['exception_type'], str) or not observation['exception_type'].isidentifier() or not isinstance(observation['message'], str)):
            raise ValueError('Invalid exception observation')
        unchanged = kind != 'serialization_error' and json_equal(observation['args_after'], case['args'], True) and json_equal(observation['kwargs_after'], case.get('kwargs', {}), True)
        mutation = case.get('check_input_unchanged', True) and not unchanged
        ok = (kind == 'value' and 'expected' in case and json_equal(observation['value'], case['expected'], case.get('ordered_dict', False))
              or kind == 'exception' and observation['exception_type'] == case.get('expected_exception')) and not mutation
        passed += bool(ok)
        if not ok and first is None:
            first = dict(test_index=index, input=_preview({'args':case['args'],'kwargs':case.get('kwargs',{})}),
                         expected=_preview(case.get('expected', {'exception':case.get('expected_exception')})),
                         actual=_preview(observation.get('value')), error=observation.get('message'),
                         failure_kind='serialization_error' if kind == 'serialization_error' else 'input_mutation' if mutation else 'wrong_exception' if 'expected_exception' in case else 'wrong_result',
                         input_unchanged=unchanged)
    return dict(status='timeout' if data.get('interrupted') else 'passed' if passed == len(tests) else 'failed',
                passed=passed, failed=len(observations)-passed, total=len(tests), tests_run=len(observations), first_failure=first,
                failure_kind='candidate_timeout' if data.get('interrupted') else None if passed == len(tests) else 'candidate_test_failure')


def _bounded_process(argv, payload=None, timeout=15):
    """Bound stdout+stderr while pumping stdin; never interpolate candidate text."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pending = (payload or '').encode(); offset=0; output={proc.stdout:bytearray(), proc.stderr:bytearray()}
    selector=selectors.DefaultSelector(); end=time.monotonic()+timeout
    for stream in (proc.stdin,proc.stdout,proc.stderr): os.set_blocking(stream.fileno(),False)
    selector.register(proc.stdout,selectors.EVENT_READ);selector.register(proc.stderr,selectors.EVENT_READ)
    if pending: selector.register(proc.stdin,selectors.EVENT_WRITE)
    else: proc.stdin.close()
    try:
        while selector.get_map():
            remaining=end-time.monotonic()
            if remaining<=0: raise subprocess.TimeoutExpired(argv,timeout)
            for key,_ in selector.select(min(remaining,.2)):
                stream=key.fileobj
                if stream is proc.stdin:
                    try: offset+=os.write(stream.fileno(),pending[offset:offset+65536])
                    except BrokenPipeError: offset=len(pending)
                    if offset==len(pending): selector.unregister(stream);stream.close()
                else:
                    chunk=os.read(stream.fileno(),65536)
                    if not chunk: selector.unregister(stream);stream.close();continue
                    output[stream].extend(chunk)
                    if sum(map(len,output.values()))>MAX_OUTPUT: raise ValueError('Candidate transport output exceeds1MiB')
        return SimpleNamespace(returncode=proc.wait(timeout=max(.01,end-time.monotonic())), stdout=bytes(output[proc.stdout]).decode(errors='replace'), stderr=bytes(output[proc.stderr]).decode(errors='replace'))
    finally:
        selector.close()
        if proc.poll() is None:proc.kill();proc.wait()
        for stream in (proc.stdin,proc.stdout,proc.stderr):
            if not stream.closed:stream.close()


def _ssh(host, command, payload=None, timeout=15):
    return _bounded_process(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','--',host,shlex.join(command)],payload,timeout)


def _state_and_cleanup(host, name, task):
    state, error = None, None
    try:
        response = _ssh(host,['docker','inspect','--format','{{json .State}}\n{{index .Config.Labels "swarm-lab.code-owner"}}\n{{index .Config.Labels "swarm-lab.code-task"}}',name])
        lines=response.stdout.splitlines()
        if response.returncode or len(lines)!=3 or lines[1:]!=[OWNER,task]:raise ValueError('Owned container inspection failed')
        raw_state=_strict_json(lines[0])
        if not isinstance(raw_state,dict):raise ValueError('Invalid container state')
        state={k:raw_state.get(k) for k in ['OOMKilled','ExitCode','Error','Running']}
    except (OSError,ValueError,subprocess.TimeoutExpired):error='inspection_infrastructure'
    exists=shlex.join(['docker','container','inspect',name])
    owner=shlex.join(['docker','inspect','--format','{{index .Config.Labels "swarm-lab.code-owner"}}',name])
    identity=shlex.join(['docker','inspect','--format','{{index .Config.Labels "swarm-lab.code-task"}}',name])
    remove=shlex.join(['docker','rm','-f',name])
    cleanup=f'if {exists} >/dev/null 2>&1; then if [ "$({owner})" = {shlex.quote(OWNER)} ] && [ "$({identity})" = {shlex.quote(task)} ]; then {remove}; else exit 1; fi; fi'
    try: clean=_ssh(host,['sh','-c',cleanup]).returncode==0
    except (OSError,ValueError,subprocess.TimeoutExpired):clean=False
    return state,error,clean and error is None


def _validate_json(value):
    t=type(value)
    if value is None or t in (str,int,bool):return
    if t is float and math.isfinite(value):return
    if t is list:
        for item in value:_validate_json(item)
        return
    if t is dict and all(type(k) is str for k in value):
        for item in value.values():_validate_json(item)
        return
    raise ValueError('Tests require exact JSON types and finite numbers')


def evaluate_code(code, function_name, tests, host, timeout=10):
    """API compatible confirmation grade; no remote work occurs on import."""
    if not isinstance(code,str) or len(code)>65536 or not isinstance(function_name,str) or not function_name.isidentifier() or keyword.iskeyword(function_name):raise ValueError('Invalid code/function name')
    if not isinstance(host,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9][A-Za-z0-9_.-]*)?',host):raise ValueError('Invalid SSH host')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=60:raise ValueError('Invalid timeout')
    if not isinstance(tests,list) or not 1<=len(tests)<=128:raise ValueError('Expected1..128 tests')
    for case in tests:
        if not isinstance(case,dict) or type(case.get('args')) is not list or type(case.get('kwargs',{})) is not dict or ('expected' in case)==('expected_exception' in case):raise ValueError('Invalid case')
        if 'expected_exception' in case and (not isinstance(case['expected_exception'],str) or not case['expected_exception'].isidentifier()):raise ValueError('Invalid exception name')
        if not all(type(k) is str for k in case.get('kwargs',{})):raise ValueError('Invalid keyword name')
        if any(flag in case and type(case[flag]) is not bool for flag in ['check_input_unchanged','ordered_dict']):raise ValueError('Invalid test flag')
    _validate_json(tests)
    # Normalize/deep-copy the private tests in the trusted parent, then remove every oracle field.
    tests=_strict_json(json.dumps(tests,allow_nan=False))
    payload=json.dumps(dict(code=code,function_name=function_name,calls=[dict(args=c['args'],kwargs=c.get('kwargs',{})) for c in tests],timeout=timeout),allow_nan=False)
    if len(payload.encode())>MAX_OUTPUT:raise ValueError('Candidate input exceeds1MiB')
    task=uuid.uuid4().hex;name='swarm-independent-code-'+task
    command=['docker','run','--pull','never','--runtime','runc','-i','--name',name,'--label','swarm-lab.code-owner='+OWNER,'--label','swarm-lab.code-task='+task,
             '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','256m','--memory-swap','256m',
             '--cpus','1','--user','65534:65534','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=16m','--workdir','/tmp','--env','NVIDIA_VISIBLE_DEVICES=void',
             '--stop-timeout','1','--entrypoint','python3',IMAGE,'-I','-S','-c',CHILD]
    result=dict(status='error',passed=0,failed=0,total=len(tests),tests_run=0)
    process,error=None,None
    try:process=_ssh(host,command,payload,timeout+15)
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:error=exc
    state,inspection,clean=_state_and_cleanup(host,name,task)
    if state and state.get('OOMKilled'):result.update(failure_kind='candidate_oom',error='Candidate exceeded container memory')
    elif isinstance(error,subprocess.TimeoutExpired):result.update(status='timeout',failure_kind='candidate_timeout' if state and not state.get('Error') else 'ssh_infrastructure',error='Execution deadline exceeded')
    elif isinstance(error,ValueError):result.update(failure_kind='candidate_protocol',error='Candidate transport output limit exceeded')
    elif error:result.update(failure_kind='ssh_infrastructure',error=type(error).__name__)
    elif process.returncode:
        kind='ssh_infrastructure' if process.returncode==255 else 'docker_infrastructure' if not state or state.get('Error') or process.returncode in (125,126,127) else 'candidate_signal' if (state.get('ExitCode') or 0)>=128 else 'candidate_runtime'
        result.update(failure_kind=kind,exit_code=process.returncode,error=kind)
    else:
        try:result=compare_observations(tests,process.stdout)
        except (ValueError,TypeError,KeyError,RecursionError):result.update(failure_kind='candidate_protocol',error='Invalid candidate observation protocol')
    if inspection:result['failure_kind']=inspection
    if not clean:result['original_failure_kind']=result.get('failure_kind');result['failure_kind']='cleanup_infrastructure'
    result.update(cleanup_ok=clean,container_state=state,provenance='infrastructure' if str(result.get('failure_kind')).endswith('_infrastructure') else 'candidate',
                  grading_authority='outer_parent',oracle_sent_to_child=False,child_payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                  observation_scope='Child values, exception names and input-after snapshots are observations, not authenticated interpreter provenance')
    return result
