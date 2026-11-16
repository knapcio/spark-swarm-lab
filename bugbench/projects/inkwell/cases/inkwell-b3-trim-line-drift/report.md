# Error messages point at the wrong line

We render templates with `strict=True` so typos fail loudly. The error for a
misspelled variable points to the wrong line, and we lost time looking at
the wrong part of the template.

```python
from inkwell import Environment

INVOICE = (
    "<h1>Invoice {{ number }}</h1>\n"                                    # line 1
    "<table>\n"                                                          # line 2
    "{%- for line in lines %}\n"                                         # line 3
    "  <tr><td>{{ line.name }}</td><td>{{ line.qty }}</td></tr>\n"       # line 4
    "{%- endfor %}\n"                                                    # line 5
    "</table>\n"                                                         # line 6
    "<p>Total: {{ totl }}</p>\n"                                         # line 7 (typo)
)
env = Environment({"invoice": INVOICE}, strict=True)
env.render("invoice", number=17, lines=[{"name": "Tea", "qty": 2}], total=8)
```

Expected: `UndefinedError` with message `invoice, line 7: 'totl' is undefined`
(`.line == 7`).
Actual: `UndefinedError` with message `invoice, line 5: 'totl' is undefined`.

The rendered HTML is fine when the variable is spelled correctly. If we write
`{%` instead of `{%-` in lines 3 and 5, the error correctly says line 7, but
then the output has extra blank lines, which is why we use the dashes. Errors
in templates without dashes also show the right line.
