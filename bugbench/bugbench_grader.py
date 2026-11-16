"""Offline bugbench grader: apply a full-file-replacement patch, run hidden probes.

Importing this module runs nothing.  Grading materializes the buggy case tree
in memory, applies the candidate patch, and sends files plus the trusted probe
source to a fresh ``python3 -I -S`` child over stdin.  The child returns only
observations; expected values never enter it, and the outer parent alone
compares them (mirroring ``independent_code_grader.py``).

Two execution backends run the same CHILD with the same payload:

* local (default): a ``python3 -I -S`` subprocess.  Process isolation for
  authored fixtures and offline development only, not a sandbox.
* ``DockerExecutor(host)``: the pinned CPU-only image on a remote host over
  ``ssh``, with the isolation flags of ``sandbox_code.py`` and
  ``independent_code_grader.py``, owned labels, inspection before guarded
  cleanup, and infrastructure-vs-candidate failure classification.  Use it for
  every model-generated patch.  Its subprocess function is injectable so the
  protocol is tested offline with a fake ``ssh``.
"""
import argparse
import ast
import difflib
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import shlex
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(ROOT, "projects")
IMAGE = "python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd"
OWNER = "swarm-lab-bugbench-eval"
LABEL_OWNER = "swarm-lab.code-owner"
LABEL_TASK = "swarm-lab.code-task"
SSH_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9][A-Za-z0-9_.-]*)?")
MAX_PAYLOAD_BYTES = 1_000_000
CONTAINER_STARTUP_SLACK = 15  # seconds added to the grading deadline for ssh + container start
MAX_FILE_BYTES = 65536
MAX_PATCH_FILES = 3
MAX_CHILD_OUTPUT = 1_048_576
CHARS_PER_TOKEN = 3.6  # rough offline estimate; record real tokenizer counts from the server
FILE_START = re.compile(r"^=== FILE: (?P<path>\S+) ===[ \t]*$")
FILE_END = re.compile(r"^=== END FILE ===[ \t]*$")
FENCE = re.compile(r"^```[A-Za-z0-9_+-]*[ \t]*$")
ELISION = re.compile(r"^\s*(#\s*)?\.\.\.\s*(\(?(rest|remaining|unchanged|same|omitted)\b.*)?$", re.I | re.M)


class PatchError(ValueError):
    """The candidate patch cannot be parsed or is not allowed."""


# --- child (trusted runner; receives files and probe source, never expected values) ---
CHILD = r'''
import json,os,signal,sys,tempfile,io,contextlib
_type,_str,_int,_float,_bool,_list,_dict = type,str,int,float,bool,list,dict
_dumps,_write = json.dumps,os.write
class Deadline(BaseException): pass
def expired(*_): raise Deadline()
def plain(value, depth=0):
    if depth > 50: raise TypeError('observation nested too deeply')
    t = _type(value)
    if value is None or t in (_str,_int,_bool): return value
    if t is _float:
        if value != value or value in (float('inf'), float('-inf')): raise TypeError('non-finite float')
        return value
    if t in (_list, tuple): return [plain(x, depth+1) for x in value]
    if t is _dict and all(_type(k) is _str for k in value): return {k: plain(v, depth+1) for k, v in value.items()}
    raise TypeError('unsupported observation type: '+t.__name__)
payload = json.load(sys.stdin)
protocol = os.dup(1)
null = os.open(os.devnull, os.O_WRONLY)
os.dup2(null, 1); os.dup2(null, 2)
sys.dont_write_bytecode = True
root = tempfile.mkdtemp(prefix='bugbench-')
for rel, text in payload['files'].items():
    path = os.path.join(root, *rel.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle: handle.write(text)
sys.path.insert(0, root)
package = payload['package']
def purge():
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'): del sys.modules[name]
result = {'version': 1}
signal.signal(signal.SIGALRM, expired)
if payload['mode'] == 'public_tests':
    import unittest
    stream = io.StringIO()
    signal.setitimer(signal.ITIMER_REAL, payload['timeout'])
    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            tests = os.path.join(root, 'tests')
            suite = unittest.defaultTestLoader.discover(start_dir=tests, top_level_dir=tests)
            run = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
        result.update(tests_run=run.testsRun, failures=len(run.failures), errors=len(run.errors),
                      ok=run.wasSuccessful())
    except Deadline:
        result.update(interrupted='timeout', ok=False)
    except BaseException as exc:
        result.update(ok=False, setup_error=_type(exc).__name__ + ': ' + _str(exc)[:1000])
    signal.setitimer(signal.ITIMER_REAL, 0)
    result['output'] = stream.getvalue()[-4000:]
else:
    result['results'] = []
    signal.setitimer(signal.ITIMER_REAL, payload['probe_timeout'])
    try:
        __import__(package)
    except Deadline:
        result['import_error'] = 'Deadline: import exceeded probe timeout'
    except BaseException as exc:
        result['import_error'] = _type(exc).__name__ + ': ' + _str(exc)[:1000]
    signal.setitimer(signal.ITIMER_REAL, 0)
    namespace = {'__name__': 'bugbench_probes'}
    exec(compile(payload['probes'], '<probes>', 'exec'), namespace)
    for name in payload['probe_names']:
        purge()
        signal.setitimer(signal.ITIMER_REAL, payload['probe_timeout'])
        try:
            observation = {'kind': 'value', 'value': plain(namespace[name]())}
            _dumps(observation, allow_nan=False)
        except Deadline:
            observation = {'kind': 'timeout'}
        except BaseException as exc:
            observation = {'kind': 'exception', 'exception_type': _type(exc).__name__, 'message': _str(exc)[:500]}
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        result['results'].append(observation)
_write(protocol, _dumps(result, allow_nan=False).encode())
'''


# --- project and case loading --------------------------------------------------
def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def load_project(name):
    base = os.path.join(PROJECTS, name)
    meta = json.loads(_read(os.path.join(base, "project.json")))
    meta.update(base=base, clean=os.path.join(base, "clean"), hidden=os.path.join(base, "hidden"))
    return meta


def read_tree(directory):
    """All text files under ``directory`` as {posix relative path: content}, skipping caches."""
    files = {}
    for current, dirs, names in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
        for name in sorted(names):
            if name.endswith((".pyc", ".pyo")) or name.startswith("."):
                continue
            path = os.path.join(current, name)
            files[os.path.relpath(path, directory).replace(os.sep, "/")] = _read(path)
    return files


def tree_sha256(files):
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode() + b"\0" + files[path].encode() + b"\0")
    return digest.hexdigest()


def list_cases(project=None):
    found = []
    for name in sorted(os.listdir(PROJECTS)):
        if project and name != project:
            continue
        cases = os.path.join(PROJECTS, name, "cases")
        if os.path.isdir(cases):
            found += sorted(entry for entry in os.listdir(cases) if os.path.isfile(os.path.join(cases, entry, "case.json")))
    return found


def load_case(case_id):
    for project in sorted(os.listdir(PROJECTS)):
        directory = os.path.join(PROJECTS, project, "cases", case_id)
        if os.path.isfile(os.path.join(directory, "case.json")):
            case = json.loads(_read(os.path.join(directory, "case.json")))
            case["dir"] = directory
            case["report_text"] = _read(os.path.join(directory, case["report"]))
            return case
    raise KeyError(f"unknown case {case_id!r}")


def apply_mutation(files, mutations):
    """Apply exact, single-occurrence text replacements (the planted bug)."""
    result = dict(files)
    for mutation in mutations:
        text = result[mutation["file"]]
        if text.count(mutation["old"]) != 1:
            raise ValueError(f"mutation anchor must occur exactly once in {mutation['file']}")
        result[mutation["file"]] = text.replace(mutation["old"], mutation["new"])
    return result


def clean_files(project_name):
    return read_tree(load_project(project_name)["clean"])


def buggy_files(case):
    return apply_mutation(clean_files(case["project"]), case["mutations"])


def editable_paths(project, files):
    return sorted(path for path in files if any(fnmatch.fnmatchcase(path, glob) for glob in project["editable"]))


# --- agent-facing material -------------------------------------------------------
def approx_tokens(text):
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


def repo_map(files):
    """Compact outline: per file line/token counts and top-level signatures with first doc lines."""
    out = []
    for path in sorted(files):
        text = files[path]
        out.append(f"{path}  ({text.count(chr(10))} lines, ~{approx_tokens(text)} tokens)")
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            out.append("  <syntax error>")
            continue

        def describe(node, prefix, indent):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                    if isinstance(child, ast.ClassDef):
                        line = f"{indent}class {prefix}{child.name}"
                    else:
                        line = f"{indent}def {prefix}{child.name}({ast.unparse(child.args)})"
                    doc = ast.get_docstring(child)
                    if doc:
                        line += "  # " + doc.strip().splitlines()[0][:90]
                    out.append(line)
                    if isinstance(child, ast.ClassDef):
                        describe(child, child.name + ".", indent + "  ")
        describe(tree, "", "  ")
    return "\n".join(out) + "\n"


def agent_bundle(case_id):
    """Everything an agent may see: buggy files, the public report, a repo map, editable paths."""
    case = load_case(case_id)
    project = load_project(case["project"])
    files = buggy_files(case)
    return {"case_id": case_id, "project": case["project"], "hint_variant": case["hint_variant"],
            "report": case["report_text"], "files": files, "repo_map": repo_map(files),
            "editable_paths": editable_paths(project, files), "patch_format": PATCH_FORMAT_HELP}


def write_tree(files, destination):
    if os.path.exists(destination) and os.listdir(destination):
        raise FileExistsError(f"{destination} is not empty")
    for path, text in files.items():
        target = os.path.join(destination, *path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)


# --- patch format -----------------------------------------------------------------
PATCH_FORMAT_HELP = """Return the COMPLETE new content of every file you change, each wrapped like this:

=== FILE: stockroom/example.py ===
<entire file content, not just the changed lines>
=== END FILE ===

Rules: change at most 3 files; only existing files listed as editable; no new files;
text outside the blocks is ignored. A Markdown code fence directly inside a block is allowed.
"""


def _normalize_path(raw):
    path = raw.strip().strip("`'\"")
    if path.startswith("./"):
        path = path[2:]
    if not path or "\\" in path or path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
        raise PatchError(f"illegal path {raw!r}")
    return path


def parse_patch(text):
    """Parse FILE blocks into {path: content}.  Raises PatchError on malformed input."""
    if not isinstance(text, str):
        raise PatchError("patch must be text")
    blocks, current_path, current_lines = {}, None, []
    for line in text.splitlines():
        start, end = FILE_START.match(line), FILE_END.match(line)
        if current_path is None:
            if start:
                current_path, current_lines = _normalize_path(start.group("path")), []
            elif end:
                raise PatchError("END FILE without a matching FILE header")
            continue
        if start:
            raise PatchError(f"FILE header inside block for {current_path}")
        if end:
            if current_path in blocks:
                raise PatchError(f"duplicate block for {current_path}")
            body = current_lines
            while body and not body[0].strip():
                body = body[1:]
            while body and not body[-1].strip():
                body = body[:-1]
            if len(body) >= 2 and FENCE.match(body[0]) and body[-1].strip() == "```":
                body = body[1:-1]
            blocks[current_path] = "\n".join(body) + "\n"
            current_path = None
            continue
        current_lines.append(line)
    if current_path is not None:
        raise PatchError(f"missing END FILE for {current_path} (truncated output?)")
    if not blocks:
        raise PatchError("no FILE blocks found")
    return blocks


def validate_patch(patch, files, project):
    """Reject anything except replacement of up to MAX_PATCH_FILES existing editable files."""
    if not isinstance(patch, dict) or not patch:
        raise PatchError("empty patch")
    if len(patch) > MAX_PATCH_FILES:
        raise PatchError(f"patch changes {len(patch)} files; at most {MAX_PATCH_FILES} allowed")
    allowed = set(editable_paths(project, files))
    for path, text in patch.items():
        if path not in files:
            raise PatchError(f"{path} does not exist (new files are not allowed)")
        if path not in allowed:
            raise PatchError(f"{path} is not editable")
        if not isinstance(text, str) or "\0" in text or len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise PatchError(f"{path}: content must be text without NUL, at most {MAX_FILE_BYTES} bytes")


def patch_from_files(changed):
    """Render {path: content} in the canonical FILE-block format."""
    return "".join(f"=== FILE: {path} ===\n{text if text.endswith(chr(10)) else text + chr(10)}=== END FILE ===\n"
                   for path, text in sorted(changed.items()))


def reference_patch(case):
    """Canonical fix: the clean content of every mutated file."""
    clean = clean_files(case["project"])
    return patch_from_files({path: clean[path] for path in sorted({m["file"] for m in case["mutations"]})})


def diff_stats(before, after):
    diff, added, removed = [], 0, 0
    for path in sorted(after):
        if before.get(path) == after[path]:
            continue
        lines = list(difflib.unified_diff(before.get(path, "").splitlines(True), after[path].splitlines(True),
                                          "a/" + path, "b/" + path))
        diff += lines
        added += sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed += sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    text = "".join(diff)
    return {"unified_diff": text, "added_lines": added, "removed_lines": removed,
            "diff_sha256": hashlib.sha256(text.encode()).hexdigest()}


def function_segments(source):
    """{qualified name: source} for every function/method, plus '<module>' for the remainder."""
    tree = ast.parse(source)
    segments, covered = {}, []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if isinstance(child, ast.ClassDef):
                    walk(child, name + ".")
                else:
                    segments[name] = ast.get_source_segment(source, child)
                    covered.append((child.lineno, child.end_lineno))
    walk(tree, "")
    lines = source.splitlines()
    outside = [line for number, line in enumerate(lines, 1) if not any(a <= number <= b for a, b in covered)]
    segments["<module>"] = "\n".join(line.rstrip() for line in outside if line.strip())
    return segments


def changed_functions(before, after):
    """Qualified names whose source differs (``path::name``); unparsable files count as '<syntax-error>'."""
    names = set()
    for path in sorted(after):
        if before.get(path) == after[path] or not path.endswith(".py"):
            continue
        try:
            old, new = function_segments(before[path]), function_segments(after[path])
        except SyntaxError:
            names.add(f"{path}::<syntax-error>")
            continue
        for name in set(old) | set(new):
            if old.get(name) != new.get(name):
                names.add(f"{path}::{name}")
    return sorted(names)


def score_localization(case, claim):
    """Score an explicit claim {"file": ..., "function": ...} against the gold location.

    ``gold.claim_aliases`` lists equivalent names for a defect outside a function
    (for example a module-level table and the function that reads it)."""
    file_hit = claim.get("file") in case["gold"]["files"]
    function = f"{claim.get('file')}::{claim.get('function')}"
    accepted = set(case["gold"]["functions"]) | set(case["gold"].get("claim_aliases", []))
    return {"file_hit": file_hit, "function_hit": function in accepted}


# --- child execution ----------------------------------------------------------------
def probe_names(probes_source):
    tree = ast.parse(probes_source)
    return [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("probe_")]


def run_child(payload, timeout, python=None):
    """Run CHILD locally with a bounded wall clock; returns (parsed result or None, error)."""
    python = python or sys.executable
    wire = json.dumps(payload, allow_nan=False)
    with tempfile.TemporaryDirectory(prefix="bugbench-run-") as scratch:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": scratch, "HOME": scratch, "LC_ALL": "C.UTF-8"}
        try:
            process = subprocess.run([python, "-I", "-S", "-c", CHILD], input=wire, capture_output=True, text=True,
                                     timeout=timeout, cwd=scratch, env=env)
        except subprocess.TimeoutExpired:
            return None, "controller_timeout"
    if process.returncode:
        return None, f"child_exit_{process.returncode}: {process.stderr[-1000:]}"
    return parse_child_output(process.stdout)


def parse_child_output(stdout):
    """(result, None) for a well-formed CHILD response, else (None, reason)."""
    if not isinstance(stdout, str) or len(stdout) > MAX_CHILD_OUTPUT:
        return None, "child_output_too_large"
    try:
        result = json.loads(stdout)
    except ValueError:
        return None, "child_protocol"
    if not isinstance(result, dict) or result.get("version") != 1:
        return None, "child_protocol"
    return result, None


def _local_failure_kind(error):
    if error is None:
        return None
    if error == "controller_timeout":
        return "candidate_timeout"
    if error in ("child_protocol", "child_output_too_large"):
        return "candidate_protocol"
    return "candidate_runtime"


def _execute(payload, timeout, python=None, executor=None):
    """Run CHILD with ``payload``; returns (result or None, error or None, execution metadata)."""
    if executor is None:
        result, error = run_child(payload, timeout, python)
        return result, error, {"executor": "local", "failure_kind": _local_failure_kind(error), "provenance": "candidate"}
    return executor(payload, timeout)


# --- docker executor (mirrors sandbox_code.py) ------------------------------------------
def container_argv(task_id):
    """The argv that runs CHILD in the pinned CPU-only image, same flags as sandbox_code.py.

    No ``--rm``: the container is inspected for OOM evidence, then removed by a
    label-guarded cleanup.  The payload (files + probes, never expected values)
    travels over stdin exactly as in local mode."""
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", task_id):
        raise ValueError("task id must be 1-64 characters of [A-Za-z0-9_-]")
    name = "swarm-bugbench-" + task_id
    return ["docker", "run", "--pull", "never", "--runtime", "runc", "-i", "--name", name,
            "--label", f"{LABEL_OWNER}={OWNER}", "--label", f"{LABEL_TASK}={task_id}",
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "256m", "--memory-swap", "256m", "--cpus", "1",
            "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--workdir", "/tmp",
            "--env", "NVIDIA_VISIBLE_DEVICES=void", "--stop-timeout", "1", "--entrypoint", "python3", IMAGE,
            "-I", "-S", "-c", CHILD]


def _ssh(host, command, payload=None, timeout=15, run=None):
    return (run or subprocess.run)(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", host,
                                    shlex.join(command)], input=payload, text=True, capture_output=True, timeout=timeout)


def _inspect_owned(host, name, task, run=None):
    """Container state, read only after verifying both unique ownership labels."""
    try:
        process = _ssh(host, ["docker", "inspect", "--format", "{{json .}}", name], run=run)
        if process.returncode:
            return None, "container inspection failed: " + (process.stderr or "")[-1000:]
        container = json.loads(process.stdout)
        labels = container.get("Config", {}).get("Labels") or {}
        if labels.get(LABEL_OWNER) != OWNER or labels.get(LABEL_TASK) != task:
            return None, "container ownership mismatch"
        state = container["State"]
        return {key: state.get(key) for key in ("OOMKilled", "ExitCode", "Error", "Running")}, None
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, "container inspection failed: " + type(exc).__name__ + ": " + str(exc)[:500]


def _cleanup(host, name, task, run=None):
    """Remove the container only if both labels match; True when nothing of ours is left."""
    owner = shlex.join(["docker", "inspect", "--format", '{{index .Config.Labels "%s"}}' % LABEL_OWNER, name])
    identity = shlex.join(["docker", "inspect", "--format", '{{index .Config.Labels "%s"}}' % LABEL_TASK, name])
    exists = shlex.join(["docker", "container", "inspect", name])
    remove = shlex.join(["docker", "rm", "-f", name])
    command = (f'if {exists} >/dev/null 2>&1; then if [ "$({owner} 2>/dev/null)" = {shlex.quote(OWNER)} ] && '
               f'[ "$({identity} 2>/dev/null)" = {shlex.quote(task)} ]; then {remove}; else exit 1; fi; fi')
    try:
        return _ssh(host, ["sh", "-c", command], timeout=15, run=run).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


class DockerExecutor:
    """Run CHILD in the pinned container on ``host`` (an SSH alias) with the payload on stdin.

    ``run`` replaces ``subprocess.run`` (tests inject a fake ``ssh``).  Returns
    ``(result, error, meta)``; ``meta.failure_kind`` is one of None,
    ``candidate_{timeout,oom,signal,runtime,protocol}`` or
    ``{ssh,docker,inspection,cleanup}_infrastructure``, and ``meta.provenance``
    says whether a failure is the candidate's or the grading infrastructure's.
    Results of infrastructure failures are discarded and must be re-graded."""

    def __init__(self, host, run=None, startup_slack=CONTAINER_STARTUP_SLACK):
        if not isinstance(host, str) or not SSH_HOST.fullmatch(host):
            raise ValueError("host must be an SSH alias or user@host")
        self.host, self.run, self.startup_slack = host, run or subprocess.run, startup_slack

    def __call__(self, payload, timeout):
        wire = json.dumps(payload, allow_nan=False)
        if len(wire.encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"grading payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        task = uuid.uuid4().hex
        name = "swarm-bugbench-" + task
        process, failure = None, None
        try:
            process = _ssh(self.host, container_argv(task), wire, timeout + self.startup_slack, self.run)
        except (subprocess.TimeoutExpired, OSError) as exc:
            failure = exc
        # --rm would erase the kernel's OOM evidence: inspect first, then always attempt guarded cleanup.
        state, inspection_error = _inspect_owned(self.host, name, task, self.run)
        cleanup_ok = _cleanup(self.host, name, task, self.run)
        meta = {"executor": "docker", "host": self.host, "container": name, "container_state": state,
                "cleanup_ok": cleanup_ok}
        result, error, kind = None, None, None
        if state and state.get("OOMKilled"):
            error, kind = "container_oom", "candidate_oom"
        elif isinstance(failure, subprocess.TimeoutExpired):
            error = "controller_timeout"
            kind = "candidate_timeout" if state and not state.get("Error") else "ssh_infrastructure"
        elif failure is not None:
            error, kind = f"{type(failure).__name__}: {str(failure)[:500]}", "ssh_infrastructure"
        elif process.returncode:
            meta["exit_code"] = process.returncode
            if process.returncode == 255:
                kind = "ssh_infrastructure"
            elif not state or state.get("Error") or process.returncode in (125, 126, 127):
                kind = "docker_infrastructure"
            else:
                kind = "candidate_signal" if (state.get("ExitCode") or 0) >= 128 else "candidate_runtime"
            error = f"exit_{process.returncode}: {(process.stderr or '')[-1000:]}"
        else:
            result, error = parse_child_output(process.stdout)
            kind = "candidate_protocol" if error else None
        if inspection_error:
            meta["inspection_error"] = inspection_error
            if not str(kind).endswith("_infrastructure"):
                meta["original_failure_kind"], kind = kind, "inspection_infrastructure"
        if not cleanup_ok:
            meta.setdefault("original_failure_kind", kind)
            kind = "cleanup_infrastructure"
        meta["failure_kind"] = kind
        meta["provenance"] = "infrastructure" if str(kind).endswith("_infrastructure") else "candidate"
        if meta["provenance"] == "infrastructure":
            result, error = None, error or kind
        return result, error, meta


# --- observing probes ----------------------------------------------------------------------
def probe_payload(project_name, files, probe_timeout=5.0):
    """The CHILD payload for the hidden probes: files and probe source, never expected values."""
    project = load_project(project_name)
    probes = _read(os.path.join(project["hidden"], "probes.py"))
    names = probe_names(probes)
    return {"mode": "probes", "package": project["package"], "files": files, "probes": probes,
            "probe_names": names, "probe_timeout": probe_timeout}, names


def _payload_sha(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def observe(project_name, files, probe_timeout=5.0, timeout=60.0, python=None, executor=None):
    """Run every hidden probe against ``files``; returns (child result, names, error, payload sha)."""
    payload, names = probe_payload(project_name, files, probe_timeout)
    result, error, _ = _execute(payload, timeout, python, executor)
    return result, names, error, _payload_sha(payload)


def run_public_tests(project_name, files, timeout=60.0, python=None, executor=None):
    """Self-check available to agents: the project's own visible tests on a patched copy."""
    project = load_project(project_name)
    result, error, meta = _execute({"mode": "public_tests", "package": project["package"], "files": files,
                                    "timeout": timeout - 5}, timeout, python, executor)
    if error or result is None:
        return {"ok": False, "error": error, "failure_kind": meta.get("failure_kind"), "provenance": meta.get("provenance")}
    return result


def json_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(json_equal(actual[k], v) for k, v in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(json_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def observation_matches(observed, expected):
    if not isinstance(observed, dict) or observed.get("kind") != expected["kind"]:
        return False
    if expected["kind"] == "exception":
        return observed.get("exception_type") == expected["exception_type"]
    if expected["kind"] == "value":
        return "value" in observed and json_equal(observed["value"], expected["value"])
    return False


def load_expected(project_name):
    return json.loads(_read(os.path.join(load_project(project_name)["hidden"], "expected.json")))


def compare(expected, names, child):
    """Trusted parent comparison; returns {probe name: bool}."""
    if names != list(expected["probes"]):
        raise ValueError("probe list differs from frozen expected.json; re-freeze deliberately")
    observations = child.get("results")
    if not isinstance(observations, list) or len(observations) != len(names):
        raise ValueError("child returned the wrong number of observations")
    return {name: observation_matches(obs, expected["probes"][name]) for name, obs in zip(names, observations)}


# --- grading --------------------------------------------------------------------------
def grade(case_id, patch_text, probe_timeout=5.0, timeout=60.0, python=None, executor=None):
    """Grade one candidate patch for one case.  Never raises for candidate faults.

    ``status``: ``passed``/``failed``/``timeout`` are candidate outcomes
    (``failure_kind`` says why, e.g. ``candidate_oom``); ``error`` means the
    grading infrastructure failed (``provenance == "infrastructure"``) and the
    patch must be re-graded; ``invalid_patch`` is never executed."""
    started = time.monotonic()
    case = load_case(case_id)
    project = load_project(case["project"])
    before = buggy_files(case)
    result = {"case_id": case_id, "status": "invalid_patch", "grading_authority": "outer_parent",
              "oracle_sent_to_child": False, "patch": {"valid": False}}
    try:
        patch = parse_patch(patch_text) if isinstance(patch_text, str) else dict(patch_text)
        validate_patch(patch, before, project)
    except PatchError as exc:
        result["patch"]["error"] = str(exc)
        result["duration_s"] = round(time.monotonic() - started, 3)
        return result
    after = dict(before)
    after.update(patch)
    stats = diff_stats(before, after)
    touched = changed_functions(before, after)
    result["patch"] = {"valid": True, "files": sorted(patch), "no_op": not stats["unified_diff"],
                       "added_lines": stats["added_lines"], "removed_lines": stats["removed_lines"],
                       "diff_sha256": stats["diff_sha256"], "unified_diff": stats["unified_diff"][:20000],
                       "suspected_elision": any(ELISION.search(text) and not ELISION.search(before[path])
                                                for path, text in patch.items())}
    gold_functions = set(case["gold"]["functions"])
    result["localization"] = {"files_touched": sorted(p for p in patch if before[p] != patch[p]),
                              "functions_touched": touched,
                              "gold_file_hit": any(p in case["gold"]["files"] and before[p] != patch[p] for p in patch),
                              "gold_function_hit": bool(gold_functions & set(touched))}
    expected = load_expected(case["project"])
    payload, names = probe_payload(case["project"], after, probe_timeout)
    result["child_payload_sha256"] = _payload_sha(payload)
    if names != list(expected["probes"]):
        result.update(status="error", error="probe list differs from frozen expected.json; re-freeze deliberately",
                      failure_kind="grader_infrastructure", provenance="infrastructure")
        return result
    child, error, meta = _execute(payload, timeout, python, executor)
    result["execution"] = {key: value for key, value in meta.items() if key not in ("failure_kind", "provenance")}
    result.update(failure_kind=meta.get("failure_kind"), provenance=meta.get("provenance"))
    if error or child is None:
        if result["provenance"] == "infrastructure":
            status = "error"
        else:
            status = "timeout" if result["failure_kind"] == "candidate_timeout" else "failed"
        result.update(status=status, error=error)
        result["duration_s"] = round(time.monotonic() - started, 3)
        return result
    try:
        passed = compare(expected, names, child)
    except ValueError as exc:
        result.update(status="failed", error=str(exc), failure_kind="candidate_protocol")
        result["duration_s"] = round(time.monotonic() - started, 3)
        return result
    targets = case["target_probes"]
    failed = [name for name, ok in passed.items() if not ok]
    result.update(
        status="passed" if not failed else "failed",
        failure_kind=None if not failed else "candidate_probe_failure",
        hidden={"passed": len(names) - len(failed), "total": len(names), "failed_probes": failed},
        target={"passed": sum(passed[name] for name in targets), "total": len(targets)},
        regression={"passed": sum(ok for name, ok in passed.items() if name not in targets),
                    "total": len(names) - len(targets), "broken": [name for name in failed if name not in targets]},
        import_error=child.get("import_error"),
        timed_out_probes=[name for name, obs in zip(names, child["results"])
                          if isinstance(obs, dict) and obs.get("kind") == "timeout"],
        duration_s=round(time.monotonic() - started, 3))
    return result


def freeze_expected(project_name, python=None):
    """Observe the clean reference and write hidden/expected.json (an explicit, reviewed step)."""
    project = load_project(project_name)
    files = clean_files(project_name)
    child, names, error, _ = observe(project_name, files, python=python)
    if error or child.get("import_error"):
        raise RuntimeError(f"clean reference failed: {error or child.get('import_error')}")
    bad = [name for name, obs in zip(names, child["results"]) if obs["kind"] == "timeout"]
    if bad:
        raise RuntimeError(f"clean reference timed out on {bad}")
    probes = _read(os.path.join(project["hidden"], "probes.py"))
    data = {"version": 1, "project": project_name, "canary": project["canary"],
            "clean_tree_sha256": tree_sha256(files),
            "probes_sha256": hashlib.sha256(probes.encode()).hexdigest(),
            "frozen_with_python": sys.version.split()[0],
            "probes": dict(zip(names, child["results"]))}
    with open(os.path.join(project["hidden"], "expected.json"), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=False)
        handle.write("\n")
    return data


def verify_case(case_id, python=None):
    """Prototype invariants for one case (used by tests and the ``verify`` command)."""
    case = load_case(case_id)
    clean = clean_files(case["project"])
    buggy = buggy_files(case)
    expected = load_expected(case["project"])
    child, names, error, _ = observe(case["project"], buggy, python=python)
    if error:
        raise RuntimeError(error)
    passed = compare(expected, names, child)
    reference = grade(case_id, reference_patch(case), python=python)
    return {"case_id": case_id,
            "buggy_failed_probes": sorted(name for name, ok in passed.items() if not ok),
            "declared_target_probes": sorted(case["target_probes"]),
            "reference_status": reference["status"],
            "reference_gold_function_hit": reference["localization"]["gold_function_hit"],
            "public_tests_clean": run_public_tests(case["project"], clean, python=python).get("ok"),
            "public_tests_buggy": run_public_tests(case["project"], buggy, python=python).get("ok")}


# --- probe strength: single-operator mutants of the clean package ---------------------------------
MUTATION_OPERATORS = (
    (" < ", " <= "), (" <= ", " < "), (" > ", " >= "), (" >= ", " > "), (" == ", " != "), (" != ", " == "),
    (" and ", " or "), (" or ", " and "), ("[0]", "[-1]"), ("[-1]", "[0]"), (" + 1", " - 1"), (" - 1", " + 1"),
    (".copy()", ""), ("True", "False"), ("False", "True"), ("sorted(", "list("), ("not ", ""), ("min(", "max("),
    ("max(", "min("), ("break", "continue"), (".lstrip()", ".rstrip()"), (".rstrip()", ".lstrip()"),
    (" += ", " -= "), ("ROUND_HALF_UP", "ROUND_HALF_EVEN"), (" is None", " is not None"),
    (" is not None", " is None"), ("return True", "return False"), ("return False", "return True"),
)


class _BlankStrings(ast.NodeTransformer):
    def visit_JoinedStr(self, node):
        return ast.Constant("")

    def visit_Constant(self, node):
        return ast.Constant("") if isinstance(node.value, str) else node


def _code_ast(source):
    """AST dump with every string literal and f-string blanked.

    Comments, docstrings and exception messages are not graded (exceptions are
    compared by type), so mutants that only touch them are not counted.  The
    operators never target semantic string literals."""
    return ast.dump(_BlankStrings().visit(ast.parse(source)))


def operator_mutants(files, paths):
    """Every single-operator, single-site mutant of ``paths`` that parses and changes the code (not only docs)."""
    mutants, seen = [], set()
    for path in paths:
        source = files[path]
        baseline, lines = _code_ast(source), source.splitlines(keepends=True)
        for number, line in enumerate(lines):
            for old, new in MUTATION_OPERATORS:
                start = line.find(old)
                while start != -1:
                    text = "".join(lines[:number] + [line[:start] + new + line[start + len(old):]] + lines[number + 1:])
                    start = line.find(old, start + 1)
                    try:
                        if _code_ast(text) == baseline:
                            continue
                    except SyntaxError:
                        continue
                    digest = hashlib.sha256(text.encode()).hexdigest()
                    if (path, digest) not in seen:
                        seen.add((path, digest))
                        mutants.append({"file": path, "line": number + 1, "old": old, "new": new, "text": text,
                                        "source_line": line.strip()})
    return mutants


def mutation_score(project_name, paths=None, limit=None, workers=8, probe_timeout=1.0, python=None):
    """Run the hidden probes against operator mutants of the clean tree (trusted code, local child).

    A mutant is killed when any probe observation differs from expected.json or
    the child fails.  Survivors need human review: some are equivalent mutants."""
    project = load_project(project_name)
    clean = clean_files(project_name)
    expected = load_expected(project_name)
    mutants = operator_mutants(clean, paths or editable_paths(project, clean))[:limit]

    def killed(mutant):
        files = dict(clean, **{mutant["file"]: mutant["text"]})
        child, names, error, _ = observe(project_name, files, probe_timeout, 120.0, python)
        if error or child.get("import_error"):
            return True
        try:
            return not all(compare(expected, names, child).values())
        except ValueError:
            return True
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(killed, mutants))
    survivors = [{key: mutant[key] for key in ("file", "line", "old", "new", "source_line")}
                 for mutant, dead in zip(mutants, outcomes) if not dead]
    total = len(mutants)
    return {"project": project_name, "mutants": total, "killed": total - len(survivors),
            "score": round((total - len(survivors)) / total, 4) if total else None, "survivors": survivors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    one = sub.add_parser("materialize", help="write the agent-visible buggy tree + REPORT.md")
    one.add_argument("case_id")
    one.add_argument("destination")
    show = sub.add_parser("reference-patch")
    show.add_argument("case_id")
    grade_cmd = sub.add_parser("grade")
    grade_cmd.add_argument("case_id")
    grade_cmd.add_argument("patch_file")
    grade_cmd.add_argument("--docker-host", help="grade in the pinned container on this SSH host (required for model patches)")
    check = sub.add_parser("selfcheck", help="public tests only (agent-visible feedback)")
    check.add_argument("case_id")
    check.add_argument("patch_file", nargs="?")
    check.add_argument("--docker-host", help="run in the pinned container on this SSH host")
    mutants = sub.add_parser("mutants", help="probe strength against single-operator mutants of clean/")
    mutants.add_argument("project")
    mutants.add_argument("--file", action="append", help="limit to these editable paths")
    mutants.add_argument("--limit", type=int)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("project")
    sub.add_parser("verify")
    args = parser.parse_args(argv)
    if args.command == "list":
        print("\n".join(list_cases()))
    elif args.command == "materialize":
        bundle = agent_bundle(args.case_id)
        files = dict(bundle["files"], **{"REPORT.md": bundle["report"], "REPO_MAP.txt": bundle["repo_map"]})
        write_tree(files, args.destination)
        print(f"wrote {len(files)} files to {args.destination}")
    elif args.command == "reference-patch":
        sys.stdout.write(reference_patch(load_case(args.case_id)))
    elif args.command == "grade":
        executor = DockerExecutor(args.docker_host) if args.docker_host else None
        result = grade(args.case_id, _read(args.patch_file), executor=executor)
        result.get("patch", {}).pop("unified_diff", None)
        print(json.dumps(result, indent=1))
        return 0 if result["status"] == "passed" else 1
    elif args.command == "selfcheck":
        case = load_case(args.case_id)
        files = buggy_files(case)
        if args.patch_file:
            patch = parse_patch(_read(args.patch_file))
            validate_patch(patch, files, load_project(case["project"]))
            files.update(patch)
        executor = DockerExecutor(args.docker_host) if args.docker_host else None
        print(json.dumps(run_public_tests(case["project"], files, executor=executor), indent=1))
    elif args.command == "mutants":
        report = mutation_score(args.project, paths=args.file, limit=args.limit)
        print(json.dumps(report, indent=1))
    elif args.command == "freeze":
        data = freeze_expected(args.project)
        print(f"froze {len(data['probes'])} probes for {args.project}")
    elif args.command == "verify":
        ok = True
        for case_id in list_cases():
            report = verify_case(case_id)
            good = (report["buggy_failed_probes"] == report["declared_target_probes"] and report["buggy_failed_probes"]
                    and report["reference_status"] == "passed" and report["public_tests_clean"] and report["public_tests_buggy"])
            ok = ok and bool(good)
            print(json.dumps(dict(report, ok=bool(good))))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
