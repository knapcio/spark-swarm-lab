# Subtracting two columns gives a wrong total

We compute the net value of order lines as gross minus discount minus
shipping:

```python
from quarry import Engine

db = Engine()
db.run_script("CREATE TABLE lines (no INTEGER, gross INTEGER, discount INTEGER, shipping INTEGER);"
              "INSERT INTO lines VALUES (1, 1000, 100, 50), (2, 500, 0, 25)")
db.query("SELECT no, gross - discount - shipping AS net FROM lines")
```

Expected: `[(1, 850), (2, 475)]`.
Actual: `[(1, 950), (2, 525)]`.

`SELECT 12 / 2 * 3` also returns 2 instead of 18. Adding parentheses,
`(gross - discount) - shipping`, gives the right result. The README says
operators of equal precedence group from left to right.
