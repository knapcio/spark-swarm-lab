# Retrying a failed INSERT reports a duplicate key for rows that do not exist

We load orders in batches. One batch had a typo in its third row and was
rejected, as it should be. After fixing the typo, the same INSERT fails
again, now with `DuplicateKey`:

```python
from quarry import Engine

db = Engine()
db.execute("CREATE TABLE orders (no INTEGER PRIMARY KEY, product INTEGER, qty INTEGER, city TEXT)")
db.execute("INSERT INTO orders VALUES (7, 10, 1, 'Lodz'), (8, 11, 2, 'Lodz'), (9, 12, 'three', 'Lodz')")
# -> TypeMismatch (correct)
db.execute("INSERT INTO orders VALUES (7, 10, 1, 'Lodz'), (8, 11, 2, 'Lodz'), (9, 12, 3, 'Lodz')")
```

Expected: the second INSERT adds 3 rows.
Actual: it raises `DuplicateKey`, and `SELECT COUNT(*) FROM orders` is 0, so
the orders 7 and 8 are not in the table.

When the very first row of a batch is rejected, the retry works. The README
says a failed statement changes nothing and later statements behave as if it
had never run.
