# patchwork

A small diff and patch toolkit: texts with final-newline tracking, a line
diff based on the longest common subsequence, hunks with context, the
unified diff format, fuzzy and reverse patch application, multi-file patch
sets over file trees, three-way merges and diffstat. Standard library only,
Python 3.10+.

```python
from patchwork import PatchSet, diffstat

old = {"app.ini": "[server]\nport = 8080\nworkers = 4\n"}
new = {"app.ini": "[server]\nport = 8080\nworkers = 8\n"}
patch = PatchSet.diff(old, new)
print(patch)                      # unified diff text
print("\n".join(diffstat(patch)))
result = PatchSet.parse(str(patch)).apply(old)
print(result.tree == new, result.log)
```

## Modules

| Module | Responsibility |
|---|---|
| `text.py` | `Text`: lines plus final-newline flag, whitespace-insensitive comparison |
| `lcs.py` | Longest common subsequence, edit script (`opcodes`), similarity |
| `hunks.py` | `Hunk`, grouping changes into hunks with context, reversing and trimming hunks |
| `unified.py` | `FilePatch`, writing and parsing the unified diff format |
| `apply.py` | Applying hunks: offset search, fuzz, reverse, partial application |
| `patchset.py` | `PatchSet`: multi-file patches, diffing and patching file trees |
| `merge.py` | Three-way merge with conflict markers |
| `stats.py` | diffstat lines, summaries, churn |
| `errors.py` | Exception hierarchy |

## Rules

- A text is a list of lines plus whether it ends with a newline. The empty
  string has no lines. A last line without a newline never equals the same
  line with a newline, so such a change shows up as a changed last line.
- Diff: among equally long common subsequences the edit script matches
  equal lines as early as possible and prefers deleting to inserting.
  Inside a hunk, deleted lines come before inserted lines.
- Hunks: each change gets up to `context` (default 3) unchanged lines on
  each side. Two changes share one hunk when at most `2 × context`
  unchanged lines separate them; with more, they get separate hunks.
- Unified format: `@@ -l,s +l,s @@`. A count of 1 is omitted, and an
  omitted count means 1. For a count of 0, `l` is the line after which the
  change goes (0 = top of file). `\ No newline at end of file` refers to the
  line before it: after a context line, both the old and the new file end
  without a newline; after a `-` line only the old file, after a `+` line
  only the new file. Path lines lose one leading component (`a/`, `b/`);
  `/dev/null` means "no file".
- Applying: hunks apply in order. Each hunk is searched for nearest to its
  expected position (its header position, shifted by the size changes of
  the earlier hunks and by the previous hunk's offset), the earlier position
  first on equal distance, never before the end of the previous hunk. If it
  is not found, it is retried with fuzz 1, then 2 (default maximum): fuzz
  `k` ignores up to `k` context lines at each end of the hunk. The reported
  offset is the placed position minus the expected position without the
  previous hunk's offset; the reported line is the 1-based line where the
  first remaining hunk line was placed.
- The patched file ends with a newline like the original unless a hunk
  reached the end of the file; then the patch decides.
- Applying never modifies the input text, the hunks or the patch set: one
  patch set can be applied to any number of trees, in any order, with the
  same results.
- A patch set applies all or nothing; the input tree dict is never changed.
- Three-way merge: regions changed on one side take that side; identical
  changes are taken once; different changes become a conflict with
  `<<<<<<< ours`, `=======`, `>>>>>>> theirs` markers.
- diffstat: one line per file, bars scaled to `width` (rounding down, at
  least one character per non-zero part), then a summary line.

Run the tests with `python -m unittest discover -s tests`.
