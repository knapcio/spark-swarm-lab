# Optional program-context reviewers: late exploratory arm

This isolated branch adds `review_elites4` to the existing program experiment;
it does not change its qualified container grader, graph data, model transport,
original author prompt, verified development fitness, source-freeze boundary or
original twelve-graph evaluation. No launch has occurred. Original program and
fresh-96 results are already known to operators: this is a late exploratory
protocol, not an untouched confirmation or a revision to those studies.

Each of four seeds owns one Spark and spends all sixteen calls with thinking
OFF, 2,048 output tokens per call, a 32,768 completion-token episode ceiling and
HTTP timeout 210 seconds. Ten calls produce programs; six produce plaintext
reviews. Realized token use and server cost remain separate measurements.

1. Generate four initial programs, then score each on the original four
   development graphs using the unchanged outer graph grader.
2. For each of three rounds, rank the current four by development graphs solved
   descending, exact conflict/error penalty ascending, then earliest candidate
   index. The third/fourth candidate contexts review the first/second.
3. Each reviewer sees its own and its target's complete source and development
   feedback, plus the four development graphs. These are stateless candidate
   contexts, not evidence of genuinely weaker persistent individuals. Critiques
   are unverified suggestions, bounded to 8,192 characters in repair prompts;
   the raw critique and truncation flag are retained. Empty critiques still
   consume their call and cause no retry or replacement author call.
4. Complete both review calls under the review-only system prompt, restore the
   original author system prompt, then make two repairs. Each repair receives
   its target's original author context plus its paired unverified critique.
   Complete both repair calls before serial development grading.
5. Retain the best four of the previous four and two repairs by the same rank.
   This retains current elites; discarded contexts are labeled not retained,
   never mathematically wrong. All ten candidates remain in the audit record.
6. After all sixteen calls, freeze the best of all ten by the unchanged rank.
   Grade all twelve original evaluation graphs once. No subsequent model calls,
   evaluation repair, reselection or hidden witness input is permitted.

Reviewer IDs, generation, source/target candidate IDs and hashes, review IDs,
repair parent IDs and population retention are logged. A review-stage parser
returns plaintext; author stages retain the existing AST-only source parser.
The shared per-client system prompt changes only between fully joined phases.
Parse failures/timeouts/wrong assignments retain their original candidate-failure
semantics; true transport, source or cleanup faults halt with partial evidence.

All four selected programs are eligible for a **separately labeled** fresh-96
followup, regardless of their original twelve-graph outcomes. This runner does
not run that followup or inject its graphs or outcomes into training. Existing
qualified grader/image pins and ten-second/256 MiB isolation are unchanged.

```sh
python3 program_search.py             # prints plan; no live gate, writes or calls
python3 -m unittest test_program_review_elites test_program_search -q
```

An eventual explicit `--run` requires a clean committed branch source, exact
source/data/config pins, the original verified 45-cohort and post-stage gates,
four idle endpoints, and root's explicit manual fresh exclusive admission.
If admitted, run this optional arm after late thinking-ON and complete owned
model/CPU drain, before unqualified structured-output probes that could fault
the shared Nemotron runtime. Its optional separately admitted384-grade CPU
confirmation would follow this arm and precede guided work. Mandatory DeepSeek
references/restoration retain priority; launch only if time remains. Nothing
auto-launches, and the original plans and stage schedules are not rewritten.
Token limits match the original program experiment; input contexts, candidate
count, review interaction and realized token use differ. No outcome or genuine
individual-intelligence advantage is claimed by this prospective branch.
