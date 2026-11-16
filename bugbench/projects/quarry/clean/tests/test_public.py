"""The project's own regression tests (visible to everyone)."""
import unittest

from quarry import (AmbiguousColumn, ConstraintError, DuplicateKey, Engine, GroupingError, ScriptFailed, SqlSyntaxError,
                    TypeMismatch, explain, format_result)
from quarry.lexer import tokenize

SETUP = """
CREATE TABLE staff (id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept TEXT, salary INTEGER, bonus REAL);
INSERT INTO staff VALUES (1, 'Ola', 'ops', 5200, 0.5), (2, 'Piotr', 'dev', 7100, NULL), (3, 'Ewa', 'dev', 6800, 1.25),
                         (4, 'Jan', NULL, 4300, 0.0), (5, 'Iga', 'ops', 5900, 2.0);
CREATE TABLE depts (code TEXT PRIMARY KEY, floor INTEGER);
INSERT INTO depts VALUES ('dev', 3), ('ops', 1);
"""


def engine():
    db = Engine()
    db.run_script(SETUP)
    return db


class LexerTests(unittest.TestCase):
    def test_tokens(self):
        kinds = [(t.kind, t.value) for t in tokenize("SELECT 'it''s', x1 != 2.5 -- note")]
        self.assertEqual(kinds, [("keyword", "SELECT"), ("string", "it's"), ("punct", ","), ("name", "x1"),
                                 ("op", "<>"), ("real", 2.5), ("end", None)])
        with self.assertRaises(SqlSyntaxError):
            tokenize("SELECT 'open")


class ExpressionTests(unittest.TestCase):
    def test_arithmetic_and_precedence(self):
        db = Engine()
        self.assertEqual(db.query("SELECT 2 + 3 * 4, (2 + 3) * 4, -7 / 2, 7 % 3, 1 / 0"), [(14, 20, -3, 1, None)])
        self.assertEqual(explain("SELECT a + b * c, NOT x = 1 AND y"), ["a + b * c", "NOT (x = 1) AND y"])

    def test_three_valued_logic(self):
        db = Engine()
        self.assertEqual(db.query("SELECT NULL AND FALSE, NULL OR TRUE, NULL = NULL, NULL IS NULL, 2 IN (1, NULL)"),
                         [(False, True, None, True, None)])
        with self.assertRaises(TypeMismatch):
            db.query("SELECT 'a' + 1")

    def test_functions(self):
        db = Engine()
        self.assertEqual(db.query("SELECT UPPER('ab'), LENGTH('abc'), ROUND(2.25, 1), SUBSTR('kayak', 2, 3), COALESCE(NULL, 4)"),
                         [("AB", 3, 2.3, "aya", 4)])


class QueryTests(unittest.TestCase):
    def test_filter_and_order(self):
        db = engine()
        rows = db.query("SELECT name FROM staff WHERE salary BETWEEN 5000 AND 7000 ORDER BY salary DESC")
        self.assertEqual(rows, [("Ewa",), ("Iga",), ("Ola",)])
        self.assertEqual(db.query("SELECT name FROM staff WHERE dept IS NULL OR bonus > 1 ORDER BY dept, name"),
                         [("Jan",), ("Ewa",), ("Iga",)])

    def test_join_and_group(self):
        db = engine()
        rows = db.query("SELECT d.code, d.floor, COUNT(*), SUM(s.salary) FROM staff s JOIN depts d ON s.dept = d.code "
                        "GROUP BY d.code, d.floor ORDER BY d.floor")
        self.assertEqual(rows, [("ops", 1, 2, 11100), ("dev", 3, 2, 13900)])
        self.assertEqual(db.query("SELECT name, floor FROM staff LEFT JOIN depts ON dept = code WHERE id = 4"), [("Jan", None)])
        with self.assertRaises(AmbiguousColumn):
            db.query("SELECT id FROM staff a JOIN staff b ON a.id = b.id")
        with self.assertRaises(GroupingError):
            db.query("SELECT name, COUNT(*) FROM staff GROUP BY dept")

    def test_nulls_sort_first(self):
        db = engine()
        self.assertEqual(db.query("SELECT id FROM staff ORDER BY bonus"), [(2,), (4,), (1,), (3,), (5,)])

    def test_aggregates_over_no_rows(self):
        db = engine()
        self.assertEqual(db.query("SELECT COUNT(*), COUNT(bonus), SUM(salary), MAX(name) FROM staff WHERE id > 99"),
                         [(0, 0, None, None)])

    def test_distinct_limit_offset(self):
        db = engine()
        self.assertEqual(db.query("SELECT DISTINCT dept FROM staff WHERE dept IS NOT NULL ORDER BY dept"), [("dev",), ("ops",)])
        self.assertEqual(db.query("SELECT id FROM staff LIMIT 2 OFFSET 1"), [(2,), (3,)])

    def test_format(self):
        db = engine()
        text = format_result(db.execute("SELECT name, bonus FROM staff WHERE id < 3"))
        self.assertEqual(text.splitlines(), ["name  | bonus", "------+------", "Ola   |   0.5", "Piotr |  NULL", "(2 rows)"])


class WriteTests(unittest.TestCase):
    def test_constraints(self):
        db = engine()
        with self.assertRaises(DuplicateKey):
            db.execute("INSERT INTO staff VALUES (1, 'Dup', 'ops', 1, NULL)")
        with self.assertRaises(ConstraintError):
            db.execute("INSERT INTO staff (id, dept) VALUES (9, 'ops')")
        self.assertEqual(db.execute("INSERT INTO staff (id, name) VALUES (9, 'Nowy')").rowcount, 1)

    def test_failed_insert_changes_nothing(self):
        db = engine()
        with self.assertRaises(TypeMismatch):
            db.execute("INSERT INTO staff VALUES (6, 'Kuba', 'ops', 'lots', NULL)")
        self.assertEqual(db.query("SELECT COUNT(*) FROM staff"), [(5,)])
        self.assertEqual(db.execute("INSERT INTO staff VALUES (6, 'Kuba', 'ops', 5000, NULL)").rowcount, 1)

    def test_update_delete(self):
        db = engine()
        self.assertEqual(db.execute("UPDATE staff SET salary = salary + 100 WHERE dept = 'ops'").rowcount, 2)
        self.assertEqual(db.execute("DELETE FROM staff WHERE salary < 5000").rowcount, 1)
        self.assertEqual(db.query("SELECT id, salary FROM staff WHERE dept = 'ops'"), [(1, 5300), (5, 6000)])
        with self.assertRaises(DuplicateKey):
            db.execute("UPDATE staff SET id = 1")

    def test_script_failure(self):
        db = Engine()
        with self.assertRaises(ScriptFailed) as caught:
            db.run_script("CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1); SELECT y FROM t")
        self.assertEqual(caught.exception.statement, 3)
        self.assertEqual(db.query("SELECT x FROM t"), [(1,)])


if __name__ == "__main__":
    unittest.main()
