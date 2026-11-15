# Coding: feedback sharing and final generalization

This second synthetic domain complements arithmetic; it does not establish
production coding performance. The authored corpus has six development and
18 evaluation functions, each with a specification and two public examples.
The separate reference file contains 177 feedback cases and 180 holdout cases.
Inputs are disjoint across public examples, feedback and holdout for every task.
Reference implementations generate expected values and are checked offline;
they are not an independent formal proof of the task specifications.

All workers receive the same public specification. Pure Python functions must
preserve their inputs and return the stated exact JSON-compatible types.
Candidate code runs only in an owned CPU-only Docker container, with no
network, GPU, host mounts or host credentials, and bounded time/resources.
This contains ordinary generated code; grading in the same interpreter is not
a claim of protection against deliberate grade-forgery attacks.

Policies include one proposal, iterative solo repair, independent private
repair tracks, a shared verified-feedback board, and semantic review/voting.
All iterative policies can receive failures from feedback tests. Shared memory
contains at most four verified feedback observations and a selected repair
base. Identical code/phase results can reuse a common grading cache; transient
timeouts and infrastructure errors are not cached.

Direct/independent/shared policies select the first candidate passing feedback,
or their best feedback-scored candidate when the search ends. Democracy grades
the complete round, reviews a shortlist of at most four unique candidates and
uses a separate model vote before choosing. Passing feedback is not a proof of
general correctness, so coding democracy still reviews passing candidates.

Selection is frozen before exactly one holdout grade. No candidate is repaired
or replaced using holdout results; private scores/cases are not voting inputs.
The reported success means passing this finite holdout set, not all possible
inputs. Public traces later expose the audit trail, including negative cases.

Initial development uses JSON-wrapped code. A separate calibration compares
raw/fenced Python output because a JSON newline-escaping failure is an output
format failure, not evidence that the model cannot implement the function.
Raw mode strips only optional fences; it never rewrites source backslashes.
Votes retain their JSON interface in both formats.

Each development case has a 180-second controller deadline, at most 1,024 model
calls and 131,072 completion tokens. Off-mode responses allow 1,024 tokens;
the separate thinking baseline allows 8,192. Four fixed job slots pair one
model endpoint with one grader host. Queue wall time and per-case latency are
different measurements. Pending model work is aborted after selection and
grading; missing client usage is not zero cost. Input/output usage, server
counters, grading/cache counts, failures and source/data hashes are retained.

Choose settings on development data and freeze them before evaluation. Keep
format/calibration cohorts separate; no published claim should conflate
feedback pass rate with heldout correctness or synthetic tasks with broad
software engineering ability.

## CPU grader environment amendment — 2026-11-15

Before any runtime-v2 primary model calls, the CPU-only grader image changed from the large vLLM v0.27.1 image to pinned ARM64 `python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd`. The [CPU grader amendment](CPU_GRADER_AMENDMENT.json) records the reason, source hashes and environment change. The actual coding grader source changes exactly one `IMAGE` constant; the stdlib grading logic, isolation flags, model policies, prompts, budgets and corpora remain unchanged. An independent git-blob/hash check is recorded in the [curation audit](results/cpu-grader-20261115/validation-audit.json).

| Environment | Previous grader | Replacement grader |
|---|---|---|
| Python | 3.12.13 | 3.12.16 |
| Compiler recorded in Python | GCC 11.4.0 | GCC 14.2.0 |
| C library | glibc 2.35 | glibc 2.41 |
| Execution | CPU-only, isolated stdlib | CPU-only, isolated stdlib |

The [validation receipt](results/cpu-grader-20261115/cpu-python-grader-validation.json) records **357/357 trusted-reference test cases in 48 phase containers**, covering feedback and holdout phases for all 24 authored functions. Three additional smoke containers exercise a correct function, timeout classification and kernel-confirmed OOM classification (`OOMKilled:true`, exit 137). Each produces its expected result/classification, with `infrastructure:false` and successful cleanup. All **51 grading-container commands** retain `runc`, no network/GPU/host mounts, read-only filesystem, dropped capabilities, no-new-privileges, PID 64, memory/no-swap 256 MiB, one CPU, unprivileged UID/GID, bounded tmpfs and Python `-I -S`. The pinned ARM64 image was pulled on four nodes and the final task-owned container lists are empty on all four.

This is finite trusted-corpus conformance and isolation validation, **not universal equivalence across Python/compiler/libc versions or a model coding-success score**. The model-call count for these checks is zero. Actual coding jobs use the new image; arithmetic-only snapshots may retain an unused historical grader file for byte identity. Source pins identify those differences explicitly.

### Preserved trusted-reference invocation failure

The [initial diagnostic receipt](results/cpu-grader-20261115/cpu-python-grader-reference-import-diagnostic.json) remains `verified:false`, including all 11 phase reports and its `NameError: name 're' is not defined`. The first validation invocation submitted function-only trusted fragments without their existing module globals. Correcting that invocation supplied only the reference module's existing `import re` and `from collections import Counter`, then reran all 48 phase batches. Reference function bodies, test cases and model-generated source were not edited, and the grader was not relaxed to hide the failure. The [manifest](results/cpu-grader-20261115/manifest.json) preserves original/export hashes and the exact path normalizations for both receipts.

All **900 primary and 80 supplementary solo attempts** run fresh under the amended uniform environment; previous runtime-v1/partial rows remain separate. Runtime-v2.1 source tags are `evaluation-runtime-v2.1` (`cbcde299`), `solo-control-runtime-v2.1` (`a8adff19`) and `throughput-runtime-v2.1` (`47bba9f0`). Model generation remains gated on independent four-replica readiness and source checks.
