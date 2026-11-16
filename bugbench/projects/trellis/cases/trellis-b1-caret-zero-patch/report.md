# Caret on a 0.0.x version lets newer patch releases in

Our `web` package depends on `tiny ^0.0.3`. The registry has tiny 0.0.3,
0.0.4 and 0.0.9:

```python
from trellis import Constraint, Workspace

index = "tiny 0.0.3\ntiny 0.0.4\ntiny 0.0.9\nweb 1.0.0: tiny ^0.0.3\n"
manifest = '[project]\nname = "shop"\n[dependencies]\nweb = "^1"\n'
print(Workspace(index, manifest).install().lock)
print(Constraint.parse("^0.0.3"))
```

Expected: the lock pins `tiny 0.0.3`, and the constraint prints as
`>=0.0.3, <0.0.4`.
Actual: the lock pins `tiny 0.0.9`, and the constraint prints as
`>=0.0.3, <0.1.0`.

The README says `^0.0.3` is `>=0.0.3, <0.0.4`. `^0.2.3` and `^1.2.3` give the
documented ranges.
