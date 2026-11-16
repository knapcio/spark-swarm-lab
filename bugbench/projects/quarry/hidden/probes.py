"""Hidden behavioural probes for the quarry project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY a41c7e93-bugbench-quarry-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _try(db, sql):
    try:
        result = db.execute(sql)
    except Exception as exc:  # observation only
        return ["error", type(exc).__name__]
    return [result.columns, [list(row) for row in result.rows], result.rowcount]


SHOP = """
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT, price REAL, stock INTEGER, active BOOLEAN);
INSERT INTO products VALUES
  (10, 'Kettle', 'kitchen', 89.99, 12, TRUE), (11, 'Toaster', 'kitchen', 129.5, 0, TRUE),
  (12, 'Lamp', 'living', 45.0, 30, FALSE), (13, 'Rug', 'living', NULL, 4, TRUE),
  (14, 'Fork set', NULL, 19.9, 100, TRUE), (15, 'Mug', 'kitchen', 7.25, 250, NULL);
CREATE TABLE orders (no INTEGER PRIMARY KEY, product INTEGER, qty INTEGER, city TEXT);
INSERT INTO orders VALUES (1, 10, 2, 'Lodz'), (2, 12, 1, 'Gdansk'), (3, 10, 1, 'Gdansk'), (4, 99, 5, 'Lodz'),
  (5, 15, 6, NULL), (6, 13, 1, 'Krakow');
"""


def _shop():
    from quarry import Engine
    db = Engine()
    db.run_script(SHOP)
    return db


# --- lexer, parser, canonical text ----------------------------------------------------
def probe_lexer_tokens():
    from quarry.lexer import split_statements, tokenize
    text = "select A_1, 'x''y' || '', 007, 3.25, a.b<>c != d <= e >= f -- tail ; 'q'\n* / % + - (;)"
    out = [[[t.kind, t.value, t.position] for t in tokenize(text)]]
    out.append([_error(tokenize, bad) for bad in ("'abc", "a # b", "a ! b", "3.", 12)])
    out.append([[t.kind, t.value] for t in tokenize("3.x .5 1e2")])
    out.append(split_statements("a; 'x;y' ; -- c;d\n b;;  ;c ''';'''"))
    out.append([[t.kind, t.value] for t in tokenize("x = 42")] + [[t.kind, t.value] for t in tokenize("y = 4.5")])
    return out


def probe_parse_errors():
    from quarry import parse
    out = []
    for sql in ("SELEC 1", "SELECT", "SELECT 1 +", "SELECT (1", "SELECT 1 FROM", "SELECT a FROM t WHERE", "SELECT 1 2 3",
                "SELECT a FROM t ORDER a", "SELECT a FROM t LIMIT x", "SELECT a FROM t LIMIT 1 OFFSET", "CREATE TABLE t (a BLOB)",
                "CREATE TABLE t (a INTEGER NOT)", "INSERT t VALUES (1)", "INSERT INTO t VALUES 1", "UPDATE t a = 1",
                "DELETE t", "DROP t", "SELECT a NOT 3 FROM t", "SELECT a IS 3", "SELECT x BETWEEN 1 OR 2", "SELECT f(1,)",
                "SELECT 1; SELECT 2", "SELECT a FROM t JOIN u", "SELECT a FROM t JOIN u ON", "SELECT 1 '+' 2"):
        try:
            parse(sql)
            out.append(None)
        except Exception as exc:  # observation only
            out.append([type(exc).__name__, getattr(exc, "position", None)])
    statement = parse("select distinct a as x, b y, t.* from t as q left join u on q.a = u.a join v w on TRUE "
                      "where a > 1 group by a, b having count(*) > 1 order by 1 desc, y limit 5 offset 2;")
    out.append([statement.distinct, statement.table, len(statement.joins), [j[2] for j in statement.joins],
                [alias for _, alias in statement.items], statement.limit, statement.offset, [d for _, d in statement.order_by]])
    return out


def probe_explain_canonical():
    from quarry import explain
    return explain("SELECT NOT a, -b, -(b + c), a + b * c, (a + b) * c, a * (b + c), a - (b + c), a || 'it''s', "
                   "x IS NOT NULL, x NOT IN (1, 2.5, NULL), x NOT BETWEEN 1 AND 2, x LIKE '%a_', NOT (x = 1 OR y = 2), "
                   "TRUE, FALSE, t.c, COUNT(*), count(DISTINCT x), coalesce(a, b, 3), a = b, a <= b AND c <> d OR e, "
                   "(a OR b) AND c, x IS NULL, -x * y, - - 3, a / (b * c), a + b + c, a * b * c") + \
        explain("SELECT a + (b + c), a - b * c, a + (b - c), a * (b * c), a || (b || c), a = (b = c), *, t.* FROM t")


# --- values, expressions, functions -----------------------------------------------------
def probe_values_direct():
    from quarry.values import arithmetic, coerce, compare, render, sort_key, truth, type_name
    out = [[type_name(v) for v in (None, True, 3, 2.5, "x")], _error(type_name, [1]),
           [arithmetic(op, 7, 2) for op in ("+", "-", "*", "/", "%", "||")], [arithmetic("/", a, b) for a, b in ((-7, 2), (7, -2), (-7, -2), (6, 3))],
           [arithmetic("%", a, b) for a, b in ((-7, 3), (7, -3), (7, 0))], arithmetic("/", 7.0, 2), arithmetic("+", None, 1),
           arithmetic("||", True, 2.5), [_error(arithmetic, op, "a", 1) for op in ("+", "%")], _error(arithmetic, "%", 7.5, 2),
           _error(arithmetic, "^", 1, 2), [compare(a, b) for a, b in ((1, 2), (2, 2.0), ("b", "a"), (False, True), (None, 1))],
           [_error(compare, a, b) for a, b in ((1, "1"), (True, 1))], [coerce(3, "REAL"), coerce(None, "INTEGER"), coerce("x", "TEXT")],
           [_error(coerce, v, t) for v, t in ((True, "INTEGER"), (1.5, "INTEGER"), (1, "TEXT"), (1, "BOOLEAN"))],
           [render(v) for v in (None, True, False, 2.0, 2.5, 1 / 3, -4, "s")], truth(None), truth(False), _error(truth, 1),
           sorted([3, None, 1.5, -2], key=sort_key), sorted(["b", None, "a"], key=sort_key)]
    return out


def probe_select_constants():
    from quarry import Engine
    db = Engine()
    return [db.query("SELECT 2 + 3, 2 * 3.5, 9 / 2, 9.0 / 2, -9 / 2, 9 % 4, -9 % 4, 5 / 0, 5 % 0, 'a' || 'b' || 1 || TRUE"),
            db.query("SELECT NULL + 1, -NULL, 1 < 2.5, 'abc' < 'abd', TRUE > FALSE, 2 = 2.0, 3 <> 3, 4 != 5, (1 + 2) * (3 + 4)"),
            [_try(db, sql) for sql in ("SELECT 1 < 'a'", "SELECT -'a'", "SELECT TRUE + 1", "SELECT NOT 1", "SELECT x")],
            db.execute("SELECT 1 AS one, 2 two, 1 + 1").columns]


def probe_three_valued_logic():
    from quarry import Engine
    db = Engine()
    db.run_script("CREATE TABLE v (b BOOLEAN); INSERT INTO v VALUES (TRUE), (FALSE), (NULL)")
    return [db.query("SELECT x.b, y.b, x.b AND y.b, x.b OR y.b FROM v x JOIN v y ON TRUE"),
            db.query("SELECT b, NOT b, b IS NULL, b IS NOT NULL, b = TRUE FROM v"),
            db.query("SELECT COUNT(*) FROM v WHERE b"), db.query("SELECT COUNT(*) FROM v WHERE NOT b"),
            db.query("SELECT COUNT(*) FROM v WHERE b OR b IS NULL"), _try(db, "SELECT 1 AND TRUE"), _try(db, "SELECT b FROM v WHERE 1")]


def probe_in_between_like():
    from quarry import Engine
    db = Engine()
    return [db.query("SELECT 2 IN (1, 2), 3 IN (1, 2), 3 IN (1, NULL), 1 IN (1, NULL), NULL IN (1), 3 NOT IN (1, 2), "
                     "3 NOT IN (1, NULL), 2.0 IN (2)"),
            db.query("SELECT 5 BETWEEN 1 AND 5, 0 BETWEEN 1 AND 5, 6 NOT BETWEEN 1 AND 5, 3 BETWEEN NULL AND 5, "
                     "9 BETWEEN NULL AND 5, 3 BETWEEN 1 + 1 AND 2 * 2"),
            db.query("SELECT 'abc' LIKE 'a%', 'abc' LIKE 'a_', 'abc' LIKE '_b_', 'a.c' LIKE 'a.c', 'abc' LIKE 'a.c', "
                     "'ABC' LIKE 'a%', 'x(y' LIKE 'x(%', 'abc' NOT LIKE '%c', NULL LIKE 'a', '' LIKE '%', 'a\nb' LIKE 'a%b'"),
            [_try(db, sql) for sql in ("SELECT 1 LIKE 'a'", "SELECT 'a' IN (1)", "SELECT 'a' BETWEEN 1 AND 2")]]


def probe_scalar_functions():
    from quarry import Engine
    db = Engine()
    out = [db.query("SELECT UPPER('aBc'), LOWER('aBc'), LENGTH(''), ABS(-3), ABS(-2.5), ROUND(2.5), ROUND(-2.5), "
                    "ROUND(1.005, 2), ROUND(7), ROUND(2.345, 2), SUBSTR('abcdef', 3), SUBSTR('abc', 2, 0), SUBSTR('abc', 5, 2), "
                    "SUBSTR('abcdef', 2, 3), SUBSTR('abc', 1, 2), SUBSTR('abc', 1)"),
           db.query("SELECT UPPER(NULL), LENGTH(NULL), ABS(NULL), ROUND(NULL, 1), ROUND(1.5, NULL), SUBSTR(NULL, 1), "
                    "COALESCE(NULL, NULL), COALESCE(NULL, 'x', 'y'), COALESCE(0, 1)")]
    out.append([_try(db, sql)[1] for sql in ("SELECT UPPER(1)", "SELECT ABS('x')", "SELECT ROUND(1.5, -1)", "SELECT ROUND('a')",
                                             "SELECT SUBSTR('a', 0)", "SELECT SUBSTR('a', 1, -1)", "SELECT SUBSTR('a', 1.5)",
                                             "SELECT UPPER()", "SELECT UPPER('a', 'b')", "SELECT nope(1)", "SELECT upper(DISTINCT 'a')",
                                             "SELECT upper(*)", "SELECT COALESCE()", "SELECT ROUND(1.5, 1, 2)")])
    return out


def probe_aggregates():
    db = _shop()
    out = [db.query("SELECT COUNT(*), COUNT(category), COUNT(DISTINCT category), SUM(stock), SUM(price), AVG(stock), "
                    "MIN(price), MAX(price), MIN(name), MAX(name), MIN(active), MAX(active) FROM products"),
           db.query("SELECT COUNT(*), SUM(stock), AVG(price), MIN(name) FROM products WHERE stock > 1000"),
           db.query("SELECT SUM(DISTINCT qty), AVG(DISTINCT qty), COUNT(DISTINCT city) FROM orders"),
           db.query("SELECT COUNT(*) + 1, MAX(stock) - MIN(stock) AS spread FROM products"),
           db.execute("SELECT COUNT(*), sum(qty) FROM orders").columns]
    out.append([_try(db, sql)[1] for sql in ("SELECT SUM(name) FROM products", "SELECT AVG(*) FROM products",
                                             "SELECT COUNT(MAX(stock)) FROM products", "SELECT name FROM products WHERE COUNT(*) > 1",
                                             "SELECT COUNT(stock, price) FROM products", "SELECT name, COUNT(*) FROM products",
                                             "SELECT MIN() FROM products")])
    return out


def probe_group_by_having():
    db = _shop()
    return [db.query("SELECT category, COUNT(*), SUM(stock), MAX(price) FROM products GROUP BY category"),
            db.query("SELECT city, SUM(qty) FROM orders GROUP BY city HAVING SUM(qty) >= 2"),
            db.query("SELECT COUNT(*), SUM(stock) FROM products GROUP BY stock > 10"),
            _try(db, "SELECT stock > 10, COUNT(*) FROM products GROUP BY stock > 10")[1],
            db.query("SELECT active, category, COUNT(*) FROM products GROUP BY active, category ORDER BY category, active"),
            db.query("SELECT COUNT(*) FROM products HAVING COUNT(*) > 100"), db.query("SELECT 1 FROM products HAVING COUNT(*) > 3"),
            db.query("SELECT category FROM products WHERE price IS NULL GROUP BY category"),
            [_try(db, sql)[1] for sql in ("SELECT name FROM products GROUP BY category", "SELECT * FROM products GROUP BY id",
                                          "SELECT id FROM products HAVING id > 1", "SELECT category FROM products GROUP BY category HAVING 1",
                                          "SELECT category FROM products GROUP BY category ORDER BY price")]]


def probe_joins():
    db = _shop()
    return [db.query("SELECT o.no, p.name, o.qty * p.price AS value FROM orders o JOIN products p ON o.product = p.id"),
            db.query("SELECT o.no, p.name FROM orders o LEFT JOIN products p ON o.product = p.id AND p.active WHERE o.qty < 6"),
            db.query("SELECT p.name, COUNT(o.no), SUM(o.qty) FROM products p LEFT JOIN orders o ON o.product = p.id "
                     "GROUP BY p.name ORDER BY p.name"),
            db.execute("SELECT o.*, p.name FROM orders o JOIN products p ON p.id = o.product WHERE no = 3").columns,
            db.query("SELECT a.no, b.no FROM orders a JOIN orders b ON a.city = b.city AND a.no < b.no"),
            db.query("SELECT x.no, y.name, z.no FROM orders x JOIN products y ON x.product = y.id JOIN orders z ON z.product = y.id "
                     "AND z.no <> x.no"),
            [_try(db, sql)[1] for sql in ("SELECT no FROM orders o JOIN orders o ON TRUE", "SELECT no FROM orders JOIN products ON 1",
                                          "SELECT x.* FROM orders", "SELECT no FROM orders JOIN nothing ON TRUE",
                                          "SELECT name FROM orders o JOIN products p ON o.product = p.id JOIN products q ON TRUE",
                                          "SELECT o.missing FROM orders o", "SELECT * FROM nothing")]]


def probe_order_by_ascending_and_unique_desc():
    db = _shop()
    return [db.query("SELECT name, price FROM products ORDER BY price"),
            db.query("SELECT name FROM products ORDER BY category, price"),
            db.query("SELECT name, stock * 2 AS doubled FROM products ORDER BY doubled DESC"),
            db.query("SELECT name, price FROM products ORDER BY price DESC"),
            db.query("SELECT name FROM products ORDER BY 1"), db.query("SELECT name FROM products ORDER BY LENGTH(name), name"),
            db.query("SELECT city, no FROM orders ORDER BY city, 2 DESC"), db.query("SELECT name FROM products ORDER BY stock + 0 DESC"),
            [_try(db, sql)[1] for sql in ("SELECT name FROM products ORDER BY 3", "SELECT name FROM products ORDER BY 0",
                                          "SELECT name, name FROM products ORDER BY name", "SELECT name FROM products ORDER BY nope")]]


def probe_distinct_limit_offset():
    db = _shop()
    return [db.query("SELECT DISTINCT category FROM products"), db.query("SELECT DISTINCT city, qty > 1 FROM orders"),
            db.query("SELECT name FROM products LIMIT 0"), db.query("SELECT name FROM products LIMIT 2 OFFSET 5"),
            db.query("SELECT name FROM products LIMIT 3 OFFSET 9"), db.query("SELECT no FROM orders ORDER BY no LIMIT 2 OFFSET 3"),
            db.query("SELECT DISTINCT category FROM products ORDER BY category LIMIT 2"), db.query("SELECT name FROM products LIMIT 2")]


def probe_create_drop_catalog():
    from quarry import Engine
    db = Engine()
    out = [_try(db, "CREATE TABLE a (x INTEGER PRIMARY KEY, y TEXT NOT NULL, z REAL, w BOOLEAN)"), db.db.table_names()]
    for sql in ("CREATE TABLE a (x INTEGER)", "CREATE TABLE b (x INTEGER PRIMARY KEY, y INTEGER PRIMARY KEY)",
                "CREATE TABLE b (x INTEGER, x TEXT)", "DROP TABLE nothing", "SELECT * FROM nothing",
                "CREATE TABLE " + "n" * 40 + " (x INTEGER)"):
        out.append(_try(db, sql)[1])
    table = db.db.table("a")
    out += [[[c.name, c.type, c.not_null, c.primary_key] for c in table.columns], table.key_index, len(table),
            _error(table.index_of, "nope"), table.index_of("z"), _error(db.db.create_table, "Bad Name", [("x", "INTEGER")]),
            _error(db.db.create_table, "c", []), _error(db.db.create_table, "c", [("X", "INTEGER")]),
            _error(db.db.create_table, "c", [("x", "BLOB")])]
    db.execute("CREATE TABLE b (q TEXT)")
    db.execute("CREATE TABLE ab (q TEXT)")
    plain = db.db.create_table("aa", [("x", "INTEGER"), ("y", "TEXT")])
    out += [db.db.table_names(), [[c.not_null, c.primary_key] for c in plain.columns], _try(db, "INSERT INTO aa VALUES (NULL, NULL)")]
    db.execute("DROP TABLE a")
    out += [db.db.table_names(), _try(db, "SELECT * FROM a")[1], _error(db.db.table, None)]
    return out


def probe_insert_rules():
    from quarry import Engine
    db = Engine()
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL, ratio REAL, flag BOOLEAN)")
    out = [_try(db, "INSERT INTO t VALUES (1, 'a', 2, TRUE)"), _try(db, "INSERT INTO t (name, id) VALUES ('b', 2), ('c', 3)"),
           _try(db, "INSERT INTO t VALUES (2 * 2, 'x' || 'y', 1.5 + 1, NOT FALSE)")]
    for sql in ("INSERT INTO t VALUES (5, 'e', 'r', NULL)", "INSERT INTO t VALUES (5, NULL, 1, NULL)",
                "INSERT INTO t VALUES (NULL, 'n', 1, NULL)", "INSERT INTO t VALUES (5, 'e', 1)", "INSERT INTO t (id) VALUES (5, 6)",
                "INSERT INTO t (id, id) VALUES (5, 6)", "INSERT INTO t (nope) VALUES (5)", "INSERT INTO t VALUES (id, 'x', 1, NULL)",
                "INSERT INTO nothing VALUES (1)", "INSERT INTO t VALUES (1, 'dup', 1, NULL)", "INSERT INTO t VALUES (2.0, 'z', 1, NULL)",
                "INSERT INTO t VALUES (7, 'g', 1, NULL), (7, 'h', 1, NULL)", "INSERT INTO t VALUES (8, 1, 1, NULL)",
                "INSERT INTO t VALUES (9, 'i', 1, 1)", "INSERT INTO t VALUES (COUNT(*), 'j', 1, NULL)"):
        out.append(_try(db, sql)[1])
    out.append(db.query("SELECT * FROM t"))
    out.append(_try(db, "INSERT INTO t VALUES (-1, '', 0, FALSE)"))
    return out


def probe_update_rules():
    db = _shop()
    out = [_try(db, "UPDATE orders SET qty = no, no = no + qty + 100 WHERE city = 'Gdansk'"),
           db.query("SELECT * FROM orders"), _try(db, "UPDATE orders SET city = 'Lodz' WHERE city IS NULL"),
           _try(db, "UPDATE products SET price = price * 2 WHERE price > 50"), db.query("SELECT id, price FROM products"),
           _try(db, "UPDATE products SET stock = 1 WHERE active")]
    for sql in ("UPDATE orders SET no = 1 WHERE no = 4", "UPDATE orders SET qty = 'x' WHERE no = 1", "UPDATE orders SET qty = 1, qty = 2",
                "UPDATE orders SET nope = 1", "UPDATE products SET name = NULL WHERE id = 10", "UPDATE orders SET qty = 1 WHERE 1",
                "UPDATE nothing SET a = 1", "UPDATE products SET price = 'x' WHERE id = 99"):
        out.append(_try(db, sql)[1])
    out.append(db.query("SELECT * FROM orders"))
    out.append(_try(db, "UPDATE orders SET no = no + 10"))
    out.append(_try(db, "INSERT INTO orders VALUES (1, 1, 1, 'New')"))
    out.append(_try(db, "INSERT INTO orders VALUES (11, 1, 1, 'Dup')"))
    return out


def probe_delete_rules():
    db = _shop()
    out = [_try(db, "DELETE FROM orders WHERE city = 'Lodz'"), db.query("SELECT no FROM orders"),
           _try(db, "INSERT INTO orders VALUES (1, 1, 1, 'Back')"), db.query("SELECT no FROM orders"),
           _try(db, "DELETE FROM products WHERE price IS NULL OR stock = 0"), _try(db, "DELETE FROM orders WHERE no > 100"),
           _try(db, "DELETE FROM orders WHERE 'x'")[1], _try(db, "DELETE FROM orders"), db.query("SELECT COUNT(*) FROM orders"),
           _try(db, "INSERT INTO orders VALUES (2, 1, 1, 'Again'), (5, 1, 1, 'Again')"), db.query("SELECT no FROM orders")]
    return out


def probe_insertion_order_kept():
    db = _shop()
    sorted_rows = db.query("SELECT id FROM products ORDER BY price DESC")
    table = db.db.table("products")
    copy = table.rows()
    copy.reverse()
    copy.append(("junk",))
    return [sorted_rows, db.query("SELECT id FROM products"), db.query("SELECT name FROM products LIMIT 2"), len(table),
            [row[0] for row in table.rows()]]


def probe_format_and_results():
    from quarry import Engine, QuarryError, format_result
    db = _shop()
    out = [format_result(db.execute("SELECT name, price, active, stock FROM products WHERE id < 14")),
           format_result(db.execute("SELECT name FROM products WHERE id = 10")),
           format_result(db.execute("SELECT name, price FROM products WHERE id > 99")),
           format_result(db.execute("SELECT price FROM products WHERE price IS NULL")),
           db.execute("SELECT MAX(stock) FROM products").scalar(), _error(db.execute("SELECT id FROM products").scalar),
           _error(db.execute("SELECT 1, 2").scalar)]
    from quarry.engine import format_values
    out.append(format_values([1, None, "a", 2.5, False]))
    results = Engine().run_script("CREATE TABLE z (a INTEGER); INSERT INTO z VALUES (1), (2); UPDATE z SET a = a + 1; "
                                  "SELECT SUM(a) FROM z; DELETE FROM z WHERE a = 2; DROP TABLE z;")
    out.append([[r.columns, [list(x) for x in r.rows], r.rowcount] for r in results])
    db2 = Engine()
    try:
        db2.run_script("CREATE TABLE z (a INTEGER);\nINSERT INTO z VALUES (1);\n-- comment;\nSELECT a FROM z WHERE a = 'x';")
        out.append(None)
    except QuarryError as exc:
        out.append([type(exc).__name__, exc.statement, type(exc.__cause__).__name__])
    out.append(db2.query("SELECT a FROM z"))
    return out


# --- target probes: DESC keeps ties in their previous order ---------------------------------------
def probe_desc_keeps_tied_rows_in_order():
    from quarry import Engine
    db = Engine()
    db.run_script("CREATE TABLE scores (player TEXT, team TEXT, points INTEGER);"
                  "INSERT INTO scores VALUES ('Ola', 'red', 90), ('Bart', 'blue', 75), ('Celina', 'red', 90), "
                  "('Dawid', 'blue', 90), ('Ewa', 'red', 60), ('Filip', 'blue', 75)")
    return [db.query("SELECT player FROM scores ORDER BY points DESC"),
            db.query("SELECT player FROM scores ORDER BY team DESC, player"),
            db.query("SELECT player FROM scores ORDER BY points DESC, team DESC"),
            db.query("SELECT player FROM scores ORDER BY team, points DESC")]


def probe_desc_ties_with_limit_and_nulls():
    db = _shop()
    return [db.query("SELECT name FROM products ORDER BY category DESC LIMIT 4"),
            db.query("SELECT name FROM products ORDER BY active DESC"),
            db.query("SELECT city, no FROM orders ORDER BY city DESC LIMIT 3 OFFSET 1"),
            db.query("SELECT DISTINCT category, active FROM products ORDER BY active DESC")]


def probe_desc_ties_in_groups():
    db = _shop()
    return [db.query("SELECT city, COUNT(*) AS n FROM orders GROUP BY city ORDER BY n DESC"),
            db.query("SELECT category, MAX(active) FROM products GROUP BY category ORDER BY 2 DESC"),
            db.query("SELECT p.category, o.city FROM orders o JOIN products p ON o.product = p.id ORDER BY p.category DESC")]


# --- target probes: equal precedence groups from left to right ----------------------------------------
def probe_left_to_right_arithmetic():
    from quarry import Engine
    db = Engine()
    return [db.query("SELECT 10 - 4 - 3, 12 / 2 * 3, 100 / 10 / 5, 7 - 2 + 1, 17 % 5 * 2, 7 * 3 / 2, 2 * 7 % 4, 1 - 1 - 1 - 1"),
            db.query("SELECT 10.0 / 4 * 2, 'a' || 1 - 1, 20 - 5 - 5 = 10, 3 - 2 - 1 BETWEEN 0 AND 0")]


def probe_left_to_right_columns():
    db = _shop()
    db.execute("CREATE TABLE lines (no INTEGER, gross INTEGER, discount INTEGER, shipping INTEGER, parts INTEGER)")
    db.execute("INSERT INTO lines VALUES (1, 1000, 100, 50, 4), (2, 500, 0, 25, 5), (3, 90, 30, 10, 3)")
    return [db.query("SELECT no, gross - discount - shipping AS net FROM lines"),
            db.query("SELECT no FROM lines WHERE gross - discount - shipping > 400"),
            db.query("SELECT no, gross / parts * 2, gross * 3 / parts FROM lines"),
            [_try(db, "UPDATE lines SET gross = gross - discount + shipping"), db.query("SELECT gross FROM lines")],
            db.query("SELECT SUM(gross - discount - shipping) FROM lines GROUP BY no > 1 ORDER BY 1")]


def probe_left_to_right_canonical_text():
    from quarry import explain
    db = _shop()
    return [explain("SELECT a - b - c, a / b * c, a - b + c, a % b % c, (a - b) - c, a * b / c"),
            db.execute("SELECT stock - 1 - 1, price / 2 * 2 FROM products WHERE id = 10").columns]


# --- target probes: failed multi-row INSERT leaves no trace -------------------------------------------
def probe_insert_retry_after_failed_batch():
    db = _shop()
    first = _try(db, "INSERT INTO orders VALUES (7, 10, 1, 'Lodz'), (8, 11, 2, 'Lodz'), (9, 12, 'three', 'Lodz')")
    second = _try(db, "INSERT INTO orders VALUES (7, 10, 1, 'Lodz'), (8, 11, 2, 'Lodz'), (9, 12, 3, 'Lodz')")
    return [first, second, db.query("SELECT no FROM orders WHERE no > 6")]


def probe_failed_batch_keys_are_free():
    from quarry import Engine
    db = Engine()
    db.execute("CREATE TABLE tags (code TEXT PRIMARY KEY, label TEXT NOT NULL)")
    db.execute("INSERT INTO tags VALUES ('a', 'Alpha')")
    out = [_try(db, "INSERT INTO tags VALUES ('b', 'Beta'), ('c', NULL)"),
           _try(db, "INSERT INTO tags VALUES ('d', 'Delta'), ('e', 'Echo'), ('a', 'Again')"),
           _try(db, "INSERT INTO tags (code, label) VALUES ('b', 'Beta')"), _try(db, "INSERT INTO tags VALUES ('d', 'Delta')"),
           _try(db, "INSERT INTO tags VALUES ('e', 'Echo'), ('c', 'Charlie')")]
    out.append(db.query("SELECT code FROM tags"))
    return out


def probe_failed_insert_in_script():
    from quarry import Engine, ScriptFailed
    db = Engine()
    db.run_script("CREATE TABLE seats (row INTEGER, seat INTEGER, id INTEGER PRIMARY KEY);")
    try:
        db.run_script("INSERT INTO seats VALUES (1, 1, 101), (1, 2, 102);\nINSERT INTO seats VALUES (2, 1, 201), (2, 2, 202), (2, 3, NULL);")
        failure = None
    except ScriptFailed as exc:
        failure = [exc.statement, type(exc.__cause__).__name__]
    results = db.run_script("INSERT INTO seats VALUES (2, 1, 201), (2, 2, 202), (2, 3, 203); SELECT COUNT(*) FROM seats")
    return [failure, [r.rowcount for r in results], results[-1].rows[0][0]]
