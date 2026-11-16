"""The project's own regression tests (visible to everyone)."""
from decimal import Decimal
import unittest

from inkwell import (Environment, FilterError, Markup, TemplateNotFound, TemplateSyntaxError, UndefinedError,
                     render_string)
from inkwell.lexer import tokenize


def render(source, **variables):
    return render_string(source, variables)


class ExpressionTests(unittest.TestCase):
    def test_arithmetic_precedence(self):
        self.assertEqual(render("{{ 1 + 2 * 3 }} {{ (1 + 2) * 3 }} {{ 7 // 2 }} {{ -2 * 3 }}"), "7 9 3 -6")

    def test_boolean_operators_return_operands(self):
        self.assertEqual(render("{{ a and b or c }}", a=1, b=0, c="c"), "c")
        self.assertEqual(render("{{ not a == b }}", a=1, b=2), "true")

    def test_membership_and_concat(self):
        self.assertEqual(render("{{ 'x' in items }} {{ 'y' not in items }} {{ 'a' ~ 1 }}", items=["x"]), "true true a1")

    def test_attribute_and_item_lookup(self):
        self.assertEqual(render("{{ user.name }} {{ user['tags'][1] }} {{ user.missing }}",
                                user={"name": "Ann", "tags": ["a", "b"]}), "Ann b ")


class StatementTests(unittest.TestCase):
    def test_if_elif_else(self):
        source = "{% if n > 10 %}big{% elif n > 5 %}mid{% else %}small{% endif %}"
        self.assertEqual([render(source, n=n) for n in (20, 7, 1)], ["big", "mid", "small"])

    def test_for_with_filter_and_loop_info(self):
        source = "{% for u in users if u.active %}{{ loop.index }}.{{ u.name }}{% if not loop.last %}, {% endif %}{% endfor %}"
        users = [{"name": "Ann", "active": True}, {"name": "Bob", "active": False}, {"name": "Cy", "active": True}]
        self.assertEqual(render(source, users=users), "1.Ann, 2.Cy")

    def test_for_else_and_unpacking(self):
        self.assertEqual(render("{% for x in [] %}x{% else %}empty{% endfor %}"), "empty")
        self.assertEqual(render("{% for k, v in m|items %}{{ k }}={{ v }};{% endfor %}", m={"a": 1, "b": 2}), "a=1;b=2;")

    def test_set_inside_loop_does_not_leak(self):
        source = "{% set total = 0 %}{% for x in [1, 2] %}{% set total = x %}{% endfor %}{{ total }}"
        self.assertEqual(render(source), "0")

    def test_whitespace_control(self):
        source = "<ul>\n  {%- for x in xs %}\n  <li>{{ x }}</li>\n  {%- endfor %}\n</ul>"
        self.assertEqual(render(source, xs=[1, 2]), "<ul>\n  <li>1</li>\n  <li>2</li>\n</ul>")

    def test_include_and_autoescape(self):
        env = Environment({"row": "<td>{{ cell }}</td>", "table": "{% for cell in cells %}{% include 'row' %}{% endfor %}"},
                          autoescape=True)
        self.assertEqual(env.render("table", cells=["a&b", Markup("<i>c</i>")]), "<td>a&amp;b</td><td><i>c</i></td>")
        with self.assertRaises(TemplateNotFound):
            env.from_string("{% include 'nope' %}").render()


class FilterTests(unittest.TestCase):
    def test_number_formatting(self):
        self.assertEqual(render("{{ x|number(2) }}", x=Decimal("1234567.891")), "1,234,567.89")
        self.assertEqual(render("{{ 0.5|percent }} {{ 2.344|round(2) }} {{ 7.25|int }}"), "50% 2.34 7")

    def test_text_filters(self):
        self.assertEqual(render("{{ 'hello big world'|truncate(12) }}"), "hello big...")
        self.assertEqual(render("{{ ' mixed Case '|trim|title }}"), "Mixed Case")

    def test_sort_and_join(self):
        people = [{"n": "bo", "a": 3}, {"n": "Al", "a": 1}]
        self.assertEqual(render("{{ people|sort(attribute='n')|map('a')|join(',') }}", people=people), "1,3")

    def test_default_and_unknown_filter(self):
        self.assertEqual(render("{{ missing|default('n/a') }}"), "n/a")
        with self.assertRaises(FilterError):
            render("{{ 1|nope }}")


class ErrorTests(unittest.TestCase):
    def test_syntax_error_line(self):
        with self.assertRaises(TemplateSyntaxError) as caught:
            render("line one\n{{ x }}\n{% if x %}\nno end\n")
        self.assertEqual(caught.exception.line, 3)

    def test_strict_undefined_line(self):
        env = Environment(strict=True)
        with self.assertRaises(UndefinedError) as caught:
            env.from_string("a\n{# note #}\nb {{ nope }}").render()
        self.assertEqual((caught.exception.name, caught.exception.line), ("<string>", 3))

    def test_tokens_keep_lines(self):
        tokens = tokenize("a\n{{ x }}\n{% if y %}")
        self.assertEqual([(token.kind, token.line) for token in tokens],
                         [("text", 1), ("output", 2), ("text", 2), ("tag", 3)])


if __name__ == "__main__":
    unittest.main()
