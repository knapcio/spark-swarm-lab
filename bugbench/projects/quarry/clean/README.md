# quarry

A small SQL engine over in-memory tables: a tokenizer, a statement parser
with operator precedence, typed tables with NOT NULL and primary keys,
joins, three-valued logic, grouping and aggregates, ordering, limits and
plain-text result tables. Standard library only, Python 3.10+.

```python
from quarry import Engine, format_result

db = Engine()
db.run_script("""
    CREATE TABLE items (sku TEXT PRIMARY KEY, name TEXT NOT NULL, price REAL, stock INTEGER);
    INSERT INTO items VALUES ('A-1', 'Tea', 4.5, 10), ('A-2', 'Coffee', 9.0, 0), ('A-3', 'Cocoa', NULL, 3);
""")
print(format_result(db.execute("SELECT name, price * stock AS worth FROM items WHERE stock > 0 ORDER BY name")))
```

## Modules

| Module | Responsibility |
|---|---|
| `lexer.py` | Tokens, keywords, string escapes, comments, splitting scripts on `;` |
| `parser.py` | Statements and the precedence-climbing expression parser |
| `expr.py` | Expression nodes, column scopes, compilation, three-valued logic, canonical text |
| `functions.py` | Scalar functions and aggregates |
| `values.py` | Types, comparison, arithmetic, NULL handling, sort keys, value text |
| `table.py` | Typed tables, constraints, primary key index, catalog |
| `planner.py` | SELECT: joins, filters, grouping, ordering, distinct, limits |
| `engine.py` | `Engine`, statement execution, scripts, result tables |
| `errors.py` | Exception hierarchy |

## Language rules

- Statements: `CREATE TABLE`, `DROP TABLE`, `INSERT INTO ... [(cols)] VALUES
  (...), ...`, `UPDATE ... SET ... [WHERE]`, `DELETE FROM ... [WHERE]` and
  `SELECT [DISTINCT] ... [FROM t [JOIN|LEFT JOIN u ON ...]] [WHERE] [GROUP
  BY] [HAVING] [ORDER BY ... [ASC|DESC]] [LIMIT n [OFFSET m]]`.
- Precedence, loosest first: `OR`, `AND`, `NOT`, comparisons (`= <> != < <=
  > >=`, `IS [NOT] NULL`, `[NOT] IN`, `[NOT] BETWEEN`, `[NOT] LIKE`), `||`,
  `+ -`, `* / %`, unary `-`. Operators of equal precedence group from left to
  right: `10 - 4 - 3` is 3 and `12 / 2 * 3` is 18.
- Integer division truncates toward zero; dividing by zero gives NULL.
  Operators and functions return NULL for NULL operands. `NULL AND FALSE` is
  FALSE and `NULL OR TRUE` is TRUE. WHERE, ON and HAVING keep only rows whose
  condition is TRUE.
- Without ORDER BY, rows come back in insertion order (joins: left row order,
  then right row order; groups: order of their first row).
- ORDER BY sorts NULL first in ascending order and last in descending order.
  Sorting is stable: rows that tie on all ORDER BY items keep their previous
  order, whether the order is ascending or descending.
- A primary key is unique and NOT NULL. `INSERT`, `UPDATE` and `DELETE` are
  atomic: if any row is rejected, the statement changes nothing, and a later
  statement behaves exactly as if the failed one had never run.

Run the tests with `python -m unittest discover -s tests`.
