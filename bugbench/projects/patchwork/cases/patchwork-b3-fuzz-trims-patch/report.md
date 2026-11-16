# The same patch changes the wrong section on the second checkout

Our deploy script parses one patch and applies it to several checkouts of
`app.ini`. The patch raises the `[server]` timeout:

```python
from patchwork import PatchSet

cfg = ("[client]\ntimeout = 30\nretries = 2\n[server]\nhost = 0.0.0.0\nport = 8080\ntimeout = 30\n"
       "workers = 4\nlog = info\ncache = on\n")
patch = PatchSet.parse("--- a/app.ini\n+++ b/app.ini\n@@ -4,7 +4,7 @@\n [server]\n host = 0.0.0.0\n port = 8080\n"
                       "-timeout = 30\n+timeout = 60\n workers = 4\n log = info\n cache = on\n")
first = patch.apply({"app.ini": cfg.replace("host = 0.0.0.0", "host = 10.0.0.5")})   # locally edited checkout
second = patch.apply({"app.ini": cfg})                                                 # pristine checkout
print(first.log[1], second.log[1])
print(second.tree["app.ini"])
```

Expected: the first checkout logs `hunk 1 applied at line 6 (fuzz 2)` (its
`host` line differs, so two context lines at each end are ignored), and the
pristine checkout logs `hunk 1 applied at line 4` and gets `timeout = 60` in
the `[server]` section.

Actual: the first checkout logs `hunk 1 applied at line 7 (offset +1, fuzz 2)`
(its content is right). The pristine checkout logs
`hunk 1 applied at line 2 (offset -2)`: the `[client]` section now says
`timeout = 60`, and the `[server]` section still says `timeout = 30`.

A run with only the pristine checkout patches the `[server]` section as
expected. The README says one patch set can be applied to any number of
trees, in any order, with the same results.
