# Published study evidence — 15–16 November 2026

[GitHub release](https://github.com/knapcio/spark-swarm-lab/releases/tag/study-20261116) · [archive](https://github.com/knapcio/spark-swarm-lab/releases/download/study-20261116/swarm-lab-evidence-20261116.tar.gz) · [checksums](https://github.com/knapcio/spark-swarm-lab/releases/download/study-20261116/SHA256SUMS.txt)

The archive contains 16,826 regular files and 225 directories: 16,820 approved evidence inputs plus six curation/README files. It is **85,944,158 bytes** compressed, representing 794,637,895 bytes of approved source inputs plus curation and tar overhead. Some curated exports deliberately duplicate canonical evidence.

Archive SHA-256:

```text
56fc3424b39bc401b600253316a00affeae8d5125aedc04447a10099d52f99c9
```

The release also provides FILES_MANIFEST.json, STAGED_MANIFEST.json, ARCHIVE_VERIFICATION.json and INDEPENDENT_READBACK.json. SHA256SUMS.txt covers the archive and these four files. A fresh separate process checked every archived member's size and hash, the exact file/directory lists, safe relative paths, and complete gzip CRC/EOF. There are no symlinks, hard links or device entries.

## Included evidence

- All valid primary/supplemental Nemotron cohorts and corrected loaded queues; canonical ledgers, costs and raw traces.
- Independent coding confirmation, direct-assignment graph studies, classical controls and late reasoning-enabled graph results.
- Original reusable-program search, prospective additional-graph confirmation, and the separate late reviewer variant/confirmation.
- The final 126-case native DeepSeek reference, development interoperability records, independently audited scores and qualified runtime provenance.
- Frozen protocol/data/source snapshots and explicit orchestration helpers, source refs, verifier qualifications, audited reports, plots and real lineages.
- Sanitized Opus-unavailability evidence, the failed two-call guided-format qualification, and GLM-not-run preparation records. These are not quality scores. The first Opus invocation's usage is unknown.

Model weights, caches, credentials, authentication-state files and historical invalid cohort raw directories are excluded. Instrumentation exclusions remain documented and their original diagnostics are retained in the study workspace. Every proposed archive file passed a heuristic content-pattern scan and explicit path/source review; the scan scope and limitations are recorded inside the archive.

## Integrity and reproduction

Download all six assets into one directory, then verify the five checksummed files. For example, on macOS:

```sh
gh release download study-20261116 --repo knapcio/spark-swarm-lab --dir evidence
cd evidence
shasum -a 256 -c SHA256SUMS.txt
```

Canonical bytes are preserved. FILES_MANIFEST.json maps original local provenance paths to archive paths and hashes. Those absolute workstation paths and captured commands describe the original environment; they are not portable launch instructions. The study source/results snapshot is Git commit `6a95f4a9a947cdc63d1bbeee1a4a526bd26b5cf3`, tag `study-20261116`. Later availability documentation can differ on main without changing that snapshot.

See [REPRODUCING.md](REPRODUCING.md) for evidence-only analysis and endpoint requirements. The documented additional-graph replay passed from a fresh historical checkout, checking all 768 stored grades and recomputing the bootstrap without executing candidate programs. [Smoke evidence](results/public-reproduction-smoke-20261116/README.md). Complete original orchestration remains study-bound; no fake admission gates are supplied.

A matching checksum detects changed bytes; it is not a signature or a proof of model correctness. Arithmetic uses exact transition proofs. Coding uses finite tests and a qualified outer-parent boundary with the limitations in [CORRECTNESS_AUDIT.md](CORRECTNESS_AUDIT.md). The native checkpoint identity is corroborated by runtime metadata and executable hashes; full weight hashing and complete source-to-binary reproduction were not performed.
