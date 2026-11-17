"""bugbench policy R: DeepSeek V4.1 reference (whole bundle in one prompt, one patch, one self-check repair).

Importing this module runs nothing and contacts nothing.

DESIGN.md section 12: "R DeepSeek V4.1 reference: the whole bundle in one prompt, one patch, one
self-check repair."  Different model, context and compute; a reference ceiling, not an equal-cost arm.

Information boundary
--------------------
Same as ``agents.py``: the prompt is built only from ``bugbench_grader.agent_bundle(case_id)`` (buggy
tree including README and public tests, report, repo map, editable paths, patch format).  The case id
and hint variant are not shown (the case id names the bug).  ``case.json``, probes, expected values and
the canary are read only by ``agents.score_attempt`` after ``selection_frozen``.

Model calls
-----------
:class:`ChatTransport` reproduces ``ds_stream_worker.StreamClient`` semantics (copied in minimal form
rather than imported, because that module imports the frozen arithmetic study): streamed OpenAI-compatible
``/chat/completions`` (DeepSeek's frontend has no ``/tokenize`` and no raw ``/v1/completions``), thinking
on via ``chat_template_kwargs``, ``stream_options.include_usage``, temperature 0.8, a request seed derived
from the attempt seed and the messages.  A gap of ``idle_timeout`` seconds without a streamed byte, a
stream error chunk, a stream without ``finish_reason`` or a call longer than ``wall_limit`` seconds is an
infrastructure fault (the runner stops admitting attempts).  The raw answer ``content`` is returned (not
JSON-parsed); ``reasoning_content`` is logged.  Missing usage is charged at ``max_tokens``.

Policy
------
1. One call: the whole bundle -> JSON claim + full-file patch (``=== FILE: ... ===`` blocks).
2. A valid, non-no-op patch gets the self-check (the project's public tests) once.
3. Only if that self-check fails: one repair call, as a second turn of the same conversation
   (first user message, the model's first answer, then the failure output and the diff).
4. Selected patch = the final valid patch (repair if valid, else the first patch), or none.
The repaired patch is self-checked too (logged, never used to change the selection).
"""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents as a  # noqa: E402
import bugbench_grader as g  # noqa: E402

MODEL = "deepseek-v4.1-flash"
ENDPOINT = "http://127.0.0.1:18889/v1"
CONTEXT_WINDOW = 1_000_000      # informational: the whole bundle (~20K tokens) fits many times over
MAX_TOKENS = 32768              # per call, thinking + answer
IDLE_TIMEOUT = 120              # seconds without any streamed byte -> infrastructure fault
WALL_LIMIT = 1800               # seconds per call -> infrastructure fault
TEMPERATURE = 0.8
REPAIR_OUTPUT_CHARS = 6000      # tail of the failing self-check output shown in the repair turn
REPAIR_DIFF_CHARS = 12000
SELECTION_RULE = "final valid patch: the repair if valid and non-empty, else the first patch; none if neither"


# --- transport --------------------------------------------------------------------------------------------
class ChatTransport:
    """One OpenAI-compatible chat-completions endpoint, streamed.  Adapted from ds_stream_worker.StreamClient."""

    def __init__(self, endpoint=ENDPOINT, model=MODEL, idle_timeout=IDLE_TIMEOUT, wall_limit=WALL_LIMIT,
                 clock=time.monotonic):
        self.endpoint = endpoint.rstrip("/")
        self.url = self.endpoint + "/chat/completions"
        self.model, self.idle_timeout, self.wall_limit, self.clock = model, idle_timeout, wall_limit, clock

    def body(self, messages, max_tokens, seed, temperature=TEMPERATURE):
        return dict(model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature, seed=seed,
                    stream=True, stream_options={"include_usage": True},
                    chat_template_kwargs={"enable_thinking": True})

    def _open(self, wire):
        """Iterable of raw SSE lines (bytes).  The socket timeout applies per read: a silent server, not a slow one."""
        request = urllib.request.Request(self.url, data=wire, headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(request, timeout=self.idle_timeout)

    def complete(self, body):
        """Stream one chat completion.  Returns dict(content, reasoning, finish_reason, usage, error)."""
        wire = json.dumps(body).encode()
        start = self.clock()
        content, reasoning, finish, usage, error = "", "", None, {}, None
        try:
            with self._open(wire) as response:
                for raw in response:
                    if self.clock() - start > self.wall_limit:
                        raise TimeoutError(f"wall limit {self.wall_limit}s exceeded")
                    line = (raw.decode() if isinstance(raw, bytes) else raw).strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[5:])
                    if chunk.get("error"):
                        raise ConnectionError(f"server stream error: {str(chunk['error'])[:200]}")
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content += delta.get("content") or ""
                        reasoning += delta.get("reasoning_content") or delta.get("reasoning") or ""
                        finish = choice.get("finish_reason") or finish
                    if chunk.get("usage"):
                        usage = {k: v for k, v in chunk["usage"].items()
                                 if k in ("prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int}
            if finish is None:
                raise ConnectionError("stream ended without finish_reason")
        except Exception as exc:  # noqa: BLE001 - every transport fault is infrastructure
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
        return dict(content=content, reasoning=reasoning, finish_reason=finish, usage=usage, error=error,
                    wall_s=round(self.clock() - start, 3))


class ChatPool:
    """Concurrency limit on the single DeepSeek endpoint, shared by every attempt."""

    def __init__(self, transport, limit=8):
        self.transport, self.transports = transport, [transport]
        self.semaphore = threading.BoundedSemaphore(limit)
        self.limit = limit

    @contextmanager
    def lease(self):
        with self.semaphore:
            yield 0, self.transport


def split_content(content, finish_reason):
    """(answer, inline_reasoning).  The frontend normally separates ``reasoning_content``; if thinking leaks
    into ``content`` the answer is the text after the LAST ``</think>``.  None = no usable answer (thinking
    never closed inside the cap, or nothing was returned)."""
    if a.END_THINK in content:
        reasoning, _, answer = content.rpartition(a.END_THINK)
        return answer, reasoning
    if content.lstrip().startswith("<think>"):
        return None, content
    if not content.strip() and finish_reason == "length":
        return None, ""
    return content, ""


class ChatCaller:
    """Logical calls for one attempt: budget, request seed, events compatible with ``agents.Caller``."""

    def __init__(self, pool, events, budget, seed, max_tokens=MAX_TOKENS):
        self.pool, self.events, self.budget, self.seed, self.max_tokens = pool, events, budget, str(seed), max_tokens

    def call(self, agent, stage, messages, max_tokens=None, **context):
        """One streamed call.  Returns dict(answer, truncated, ...) or None when the budget is spent.

        Raises ``agents.InfrastructureFault`` on any transport fault."""
        max_tokens = max_tokens or self.max_tokens
        call_id = uuid.uuid4().hex[:12]
        for message in messages:
            if message["role"] == "user":
                self.events.prompt(message["content"])
        messages_sha = a.sha(json.dumps(messages, ensure_ascii=False))
        prompt_chars = sum(len(m["content"]) for m in messages)
        if not self.budget.start_call():
            self.events.emit("budget_exhausted", agent=agent, stage=stage, call_id=call_id, reason="max_calls",
                             budget=self.budget.snapshot())
            return None
        if not self.budget.reserve(max_tokens):
            self.events.emit("budget_exhausted", agent=agent, stage=stage, call_id=call_id, requested=max_tokens,
                             reason="completion_tokens", budget=self.budget.snapshot())
            return None
        seed = int.from_bytes(hashlib.sha256(f"{self.seed}:{agent}:{stage}:{messages_sha}".encode()).digest()[:4],
                              "big")
        with self.pool.lease() as (index, transport):
            body = transport.body(messages, max_tokens, seed)
            wire_sha = a.sha(json.dumps(body))
            self.events.emit("call_start", call_id=call_id, agent=agent, stage=stage, endpoint_index=index,
                             model=transport.model, messages_sha256=messages_sha, turns=len(messages),
                             prompt_chars=prompt_chars, prompt_tokens_estimate=g.approx_tokens(
                                 "".join(m["content"] for m in messages)), max_tokens=max_tokens, **context)
            request_id = uuid.uuid4().hex[:12]
            self.events.emit("request_start", request_id=request_id, call_id=call_id, agent=agent, stage=stage,
                             phase="chat", endpoint_index=index, endpoint=transport.endpoint,
                             request_body={k: v for k, v in body.items() if k != "messages"},
                             messages=[dict(role=m["role"], sha256=a.sha(m["content"]), chars=len(m["content"]))
                                       for m in messages],
                             request_body_sha256=wire_sha, max_tokens=max_tokens, seed=seed, temperature=TEMPERATURE,
                             request_thinking=True)
            started = time.monotonic()
            out = transport.complete(body)
        reported = out["usage"].get("completion_tokens")
        settled = reported if out["error"] is None else None
        self.budget.settle(max_tokens, settled)
        charged = max_tokens if settled is None else settled
        self.events.emit("request_end", request_id=request_id, call_id=call_id, agent=agent, stage=stage, phase="chat",
                         endpoint_index=index, latency_ms=round((time.monotonic() - started) * 1000, 1),
                         usage=out["usage"], usage_estimated=reported is None, completion_tokens=charged,
                         completion_tokens_reported=reported, finish_reason=out["finish_reason"], error=out["error"],
                         text=out["content"], reasoning=out["reasoning"])
        if out["error"]:
            raise a.InfrastructureFault(f"{agent}/{stage}: {out['error']}")
        answer, inline = split_content(out["content"], out["finish_reason"])
        truncated = out["finish_reason"] == "length"
        result = dict(call_id=call_id, answer=answer, truncated=truncated, forced=False,
                      prompt_tokens=out["usage"].get("prompt_tokens"), completion_tokens=charged,
                      usage_estimated=reported is None, endpoint_index=index, closed_thinking=answer is not None,
                      reasoning_chars=len(out["reasoning"]) + len(inline), finish_reason=out["finish_reason"])
        self.events.emit("call_end", call_id=call_id, agent=agent, stage=stage, forced=False, truncated=truncated,
                         completion_tokens=charged, prompt_tokens=result["prompt_tokens"],
                         closed_thinking=answer is not None, finish_reason=out["finish_reason"], answer=answer)
        return result


# --- prompts --------------------------------------------------------------------------------------------
def prompt_r(bundle):
    """The whole agent-visible bundle in one user message.  Never the case id or hint variant."""
    files = bundle["files"]
    editable = "\n".join(bundle["editable_paths"])
    return (f"A user reported a bug in the Python project `{bundle['project']}`. Below you get the WHOLE project: "
            "the bug report, a repository map, the list of files you may edit and the complete content of every "
            "file (package, README.md and the visible tests). You cannot run code. After your answer the project's "
            "visible tests are run on your patched code; if they fail you see the output once and may repair.\n\n"
            f"# Bug report (REPORT.md)\n{bundle['report'].strip()}\n\n"
            f"# Repository map (REPO_MAP.txt)\n{bundle['repo_map']}\n"
            f"# Editable files\n{editable}\n\n"
            f"# Project files (complete)\n{a.show_files(files, sorted(files))}"
            "# Your answer\nFind the defect that causes the reported behaviour (the symptom often surfaces in a "
            "different module than the defect) and fix its root cause. First ONE JSON object:\n"
            '{"location": {"file": "<path>", "function": "<function or Class.method>"}, '
            '"hypothesis": "<the defect and your fix, <= 60 words>"}\n'
            f"then the fix:\n{bundle['patch_format']}"
            "Change as little as possible and keep every other line identical. Never abbreviate with \"...\" or "
            "\"rest unchanged\". Fix the root cause at the defective function, not only the example in the report. "
            "The visible tests pass on the current code and must keep passing.\n")


def prompt_r_repair(bundle, candidate, selfcheck):
    output = (selfcheck.get("output") or selfcheck.get("setup_error") or selfcheck.get("error") or "")
    diff = g.diff_stats(bundle["files"], dict(bundle["files"], **candidate["files"]))["unified_diff"]
    return ("# Self-check failed\nThe project's own visible tests pass on the original code but FAIL on your "
            f"patched code, so your change broke documented behaviour:\n{output[-REPAIR_OUTPUT_CHARS:]}\n\n"
            f"# Your patch as a diff against the original code\n{diff[:REPAIR_DIFF_CHARS]}\n"
            "# Your answer\nRepair the fix (you may also choose a different approach). Answer as before: ONE JSON "
            "object\n"
            '{"location": {"file": "<path>", "function": "<function or Class.method>"}, '
            '"hypothesis": "<= 60 words"}\n'
            f"then the fix:\n{bundle['patch_format']}"
            "Each block must contain the complete file. A file you leave out reverts to its ORIGINAL content (as "
            "shown in my first message), not to your previous patch.\n")


# --- policy -----------------------------------------------------------------------------------------------
def _candidate(ctx, decision, parsed, result, stage):
    claim = decision.get("location") if isinstance(decision.get("location"), dict) else None
    if claim:
        claim = {"file": a._str(claim.get("file"), 200), "function": a._str(claim.get("function"), 200)}
    return dict(agent="r", rank=0, stage=stage, call_id=result["call_id"], order=ctx.next_order(),
                files=parsed["files"], key=parsed["key"], valid=parsed["valid"], no_op=parsed["no_op"],
                error=parsed["error"], claim=claim, hypothesis=a._str(decision.get("hypothesis"), 600),
                shown=sorted(ctx.files), selfcheck=None,
                patch_text=g.patch_from_files(parsed["files"]) if parsed["valid"] else None)


def _check(ctx, candidate):
    result = ctx.selfcheck(dict(ctx.files, **candidate["files"]))
    candidate["selfcheck"] = a._selfcheck_summary(result)
    ctx.events.emit("selfcheck", agent="r", call_id=candidate["call_id"], order=candidate["order"],
                    ok=bool(result.get("ok")), summary=candidate["selfcheck"])
    return result


def _parse(ctx, result, stage, trace):
    decision = a.extract_json(result["answer"], keys=("location", "hypothesis")) or {}
    parsed = a.parse_patch_answer(result["answer"], ctx.files, ctx.editable)
    candidate = _candidate(ctx, decision, parsed, result, stage)
    trace.append(dict(stage=stage, call_id=result["call_id"], parsed_json=bool(decision), patch_valid=parsed["valid"],
                      patch_error=parsed["error"], no_op=parsed["no_op"], truncated=result["truncated"],
                      closed_thinking=result["closed_thinking"], finish_reason=result["finish_reason"],
                      completion_tokens=result["completion_tokens"], prompt_tokens=result["prompt_tokens"]))
    return candidate, parsed["valid"] and not parsed["no_op"]


def policy_r(ctx, max_tokens=MAX_TOKENS):
    """One whole-bundle call; self-check once; one repair turn only if that self-check failed."""
    messages = [{"role": "system", "content": a.SYSTEM}, {"role": "user", "content": prompt_r(ctx.bundle)}]
    trace, candidates = [], []
    result = ctx.caller.call("r", "patch", messages, max_tokens)
    if result is not None:
        first, ok = _parse(ctx, result, "patch", trace)
        if ok:
            candidates.append(first)
            ctx.record_patch(first)
            check = _check(ctx, first)
            if not check.get("ok"):
                repair_messages = messages + [{"role": "assistant", "content": result["answer"]},
                                              {"role": "user", "content": prompt_r_repair(ctx.bundle, first, check)}]
                second = ctx.caller.call("r", "repair", repair_messages, max_tokens)
                if second is not None:
                    repair, ok = _parse(ctx, second, "repair", trace)
                    if ok:
                        candidates.append(repair)
                        ctx.record_patch(repair)
                        _check(ctx, repair)  # logged only; the selection is the final valid patch regardless
    claims = [c["claim"] for c in candidates if c.get("claim")]
    return dict(candidates=candidates, agents={"r": dict(trace=trace, claims=claims, calls=len(trace))})


def select_final(candidates):
    """Final valid patch (generation order), or none.  Uses visible material only."""
    valid = [c for c in candidates if c and c["valid"] and not c["no_op"]]
    info = dict(candidates=len([c for c in candidates if c]), valid=len(valid), rule_text=SELECTION_RULE)
    if not valid:
        return None, dict(info, rule="no_valid_patch")
    best = max(valid, key=lambda c: c["order"])
    return best, dict(info, rule="final_valid", selected_order=best["order"], selected_agent=best["agent"],
                      selected_stage=best["stage"], selected_key=best["key"],
                      selfcheck_passing=sum(1 for c in valid if c["selfcheck"] and c["selfcheck"].get("ok")))


POLICIES = {
    "R": dict(fn=policy_r, kwargs=dict(max_tokens=MAX_TOKENS), max_calls=2, selection=SELECTION_RULE,
              budget=dict(max_calls=2, max_completion_tokens=2 * MAX_TOKENS)),
}


# --- attempt: run policy, freeze selection, then (and only then) grade ---------------------------------------
def run_policy(bundle, policy, pool, events, seed, selfcheck, budget=None, **overrides):
    spec = POLICIES[policy]
    budget = budget or a.Budget(**spec["budget"])
    kwargs = dict(spec["kwargs"], **overrides)
    caller = ChatCaller(pool, events, budget, f"{seed}:{bundle['case_id']}:{policy}", kwargs["max_tokens"])
    ctx = a.Context(bundle, caller, selfcheck, events)
    started = time.monotonic()
    out = spec["fn"](ctx, **kwargs)
    selected, info = select_final(out["candidates"])
    out.update(selected=selected, selection=info, all_patches=ctx.patches, budget=budget.snapshot(),
               agent_wall_s=round(time.monotonic() - started, 3))
    events.emit("selection_frozen", selection=info,
                selected_patch_sha256=a.sha(selected["patch_text"]) if selected else None,
                candidate_orders=[c["order"] for c in out["candidates"]], budget=out["budget"])
    return out


def usage_summary(events):
    """Same keys as ``agents.usage_summary``; prompt tokens are server-reported (estimate if missing)."""
    ends = events.of("request_end")
    calls = events.of("call_end")
    starts = {e["call_id"]: e for e in events.of("call_start")}
    reported = [e.get("prompt_tokens") for e in calls]
    prompt = sum(p if p is not None else starts.get(e["call_id"], {}).get("prompt_tokens_estimate", 0)
                 for p, e in zip(reported, calls))
    return dict(calls=len(calls), requests=len(ends), forced=0, truncated=sum(1 for e in calls if e["truncated"]),
                completion_tokens=sum(e["completion_tokens"] for e in ends), prompt_tokens=prompt,
                prompt_tokens_estimated=any(p is None for p in reported),
                completion_tokens_estimated=any(e.get("usage_estimated") for e in ends))


def run_attempt(case_id, policy, seed, pool, events_path=None, executor=None, grade_fn=None, selfcheck=None,
                budget=None, oracle=True, tester=None, **overrides):
    """Agent phase -> frozen selection -> one hidden grade -> oracle.  Same record shape as ``agents.run_attempt``."""
    bundle = g.agent_bundle(case_id)
    events = a.Events(events_path, case_id=case_id, policy=policy, seed=seed)
    selfcheck = selfcheck or a.make_selfcheck(bundle["project"], executor)
    record = dict(case_id=case_id, policy=policy, seed=seed, status="completed")
    started = time.monotonic()
    try:
        events.emit("attempt_start", policy_kwargs=dict(POLICIES[policy]["kwargs"], **overrides),
                    model=pool.transport.model, endpoint=pool.transport.endpoint)
        out = run_policy(bundle, policy, pool, events, seed, selfcheck, budget=budget, **overrides)
        record.update(selection=out["selection"], selected=a._public(out["selected"]), budget=out["budget"],
                      candidates=[a._public(c) for c in out["candidates"]],
                      patches_generated=len(out["all_patches"]), agents=out.get("agents"), scouts=None,
                      aggregate=None)
        record.update(a.score_attempt(case_id, out, events, grade_fn, executor, oracle))
    except a.InfrastructureFault as exc:
        record.update(status="infrastructure_fault", error=str(exc))
    record["wall_s"] = round(time.monotonic() - started, 3)
    record["usage"] = usage_summary(events)
    events.emit("attempt_end", status=record["status"], fixed=record.get("fixed"), wall_s=record["wall_s"],
                usage=record["usage"])
    events.close()
    record["events"] = events
    return record


def preflight(transport):
    """Cheap live check before admitting attempts: the endpoint serves ``transport.model``."""
    with urllib.request.urlopen(transport.endpoint + "/models", timeout=15) as response:
        served = [m.get("id") for m in json.load(response).get("data", [])]
    if transport.model not in served:
        raise SystemExit(f"{transport.endpoint} does not serve {transport.model!r}: {served}")
