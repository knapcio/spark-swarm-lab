| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Reviewer contexts (late exploratory) | 47/48 | 97.9% | 87.5%–100.0% |

Training is charged once per frozen program, separate from graph evaluation.

| Method | Model calls | Client prompt / completion | Known server completion | Coverage |
|---|---:|---:|---:|---:|
| Reviewer contexts (late exploratory) | 64 | 290793 / 66718 | 66718 | 4/4 |

Late exploratory program-context reviewers;4training seeds; original12 and operator-known96 reported separately. Task-only CI conditions on frozen programs; crossed CI resamples graph and training-seed labels, limited by4seeds. No randomized isolated reviewer-effect claim, no pooling and no generic100% guarantee. Critiques are unverified; absence from population is not mathematical failure. Training64calls charged once, not per graph; no remote solver CPU measurement. No wire-level prompt capture.

Historical independent4 context is separate, not a randomized isolated comparison. Original12:47/48; known96:376/384;64training calls,247144input/69935output. Review training:290793input/66718output; four-node fleet214.8215565s includes3qualification containers and drain.188episode containers+3qualification;20parse skips were not executed. No remote CPU time measured.
