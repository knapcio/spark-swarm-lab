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
