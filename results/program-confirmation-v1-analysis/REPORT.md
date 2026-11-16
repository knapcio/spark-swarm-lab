# Fresh-graph confirmation of eight frozen programs

All eight programs selected in the original experiment were evaluated unchanged on all 96 fresh graphs from the same planted generator: 768 CPU-only grades, zero additional model calls, no new training or repair. This confirms the behavior of these fixed source artifacts on this finite distribution; no GPU model weights were improved. The original 12-graph results remain [separate](../program-search-v1-analysis/REPORT.md).

| Method | Fresh graph/program outcomes solved | Accuracy | Crossed graph/training-seed 95% CI | Task-only 95% CI, conditional on frozen programs |
|---|---:|---:|---:|---:|
| Four independent program chains | 376/384 | 97.92% | 92.97–100.00% | 96.35–99.22% |
| Sequential program refinement | 237/384 | 61.72% | 21.35–90.10% | 57.03–66.15% |

Each arm has four paired training seeds. The 5,000-replicate bootstrap (seed 20261115) independently resamples graph tasks and paired training-seed labels, sharing draws across arms. The conditional interval fixes the eight trained programs; the crossed interval also reflects empirical training-seed variation. There are 96 graph tasks and four trained-program pairs, not 384 independent tasks per arm or 768 independent tasks overall.

The paired independent-minus-sequential accuracy difference is +36.20 percentage points, with a pointwise crossed interval +5.73 to +78.39 points. Four training seeds give limited evidence about new training episodes, even with more fresh graphs; this is not a universal method ranking.

## Results of each frozen program

| Training seed | Four independent program chains | Sequential program refinement |
|---|---:|---:|
| 1 | 88/96 | 87/96 |
| 2 | 96/96 | 0/96 |
| 3 | 96/96 | 83/96 |
| 4 | 96/96 | 67/96 |

Independent-program seeds 2, 3, and 4 each solve 96/96 of these graphs; seed 1 solves 88/96. Sequential programs solve 87, 0, 83, and 67 of 96 respectively. An all-pass empirical bootstrap for an individual frozen program can collapse to 100%–100%; it cannot establish a true 100% success probability, correctness on every graph, or performance outside this generator. The corpus contains eight fresh generation seeds across the same twelve factorial cells, with no claim of arbitrary graph hardness or universal solver correctness.

## Cost and grading scope

The original training cost is charged once for each of the eight selected programs: 128 model calls in total. Historical training server output is 69,935 tokens for independent chains and 100,120 for sequential refinement (64 calls per method), with full original server-counter coverage. These are references to already-spent training cost, not new inference charged again for each graph. Fresh confirmation makes zero model calls. It uses 768 additional fresh CPU containers/grades; its recorded full wall is 515.966 seconds including remote transport, container work, and cleanup. Remote solver CPU seconds remain unknown, not zero, and CPU grades are not equivalent to model calls.

Every one of the 768 outcomes has an explicit false infrastructure flag and successful cleanup. The exact original graph verifier independently replays 626 returned-assignment proofs: 613 pass and 13 violate graph constraints. The other 142 outcomes (125 candidate runtime errors and 17 candidate timeouts) remain unsolved in the denominator; no assignment proof is invented for them. All eight selected-source SHA values, graph hashes, child payload hashes, outer grading authority, complete unique grid, source-before/source-after identities, and four final health/drain receipts were checked. Astra independently audited the complete cohort before statistics ran.

No original raw inputs, frozen source files, methods, or graders were changed for this report. Small evidence files are byte copies; the manifest preserves original input/source/output SHA values. These fresh96 results do not replace or pool with the original12 outcomes.

- [Statistics and provenance JSON](fresh96/analysis.json), [CSV](fresh96/summary.csv), [paired contrasts](fresh96/paired-deltas.csv)
- [Crossed-interval PNG](fresh96/accuracy-crossed95.png), [SVG](fresh96/accuracy-crossed95.svg)
- [Byte-preserved evidence](evidence/), [independent audit](evidence/independent-audit.json), [hash manifest](manifest.json)
