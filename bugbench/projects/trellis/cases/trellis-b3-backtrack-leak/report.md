# Resolution fails although an older release would work

Our project needs `ui` (any version) and `theme ^1`. `ui 1.1.0` requires
`theme ^2`, but `ui 1.0.0` works with `theme ^1`:

```python
from trellis import Workspace

index = "ui 1.1.0: theme ^2\nui 1.0.0: theme ^1\ntheme 1.0.0\ntheme 1.1.0\ntheme 1.2.0\ntheme 2.0.0\n"
manifest = '[project]\nname = "shop"\n[dependencies]\nui = "*"\ntheme = "^1"\n'
print(Workspace(index, manifest).install().lock)
```

Expected: a lock with `theme 1.2.0` and `ui 1.0.0`.
Actual: `ResolutionImpossible` with

```
no version of theme satisfies all requirements:
  shop requires theme >=1.0.0, <2.0.0
  ui 1.1.0 requires theme >=2.0.0, <3.0.0
```

If we pin `ui = "1.0.0"` in the manifest, the same index resolves fine. The
README says the resolver backtracks on conflicts and that an abandoned choice
must not leave any requirement behind. We also see older versions picked
than necessary in other projects after the resolver has backtracked.
