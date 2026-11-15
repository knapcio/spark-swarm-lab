"""Evaluate generated functions only in a constrained, CPU-only remote container.

Importing this module never contacts a host or executes candidate code. This is
container isolation, not a defense against a malicious candidate forging grades
inside the same Python interpreter as its tests.
"""
import copy
import inspect
import json
import keyword
import math
import re
import shlex
import subprocess
import uuid

IMAGE = "python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd"
OWNER = "swarm-lab-code-eval"


def _bounded(value):
    try:
        text = json.dumps(value, allow_nan=False)
        if len(text) <= 1200:
            return value
    except (TypeError, ValueError):
        text = repr(value)
    return {"truncated_or_non_json": True, "preview": text[:1200]}


def _json_equal(actual, expected, ordered_dict=False):
    """Exact JSON types/shape/value: bool, int and float are distinct; no tolerance."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        if not all(type(key) is str for key in actual) or actual.keys() != expected.keys():
            return False
        if ordered_dict and list(actual) != list(expected):
            return False
        return all(_json_equal(actual[key], value, ordered_dict) for key, value in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_json_equal(a, b, ordered_dict) for a, b in zip(actual, expected))
    return type(expected) in (str, int, float, bool, type(None)) and actual == expected


def _run_cases(function, tests):
    """Trusted grading logic; tests may call this only with trusted functions."""
    passed, first_failure = 0, None
    for index, case in enumerate(tests):
        args, kwargs = copy.deepcopy(case["args"]), copy.deepcopy(case.get("kwargs", {}))
        actual, error = None, None
        try:
            actual = function(*args, **kwargs)
            ok = "expected_exception" not in case and _json_equal(actual, case["expected"], case.get("ordered_dict", False))
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)[:1000]
            ok = type(exc).__name__ == case.get("expected_exception")
        unchanged = _json_equal(args, case["args"], True) and _json_equal(kwargs, case.get("kwargs", {}), True)
        mutation = case.get("check_input_unchanged", True) and not unchanged
        ok = ok and not mutation
        passed += bool(ok)
        if not ok and first_failure is None:
            first_failure = {"test_index": index, "input": _bounded({"args": case["args"], "kwargs": case.get("kwargs", {})}),
                             "expected": _bounded(case.get("expected", {"exception": case.get("expected_exception")})),
                             "actual": _bounded(actual), "error": error,
                             "actual_type": type(actual).__name__, "expected_type": type(case.get("expected")).__name__,
                             "failure_kind": "input_mutation" if mutation else "wrong_exception" if "expected_exception" in case else "wrong_result",
                             "input_unchanged": unchanged}
            if mutation:
                first_failure["input_after"] = _bounded({"args": args, "kwargs": kwargs})
    return {"status": "passed" if passed == len(tests) else "failed", "total": len(tests),
            "tests_run": len(tests), "passed": passed, "failed": len(tests) - passed,
            "first_failure": first_failure}


# Static trusted source only. Candidate source and cases travel through stdin JSON.
RUNNER = "import copy,json,os,signal,sys,contextlib,io\n" + inspect.getsource(_bounded) + inspect.getsource(_json_equal) + inspect.getsource(_run_cases) + r'''
class Deadline(BaseException): pass
def deadline(*_): raise Deadline()
class Capture(io.TextIOBase):
    def __init__(self): self.text = ""
    def write(self, text):
        self.text += str(text)[:max(0, 2048-len(self.text))]
        return len(text)
    def flush(self): pass
payload = json.load(sys.stdin)
protocol = os.dup(1)
null = os.open(os.devnull, os.O_WRONLY)
os.dup2(null, 1)
os.dup2(null, 2)
capture = Capture()
signal.signal(signal.SIGALRM, deadline)
signal.setitimer(signal.ITIMER_REAL, payload["timeout"])
try:
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
        namespace = {}
        exec(compile(payload["code"], "<candidate>", "exec"), namespace)
        function = namespace.get(payload["function_name"])
        if not callable(function): raise TypeError("Named function is not callable")
        result = _run_cases(function, payload["tests"])
except Deadline:
    result = {"status":"timeout", "tests_run":0, "passed":0, "failed":0, "error":"Execution deadline exceeded"}
except BaseException as exc:
    result = {"status":"error", "tests_run":0, "passed":0, "failed":0, "error":type(exc).__name__+": "+str(exc)[:1000]}
signal.setitimer(signal.ITIMER_REAL, 0)
result["captured_output"] = capture.text
result["total"] = len(payload["tests"])
os.write(protocol, json.dumps(result, allow_nan=False).encode())
'''


def _validate(code, function_name, tests, host, timeout):
    if not isinstance(code, str) or len(code) > 65536:
        raise ValueError("code must be a string of at most 65536 characters")
    if not isinstance(function_name, str) or not function_name.isidentifier() or keyword.iskeyword(function_name):
        raise ValueError("function_name must be a Python identifier")
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9][A-Za-z0-9_.-]*)?", host):
        raise ValueError("host must be an SSH alias or user@host")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("timeout must be positive and at most 60 seconds")
    if not isinstance(tests, list) or not 1 <= len(tests) <= 128:
        raise ValueError("tests must contain 1..128 cases")
    for case in tests:
        if not isinstance(case, dict) or not isinstance(case.get("args"), list) or not isinstance(case.get("kwargs", {}), dict):
            raise ValueError("each case needs args:list and optional kwargs:dict")
        if not all(isinstance(key, str) for key in case.get("kwargs", {})):
            raise ValueError("keyword argument names must be strings")
        if ("expected" in case) == ("expected_exception" in case):
            raise ValueError("each case needs exactly one of expected or expected_exception")
        if "expected_exception" in case and (not isinstance(case["expected_exception"], str) or not case["expected_exception"].isidentifier()):
            raise ValueError("expected_exception must be an exception class name")
        for flag in ("check_input_unchanged", "ordered_dict"):
            if flag in case and type(case[flag]) is not bool:
                raise ValueError(flag + " must be a boolean")


def _ssh(host, command, payload=None, timeout=15):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", host,
                           shlex.join(command)], input=payload, text=True, capture_output=True, timeout=timeout)


def _cleanup(host, name, task):
    # Inspect two exact labels before removing this unique task's container.
    owner = shlex.join(["docker", "inspect", "--format", '{{index .Config.Labels "swarm-lab.code-owner"}}', name])
    identity = shlex.join(["docker", "inspect", "--format", '{{index .Config.Labels "swarm-lab.code-task"}}', name])
    exists = shlex.join(["docker", "container", "inspect", name])
    remove = shlex.join(["docker", "rm", "-f", name])
    command = f'if {exists} >/dev/null 2>&1; then if [ "$({owner} 2>/dev/null)" = {shlex.quote(OWNER)} ] && [ "$({identity} 2>/dev/null)" = {shlex.quote(task)} ]; then {remove}; else exit 1; fi; fi'
    try:
        result = _ssh(host, ["sh", "-c", command], timeout=15)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _inspect_owned(host, name, task):
    """Read exit/OOM evidence only after verifying both unique ownership labels."""
    try:
        process = _ssh(host, ["docker", "inspect", "--format", "{{json .}}", name])
        if process.returncode:
            return None, "Container inspection failed: " + process.stderr[-1000:]
        container = json.loads(process.stdout)
        labels = container.get("Config", {}).get("Labels", {})
        if labels.get("swarm-lab.code-owner") != OWNER or labels.get("swarm-lab.code-task") != task:
            return None, "Container ownership mismatch"
        state = container["State"]
        return {key: state.get(key) for key in ("OOMKilled", "ExitCode", "Error", "Running")}, None
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, "Container inspection failed: " + str(exc)[:1000]


def evaluate_code(code, function_name, tests, host, timeout=10):
    """Return bounded diagnostics; execute candidate code only on the named host."""
    _validate(code, function_name, tests, host, timeout)
    payload = json.dumps(dict(code=code, function_name=function_name, tests=tests, timeout=timeout), allow_nan=False)
    if len(payload.encode()) > 1_000_000:
        raise ValueError("evaluation payload exceeds 1 MB")
    task = uuid.uuid4().hex
    name = "swarm-code-" + task
    command = ["docker", "run", "--pull", "never", "--runtime", "runc", "-i", "--name", name,
               "--label", "swarm-lab.code-owner=" + OWNER, "--label", "swarm-lab.code-task=" + task,
               "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", "64", "--memory", "256m", "--memory-swap", "256m", "--cpus", "1",
               "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--workdir", "/tmp",
               "--env", "NVIDIA_VISIBLE_DEVICES=void",
               "--stop-timeout", "1", "--entrypoint", "python3", IMAGE, "-I", "-S", "-c", RUNNER]
    process, execution_error = None, None
    try:
        process = _ssh(host, command, payload, timeout=timeout + 15)
    except (subprocess.TimeoutExpired, OSError) as exc:
        execution_error = exc
    # --rm would erase the kernel's OOM evidence. Inspect, then always guard cleanup.
    state, inspect_error = _inspect_owned(host, name, task)
    cleanup_ok = _cleanup(host, name, task)
    result = dict(status="error", passed=0, failed=0, tests_run=0, total=len(tests))
    if isinstance(execution_error, subprocess.TimeoutExpired):
        result.update(status="timeout", error="Controller deadline exceeded",
                      failure_kind="candidate_timeout" if state and not state.get("Error") else "ssh_infrastructure")
    elif execution_error is not None:
        result.update(error=type(execution_error).__name__ + ": " + str(execution_error)[:1000], failure_kind="ssh_infrastructure")
    elif process.returncode:
        kind = "docker_infrastructure"
        if process.returncode == 255:
            kind = "ssh_infrastructure"
        elif state and state.get("OOMKilled"):
            kind = "candidate_oom"
        elif state and not state.get("Error") and process.returncode not in (125, 126, 127):
            kind = "candidate_signal" if (state.get("ExitCode") or 0) >= 128 else "candidate_runtime"
        result.update(error=process.stderr[-2000:] or kind.replace("_", " "), exit_code=process.returncode, failure_kind=kind)
    else:
        try:
            if len(process.stdout) > 65536:
                raise ValueError("runner output exceeds 64 KiB")
            parsed = json.loads(process.stdout)
            if not isinstance(parsed, dict) or parsed.get("status") not in ("passed", "failed", "error", "timeout"):
                raise ValueError("invalid runner response")
            result = parsed
            result["failure_kind"] = {"passed": None, "failed": "candidate_test_failure", "error": "candidate_runtime", "timeout": "candidate_timeout"}[result["status"]]
        except (ValueError, TypeError) as exc:
            result.update(error="Invalid runner protocol: " + str(exc)[:1000], failure_kind="protocol_infrastructure")
    result.update(container_state=state, cleanup_ok=cleanup_ok)
    if inspect_error:
        result["inspection_error"] = inspect_error
        if not result.get("failure_kind", "") or not result.get("failure_kind", "").endswith("_infrastructure"):
            result["failure_kind"] = "inspection_infrastructure"
    if not cleanup_ok:
        result["original_failure_kind"] = result.get("failure_kind")
        result["failure_kind"] = "cleanup_infrastructure"
    result["provenance"] = "infrastructure" if str(result.get("failure_kind")).endswith("_infrastructure") else "candidate"
    return result
