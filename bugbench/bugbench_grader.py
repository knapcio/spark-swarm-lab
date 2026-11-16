"""Offline bugbench grader: apply a full-file-replacement patch, run hidden probes.

Importing this module runs nothing.  Grading materializes the buggy case tree
in memory, applies the candidate patch, and sends files plus the trusted probe
source to a fresh ``python3 -I -S`` child over stdin.  The child returns only
observations; expected values never enter it, and the outer parent alone
compares them (mirroring ``independent_code_grader.py``).

Local mode is process isolation for authored fixtures and offline development,
not a sandbox for untrusted model code.  Model-generated patches must be graded
with the same CHILD inside the pinned CPU-only container; see
``container_argv`` (TODO: execution is intentionally not wired here).
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
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(ROOT, "projects")
IMAGE = "python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd"
OWNER = "swarm-lab-bugbench-eval"
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
    """Score an explicit claim {"file": ..., "function": ...} against the gold location."""
    file_hit = claim.get("file") in case["gold"]["files"]
    function = f"{claim.get('file')}::{claim.get('function')}"
    return {"file_hit": file_hit, "function_hit": function in case["gold"]["functions"]}


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
    if len(process.stdout) > MAX_CHILD_OUTPUT:
        return None, "child_output_too_large"
    if process.returncode:
        return None, f"child_exit_{process.returncode}: {process.stderr[-1000:]}"
    try:
        result = json.loads(process.stdout)
    except ValueError:
        return None, "child_protocol"
    if not isinstance(result, dict) or result.get("version") != 1:
        return None, "child_protocol"
    return result, None


def container_argv(task_id):
    """TODO(docker): the argv to run CHILD in the pinned CPU-only grader, same flags as
    independent_code_grader.py.  Not executed by this offline prototype; the payload
    (files + probes, no expected values) travels over stdin exactly as in local mode."""
    name = "swarm-bugbench-" + task_id
    return ["docker", "run", "--pull", "never", "--runtime", "runc", "-i", "--name", name,
            "--label", "swarm-lab.code-owner=" + OWNER, "--label", "swarm-lab.code-task=" + task_id,
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "256m", "--memory-swap", "256m", "--cpus", "1",
            "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--workdir", "/tmp",
            "--env", "NVIDIA_VISIBLE_DEVICES=void", "--stop-timeout", "1", "--entrypoint", "python3", IMAGE,
            "-I", "-S", "-c", CHILD]


def observe(project_name, files, probe_timeout=5.0, timeout=60.0, python=None):
    """Run every hidden probe against ``files``; returns (child result, names, error)."""
    project = load_project(project_name)
    probes = _read(os.path.join(project["hidden"], "probes.py"))
    names = probe_names(probes)
    payload = {"mode": "probes", "package": project["package"], "files": files, "probes": probes,
               "probe_names": names, "probe_timeout": probe_timeout}
    result, error = run_child(payload, timeout, python)
    return result, names, error, hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run_public_tests(project_name, files, timeout=60.0, python=None):
    """Self-check available to agents: the project's own visible tests on a patched copy."""
    project = load_project(project_name)
    result, error = run_child({"mode": "public_tests", "package": project["package"], "files": files,
                               "timeout": timeout - 5}, timeout, python)
    if error:
        return {"ok": False, "error": error}
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
def grade(case_id, patch_text, probe_timeout=5.0, timeout=60.0, python=None):
    """Grade one candidate patch for one case.  Never raises for candidate faults."""
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
    child, names, error, payload_sha = observe(case["project"], after, probe_timeout, timeout, python)
    result["child_payload_sha256"] = payload_sha
    if error:
        result.update(status="timeout" if error == "controller_timeout" else "error", error=error)
        result["duration_s"] = round(time.monotonic() - started, 3)
        return result
    try:
        passed = compare(expected, names, child)
    except ValueError as exc:
        result.update(status="error", error=str(exc))
        return result
    targets = case["target_probes"]
    failed = [name for name, ok in passed.items() if not ok]
    result.update(
        status="passed" if not failed else "failed",
        hidden={"passed": len(names) - len(failed), "total": len(names), "failed_probes": failed},
        target={"passed": sum(passed[name] for name in targets), "total": len(targets)},
        regression={"passed": sum(ok for name, ok in passed.items() if name not in targets),
                    "total": len(names) - len(targets), "broken": [name for name in failed if name not in targets]},
        import_error=child.get("import_error"),
        timed_out_probes=[name for name, obs in zip(names, child["results"]) if obs.get("kind") == "timeout"],
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
    check = sub.add_parser("selfcheck", help="public tests only (agent-visible feedback)")
    check.add_argument("case_id")
    check.add_argument("patch_file", nargs="?")
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
        result = grade(args.case_id, _read(args.patch_file))
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
        print(json.dumps(run_public_tests(case["project"], files), indent=1))
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
