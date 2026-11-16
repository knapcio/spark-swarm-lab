# trellis

A small package manager core: semantic versions, version constraints, a
registry index, project manifests, a backtracking dependency resolver with
lock files, install order, dependency trees and lock checks. Standard
library only, Python 3.10+.

```python
from trellis import Workspace

index = """
web 2.3.0: fmt ^2.0; log >=1.0, <2
web 2.1.0: fmt ^1.5
fmt 2.0.1
fmt 1.6.0
log 1.4.2: fmt ^2.0
"""
manifest = '[project]\nname = "shop"\n[dependencies]\nweb = "^2.1"\n'
plan = Workspace(index, manifest).install()
print(plan.lock, plan.order)
```

## Modules

| Module | Responsibility |
|---|---|
| `version.py` | `Version` parsing and ordering, pre-release identifiers |
| `constraint.py` | Constraint syntax (`^`, `~`, wildcards, comparators, `,` and `||`), pre-release rule |
| `registry.py` | Releases, yanked releases, the index text format |
| `manifest.py` | Project manifests with dependency and dev-dependency sections |
| `resolver.py` | Backtracking resolver, lock preference, dead-end explanations |
| `graph.py` | Install order, tree view, "why" paths, reverse dependencies |
| `lockfile.py` | Lock file format, lock checks, lock differences |
| `workspace.py` | `Workspace`: install, update, check, outdated |
| `errors.py` | Exception hierarchy |

## Rules

- Versions are `MAJOR.MINOR.PATCH[-pre.release]`. A pre-release sorts before
  its release; numeric pre-release identifiers compare as numbers.
- Caret constraints allow changes that do not modify the left-most non-zero
  part: `^1.2.3` is `>=1.2.3, <2.0.0`, `^0.2.3` is `>=0.2.3, <0.3.0` and
  `^0.0.3` is `>=0.0.3, <0.0.4`. Tilde allows patch changes: `~1.2.3` is
  `>=1.2.3, <1.3.0`. A comma means "and", `||` means "or".
- A pre-release is only allowed by a constraint part that itself names a
  pre-release of the same `MAJOR.MINOR.PATCH`.
- The resolver picks one package at a time (fewest remaining candidates
  first, ties alphabetical) and tries its versions newest first, a still
  allowed locked version before all others. Yanked releases are only used
  when locked. On a conflict it backtracks; an abandoned choice must not
  leave any requirement behind.
- Install order: every package after its dependencies; among the packages
  that are ready, alphabetical order.
- Lock files list one pinned version per package, sorted by name.

Run the tests with `python -m unittest discover -s tests`.
