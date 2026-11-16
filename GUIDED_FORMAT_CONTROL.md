# Prospective format-only CSP control

This isolated exploratory branch starts at `dadba8c29cd5b11bd71e49b4c8ba4e6ee5adaab5`. It does not replace the original unconstrained CSP study or its results. It is motivated after inspection of the first 112 original cases (development plus evaluation seed 1): no solved assignments and 1,168 malformed candidates, mainly arrays with wrong cardinality. These are posthoc observations, not preregistration before the original outcomes.

The new `core_guided_off16` profile covers all 12 evaluation tasks, the original seven methods, and seed 1: 84 cases. It retains the original prompts, data, policies, T0.8, reasoning OFF, 512 completion tokens/call, 16 calls and 8,192 completion tokens/case, nominal 180-second case budget, and 210-second request timeout. Only the request's JSON-schema constraint changes. Candidate schemas require exactly one assignment field, exactly n integer entries, and colors enumerated 0 through k−1. They encode no edges, witness, score, or suggested move. Review calls instead require exactly one critique string of length 1–4,000. The exact existing verifier still checks every edge. A well-formed array can remain wholly incorrect.

The Client hook is absent by default; original request bodies and request-seed derivation remain unchanged. Worker and profile flags opt in. No constrained model requests have been made during preparation. Default runner behavior prints a plan and performs no gate/server/model requests or output writes.

## Versioned compatibility evidence

Official [vLLM v0.32 structured-output documentation](https://docs.vllm.ai/en/v0.32.0/features/structured_outputs/) documents the `structured_outputs: {json: schema}` request field. No deprecated guided_json field or runtime change is needed.

The [v0.32 StructuredOutputManager](https://github.com/vllm-project/vllm/blob/v0.32.0/vllm/v1/structured_output/__init__.py) implements draft-prefix validation, masks for every speculative position plus bonus token, and grammar rollback. The [GPU structured-output code](https://github.com/vllm-project/vllm/blob/v0.32.0/vllm/v1/worker/gpu/structured_outputs.py) maps masks across draft and bonus positions. [Versioned speculation tests](https://github.com/vllm-project/vllm/blob/v0.32.0/tests/v1/spec_decode/test_mtp_structured_output.py) exercise grammar masking with xgrammar and guidance; they are not an end-to-end Nemotron/GB10 qualification. The [v0.32 xgrammar validator](https://github.com/vllm-project/vllm/blob/v0.32.0/vllm/v1/structured_output/backend_xgrammar.py) does not flag plain minItems/maxItems, integer enum, or plain minLength/maxLength among its unsupported combinations. Backend auto-selection remains the existing runtime default; this branch does not change serving flags.

Historical [issue #50924](https://github.com/vllm-project/vllm/issues/50924) describes a v0.26 DSpark/DeepSeek guided-output engine crash caused by tokenizer vocabulary-size overcount. [PR #51727](https://github.com/vllm-project/vllm/pull/51727), merged 2026-08-10, fixes DeepSeek V4/V3.2 tokenizers. This is relevant context, not evidence of a present Nemotron bug or proof that the exact current combination is safe.

Source-level structured-output support with speculative decoding is present. The exact pinned ARM64 vLLM0.32 + Nemotron hybrid Mamba + DSpark3 combination remains **unqualified** until the probes below pass. The runtime/image/model/draft/DSpark settings remain unchanged. No datacenter/model-general result substitutes for those probes.

## Admission and fixed qualification

Root must review and publish this separate branch/tag before any guided outcomes. Never merge or cherry-pick its Client changes into the active main/frozen sources. Original SEARCH_SELECTION and main harness stay untouched.

Only after all original Nemotron/core/program work and verified four-node drain, parent may manually admit exactly three prospective tiny probes:

1. A hand-authored cardinality-only n=24 schema with color enum (no graph edges or solver hint).
2. A hand-authored cardinality-only n=64 schema with color enum (no graph edges or solver hint).
3. The separate reviewer critique schema with minLength=1 and maxLength=4000.

Keep request/response/usage/finish reason/schema, image/model/draft pins, and before/after health/drain evidence. All probes must return within the existing bound, satisfy their schema, and leave the engine healthy/drained. These are API/format qualification only, not a CSP quality pilot. No extra probes, tuning, DSpark disabling, runtime changes, or schema relaxation after a failure. If any schema is unsupported or serving faults, label the feature unqualified and abort before the 84 cases. Root separately verifies this admission boundary; the existing original-study gate alone does not certify completion of later core/program work.

After successful qualification and explicit root admission, the future balanced plan is:

```sh
python3 run_csp_search.py --profile core_guided_off16 --split evaluation --seed 1 --gate-root /path/to/main/app
```

This command remains plan-only unless `--run` is explicitly supplied. Actual execution must use the published clean worktree/source pins and preserve all original data. Report this 84-case cohort as a posthoc format control with its own source and schema constraints; do not pool it with original unconstrained outcomes or describe differences as algorithm-only improvements.
