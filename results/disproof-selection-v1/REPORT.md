# Executable-disproof code selection (astra idea #1)

Plan `DISPROOF_PLAN.json` (frozen in a06eff6 before any contract call on evaluation tasks; amendment 1 adds the Inkling
resume run to the candidate set before any selection). Runner `disproof_select.py`.

For each of the 72 coding cases (24 evaluation tasks x 3 seeds), Inkling-2-Mini saw only the PUBLIC task (spec, function
name, examples) and wrote an executable contract: 20-30 test inputs plus `check(args, out)`, which returns False only when
an output certainly violates the specification (most contracts carry a brute-force reference). A contract is used only if,
in the pinned CPU sandbox, it loads, yields inputs of the right arity and accepts every public example. Every candidate
that passed the public feedback cases is executed on the contract inputs; a candidate is disproved if check() returns
False on any of them. Frozen rule: earliest non-disproved feedback-passing candidate; fallback to the original rule
(earliest feedback-passing) when the contract is invalid or disproves everyone. Hidden holdout results score afterwards.

Contracts: 62/72 valid (3 no code, 3 inputs unavailable, 3 rejected a public example, 1 wrong arity), 13.3K completion
tokens per contract, no infrastructure faults.

| Selector (72 cases, k = 8 agents) | Inkling candidates | Nemotron candidates |
|---|---:|---:|
| First agent passing the public feedback cases (original rule) | 69 | 56 |
| Agent-written test inputs, majority vote of outputs (CX, earlier) | | 55 |
| Nemotron judge on concrete disagreements (earlier) | | 57 |
| **Executable disproof (this study)** | **70** | **59** |
| Oracle: some agent right | 71 | 64 |
| Wrong candidates disproved / correct candidates disproved | 1 / 12 | 19 / 7 |

At k = 4: Inkling 68 -> 69 (oracle 70), Nemotron 51 -> 54 (oracle 59).

Reading: executable disproofs are the best arbiter-free selector measured so far on this coding set. On Nemotron candidates
they recover 3 of the 8 cases lost to selection (56 -> 59), more than the judge (57) or output voting (55). On Inkling the
original rule already loses only 2 cases; disproofs recover one. Contracts also disprove correct programs (12 for Inkling,
7 for Nemotron), harmless here because another candidate survived, but a contract can be wrong. The Nemotron column uses
Inkling-written contracts (a different model from the one that wrote the code), so it is a cross-model result.
