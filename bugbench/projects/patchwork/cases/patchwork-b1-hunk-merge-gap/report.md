# Two nearby changes come out as two hunks

We bumped two pins in a requirements file. Six unchanged lines separate the
two changes:

```python
from patchwork import PatchSet, diff_texts, summary

old = "".join(f"{name}\n" for name in ["click==8.1", "flask==3.0", "jinja2==3.1", "markupsafe==2.1", "pytest==8.2",
                                        "requests==2.32", "rich==13.7", "urllib3==2.2", "werkzeug==3.0", "zipp==3.19"])
new = old.replace("flask==3.0", "flask==3.1").replace("werkzeug==3.0", "werkzeug==3.1")
print(diff_texts(old, new, "requirements.txt"))
print(summary(PatchSet.diff({"r": old}, {"r": new}))["hunks"])
```

Expected: one hunk, `@@ -1,10 +1,10 @@`, covering the whole file, and a
hunk count of 1.
Actual: two hunks, `@@ -1,5 +1,5 @@` and `@@ -6,5 +6,5 @@`, and a hunk count
of 2.

The README says two changes share one hunk when at most 2 × context unchanged
lines separate them, and the default context is 3. With five unchanged lines
in between we get one hunk, and with seven we get two, as expected.
