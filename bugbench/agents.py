"""bugbench agent side: budget-forced Nemotron calls, S1/S3/W1 policies, selection, grading.

Importing this module runs nothing and contacts nothing.

Information boundary
--------------------
Policies receive only ``bugbench_grader.agent_bundle(case_id)`` (buggy tree, README,
public tests, report, repo map, editable paths) and the self-check
``run_public_tests``.  ``case.json``, probes, expected values and the canary are read
only by :func:`score_attempt`, which runs *after* the selection has been frozen and
logged.  Oracle grades (every distinct candidate) are a hindsight upper bound and are
never fed back into selection.

Model calls
-----------
:class:`HTTPTransport` and :class:`Caller` reproduce the semantics of
``.runtime/nemotron-long-source/forced72.py`` (``ForcedClient``, copied here in
minimal form rather than imported because that module imports the arithmetic
study): the prompt is rendered with the server's own chat template through
``/tokenize`` (thinking on), then streamed through ``/v1/completions`` with
``return_token_ids``.  If the first request hits its think cap without closing
``</think>``, the exact same token sequence plus ``"\\n</think>\\n"`` is continued
within the remaining completion budget; if the answer itself was cut, the sequence
is continued without the suffix.  Per logical call, ``total = min(8192, 16000 -
prompt_tokens - suffix_tokens)`` and ``think_cap = total - answer_reserve``, so
prompt + every completion token (+ the 3-4 suffix tokens) stays <= 16,000 in the
16,384 window.  There is no wall-clock quality cutoff; only a stream that is silent
for ``idle_timeout`` seconds (a hung server) is an infrastructure failure.
"""
import ast
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bugbench_grader as g  # noqa: E402

MODEL = "nemotron-lightning"
ENDPOINTS = tuple(f"http://127.0.0.1:{port}/v1" for port in (18081, 18082, 18083, 18084))
CONTEXT_LIMIT = 16000          # prompt + completion per request; the server window is 16,384
MAX_COMPLETION = 8192          # per logical call (thinking + answer)
PATCH_ANSWER_RESERVE = 2800    # minimum answer budget after forcing when a full-file patch may follow
JSON_ANSWER_RESERVE = 1024     # answer budget for JSON-only calls (navigator step 1, scouts)
MIN_THINK = 1024               # below this the prompt is too long for a meaningful call
END_THINK = "</think>"
FORCE_TEXT = "\n</think>\n"
IDLE_TIMEOUT = 120
TEMPERATURE = 0.8
NOTES_CHARS = 3600             # ~1K tokens of navigator notes
SELFCHECK_OUTPUT_CHARS = 2500
CODE_CHARS_PER_TOKEN = 3.0     # conservative for code when sizing the answer reserve

SYSTEM = ("You are a careful senior Python engineer fixing a reported bug in a small project. "
          "You cannot run code. Follow the requested output format exactly.")


class InfrastructureFault(RuntimeError):
    """Transport, tokenizer, accounting or self-check infrastructure failed: stop the attempt."""


class PromptTooLong(ValueError):
    """The rendered prompt leaves less than MIN_THINK + answer reserve inside CONTEXT_LIMIT."""


def sha(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


# --- events -------------------------------------------------------------------------------
class Events:
    """Thread-safe JSONL event log.  ``path=None`` keeps events in memory (tests)."""

    def __init__(self, path=None, **base):
        self.base, self.lock, self.records, self.counter = base, threading.Lock(), [], 0
        self.file = open(path, "x", encoding="utf-8") if path else None
        self.started = time.monotonic()
        self.prompts_seen = set()

    def emit(self, kind, **fields):
        with self.lock:
            self.counter += 1
            event = dict(event_id=self.counter, type=kind, timestamp=datetime.now(timezone.utc).isoformat(),
                         t_s=round(time.monotonic() - self.started, 3), **self.base)
            event.update(fields)
            self.records.append(event)
            if self.file:
                self.file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                self.file.flush()
            return event

    def prompt(self, text):
        """Log a prompt's full text once per attempt; return its sha256."""
        digest = sha(text)
        with self.lock:
            fresh = digest not in self.prompts_seen
            self.prompts_seen.add(digest)
        if fresh:
            self.emit("prompt_text", prompt_sha256=digest, text=text)
        return digest

    def of(self, kind):
        return [event for event in self.records if event["type"] == kind]

    def close(self):
        if self.file:
            self.file.close()


# --- budget -------------------------------------------------------------------------------
class Budget:
    """Per-attempt cap on logical calls and completion tokens (reserve before dispatch, settle after).

    Missing usage is charged at the reservation, as in ``harness.Budget``."""

    def __init__(self, max_calls=48, max_completion_tokens=256_000):
        self.max_calls, self.max_tokens = max_calls, max_completion_tokens
        self.calls = self.requests = self.tokens = self.reserved = 0
        self.lock = threading.Lock()

    def start_call(self):
        with self.lock:
            if self.calls >= self.max_calls:
                return False
            self.calls += 1
            return True

    def reserve(self, tokens):
        with self.lock:
            if self.tokens + self.reserved + tokens > self.max_tokens:
                return False
            self.requests += 1
            self.reserved += tokens
            return True

    def settle(self, reserved, reported):
        with self.lock:
            self.reserved -= reserved
            self.tokens += reserved if reported is None else reported

    def snapshot(self):
        with self.lock:
            return dict(calls=self.calls, requests=self.requests, completion_tokens=self.tokens,
                        max_calls=self.max_calls, max_completion_tokens=self.max_tokens)


def compute_caps(prompt_tokens, suffix_tokens, answer_reserve, limit=CONTEXT_LIMIT, max_total=MAX_COMPLETION):
    """(total, think_cap) for one logical call; raises PromptTooLong when thinking would get < MIN_THINK.

    The forced continuation re-sends prompt + generated tokens + suffix, so the suffix
    is charged against the window too: prompt + suffix + total <= limit."""
    total = min(max_total, limit - prompt_tokens - suffix_tokens)
    think = total - answer_reserve
    if think < MIN_THINK:
        raise PromptTooLong(f"prompt {prompt_tokens} tokens leaves total {total}, think {think}")
    return total, think


def split_answer(text):
    """(answer, reasoning): answer is the text after the LAST ``</think>``; None if thinking never closed."""
    if END_THINK not in text:
        return None, text
    reasoning, _, answer = text.rpartition(END_THINK)
    return answer, reasoning


# --- transport (minimal copy of forced72.ForcedClient transport) -------------------------------
class HTTPTransport:
    """One OpenAI-compatible vLLM/SGLang replica.  Adapted from forced72.ForcedClient (swarm-lab)."""

    def __init__(self, endpoint, model=MODEL, idle_timeout=IDLE_TIMEOUT):
        self.base = endpoint.rstrip("/").removesuffix("/v1")
        self.endpoint, self.model, self.idle_timeout = endpoint, model, idle_timeout
        self._force = None

    def _post(self, path, body, timeout):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(request, timeout=timeout)

    def tokenize_chat(self, messages):
        with self._post("/tokenize", dict(model=self.model, messages=messages, add_generation_prompt=True,
                                          chat_template_kwargs={"enable_thinking": True}), 60) as response:
            return json.load(response)["tokens"]

    def force_ids(self):
        if self._force is None:
            with self._post("/tokenize", dict(model=self.model, prompt=FORCE_TEXT, add_special_tokens=False),
                            60) as response:
                self._force = json.load(response)["tokens"]
        return list(self._force)

    def complete(self, prompt_ids, max_tokens, seed, temperature=TEMPERATURE):
        """Stream one raw completion.  Returns dict(text, token_ids, finish_reason, usage, error)."""
        body = dict(model=self.model, prompt=prompt_ids, max_tokens=max_tokens, temperature=temperature, seed=seed,
                    stream=True, return_token_ids=True, stream_options={"include_usage": True})
        text, token_ids, finish, usage, error = "", [], None, {}, None
        try:
            # The socket timeout applies per read: it detects a silent server, not a slow one.
            with self._post("/v1/completions", body, self.idle_timeout) as response:
                for raw in response:
                    line = raw.decode().strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[5:])
                    if chunk.get("error"):
                        raise ConnectionError(f"server stream error: {str(chunk['error'])[:200]}")
                    for choice in chunk.get("choices", []):
                        text += choice.get("text") or ""
                        token_ids += choice.get("token_ids") or []
                        finish = choice.get("finish_reason") or finish
                    if chunk.get("usage"):
                        usage = {k: v for k, v in chunk["usage"].items()
                                 if k in ("prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int}
            if finish is None:
                raise ConnectionError("stream ended without finish_reason")
        except Exception as exc:  # noqa: BLE001 - every transport fault is infrastructure
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
        return dict(text=text, token_ids=token_ids, finish_reason=finish, usage=usage, error=error)


class EndpointPool:
    """Per-endpoint concurrency limits shared by every attempt; leases the least-loaded replica."""

    def __init__(self, transports, per_endpoint=8):
        self.transports, self.free = list(transports), [per_endpoint] * len(transports)
        self.cond = threading.Condition()
        self.leases = [0] * len(self.transports)

    @contextmanager
    def lease(self, hint=0):
        n = len(self.transports)
        with self.cond:
            while max(self.free) == 0:
                self.cond.wait()
            index = min(range(n), key=lambda i: (-self.free[i], (i - hint) % n))
            self.free[index] -= 1
            self.leases[index] += 1
        try:
            yield index, self.transports[index]
        finally:
            with self.cond:
                self.free[index] += 1
                self.cond.notify()


class Caller:
    """Budget-forced logical calls for one attempt (thread-safe; shared by its agents)."""

    def __init__(self, pool, events, budget, seed, abort=None):
        self.pool, self.events, self.budget, self.seed = pool, events, budget, str(seed)
        self.abort = abort or threading.Event()

    def _request(self, transport, endpoint_index, agent, stage, phase, ids, max_tokens, call_id, **context):
        if not self.budget.reserve(max_tokens):
            self.events.emit("budget_exhausted", agent=agent, stage=stage, phase=phase, call_id=call_id,
                             requested=max_tokens, budget=self.budget.snapshot())
            return None
        request_id = uuid.uuid4().hex[:12]
        ids_sha = sha(json.dumps(ids))
        seed = int.from_bytes(hashlib.sha256(f"{self.seed}:{agent}:{stage}:{phase}:{ids_sha}".encode()).digest()[:4],
                              "big")
        self.events.emit("request_start", request_id=request_id, call_id=call_id, agent=agent, stage=stage,
                         phase=phase, endpoint_index=endpoint_index, prompt_token_count=len(ids),
                         prompt_ids_sha256=ids_sha, max_tokens=max_tokens, seed=seed, temperature=TEMPERATURE,
                         **context)
        start = time.monotonic()
        out = transport.complete(ids, max_tokens, seed)
        reported = out["usage"].get("completion_tokens")
        if out["error"] is None and reported is not None and reported != len(out["token_ids"]):
            out["error"] = f"token id count {len(out['token_ids'])} != reported {reported}"
        self.budget.settle(max_tokens, reported if out["error"] is None else None)
        self.events.emit("request_end", request_id=request_id, call_id=call_id, agent=agent, stage=stage, phase=phase,
                         endpoint_index=endpoint_index, latency_ms=round((time.monotonic() - start) * 1000, 1),
                         usage=out["usage"], usage_estimated=reported is None,
                         completion_tokens=len(out["token_ids"]),
                         token_ids_sha256=sha(json.dumps(out["token_ids"])), finish_reason=out["finish_reason"],
                         error=out["error"], text=out["text"])
        if out["error"]:
            raise InfrastructureFault(f"{agent}/{stage}/{phase}: {out['error']}")
        return out

    def call(self, agent, stage, user, answer_reserve=PATCH_ANSWER_RESERVE, hint=0, **context):
        """One logical call.  Returns dict(answer, truncated, forced, ...) or None when the budget is spent.

        Raises PromptTooLong (caller may shrink the prompt) or InfrastructureFault."""
        if self.abort.is_set():
            raise InfrastructureFault("attempt aborted after an infrastructure fault")
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        prompt_sha = self.events.prompt(user)
        call_id = uuid.uuid4().hex[:12]
        with self.pool.lease(hint) as (index, transport):
            try:
                prompt_ids = transport.tokenize_chat(messages)
                suffix = transport.force_ids()
            except Exception as exc:  # noqa: BLE001
                raise InfrastructureFault(f"tokenize failed: {type(exc).__name__}: {str(exc)[:300]}") from exc
            total, think = compute_caps(len(prompt_ids), len(suffix), answer_reserve)
            if not self.budget.start_call():
                self.events.emit("budget_exhausted", agent=agent, stage=stage, call_id=call_id,
                                 reason="max_calls", budget=self.budget.snapshot())
                return None
            self.events.emit("call_start", call_id=call_id, agent=agent, stage=stage, endpoint_index=index,
                             prompt_sha256=prompt_sha, prompt_tokens=len(prompt_ids), total_cap=total,
                             think_cap=think, answer_reserve=answer_reserve, **context)
            first = self._request(transport, index, agent, stage, "think", prompt_ids, think, call_id)
            if first is None:
                return None
            answer, _ = split_answer(first["text"])
            used = len(first["token_ids"])
            second, forced = None, False
            if first["finish_reason"] == "length" and total - used > 0:
                forced = answer is None
                ids = prompt_ids + first["token_ids"] + (suffix if forced else [])
                self.events.emit("budget_forced" if forced else "answer_continued", call_id=call_id, agent=agent,
                                 stage=stage, after_tokens=used, remaining=total - used)
                second = self._request(transport, index, agent, stage, "forced" if forced else "continued",
                                       ids, total - used, call_id)
                if second is not None:
                    tail, _ = split_answer(second["text"])
                    if forced:  # a forced continuation may close thinking again; the answer follows the last marker
                        answer = second["text"] if tail is None else tail
                    else:
                        answer = answer + (second["text"] if tail is None else tail)
            last = second or first
            truncated = last["finish_reason"] == "length"
            completion = used + (len(second["token_ids"]) if second else 0)
        result = dict(call_id=call_id, answer=answer, truncated=truncated, forced=forced,
                      prompt_tokens=len(prompt_ids), completion_tokens=completion, total_cap=total, think_cap=think,
                      endpoint_index=index, closed_thinking=answer is not None)
        self.events.emit("call_end", call_id=call_id, agent=agent, stage=stage, forced=forced, truncated=truncated,
                         completion_tokens=completion, closed_thinking=answer is not None,
                         answer=answer)
        return result


# --- parsing --------------------------------------------------------------------------------
_DECODER = json.JSONDecoder()


def extract_json(text, keys=()):
    """First JSON object in ``text`` (outside FILE blocks) that contains any of ``keys``; None if absent.

    Tolerates prose, Markdown fences and trailing text.  Never raises."""
    if not isinstance(text, str):
        return None
    head = re.split(r"(?m)^=== FILE: ", text, maxsplit=1)[0]
    fallback = None
    for match in re.finditer(r"\{", head):
        try:
            value, _ = _DECODER.raw_decode(head, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            if not keys or any(key in value for key in keys):
                return value
            fallback = fallback or value
    return fallback if not keys else None


def _str(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def _words(text, limit):
    words = text.split()
    return " ".join(words[:limit])


def parse_patch_answer(answer, files, editable, allowed=None):
    """Validate the FILE blocks of a model answer.  Returns dict(valid, files, error, no_op, key)."""
    if answer is None:
        return dict(valid=False, files={}, error="no answer (thinking never closed)", no_op=False, key=None)
    try:
        patch = g.parse_patch(answer)
        g.validate_patch(patch, files, {"editable": list(editable)})
        if allowed is not None:
            unseen = sorted(set(patch) - set(allowed))
            if unseen:
                raise g.PatchError(f"you may only rewrite files whose content is shown to you; not shown: {unseen}")
    except g.PatchError as exc:
        return dict(valid=False, files={}, error=str(exc), no_op=False, key=None)
    key = normalized_key(files, patch)
    return dict(valid=True, files=patch, error=None, no_op=key is None, key=key)


def _norm_source(text):
    try:
        return ast.dump(ast.parse(text))
    except SyntaxError:
        return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


def normalized_key(before, patch):
    """Cluster key of a patch: per changed file, the AST dump (comments/formatting ignored); None if a no-op."""
    parts = []
    for path in sorted(patch):
        if path in before and _norm_source(patch[path]) == _norm_source(before[path]):
            continue
        parts.append([path, _norm_source(patch[path])])
    return sha(json.dumps(parts)) if parts else None


# --- prompt material ------------------------------------------------------------------------
def compressed_map(files, editable):
    """Signatures of editable modules without docstrings or dunders; the errors module is one line."""
    out = []
    for path in sorted(editable):
        text = files[path]
        out.append(f"{path} ({text.count(chr(10))} lines)")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        if path.rsplit("/", 1)[-1] in ("errors.py", "exceptions.py"):
            names = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
            out.append("  exceptions: " + ", ".join(names))
            continue

        def walk(node, prefix, indent):
            for child in node.body:
                if isinstance(child, ast.ClassDef):
                    out.append(f"{indent}class {child.name}")
                    walk(child, child.name + ".", indent + "  ")
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("__") and child.name.endswith("__") and child.name != "__init__":
                        continue
                    args = [a.arg for a in child.args.posonlyargs + child.args.args + child.args.kwonlyargs
                            if a.arg not in ("self", "cls")]
                    out.append(f"{indent}{prefix}{child.name}({', '.join(args)})")
        walk(tree, "", "  ")
    return "\n".join(out) + "\n"


def file_list(files):
    return "\n".join(f"{path} ({text.count(chr(10))} lines)" for path, text in sorted(files.items())) + "\n"


def show_files(files, paths):
    return "".join(f"--- BEGIN {path} ---\n{files[path]}{'' if files[path].endswith(chr(10)) else chr(10)}"
                   f"--- END {path} ---\n\n" for path in paths)


def patch_reserve(files, paths):
    longest = max((len(files[p]) for p in paths), default=0)
    return max(PATCH_ANSWER_RESERVE, int(math.ceil(longest / CODE_CHARS_PER_TOKEN * 1.1)) + 400)


INTRO = ("A user reported a bug in the Python project `{project}`. The whole project does not fit in your "
         "context, so you work in steps and see at most two files at a time.\n")

ANSWER_OPTIONS = """# Your answer
Option A (only if you cannot yet locate the defect): read other files. Answer with ONE JSON object and nothing else:
{{"action": "read", "files": ["<path>", "<path>"], "notes": "<what you learned and still suspect, <= 150 words>"}}

Option B: fix the defect. First ONE JSON object:
{{"action": "patch", "location": {{"file": "<path>", "function": "<function or Class.method>"}}, "hypothesis": "<the defect and your fix, <= 60 words>", "notes": "<= 150 words"}}
then the fix:
{patch_help}
Only rewrite files whose content is shown above. Change as little as possible and keep every other line identical. Never abbreviate with "..." or "rest unchanged". Fix the root cause at the defective function, not only the example in the report.
"""


def prompt_plan(bundle, cmap, calls):
    return (INTRO.format(project=bundle["project"])
            + f"You have {calls} model calls in total, including this one; keep at least one for the fix.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# README\n{bundle['files'].get('README.md', '').strip()}\n\n"
            f"# Code map (signatures only)\n{cmap}\n"
            "Other files: README.md, tests/test_public.py (the visible tests; they pass on the current code).\n\n"
            "# Your answer\nThink about which module most likely contains the defect (the symptom often surfaces "
            "in a different module than the defect). Then answer with ONE JSON object and nothing else:\n"
            '{"files": ["<path>", "<path>"], "hypothesis": "<where the defect probably is and why, <= 60 words>", '
            '"notes": "<anything worth remembering, <= 150 words>"}\n'
            "`files` lists 1 or 2 paths to read next.\n")


def prompt_step(bundle, notes, read, shown, step, calls, must_patch, feedback=None):
    last = ("\nYou must choose Option B (the fix) in this answer.\n" if must_patch else "")
    fb = f"# Feedback on your previous answer\n{feedback}\n\n" if feedback else ""
    return (INTRO.format(project=bundle["project"]) + f"This is call {step} of {calls}.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# Your notes so far\n{notes.strip() or '(none)'}\n"
            f"Files read so far: {', '.join(read) or '(none)'}\n\n{fb}"
            f"# Project files\n{file_list(bundle['files'])}\n# Files you requested\n"
            f"{show_files(bundle['files'], shown)}"
            + ANSWER_OPTIONS.format(patch_help=g.PATCH_FORMAT_HELP) + last)


def prompt_repair(bundle, notes, candidate, selfcheck, patched_files):
    output = (selfcheck.get("output") or selfcheck.get("setup_error") or "")[-SELFCHECK_OUTPUT_CHARS:]
    diff = g.diff_stats(bundle["files"], dict(bundle["files"], **candidate["files"]))["unified_diff"][:4000]
    claim = candidate.get("claim") or {}
    return (INTRO.format(project=bundle["project"]) + "This is your repair call.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# Your notes so far\n{notes.strip() or '(none)'}\n\n"
            f"# Your proposed fix\nLocation: {claim.get('file')} :: {claim.get('function')}\n"
            f"Hypothesis: {candidate.get('hypothesis') or ''}\n\nDiff against the original code:\n{diff}\n"
            "# Self-check failed\nThe project's own visible tests pass on the original code but FAIL on your "
            f"patched code, so your change broke documented behaviour:\n{output}\n\n"
            f"# Your patched file(s)\n{show_files(patched_files, sorted(candidate['files']))}"
            "Repair the fix (you may also choose a different approach). Answer with ONE JSON object\n"
            '{"action": "patch", "location": {"file": "<path>", "function": "<name>"}, "hypothesis": "<= 60 words", '
            '"notes": "<= 150 words"}\n'
            f"then the fix:\n{g.PATCH_FORMAT_HELP}"
            "Only rewrite the file(s) shown above. Each block must contain the complete file; a file you leave out "
            "reverts to its ORIGINAL content.\n")


def prompt_scout(bundle, cmap, path):
    return (f"A user reported a bug in the Python project `{bundle['project']}`. Several reviewers each read ONE "
            "module. Judge whether the defect that causes the reported behaviour is in YOUR module. The symptom "
            "often surfaces in a different module than the defect.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# Code map (signatures only)\n{cmap}\n"
            f"# Your module: {path}\n{show_files(bundle['files'], [path])}"
            "# Your answer\nONE JSON object and nothing else:\n"
            '{"suspicion": <0.0-1.0, probability that the defect is in this module>, '
            '"function": "<most suspicious function in this module, e.g. Class.method>", '
            '"evidence": "<= 80 words: the exact code and why it contradicts the report or documentation", '
            '"also_check": ["<other path worth reading>"]}\n')


# --- self-check -----------------------------------------------------------------------------
def make_selfcheck(project, executor=None):
    """Self-check = the project's visible tests on a patched copy (the only execution feedback)."""
    def selfcheck(files):
        result = g.run_public_tests(project, files, executor=executor)
        if result.get("provenance") == "infrastructure":
            raise InfrastructureFault(f"self-check infrastructure: {result.get('error')}")
        return result
    return selfcheck


# --- attempt context ------------------------------------------------------------------------
class Context:
    """Everything a policy may use: the visible bundle, the caller, the self-check, the event log."""

    def __init__(self, bundle, caller, selfcheck, events):
        self.bundle, self.caller, self.selfcheck, self.events = bundle, caller, selfcheck, events
        self.files = bundle["files"]
        self.editable = bundle["editable_paths"]
        self.cmap = compressed_map(self.files, self.editable)
        self._order = 0
        self._lock = threading.Lock()
        self.patches = []  # every valid, non-no-op patch produced in the attempt (oracle pool)
        self.tester = None     # agent-test sandbox (T1/T3): public tests + agent-written tests, never probes
        self.test_cache = {}

    def next_order(self):
        with self._lock:
            self._order += 1
            return self._order

    def record_patch(self, candidate):
        with self._lock:
            self.patches.append(candidate)


def _selfcheck_summary(result):
    return {k: result.get(k) for k in ("ok", "tests_run", "failures", "errors", "interrupted", "setup_error", "error")}


class Navigator:
    """S1: one sequential agent.  Also used as the W1 fixer (``initial_files`` set, ``max_calls`` small)."""

    def __init__(self, ctx, name, max_calls=6, hint=0, initial_files=None, initial_notes="", patch_now=False):
        self.ctx, self.name, self.max_calls, self.hint = ctx, name, max_calls, hint
        self.patch_now = patch_now  # W1 fixers: the first call must already produce a patch
        self.notes, self.read, self.shown = initial_notes[:NOTES_CHARS], [], list(initial_files or [])
        self.calls = 0
        self.trace = []
        self.candidates = []  # valid patches of this chain in order
        self.claims = []

    def _call(self, stage, prompt, reserve):
        self.calls += 1
        return self.ctx.caller.call(self.name, stage, prompt, answer_reserve=reserve, hint=self.hint)

    def _readable(self, paths):
        files = self.ctx.files
        out = []
        for path in paths if isinstance(paths, list) else []:
            if isinstance(path, str):
                path = path.strip().strip("`'\"").removeprefix("./")
                if path in files and path not in out:
                    out.append(path)
        return out[:2]

    def _plan(self):
        prompt = prompt_plan(self.ctx.bundle, self.ctx.cmap, self.max_calls)
        result = self._call("plan", prompt, JSON_ANSWER_RESERVE)
        if result is None:
            return False
        plan = extract_json(result["answer"], keys=("files", "hypothesis"))
        files = self._readable((plan or {}).get("files"))
        self.trace.append(dict(stage="plan", call_id=result["call_id"], parsed=plan is not None, files=files,
                               truncated=result["truncated"], forced=result["forced"]))
        if plan:
            self.notes = (f"Initial hypothesis: {_str(plan.get('hypothesis'), 600)}\n{_str(plan.get('notes'), 1500)}"
                          )[:NOTES_CHARS]
        # Garbled plan: fall back to the README and nothing else; the agent can ask again.
        self.shown = files or ["README.md"]
        return True

    def _step(self, feedback, must_patch):
        shown = list(self.shown)
        while True:
            prompt = prompt_step(self.ctx.bundle, self.notes, self.read, shown, self.calls + 1, self.max_calls,
                                 must_patch, feedback)
            try:
                result = self._call("step", prompt, patch_reserve(self.ctx.files, shown))
                break
            except PromptTooLong:
                self.calls -= 1
                if len(shown) <= 1:
                    raise
                shown = shown[:1]
        for path in shown:
            if path not in self.read:
                self.read.append(path)
        return result, shown

    def _candidate(self, decision, parsed, call_id, stage, shown):
        claim = decision.get("location") if isinstance(decision.get("location"), dict) else None
        if claim:
            claim = {"file": _str(claim.get("file"), 200), "function": _str(claim.get("function"), 200)}
            self.claims.append(claim)
        return dict(agent=self.name, rank=self.hint, stage=stage, call_id=call_id, order=self.ctx.next_order(),
                    files=parsed["files"],
                    key=parsed["key"], valid=parsed["valid"], no_op=parsed["no_op"], error=parsed["error"],
                    claim=claim, hypothesis=_str(decision.get("hypothesis"), 600), shown=shown,
                    patch_text=g.patch_from_files(parsed["files"]) if parsed["valid"] else None, selfcheck=None)

    def _check(self, candidate):
        patched = dict(self.ctx.files, **candidate["files"])
        result = self.ctx.selfcheck(patched)
        candidate["selfcheck"] = _selfcheck_summary(result)
        self.ctx.events.emit("selfcheck", agent=self.name, call_id=candidate["call_id"], order=candidate["order"],
                             ok=bool(result.get("ok")), summary=candidate["selfcheck"])
        return result, patched

    def run(self):
        """Run the chain; returns this agent's final candidate (or None)."""
        if not self.shown:
            if not self._plan():
                return self.final()
        feedback, repaired = None, False
        while self.calls < self.max_calls:
            must_patch = self.patch_now or self.calls + 1 >= self.max_calls
            result, shown = self._step(feedback, must_patch)
            if result is None:
                break
            answer = result["answer"]
            decision = extract_json(answer, keys=("action", "location", "files")) or {}
            if decision.get("notes"):
                self.notes = _str(decision.get("notes"), NOTES_CHARS)
            has_blocks = isinstance(answer, str) and "=== FILE:" in answer
            entry = dict(stage="step", call_id=result["call_id"], shown=shown, action=decision.get("action"),
                         truncated=result["truncated"], forced=result["forced"])
            self.trace.append(entry)
            wants_read = decision.get("action") == "read" or (
                not decision.get("action") and "files" in decision and "location" not in decision)
            if wants_read and not has_blocks and not must_patch:
                files = self._readable(decision.get("files"))
                entry["files"] = files
                if files:
                    self.shown, feedback = files, None
                else:
                    feedback = "Your read request named no existing file. Use paths from the project file list."
                continue
            parsed = parse_patch_answer(answer, self.ctx.files, self.ctx.editable, allowed=shown)
            candidate = self._candidate(decision, parsed, result["call_id"], "patch", shown)
            entry.update(patch_valid=parsed["valid"], patch_error=parsed["error"], no_op=parsed["no_op"])
            if not parsed["valid"] or parsed["no_op"]:
                if not decision:
                    feedback = "Your answer had neither a JSON object nor a valid patch. Follow the format exactly."
                else:
                    feedback = (f"Your patch could not be used: {parsed['error'] or 'it changes nothing'}. "
                                "Give the complete content of each changed file.")
                if result["truncated"]:
                    feedback += " Your answer was cut off: think less and keep the answer short."
                continue
            self.candidates.append(candidate)
            self.ctx.record_patch(candidate)
            check, patched = self._check(candidate)
            if check.get("ok") or repaired or self.calls >= self.max_calls:
                break
            repaired = True
            result = self._call("repair", prompt_repair(self.ctx.bundle, self.notes, candidate, check, patched),
                                patch_reserve(patched, sorted(candidate["files"])))
            if result is None:
                break
            decision = extract_json(result["answer"], keys=("action", "location")) or {}
            # The repair rewrites the patched files; a repaired block is compared with the ORIGINAL tree.
            parsed = parse_patch_answer(result["answer"], self.ctx.files, self.ctx.editable,
                                        allowed=sorted(candidate["files"]))
            repair = self._candidate(decision, parsed, result["call_id"], "repair", sorted(candidate["files"]))
            self.trace.append(dict(stage="repair", call_id=result["call_id"], patch_valid=parsed["valid"],
                                   patch_error=parsed["error"], no_op=parsed["no_op"], truncated=result["truncated"],
                                   forced=result["forced"]))
            if parsed["valid"] and not parsed["no_op"]:
                self.candidates.append(repair)
                self.ctx.record_patch(repair)
                self._check(repair)
            break
        return self.final()

    def final(self):
        passing = [c for c in self.candidates if c["selfcheck"] and c["selfcheck"]["ok"]]
        return (passing or self.candidates or [None])[-1]


# --- selection (visible material only) -----------------------------------------------------------
def select(candidates):
    """valid -> passes public tests -> largest cluster of identical normalized diffs -> earliest.

    "Earliest" is deterministic: lowest agent rank (chain/fixer index), then generation order.
    Uses only fields computed from visible material; returns (selected or None, info)."""
    def position(c):
        return (c.get("rank", 0), c["order"])
    valid = [c for c in candidates if c and c["valid"] and not c["no_op"]]
    info = dict(candidates=len([c for c in candidates if c]), valid=len(valid))
    if not valid:
        return None, dict(info, rule="no_valid_patch")
    passing = [c for c in valid if c["selfcheck"] and c["selfcheck"].get("ok")]
    pool = passing or valid
    clusters = {}
    for c in pool:
        clusters.setdefault(c["key"], []).append(c)
    ranked = sorted(clusters.values(), key=lambda members: (-len(members), min(position(m) for m in members)))
    best = min(ranked[0], key=position)
    info.update(selfcheck_passing=len(passing), clusters=[len(m) for m in ranked], cluster_size=len(ranked[0]),
                rule="vote" if len(ranked[0]) > 1 else "earliest", selected_order=best["order"],
                selected_agent=best["agent"], selected_key=best["key"])
    return best, info


# --- policies ---------------------------------------------------------------------------------
def policy_s1(ctx, calls=6, name="s1", hint=0):
    nav = Navigator(ctx, name, max_calls=calls, hint=hint)
    final = nav.run()
    return dict(candidates=[final] if final else [], agents={name: dict(trace=nav.trace, claims=nav.claims,
                                                                          calls=nav.calls)})


def policy_s3(ctx, k=8, calls=6):
    """K independent S1 chains: separate Navigator objects, distinct agent names (=> distinct seeds), no sharing."""
    navs = [Navigator(ctx, f"s3c{i}", max_calls=calls, hint=i) for i in range(k)]
    with ThreadPoolExecutor(max_workers=k) as pool:
        futures = [pool.submit(nav.run) for nav in navs]
        finals = _gather(ctx, futures)
    return dict(candidates=[f for f in finals if f],
                agents={nav.name: dict(trace=nav.trace, claims=nav.claims, calls=nav.calls) for nav in navs})


def _gather(ctx, futures):
    out, fault = [], None
    for future in futures:
        try:
            out.append(future.result())
        except InfrastructureFault as exc:
            ctx.caller.abort.set()
            fault = fault or exc
    if fault:
        raise fault
    return out


def parse_scout(answer, path, files):
    data = extract_json(answer, keys=("suspicion", "function", "evidence"))
    if not data:
        return dict(file=path, suspicion=0.0, function="", evidence="", also_check=[], parsed=False)
    try:
        suspicion = float(data.get("suspicion", 0))
    except (TypeError, ValueError):
        suspicion = 0.0
    suspicion = min(1.0, max(0.0, suspicion)) if math.isfinite(suspicion) else 0.0
    also = [p for p in data.get("also_check", []) if isinstance(p, str) and p in files and p != path] \
        if isinstance(data.get("also_check"), list) else []
    function = _str(data.get("function"), 120).strip()
    function = function.split("::")[-1].removesuffix("()")
    return dict(file=path, suspicion=suspicion, function=function,
                evidence=_words(_str(data.get("evidence"), 2000), 80), also_check=also[:3], parsed=True)


def aggregate_scouts(reports, top_modules=2, top_evidence=3):
    """Rank (file, function) by summed suspicion, ties to more independent mentions, then file name.

    ``also_check`` adds a mention (not suspicion) for the named file."""
    entries, files = {}, {}
    for r in reports:
        key = (r["file"], r["function"])
        e = entries.setdefault(key, dict(file=r["file"], function=r["function"], suspicion=0.0, mentions=0,
                                         evidence=[]))
        e["suspicion"] += r["suspicion"]
        e["mentions"] += 1
        if r["evidence"]:
            e["evidence"].append((r["suspicion"], r["evidence"]))
        f = files.setdefault(r["file"], dict(suspicion=0.0, mentions=0))
        f["suspicion"] += r["suspicion"]
        f["mentions"] += 1
        for other in r["also_check"]:
            files.setdefault(other, dict(suspicion=0.0, mentions=0))["mentions"] += 1
    ranked = sorted(entries.values(), key=lambda e: (-e["suspicion"], -e["mentions"], e["file"], e["function"]))
    modules = []
    for e in ranked:
        if e["suspicion"] > 0 and e["file"] not in modules:
            modules.append(e["file"])
    for path in sorted(files, key=lambda p: (-files[p]["suspicion"], -files[p]["mentions"], p)):
        if path not in modules:
            modules.append(path)
    notes = []
    for e in ranked:
        for score, text in sorted(e["evidence"], key=lambda x: -x[0]):
            notes.append(dict(file=e["file"], function=e["function"], suspicion=round(score, 3), evidence=text))
    notes = sorted(notes, key=lambda n: -n["suspicion"])[:top_evidence]
    return dict(ranked=[{k: v for k, v in e.items() if k != "evidence"} for e in ranked],
                modules=modules[:top_modules], evidence=notes,
                claim={"file": ranked[0]["file"], "function": ranked[0]["function"]} if ranked else None)


def policy_w1(ctx, fixers=4, fixer_calls=2, scout_modules=None):
    """W1 module sharding: one scout per editable module, aggregate, ``fixers`` fixers on the top-2 modules."""
    modules = scout_modules or list(ctx.editable)

    def scout(i, path):
        result = ctx.caller.call(f"w1scout{i}", "scout", prompt_scout(ctx.bundle, ctx.cmap, path),
                                 answer_reserve=JSON_ANSWER_RESERVE, hint=i, module=path)
        report = parse_scout(result["answer"] if result else None, path, ctx.files)
        ctx.events.emit("scout_report", agent=f"w1scout{i}", **report)
        return report
    with ThreadPoolExecutor(max_workers=len(modules)) as pool:
        reports = _gather(ctx, [pool.submit(scout, i, path) for i, path in enumerate(modules)])
    agg = aggregate_scouts(reports)
    ctx.events.emit("scout_aggregate", **agg)
    notes = "Findings of module reviewers (most suspicious first):\n" + "\n".join(
        f"- {n['file']} :: {n['function']} (suspicion {n['suspicion']}): {n['evidence']}" for n in agg["evidence"])
    navs = [Navigator(ctx, f"w1fix{i}", max_calls=fixer_calls, hint=i, initial_files=agg["modules"],
                      initial_notes=notes, patch_now=True) for i in range(fixers)]
    with ThreadPoolExecutor(max_workers=fixers) as pool:
        finals = _gather(ctx, [pool.submit(nav.run) for nav in navs])
    agents = {nav.name: dict(trace=nav.trace, claims=nav.claims, calls=nav.calls) for nav in navs}
    return dict(candidates=[f for f in finals if f], agents=agents, scouts=reports, aggregate=agg,
                pre_patch_claim=agg["claim"])


# --- test-first agents (T1/T3) and reviewed best-of-k (V3) ----------------------------------------
# Self-correction without an external arbiter: every signal below is produced by the agents themselves
# (their own reproduction tests, model reviews) or is visible material (public tests).  Hidden probes
# and expected.json are touched only by score_attempt, after selection_frozen.
TEST_ANSWER_RESERVE = 2000
TEST_OUTPUT_CHARS = 1500
TEST_LOG_CHARS = 2500
TEST_START = re.compile(r"^=== TEST: (?P<path>\S+) ===[ \t]*$")
TEST_END = re.compile(r"^=== END TEST ===[ \t]*$")
TEST_BLOCK = re.compile(r"(?ms)^=== TEST: \S+ ===[ \t]*$.*?(?:^=== END TEST ===[ \t]*$|\Z)")
REPRO_STATUSES = ("fail", "timeout")  # a test that fails (or hangs) on the original code reproduces the bug
PUBLIC_EXTRA = ("public_ok", "repro_fails_before", "repro_passes_after", "own_status", "own_test_sha256")

TEST_RULES = """Rules for the test:
- plain `unittest`: `import unittest`, classes derive from `unittest.TestCase`, method names start with `test`; no pytest;
- self-contained: import only the project's package and the standard library (do not import tests/test_public.py);
- assert the EXACT behaviour the bug report and README say is correct (values, strings, exception types), not what the current code does;
- it must FAIL on the current (buggy) code and PASS once the defect is fixed; 1-3 short test methods, nothing unrelated.
"""


def _strip_block(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    if len(lines) >= 2 and g.FENCE.match(lines[0]) and lines[-1].strip() == "```":
        lines = lines[1:-1]
    return "\n".join(lines) + "\n"


def parse_test_block(answer, allow_file=False):
    """(test source or None, error).  The first ``=== TEST: ... ===`` block; with ``allow_file`` a
    ``=== FILE: tests/... ===`` block is accepted as well.  The path the model wrote is ignored."""
    if not isinstance(answer, str):
        return None, "no answer (thinking never closed)"
    kinds = [(TEST_START, TEST_END, False)] + ([(g.FILE_START, g.FILE_END, True)] if allow_file else [])
    for start_re, end_re, under_tests in kinds:
        inside, body = False, []
        for line in answer.splitlines():
            if not inside:
                match = start_re.match(line)
                if match and (not under_tests or match.group("path").strip("`'\"").removeprefix("./")
                              .startswith("tests/")):
                    inside, body = True, []
                continue
            if end_re.match(line):
                text = _strip_block(body)
                return (text, None) if text.strip() else (None, "empty TEST block")
            body.append(line)
        if inside:
            return None, "missing END TEST (truncated output?)"
    return None, "no TEST block found"


def strip_test_blocks(answer):
    return TEST_BLOCK.sub("", answer) if isinstance(answer, str) else answer


def check_test_source(text):
    """Cheap static check before the sandbox run; returns an error string or None."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno})"
    for node in ast.walk(tree):
        names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        if any(name.split(".")[0] == "pytest" for name in names):
            return "pytest is not available; use plain unittest"
    return None


def _readable_paths(files, paths, limit=2):
    out = []
    for path in paths if isinstance(paths, list) else []:
        if isinstance(path, str):
            path = path.strip().strip("`'\"").removeprefix("./")
            if path in files and path not in out:
                out.append(path)
    return out[:limit]


def make_agent_tester(bundle, executor=None, workers=4):
    """Sandbox for agent-written tests: ``g.run_agent_tests`` on the visible bundle (public_tests mode only)."""
    def tester(patch_files, tests, include_public):
        result = g.run_agent_tests(bundle, patch_files or None, tests, executor=executor,
                                   include_public=include_public, workers=workers)
        if result.get("provenance") == "infrastructure":
            bad = [r for r in list(result["tests"].values()) + [result.get("public") or {}]
                   if r.get("provenance") == "infrastructure"]
            raise InfrastructureFault(f"agent-test infrastructure: {(bad[0] if bad else {}).get('error')}")
        return result
    return tester


def _test_summary(result):
    keys = ("ok", "tests_run", "failures", "errors", "interrupted", "setup_error", "error", "failure_kind")
    return {k: result.get(k) for k in keys if k in result}


def run_agent_tests_logged(ctx, agent, purpose, patch_files, tests, include_public=False):
    """Run public tests and/or agent tests (cached per patch x test) and log every run.

    Returns dict(public=result or None, tests={path: result with ``classification``})."""
    if ctx.tester is None:
        raise InfrastructureFault("no agent-test sandbox configured")
    patch_sha = sha(g.patch_from_files(patch_files)) if patch_files else None
    out, todo = {}, {}
    for path, text in sorted(tests.items()):
        key = ("test", patch_sha, path, sha(text))
        with ctx._lock:
            cached = ctx.test_cache.get(key)
            fresh_text = ("text", sha(text)) not in ctx.test_cache
            ctx.test_cache[("text", sha(text))] = True
        if fresh_text:
            ctx.events.emit("agent_test_text", agent=agent, test_path=path, test_sha256=sha(text), text=text)
        if cached is None:
            todo[path] = text
        else:
            out[path] = (cached, True)
    public, public_cached = None, False
    if include_public:
        with ctx._lock:
            public = ctx.test_cache.get(("public", patch_sha))
        public_cached = public is not None
    if todo or (include_public and public is None):
        result = ctx.tester(patch_files, todo, include_public and public is None)
        for path, res in result["tests"].items():
            with ctx._lock:
                ctx.test_cache[("test", patch_sha, path, sha(todo[path]))] = res
            out[path] = (res, False)
        if include_public and public is None:
            public = result["public"]
            with ctx._lock:
                ctx.test_cache[("public", patch_sha)] = public
    for path, (res, cached) in sorted(out.items()):
        ctx.events.emit("agent_test_run", agent=agent, purpose=purpose, target="agent_test", patch_sha256=patch_sha,
                        test_path=path, test_sha256=sha(tests[path]), cached=cached,
                        classification=res.get("classification"), summary=_test_summary(res),
                        output=(res.get("output") or "")[-TEST_LOG_CHARS:])
    if include_public:
        ctx.events.emit("agent_test_run", agent=agent, purpose=purpose, target="public_tests", patch_sha256=patch_sha,
                        cached=public_cached, ok=bool(public.get("ok")), summary=_test_summary(public),
                        output=(public.get("output") or "")[-TEST_LOG_CHARS:])
    return dict(public=public, tests={path: res for path, (res, _) in out.items()})


def _tail(result, limit=TEST_OUTPUT_CHARS):
    if not result:
        return ""
    return (result.get("output") or result.get("setup_error") or result.get("error") or "")[-limit:]


def _test_section(test, limit=TEST_OUTPUT_CHARS):
    if not test:
        return "# Your reproduction test\n(none: rely on the bug report)\n\n"
    verdict = {"fail": "it FAILS, as a reproduction should", "timeout": "it hangs (timeout), which reproduces a hang",
               "pass": "it PASSES, so it does NOT reproduce the bug; rely on the bug report",
               "broken": "the test module could not be imported", "empty": "it contains no test methods",
               "crash": "the test run crashed"}.get(test["status"], test["status"])
    return (f"# Your reproduction test ({test['path']})\n=== TEST: {test['path']} ===\n{test['text']}=== END TEST ===\n"
            f"Result on the current code: {verdict}.\n{test['output'][-limit:]}\n\n")


def prompt_t1_plan(bundle, cmap, calls):
    return (INTRO.format(project=bundle["project"])
            + f"You have {calls} model calls in total, including this one. You work test-first: first you write a "
            "reproduction test that must fail on the current code; then you fix the code; your test and the "
            "project's visible tests are then run on your fix and you see the results, so you can correct "
            "mistakes.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# README\n{bundle['files'].get('README.md', '').strip()}\n\n"
            f"# Code map (signatures only)\n{cmap}\n"
            "Other files: README.md, tests/test_public.py (the visible tests; they pass on the current code and "
            "show how the API is used).\n\n"
            "# Your answer\nDecide which files you need to write a precise reproduction test (the module behind the "
            "reported API, or tests/test_public.py for usage examples) and where the defect probably is (the "
            "symptom often surfaces in a different module than the defect). Answer with ONE JSON object and "
            "nothing else:\n"
            '{"files": ["<path>", "<path>"], "hypothesis": "<where the defect probably is and why, <= 60 words>", '
            '"notes": "<anything worth remembering, <= 150 words>"}\n'
            "`files` lists 1 or 2 paths to read next (test-first method).\n")


def prompt_t1_test(bundle, notes, read, shown, step, calls, must_test, test_path, feedback=None, previous=None):
    fb = f"# Feedback on your previous answer\n{feedback}\n\n" if feedback else ""
    prev = ""
    if previous:
        prev = _test_section(dict(previous, path=test_path)).replace("# Your reproduction test",
                                                                     "# Your previous test", 1)
    options = ("" if must_test else
               "Option A (only if you need other files to write the test): ONE JSON object and nothing else:\n"
               '{"action": "read", "files": ["<path>", "<path>"], "notes": "<what you learned, <= 150 words>"}\n\n'
               "Option B: ")
    return (INTRO.format(project=bundle["project"]) + f"This is call {step} of {calls}. Phase 1 of 2: write a "
            "reproduction test.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# Your notes so far\n{notes.strip() or '(none)'}\n"
            f"Files read so far: {', '.join(read) or '(none)'}\n\n{fb}{prev}"
            f"# Project files\n{file_list(bundle['files'])}\n# Files you requested\n"
            f"{show_files(bundle['files'], shown)}"
            "# Your answer\n" + options + "write the reproduction test. First ONE JSON object:\n"
            '{"action": "test", "expected": "<the exact correct behaviour from the report, <= 60 words>", '
            '"suspect": {"file": "<path>", "function": "<function or Class.method>"}, '
            '"files": ["<1-2 paths to show you when you write the fix>"], "notes": "<= 150 words"}\n'
            f"then the test, exactly in this format:\n=== TEST: {test_path} ===\n<complete unittest module>\n"
            "=== END TEST ===\n" + TEST_RULES
            + ("\nYou must write the test (Option B) in this answer.\n" if must_test else ""))


def prompt_t1_fix(bundle, notes, read, shown, step, calls, must_patch, test, feedback=None):
    last = "\nYou must choose Option B (the fix) in this answer.\n" if must_patch else ""
    fb = f"# Feedback on your previous answer\n{feedback}\n\n" if feedback else ""
    return (INTRO.format(project=bundle["project"]) + f"This is call {step} of {calls}. Phase 2 of 2: fix the "
            "defect. After your patch, your reproduction test and the project's visible tests run on the patched "
            "code and you see the results.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# Your notes so far\n{notes.strip() or '(none)'}\n"
            f"Files read so far: {', '.join(read) or '(none)'}\n\n{_test_section(test)}{fb}"
            f"# Project files\n{file_list(bundle['files'])}\n# Files you requested\n"
            f"{show_files(bundle['files'], shown)}"
            + ANSWER_OPTIONS.format(patch_help=g.PATCH_FORMAT_HELP) + last)


def prompt_t1_repair(bundle, notes, candidate, patched_files, test, step, calls, feedback=None, compact=False):
    limit = 600 if compact else TEST_OUTPUT_CHARS
    claim = candidate.get("claim") or {}
    diff = "" if compact else ("Diff against the original code:\n" + g.diff_stats(
        bundle["files"], dict(bundle["files"], **candidate["files"]))["unified_diff"][:4000] + "\n")
    public = "PASS" if candidate.get("public_ok") else "FAIL"
    own = candidate.get("own_status")
    own_line = (f"Your reproduction test {test['path']}: {'PASS' if own == 'pass' else (own or 'not run').upper()}\n"
                f"{candidate.get('own_output', '')[-limit:]}\n") if test else "Your reproduction test: none\n"
    fb = f"# Feedback on your previous answer\n{feedback}\n\n" if feedback else ""
    path = test["path"] if test else "tests/test_repro.py"
    return (INTRO.format(project=bundle["project"]) + f"This is call {step} of {calls}: repair.\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# Your notes so far\n{notes.strip() or '(none)'}\n\n"
            f"# Your proposed fix\nLocation: {claim.get('file')} :: {claim.get('function')}\n"
            f"Hypothesis: {candidate.get('hypothesis') or ''}\n\n{diff}"
            "# Test results on your patched code\n"
            f"Visible project tests (they pass on the original code): {public}\n"
            f"{candidate.get('public_output', '')[-limit:] if public == 'FAIL' else ''}\n{own_line}\n{fb}"
            f"# Your patched file(s)\n{show_files(patched_files, sorted(candidate['files']))}"
            + (_test_section(test, limit) if test else "")
            + "# Your answer\nFind out what is wrong and correct it. A failing visible test means your change broke "
            "documented behaviour. A failing reproduction test means the reported defect is not fixed yet, unless "
            "the test itself contradicts the bug report.\nFirst ONE JSON object:\n"
            '{"action": "patch", "location": {"file": "<path>", "function": "<name>"}, "hypothesis": "<= 60 words", '
            '"notes": "<= 150 words"}\n'
            f"then the corrected code:\n{g.PATCH_FORMAT_HELP}"
            "Only rewrite the file(s) shown under 'Your patched file(s)'. Each block must contain the complete file; "
            "a file you leave out reverts to its ORIGINAL content.\n"
            f"Only if your test contradicts the bug report, you may add a corrected test in a `=== TEST: {path} ===` "
            "... `=== END TEST ===` block; it must still fail on the original code. If only the test was wrong, send "
            "just the JSON object and the TEST block: your current fix is then kept.\n")


class TestFirstAgent:
    """T1: write a reproduction test, check it fails on the original code, fix, run own + visible tests, repair.

    Call plan for ``max_calls=8``: plan (1), test by call 3, one test revision by call 4, patch by call 6,
    repairs until all of the agent's checks pass or the calls run out."""

    def __init__(self, ctx, name, max_calls=8, hint=0):
        self.ctx, self.name, self.max_calls, self.hint = ctx, name, max_calls, hint
        self.test_path = f"tests/test_repro_{name}.py"
        self.notes, self.read, self.shown, self.fix_files = "", [], [], []
        self.calls = 0
        self.trace, self.candidates, self.claims, self.tests_written = [], [], [], []
        self.test = None  # adopted test: dict(path, text, sha, status, output, valid, call_id)
        self.test_deadline = max(2, min(3, max_calls - 3))
        self.test_limit = min(self.test_deadline + 1, max(2, max_calls - 2))
        self.patch_deadline = max(self.test_limit + 1, max_calls - 2)
        self.stopped = None

    def _call(self, stage, prompt, reserve):
        self.calls += 1
        return self.ctx.caller.call(self.name, stage, prompt, answer_reserve=reserve, hint=self.hint)

    def _ask(self, stage, build, shown, reserve):
        shown = list(shown)
        while True:
            try:
                result = self._call(stage, build(shown), reserve(shown))
                break
            except PromptTooLong:
                self.calls -= 1
                if len(shown) <= 1:
                    raise
                shown = shown[:1]
        for path in shown:
            if path not in self.read:
                self.read.append(path)
        return result, shown

    def _notes(self, decision):
        if decision.get("notes"):
            self.notes = _str(decision.get("notes"), NOTES_CHARS)

    # -- tests ----------------------------------------------------------------------------------
    def _try_test(self, text, call_id):
        """Run a proposed test on the ORIGINAL (buggy) tree; returns its record (not yet adopted)."""
        error = check_test_source(text)
        if error:
            status, output = "broken", error
        else:
            res = run_agent_tests_logged(self.ctx, self.name, "repro_on_original", None,
                                         {self.test_path: text})["tests"][self.test_path]
            status, output = res["classification"], _tail(res, TEST_LOG_CHARS)
        record = dict(path=self.test_path, text=text, sha=sha(text), status=status, output=output,
                      valid=status in REPRO_STATUSES, call_id=call_id)
        self.tests_written.append({k: record[k] for k in ("call_id", "sha", "status", "valid")})
        return record

    def _adopt(self, record):
        """Never replace a reproducing test by a non-reproducing one."""
        if self.test is None or record["valid"] or not self.test["valid"]:
            self.test = record
            return True
        return False

    def _test_phase(self):
        files, shown, feedback, previous, revisions = self.ctx.files, list(self.shown), None, None, 1
        while self.calls < self.test_limit:
            must = self.calls + 1 >= self.test_deadline or previous is not None
            result, used = self._ask("test", lambda s: prompt_t1_test(
                self.ctx.bundle, self.notes, self.read, s, self.calls + 1, self.max_calls, must, self.test_path,
                feedback, previous), shown, lambda s: TEST_ANSWER_RESERVE)
            if result is None:
                self.stopped = "budget"
                return False
            answer = result["answer"]
            text, error = parse_test_block(answer, allow_file=True)
            decision = extract_json(strip_test_blocks(answer), keys=("action", "files", "expected", "suspect")) or {}
            self._notes(decision)
            entry = dict(stage="test", call_id=result["call_id"], shown=used, action=decision.get("action"),
                         truncated=result["truncated"], forced=result["forced"],
                         expected=_str(decision.get("expected"), 600),
                         suspect=decision.get("suspect") if isinstance(decision.get("suspect"), dict) else None)
            self.trace.append(entry)
            if text is None:
                wants_read = decision.get("action") == "read" or (
                    decision.get("action") not in ("test",) and "files" in decision)
                if wants_read and not must:
                    paths = _readable_paths(files, decision.get("files"))
                    entry["files"] = paths
                    if paths:
                        shown, feedback = paths, None
                    else:
                        feedback = "Your read request named no existing file. Use paths from the project file list."
                    continue
                feedback = (f"Your answer had no usable test ({error}). Write the test inside "
                            f"`=== TEST: {self.test_path} ===` ... `=== END TEST ===`.")
                if result["truncated"]:
                    feedback += " Your answer was cut off: think less and keep the test short."
                continue
            record = self._try_test(text, result["call_id"])
            entry.update(test_sha256=record["sha"], test_status=record["status"], adopted=self._adopt(record))
            fix_files = [p for p in _readable_paths(files, decision.get("files")) if p in self.ctx.editable]
            if fix_files:
                self.fix_files = fix_files
            if record["valid"]:
                break
            if revisions and self.calls < self.test_limit:
                revisions, previous = revisions - 1, record
                feedback = {
                    "pass": "Your test PASSED on the current (buggy) code, so it does not reproduce the reported bug. "
                            "Re-read the report and assert exactly the behaviour it says is expected.",
                    "broken": "Your test module could not be imported or parsed (see the output). Fix the imports; "
                              "use only names that exist in the project.",
                    "empty": "Your test module ran no test methods. Define a unittest.TestCase subclass with test_* "
                             "methods.",
                }.get(record["status"], f"Your test did not fail cleanly on the current code ({record['status']}).")
                feedback += " You may revise the test once."
                continue
            break
        self.shown = self.fix_files or [p for p in shown if p in self.ctx.editable] or shown
        return True

    # -- fix ------------------------------------------------------------------------------------
    def _candidate(self, decision, parsed, call_id, stage, shown):
        claim = decision.get("location") if isinstance(decision.get("location"), dict) else None
        if claim:
            claim = {"file": _str(claim.get("file"), 200), "function": _str(claim.get("function"), 200)}
            self.claims.append(claim)
        return dict(agent=self.name, rank=self.hint, stage=stage, call_id=call_id, order=self.ctx.next_order(),
                    files=parsed["files"], key=parsed["key"], valid=parsed["valid"], no_op=parsed["no_op"],
                    error=parsed["error"], claim=claim, hypothesis=_str(decision.get("hypothesis"), 600), shown=shown,
                    patch_text=g.patch_from_files(parsed["files"]) if parsed["valid"] else None, selfcheck=None,
                    public_ok=False, repro_fails_before=False, repro_passes_after=False, own_status=None,
                    own_test_sha256=None, own_output="", public_output="")

    def _evaluate(self, candidate):
        tests = {self.test_path: self.test["text"]} if self.test else {}
        res = run_agent_tests_logged(self.ctx, self.name, "own_on_patch", candidate["files"], tests,
                                     include_public=True)
        public, own = res["public"], res["tests"].get(self.test_path)
        candidate.update(selfcheck=_selfcheck_summary(public), public_ok=bool(public.get("ok")),
                         public_output=_tail(public), own_test_sha256=self.test["sha"] if self.test else None,
                         repro_fails_before=bool(self.test and self.test["valid"]),
                         own_status=own["classification"] if own else None, own_output=_tail(own),
                         repro_passes_after=bool(own and own["classification"] == "pass"))

    def _all_ok(self, candidate):
        return candidate["public_ok"] and (self.test is None or candidate["own_status"] == "pass")

    def _accept(self, candidate):
        self.candidates.append(candidate)
        self.ctx.record_patch(candidate)
        self._evaluate(candidate)

    def _repair_call(self, current, feedback):
        patched = dict(self.ctx.files, **current["files"])
        reserve = patch_reserve(patched, sorted(current["files"]))
        for compact in (False, True):
            try:
                return self._call("repair", prompt_t1_repair(self.ctx.bundle, self.notes, current, patched, self.test,
                                                             self.calls + 1, self.max_calls, feedback, compact),
                                  reserve)
            except PromptTooLong:
                self.calls -= 1
                if compact:
                    raise

    def _fix_phase(self):
        files, editable = self.ctx.files, self.ctx.editable
        shown, feedback, current = list(self.shown), None, None
        while self.calls < self.max_calls:
            if current is None:
                must = self.calls + 1 >= min(self.patch_deadline, self.max_calls)
                result, used = self._ask("step", lambda s: prompt_t1_fix(
                    self.ctx.bundle, self.notes, self.read, s, self.calls + 1, self.max_calls, must, self.test,
                    feedback), shown, lambda s: patch_reserve(files, s))
                if result is None:
                    self.stopped = "budget"
                    break
                answer = strip_test_blocks(result["answer"])
                decision = extract_json(answer, keys=("action", "location", "files")) or {}
                self._notes(decision)
                has_blocks = isinstance(answer, str) and "=== FILE:" in answer
                entry = dict(stage="step", call_id=result["call_id"], shown=used, action=decision.get("action"),
                             truncated=result["truncated"], forced=result["forced"])
                self.trace.append(entry)
                wants_read = decision.get("action") == "read" or (
                    not decision.get("action") and "files" in decision and "location" not in decision)
                if wants_read and not has_blocks and not must:
                    paths = _readable_paths(files, decision.get("files"))
                    entry["files"] = paths
                    if paths:
                        shown, feedback = paths, None
                    else:
                        feedback = "Your read request named no existing file. Use paths from the project file list."
                    continue
                parsed = parse_patch_answer(answer, files, editable, allowed=used)
                entry.update(patch_valid=parsed["valid"], patch_error=parsed["error"], no_op=parsed["no_op"])
                if not parsed["valid"] or parsed["no_op"]:
                    if not decision:
                        feedback = "Your answer had neither a JSON object nor a valid patch. Follow the format exactly."
                    else:
                        feedback = (f"Your patch could not be used: {parsed['error'] or 'it changes nothing'}. "
                                    "Give the complete content of each changed file.")
                    if result["truncated"]:
                        feedback += " Your answer was cut off: think less and keep the answer short."
                    continue
                current = self._candidate(decision, parsed, result["call_id"], "patch", used)
                self._accept(current)
                entry.update(public_ok=current["public_ok"], own_status=current["own_status"])
                feedback = None
                if self._all_ok(current):
                    break
                continue
            result = self._repair_call(current, feedback)
            if result is None:
                self.stopped = "budget"
                break
            answer = result["answer"]
            code = strip_test_blocks(answer)
            decision = extract_json(code, keys=("action", "location")) or {}
            self._notes(decision)
            entry = dict(stage="repair", call_id=result["call_id"], truncated=result["truncated"],
                         forced=result["forced"])
            self.trace.append(entry)
            notes, new_test = [], False
            text, _ = parse_test_block(answer)
            if text is not None:
                record = self._try_test(text, result["call_id"])
                new_test = record["valid"] and self._adopt(record)
                entry.update(test_sha256=record["sha"], test_status=record["status"], adopted=new_test)
                if not new_test:
                    notes.append(f"Your corrected test was rejected: on the original code it ended with "
                                 f"'{record['status']}' instead of failing, so your previous test is kept.")
            if isinstance(code, str) and "=== FILE:" in code:
                parsed = parse_patch_answer(code, files, editable, allowed=sorted(current["files"]))
                entry.update(patch_valid=parsed["valid"], patch_error=parsed["error"], no_op=parsed["no_op"])
                if parsed["valid"] and not parsed["no_op"]:
                    current = self._candidate(decision, parsed, result["call_id"], "repair",
                                              sorted(current["files"]))
                    self._accept(current)
                else:
                    notes.append(f"Your repaired patch could not be used: {parsed['error'] or 'it changes nothing'}; "
                                 "your previous fix is kept.")
                    if result["truncated"]:
                        notes.append("Your answer was cut off: think less and keep the answer short.")
            elif new_test:
                self._evaluate(current)
            elif text is None:
                notes.append("Your answer contained neither a corrected fix (FILE blocks) nor a corrected test.")
            entry.update(public_ok=current["public_ok"], own_status=current["own_status"])
            feedback = " ".join(notes) or None
            if self._all_ok(current):
                break

    def run(self):
        try:
            if self._plan() and self._test_phase():
                self._fix_phase()
        except PromptTooLong as exc:
            self.stopped = "prompt_too_long"
            self.trace.append(dict(stage="prompt_too_long", error=str(exc)[:300]))
        return self.final()

    def _plan(self):
        result = self._call("plan", prompt_t1_plan(self.ctx.bundle, self.ctx.cmap, self.max_calls),
                            JSON_ANSWER_RESERVE)
        if result is None:
            self.stopped = "budget"
            return False
        plan = extract_json(result["answer"], keys=("files", "hypothesis"))
        paths = _readable_paths(self.ctx.files, (plan or {}).get("files"))
        self.trace.append(dict(stage="plan", call_id=result["call_id"], parsed=plan is not None, files=paths,
                               truncated=result["truncated"], forced=result["forced"]))
        if plan:
            self.notes = (f"Initial hypothesis: {_str(plan.get('hypothesis'), 600)}\n{_str(plan.get('notes'), 1500)}"
                          )[:NOTES_CHARS]
        self.shown = paths or ["README.md"]
        return True

    def final(self):
        full = [c for c in self.candidates if c["public_ok"] and c["repro_fails_before"] and c["repro_passes_after"]]
        public = [c for c in self.candidates if c["public_ok"]]
        return (full or public or self.candidates or [None])[-1]

    def summary(self):
        final = self.final()
        return dict(trace=self.trace, claims=self.claims, calls=self.calls, stopped=self.stopped,
                    test_path=self.test_path, test_sha256=self.test["sha"] if self.test else None,
                    test_status_on_original=self.test["status"] if self.test else None,
                    tests_written=self.tests_written,
                    repro_fails_before=bool(self.test and self.test["valid"]),
                    repro_passes_after=bool(final and final["repro_passes_after"]),
                    public_ok=bool(final and final["public_ok"]),
                    final_order=final["order"] if final else None)


def _position(c):
    return (c.get("rank", 0), c["order"])


def crossval_pool(valid):
    """(tier, pool): own repro fails-before & passes-after & public OK -> public OK -> any valid patch."""
    qualified = [c for c in valid if c.get("public_ok") and c.get("repro_fails_before") and c.get("repro_passes_after")]
    public = [c for c in valid if c.get("public_ok")]
    if qualified:
        return "own_repro", qualified
    if public:
        return "public_only", public
    return "valid_only", valid


def _decide(pool, keyfn, best):
    """Name the criterion that separated ``best`` from the best candidate with a different patch."""
    others = sorted((c for c in pool if c["key"] != best["key"]), key=keyfn)
    if not others:
        return None
    mine, theirs = keyfn(best), keyfn(others[0])
    for index, (a_, b_) in enumerate(zip(mine, theirs)):
        if a_ != b_:
            return index
    return len(mine)


def select_crossval(candidates, valid_tests, passes):
    """T1/T3 selection from agent-generated evidence only.

    ``valid_tests``: {agent: test} for tests that fail on the original code; ``passes``:
    {(patch key, test agent): bool}.  Tier (own repro / public / valid) -> score = number of OTHER
    agents' valid tests the patch passes -> largest identical-diff cluster -> earliest (rank, order)."""
    valid = [c for c in candidates if c and c["valid"] and not c["no_op"]]
    info = dict(candidates=len([c for c in candidates if c]), valid=len(valid))
    if not valid:
        return None, dict(info, rule="no_valid_patch")
    tier, pool = crossval_pool(valid)
    clusters = {}
    for c in pool:
        clusters.setdefault(c["key"], []).append(c)

    def score(c):
        return sum(1 for agent in valid_tests if agent != c["agent"] and passes.get((c["key"], agent)))

    def keyfn(c):
        return (-score(c), -len(clusters[c["key"]])) + _position(c)
    best = min(pool, key=keyfn)
    decided = _decide(pool, keyfn, best)
    rule = ("vote" if len(clusters[best["key"]]) > 1 else "earliest") if decided is None else \
        {0: "crossval", 1: "vote"}.get(decided, "earliest")
    info.update(tier=tier, selfcheck_passing=sum(1 for c in valid if c.get("public_ok")),
                own_repro_qualified=sum(1 for c in valid if c.get("public_ok") and c.get("repro_fails_before")
                                        and c.get("repro_passes_after")),
                valid_tests=len(valid_tests), clusters=sorted((len(m) for m in clusters.values()), reverse=True),
                cluster_size=len(clusters[best["key"]]), rule=rule, selected_order=best["order"],
                selected_agent=best["agent"], selected_key=best["key"], selected_score=score(best),
                scores=[dict(agent=c["agent"], order=c["order"], key=c["key"], score=score(c),
                             cluster=len(clusters[c["key"]])) for c in sorted(pool, key=_position)])
    return best, info


def _chain_tests(chains):
    return {x.name: x.test for x in chains if x.test and x.test["valid"]}


def crossval_matrix(ctx, candidates, valid_tests, workers=2):
    """Run every distinct pool patch against every valid agent test (agent-test sandbox, cached, logged)."""
    valid = [c for c in candidates if c and c["valid"] and not c["no_op"]]
    if not valid or not valid_tests:
        return {}
    _, pool = crossval_pool(valid)
    reps = {}
    for c in sorted(pool, key=_position):
        reps.setdefault(c["key"], c)
    tests = {t["path"]: t["text"] for t in valid_tests.values()}

    def one(item):
        key, cand = item
        res = run_agent_tests_logged(ctx, "crossval", "crossval", cand["files"], tests)["tests"]
        return {(key, agent): res[t["path"]]["classification"] == "pass" for agent, t in valid_tests.items()}
    passes = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(reps)))) as pool_:
        for part in _gather(ctx, [pool_.submit(one, item) for item in reps.items()]):
            passes.update(part)
    return passes


def _evidence(chains, valid_tests, passes):
    return dict(
        label="agent-generated evidence only (own repro tests on original/patched trees, public tests); "
              "no hidden probe or expected value was used",
        chains={x.name: {k: v for k, v in x.summary().items() if k not in ("trace", "claims")} for x in chains},
        valid_tests={agent: t["sha"] for agent, t in valid_tests.items()},
        matrix=[dict(key=key, test_agent=agent, passes=ok) for (key, agent), ok in sorted(passes.items())])


def policy_t1(ctx, calls=8, name="t1", hint=0):
    agent = TestFirstAgent(ctx, name, max_calls=calls, hint=hint)
    final = agent.run()
    candidates = [final] if final else []
    selected, info = select_crossval(candidates, {}, {})
    evidence = _evidence([agent], {}, {})
    ctx.events.emit("selection_evidence", selection=info, evidence=evidence)
    return dict(candidates=candidates, agents={name: agent.summary()}, selected=selected, selection=info,
                evidence=evidence)


def policy_t3(ctx, k=8, calls=8):
    """K independent T1 chains, then arbiter-free consensus: cross-validate patches on the others' repro tests."""
    chains = [TestFirstAgent(ctx, f"t3c{i}", max_calls=calls, hint=i) for i in range(k)]
    with ThreadPoolExecutor(max_workers=k) as pool:
        finals = _gather(ctx, [pool.submit(x.run) for x in chains])
    candidates = [f for f in finals if f]
    valid_tests = _chain_tests(chains)
    passes = crossval_matrix(ctx, candidates, valid_tests)
    selected, info = select_crossval(candidates, valid_tests, passes)
    evidence = _evidence(chains, valid_tests, passes)
    ctx.events.emit("selection_evidence", selection=info, evidence=evidence)
    return dict(candidates=candidates, agents={x.name: x.summary() for x in chains}, selected=selected,
                selection=info, evidence=evidence)


# --- V3: S3 candidates + one model review per distinct patch ------------------------------------------
def prompt_review(bundle, candidate, compact=False):
    before = bundle["files"]
    changed = sorted(p for p in candidate["files"] if before.get(p) != candidate["files"][p])
    shown = changed[:1] if compact else changed
    diff = g.diff_stats(before, dict(before, **candidate["files"]))["unified_diff"][:6000]
    return (f"A user reported a bug in the Python project `{bundle['project']}`. A colleague proposes the change "
            "below. You cannot run code. Review it critically: does it fix the ROOT CAUSE of the reported "
            "behaviour (every case the report and README imply, not only the example), without breaking other "
            "documented behaviour?\n\n"
            f"# Bug report\n{bundle['report'].strip()}\n\n# Proposed change (unified diff)\n{diff}\n"
            f"# Changed module(s) after the change\n{show_files(candidate['files'], shown)}"
            "# Your answer\nONE JSON object and nothing else:\n"
            '{"fixes_report": true or false, "risk": "<= 60 words: what could still be wrong or broken"}\n')


def parse_review(answer):
    data = extract_json(answer, keys=("fixes_report", "risk"))
    if not data:
        return dict(fixes_report=None, risk="", parsed=False)
    value = data.get("fixes_report")
    if isinstance(value, str):
        value = {"true": True, "yes": True, "false": False, "no": False}.get(value.strip().lower())
    return dict(fixes_report=value if isinstance(value, bool) else None, risk=_words(_str(data.get("risk"), 2000), 60),
                parsed=True)


def select_review(candidates, reviews):
    """V3: valid -> public tests -> approved by its reviewer -> largest cluster -> earliest."""
    valid = [c for c in candidates if c and c["valid"] and not c["no_op"]]
    info = dict(candidates=len([c for c in candidates if c]), valid=len(valid))
    if not valid:
        return None, dict(info, rule="no_valid_patch")
    passing = [c for c in valid if c["selfcheck"] and c["selfcheck"].get("ok")]
    pool = passing or valid
    clusters = {}
    for c in pool:
        clusters.setdefault(c["key"], []).append(c)

    def approved(c):
        return (reviews.get(c["key"]) or {}).get("fixes_report") is True

    def keyfn(c):
        return (not approved(c), -len(clusters[c["key"]])) + _position(c)
    best = min(pool, key=keyfn)
    decided = _decide(pool, keyfn, best)
    rule = ("vote" if len(clusters[best["key"]]) > 1 else "earliest") if decided is None else \
        {0: "review", 1: "vote"}.get(decided, "earliest")
    info.update(selfcheck_passing=len(passing), clusters=sorted((len(m) for m in clusters.values()), reverse=True),
                cluster_size=len(clusters[best["key"]]), rule=rule, selected_order=best["order"],
                selected_agent=best["agent"], selected_key=best["key"], selected_approved=approved(best),
                approved_keys=sum(1 for key in clusters if (reviews.get(key) or {}).get("fixes_report") is True),
                reviewed_keys=len(reviews))
    return best, info


def policy_v3(ctx, k=8, calls=6):
    """S3 chains (unchanged), then one reviewer per distinct patch in the selection pool."""
    out = policy_s3(ctx, k=k, calls=calls)
    valid = [c for c in out["candidates"] if c and c["valid"] and not c["no_op"]]
    pool = [c for c in valid if c["selfcheck"] and c["selfcheck"].get("ok")] or valid
    reps = {}
    for c in sorted(pool, key=_position):
        reps.setdefault(c["key"], c)

    def review(i, key, cand):
        result = None
        for compact in (False, True):
            try:
                result = ctx.caller.call(f"v3rev{i}", "review", prompt_review(ctx.bundle, cand, compact),
                                         answer_reserve=JSON_ANSWER_RESERVE, hint=i, patch_key=key)
                break
            except PromptTooLong:
                continue
        parsed = parse_review(result["answer"] if result else None)
        parsed.update(key=key, agent=cand["agent"], order=cand["order"], call_id=result["call_id"] if result else None)
        ctx.events.emit("review", reviewer=f"v3rev{i}", **parsed)
        return parsed
    with ThreadPoolExecutor(max_workers=max(1, len(reps))) as pool_:
        rows = _gather(ctx, [pool_.submit(review, i, key, cand) for i, (key, cand) in enumerate(reps.items())])
    reviews = {row["key"]: row for row in rows}
    selected, info = select_review(out["candidates"], reviews)
    evidence = dict(label="model reviews of each distinct patch (report + diff + module); no hidden material",
                    reviews=rows)
    ctx.events.emit("selection_evidence", selection=info, evidence=evidence)
    out.update(selected=selected, selection=info, evidence=evidence)
    return out


SELECTION_RULES = {
    "T1": "own repro fails-before & passes-after & public OK -> public OK -> valid; single chain",
    "T3": "tier (own repro & public -> public -> valid) -> passes most OTHER agents' reproducing tests -> "
          "largest cluster of identical normalized diffs -> earliest",
    "V3": "valid -> passes public tests -> approved by its reviewer -> largest cluster -> earliest",
}

POLICIES = {
    "S1": dict(fn=policy_s1, kwargs=dict(calls=6), max_calls=6),
    "S3": dict(fn=policy_s3, kwargs=dict(k=8, calls=6), max_calls=48),
    "W1": dict(fn=policy_w1, kwargs=dict(fixers=4, fixer_calls=2), max_calls=10 + 4 * 2),
    "T1": dict(fn=policy_t1, kwargs=dict(calls=8), max_calls=8, selection=SELECTION_RULES["T1"]),
    "T3": dict(fn=policy_t3, kwargs=dict(k=8, calls=8), max_calls=64, selection=SELECTION_RULES["T3"],
               budget=dict(max_calls=64, max_completion_tokens=512_000)),
    "V3": dict(fn=policy_v3, kwargs=dict(k=8, calls=6), max_calls=48 + 8, selection=SELECTION_RULES["V3"],
               budget=dict(max_calls=56, max_completion_tokens=320_000)),
}


# --- attempt: run policy, freeze selection, then (and only then) grade ------------------------------
def run_policy(bundle, policy, pool, events, seed, selfcheck, budget=None, abort=None, tester=None, **overrides):
    """Agent phase of one attempt.  Uses only the visible bundle, the self-check and (T1/T3) the agent-test
    sandbox.  A policy may return its own frozen ``selected``/``selection`` (T1/T3/V3); otherwise ``select``."""
    spec = POLICIES[policy]
    budget = budget or Budget(**spec.get("budget", dict(max_calls=48, max_completion_tokens=256_000)))
    caller = Caller(pool, events, budget, f"{seed}:{bundle['case_id']}:{policy}", abort)
    ctx = Context(bundle, caller, selfcheck, events)
    ctx.tester = tester
    started = time.monotonic()
    out = spec["fn"](ctx, **dict(spec["kwargs"], **overrides))
    if "selection" in out:
        selected, info = out.pop("selected"), out["selection"]
    else:
        selected, info = select(out["candidates"])
    out.update(selected=selected, selection=info, all_patches=ctx.patches, budget=budget.snapshot(),
               agent_wall_s=round(time.monotonic() - started, 3))
    events.emit("selection_frozen", selection=info,
                selected_patch_sha256=sha(selected["patch_text"]) if selected else None,
                candidate_orders=[c["order"] for c in out["candidates"]], budget=out["budget"])
    return out


def _public(candidate):
    if not candidate:
        return None
    return {k: candidate[k] for k in ("agent", "rank", "stage", "call_id", "order", "key", "claim", "hypothesis",
                                      "selfcheck", "shown")} | {"patch_sha256": sha(candidate["patch_text"]),
                                                                "files": sorted(candidate["files"])} | {
        k: candidate[k] for k in PUBLIC_EXTRA if k in candidate}


def score_attempt(case_id, out, events, grade_fn=None, executor=None, oracle=True):
    """Hidden phase, after ``selection_frozen``: exactly one hidden grade of the selection, then oracle grades.

    Oracle grades are labelled hindsight upper bound and never change the selection."""
    grade_fn = grade_fn or (lambda patch: g.grade(case_id, patch, executor=executor))
    selected = out["selected"]
    primary = None
    if selected:
        primary = grade_fn(selected["patch_text"])
        primary.get("patch", {}).pop("unified_diff", None)
        events.emit("hidden_grade", role="selected", patch_sha256=sha(selected["patch_text"]),
                    status=primary["status"], failure_kind=primary.get("failure_kind"),
                    provenance=primary.get("provenance"), grade=primary)
        if primary["status"] == "error":
            raise InfrastructureFault(f"grading infrastructure: {primary.get('error')}")
    distinct = {}
    for c in out["all_patches"]:
        distinct.setdefault(sha(c["patch_text"]), c)
    oracle_rows = []
    if oracle:
        for digest, c in distinct.items():
            if selected and digest == sha(selected["patch_text"]):
                result, reused = primary, True
            else:
                result, reused = grade_fn(c["patch_text"]), False
                result.get("patch", {}).pop("unified_diff", None)
            row = dict(patch_sha256=digest, order=c["order"], agent=c["agent"], status=result["status"],
                       target=result.get("target"), regression=result.get("regression"),
                       selfcheck_ok=bool(c["selfcheck"] and c["selfcheck"].get("ok")), reused_selected_grade=reused)
            events.emit("oracle_grade", label="ORACLE hindsight upper bound; never used for selection", **row)
            if result["status"] == "error":
                raise InfrastructureFault(f"grading infrastructure (oracle): {result.get('error')}")
            oracle_rows.append(row)
    case = g.load_case(case_id)
    claims = [c["claim"] for c in out["candidates"] if c and c.get("claim")]
    loc = {}
    if selected and selected.get("claim"):
        loc["selected_claim"] = g.score_localization(case, selected["claim"])
    if out.get("pre_patch_claim"):
        loc["pre_patch_claim"] = g.score_localization(case, out["pre_patch_claim"])
    loc["any_claim_function_hit"] = any(g.score_localization(case, c)["function_hit"] for c in claims)
    return dict(
        fixed=bool(primary and primary["status"] == "passed"),
        selected_grade={k: primary.get(k) for k in ("status", "failure_kind", "provenance", "hidden", "target",
                                                    "regression", "localization", "patch")} if primary else None,
        localization=loc,
        oracle=dict(label="ORACLE: hidden grade of every distinct candidate; hindsight upper bound, not used for "
                          "selection", distinct=len(oracle_rows), any_passed=any(r["status"] == "passed"
                                                                                  for r in oracle_rows),
                    passed=sum(r["status"] == "passed" for r in oracle_rows), rows=oracle_rows) if oracle else None)


def run_attempt(case_id, policy, seed, pool, events_path=None, executor=None, grade_fn=None, selfcheck=None,
                budget=None, oracle=True, tester=None, **overrides):
    """Agent phase -> frozen selection -> one hidden grade -> oracle.  Returns the attempt record.

    ``status``: ``completed`` (fixed or not: candidate failures are outcomes) or
    ``infrastructure_fault`` (the runner must stop admitting attempts)."""
    bundle = g.agent_bundle(case_id)
    events = Events(events_path, case_id=case_id, policy=policy, seed=seed)
    selfcheck = selfcheck or make_selfcheck(bundle["project"], executor)
    tester = tester or make_agent_tester(bundle, executor)
    record = dict(case_id=case_id, policy=policy, seed=seed, status="completed")
    started = time.monotonic()
    try:
        events.emit("attempt_start", policy_kwargs=dict(POLICIES[policy]["kwargs"], **overrides))
        out = run_policy(bundle, policy, pool, events, seed, selfcheck, budget=budget, tester=tester, **overrides)
        record.update(selection=out["selection"], selected=_public(out["selected"]), budget=out["budget"],
                      candidates=[_public(c) for c in out["candidates"]],
                      patches_generated=len(out["all_patches"]), agents=out.get("agents"),
                      scouts=out.get("scouts"), aggregate=out.get("aggregate"))
        if out.get("evidence") is not None:  # T1/T3/V3 only: S1/S3/W1 records keep their exact keys
            record["evidence"] = out["evidence"]
        record.update(score_attempt(case_id, out, events, grade_fn, executor, oracle))
    except InfrastructureFault as exc:
        record.update(status="infrastructure_fault", error=str(exc))
    except PromptTooLong as exc:
        record.update(status="prompt_too_long", error=str(exc))
    record["wall_s"] = round(time.monotonic() - started, 3)
    record["usage"] = usage_summary(events)
    events.emit("attempt_end", status=record["status"], fixed=record.get("fixed"), wall_s=record["wall_s"],
                usage=record["usage"])
    events.close()
    record["events"] = events
    return record


def usage_summary(events):
    ends = events.of("request_end")
    calls = events.of("call_end")
    return dict(calls=len(calls), requests=len(ends), forced=sum(1 for e in calls if e["forced"]),
                truncated=sum(1 for e in calls if e["truncated"]),
                completion_tokens=sum(e["completion_tokens"] for e in ends),
                prompt_tokens=sum(e["prompt_tokens"] for e in events.of("call_start")))
