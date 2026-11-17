"""bugbench policies L1/L8: Nemotron with the WHOLE project in one prompt (long-context serving, 128K window).

Context-gap experiment.  DeepSeek policy R (deepseek_ref.py) sees the whole agent-visible bundle in one prompt
and fixed 36/36; every Nemotron policy so far had to navigate file by file inside a 16K window.  With the
Nemotron replicas served at --max-model-len 131072 (ctx_switch.py), L1/L8 give Nemotron the same prompt as R:

  L1  one whole-bundle call (prompt_r, identical text to R) -> full-file patch -> public self-check -> at most
      one repair call if the self-check fails (prompt_r + the agent's own previous answer + prompt_r_repair, in
      one user message, because the budget-forced Caller is single-turn).
  L8  eight independent L1 agents (distinct agent names => distinct seeds), no sharing.
Selection (both): agents.select = valid -> passes public tests -> largest cluster of identical normalized
diffs -> earliest.  Public tests are part of the agent-visible bundle; hidden probes are graded once after
the selection is frozen (agents.score_attempt), exactly as for S1..V3 and R.

Budget forcing as in agents.Caller (think cap, then "\\n</think>\\n" and continue the same sequence), with the
per-request window raised to CONTEXT_LIMIT and the per-call total to MAX_TOTAL (DeepSeek R used max_tokens
32768).  The caps are installed by ``install()``, which swaps ``agents.compute_caps`` for this process; the
runner therefore refuses to mix L-policies with 16K policies.

Importing this module changes nothing and contacts nothing.
"""
import functools
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents as a  # noqa: E402
import deepseek_ref as dr  # noqa: E402

CONTEXT_LIMIT = 131000        # server window 131,072
MAX_TOTAL = 32768             # per logical call, thinking + answer (same as DeepSeek R max_tokens)
ANSWER_RESERVE = 6000         # whole-file patches; forced answer budget after the think cap
FORMAT_FOLLOWUP = False       # v2 policies L1F/L8F set it (process-wide, like the caps)
SELECTION = "valid -> passes public tests -> largest cluster of identical normalized diffs -> earliest"
_ORIGINAL_CAPS = a.compute_caps


def install():
    a.compute_caps = functools.partial(_ORIGINAL_CAPS, limit=CONTEXT_LIMIT, max_total=MAX_TOTAL)
    a.CONTEXT_LIMIT, a.MAX_COMPLETION = CONTEXT_LIMIT, MAX_TOTAL  # recorded in plan.json budgets


_GLUED_HEADER = re.compile(r"(?m)^(\{.*\})[ \t]*=== FILE: ")  # only after the JSON object, never inside code
_OPEN_HEADER = re.compile(r"(?m)^=== FILE: (\S+?)(?:[ \t]+(?:---|==))?[ \t]*$")  # header closed by '---' or not at all
_END_WITH_PATH = re.compile(r"(?m)^=== END FILE: [^\n]*? ===[ \t]*$")


def normalize_answer(answer):
    """v2 (dev pilot finding): Nemotron often closes a block with '=== END FILE: <path> ===' instead of the
    required '=== END FILE ==='.  Rewrite only that marker; everything else goes to the unchanged parser."""
    if not FORMAT_FOLLOWUP or not isinstance(answer, str):
        return answer
    answer = _GLUED_HEADER.sub("\\1\n=== FILE: ", answer)  # header glued to the JSON line
    answer = _OPEN_HEADER.sub(lambda m: f"=== FILE: {m.group(1)} ===", answer)
    return _END_WITH_PATH.sub("=== END FILE ===", answer)


def _candidate(ctx, name, rank, stage, result, diagnosis=None):
    answer = normalize_answer(result["answer"])
    decision = a.extract_json(answer, keys=("location", "hypothesis")) or {}
    if not decision and diagnosis:  # format follow-up answers carry only FILE blocks; keep the first diagnosis
        decision = a.extract_json(diagnosis, keys=("location", "hypothesis")) or {}
    parsed = a.parse_patch_answer(answer, ctx.files, ctx.editable)
    claim = decision.get("location") if isinstance(decision.get("location"), dict) else None
    if claim:
        claim = {"file": a._str(claim.get("file"), 200), "function": a._str(claim.get("function"), 200)}
    cand = dict(agent=name, rank=rank, stage=stage, call_id=result["call_id"], order=ctx.next_order(),
                files=parsed["files"], key=parsed["key"], valid=parsed["valid"], no_op=parsed["no_op"],
                error=parsed["error"], claim=claim, hypothesis=a._str(decision.get("hypothesis"), 600),
                shown=sorted(ctx.files), selfcheck=None,
                patch_text=a.g.patch_from_files(parsed["files"]) if parsed["valid"] else None)
    step = dict(stage=stage, call_id=result["call_id"], parsed_json=bool(decision), patch_valid=parsed["valid"],
                patch_error=parsed["error"], no_op=parsed["no_op"], truncated=result["truncated"],
                forced=result["forced"], closed_thinking=result["closed_thinking"],
                completion_tokens=result["completion_tokens"], prompt_tokens=result["prompt_tokens"])
    return cand, step, parsed["valid"] and not parsed["no_op"]


def _check(ctx, name, cand):
    result = ctx.selfcheck(dict(ctx.files, **cand["files"]))
    cand["selfcheck"] = a._selfcheck_summary(result)
    ctx.events.emit("selfcheck", agent=name, call_id=cand["call_id"], order=cand["order"],
                    ok=bool(result.get("ok")), summary=cand["selfcheck"])
    return result


def whole_agent(ctx, name="l1", rank=0):
    """One L1 agent.  Returns (candidates, trace)."""
    prompt = dr.prompt_r(ctx.bundle)
    trace, cands = [], []
    result = ctx.caller.call(name, "patch", prompt, answer_reserve=ANSWER_RESERVE, hint=rank)
    if result is None:
        return cands, trace
    first, step, ok = _candidate(ctx, name, rank, "patch", result)
    trace.append(step)
    if not ok and FORMAT_FOLLOWUP and first["error"] == "no FILE blocks found" and result["answer"]:
        # v2 (dev pilot finding): Nemotron often stops after the JSON diagnosis and never writes the patch.
        diagnosis = result["answer"]
        follow = (prompt + "\n# Your previous answer\n" + diagnosis + "\n\n# Your answer\nYour previous answer "
                  "gave only the diagnosis and NO patch. Do NOT repeat the JSON. Output ONLY the patch that implements "
                  "your diagnosis: the complete new content of each changed file, starting with a line "
                  f"'=== FILE: <path> ===', in exactly this format:\n{ctx.bundle['patch_format']}")
        result = ctx.caller.call(name, "format", follow, answer_reserve=ANSWER_RESERVE, hint=rank)
        if result is None:
            return cands, trace
        first, step, ok = _candidate(ctx, name, rank, "format", result, diagnosis)
        trace.append(step)
    if not ok:
        return cands, trace
    cands.append(first)
    ctx.record_patch(first)
    check = _check(ctx, name, first)
    if check.get("ok"):
        return cands, trace
    repair_prompt = (prompt + "\n# Your previous answer\n" + (result["answer"] or "") + "\n\n"
                     + dr.prompt_r_repair(ctx.bundle, first, check))
    second = ctx.caller.call(name, "repair", repair_prompt, answer_reserve=ANSWER_RESERVE, hint=rank)
    if second is None:
        return cands, trace
    repair, step, ok = _candidate(ctx, name, rank, "repair", second)
    trace.append(step)
    if ok:
        cands.append(repair)
        ctx.record_patch(repair)
        _check(ctx, name, repair)
    return cands, trace


def policy_l1(ctx):
    cands, trace = whole_agent(ctx, "l1", 0)
    return dict(candidates=cands, agents={"l1": dict(trace=trace, claims=[c["claim"] for c in cands if c["claim"]],
                                                     calls=len(trace))})


def policy_l8(ctx, k=8):
    names = [f"l8c{i}" for i in range(k)]
    with ThreadPoolExecutor(max_workers=k) as pool:
        futures = [pool.submit(whole_agent, ctx, n, i) for i, n in enumerate(names)]
        outs = a._gather(ctx, futures)
    cands = [c for out, _ in outs for c in out]
    return dict(candidates=cands, agents={n: dict(trace=t, claims=[c["claim"] for c in o if c["claim"]],
                                                  calls=len(t)) for n, (o, t) in zip(names, outs)})


POLICIES = {
    "L1": dict(fn=policy_l1, kwargs={}, max_calls=2, budget=dict(max_calls=2, max_completion_tokens=2 * MAX_TOTAL)),
    "L8": dict(fn=policy_l8, kwargs=dict(k=8), max_calls=16,
               budget=dict(max_calls=16, max_completion_tokens=16 * MAX_TOTAL)),
    # v2: + one format follow-up call when the first answer has no FILE blocks (3 calls per agent at most)
    "L1F": dict(fn=policy_l1, kwargs={}, max_calls=3, budget=dict(max_calls=3, max_completion_tokens=3 * MAX_TOTAL)),
    "L8F": dict(fn=policy_l8, kwargs=dict(k=8), max_calls=24,
                budget=dict(max_calls=24, max_completion_tokens=24 * MAX_TOTAL)),
}
for _spec in POLICIES.values():
    _spec["selection"] = SELECTION


def main(argv=None):
    """Run the standard bugbench runner with L-policies only and the long-context caps installed."""
    argv = list(sys.argv[1:] if argv is None else argv)
    pols = argv[argv.index("--policies") + 1:] if "--policies" in argv else []
    pols = [p for p in pols[:next((i for i, p in enumerate(pols) if p.startswith("--")), len(pols))]]
    if not pols or any(p not in POLICIES for p in pols):
        raise SystemExit("nemotron_long runs only L-policies (--policies L1 [L8] | L1F [L8F])")
    follow = {p.endswith("F") for p in pols}
    if len(follow) != 1:
        raise SystemExit("do not mix v1 (L1/L8) and v2 (L1F/L8F) policies in one process")
    global FORMAT_FOLLOWUP
    FORMAT_FOLLOWUP = follow.pop()
    install()
    a.POLICIES.update(POLICIES)
    import run_agents  # noqa: E402  (imported after install so its POLICIES table includes L1/L8)
    run_agents.POLICIES.update(POLICIES)
    return run_agents.main(argv)


if __name__ == "__main__":
    sys.exit(main())
