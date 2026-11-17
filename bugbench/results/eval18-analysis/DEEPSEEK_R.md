# bugbench evaluation: DeepSeek whole-repo reference (policy R)

Same 18 frozen evaluation cases x 2 seeds as the Nemotron policies (bugbench/EVAL_PLAN.json). DeepSeek V4.1 (native TP4, default effort, 32K completion cap) receives the WHOLE agent-visible bundle in one prompt (~15-20K tokens), returns a full-file patch, runs the public self-check, and gets at most one repair call. One hidden grade per attempt. Plan bugbench/DEEPSEEK_R_PLAN.json frozen before any DeepSeek call.

| Policy | Fixed / 36 | Mean model calls | Mean completion tokens |
|---|---:|---:|---:|
| **DeepSeek R (whole repo, 1 call + optional repair)** | **36** | 1.0 | 2,786 |
| Nemotron V3 (8 navigators + model reviewer) | 28 | 38.3 | 122,233 |
| Nemotron S3 (8 navigators + vote) | 26 | 36.6 | 116,996 |
| Nemotron T3 (8 test-first agents) | 26 | 59.0 | 210,592 |
| Nemotron S1 (single navigator) | 18 | 4.8 | 15,888 |

Repairs used: 0/36. Mean prompt tokens per attempt: 17,886.

Reading: with the whole project in context, one DeepSeek call fixes every planted bug, including the three that no Nemotron policy fixed. Nemotron's 16K context forces it to navigate the project file by file; its swarms recover much of the gap (50% -> 78%) without any arbiter, but not all of it. Bundled comparison: model, context length and serving differ.
