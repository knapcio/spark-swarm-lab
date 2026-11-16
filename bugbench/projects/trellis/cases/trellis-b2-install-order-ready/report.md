# Install plan does not follow alphabetical order

Our project depends on `web`, `auth` and `zip`. `web` needs `log`, and both
`log` and `auth` need `fmt`:

```python
from trellis import Workspace

index = "fmt 2.0.0\nlog 1.0.0: fmt *\nweb 1.0.0: log *\nauth 1.0.0: fmt *\nzip 1.0.0\n"
manifest = '[project]\nname = "shop"\n[dependencies]\nweb = "*"\nauth = "*"\nzip = "*"\n'
print(Workspace(index, manifest).install().order)
```

Expected: `['fmt', 'auth', 'log', 'web', 'zip']`. After `fmt`, both `auth` and
`zip` can be installed, and `auth` comes first alphabetically.
Actual: `['fmt', 'zip', 'auth', 'log', 'web']`.

Every package still comes after its dependencies, but the README says that
among the packages that are ready, the alphabetically first one goes next.
Our deployment tooling diffs install plans between machines, so the order
has to be the documented one.
