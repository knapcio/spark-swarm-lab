"""Hidden behavioural probes for the inkwell project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY 3d81b6e4-bugbench-inkwell-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""
from decimal import Decimal


def _env(**kwargs):
    from inkwell import Environment
    return Environment(**kwargs)


def _r(source, **variables):
    return _env().from_string(source).render(variables)


def _outcome(callable_, *args, **kwargs):
    """Rendered text, or [exception type, line, template name] for inkwell errors."""
    try:
        return callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return [type(exc).__name__, getattr(exc, "line", None), getattr(exc, "name", None)]


def _render_outcome(source, env=None, **variables):
    env = env or _env()
    return _outcome(lambda: env.from_string(source).render(variables))


# --- lexer ----------------------------------------------------------------------
def probe_lexer_tokens():
    from inkwell.lexer import tokenize
    tokens = tokenize('x {{ "a %} b" ~ \'c\\n\' }}\n{% set n = 1.50 %}{# c\n #}y\n{{ n }}')
    out = [[t.kind, t.line, t.value if t.kind == "text" else [[i.kind, str(i.value), i.line] for i in t.value]]
           for t in tokens]
    for bad in ("{# open", "{{ 'abc }}", "{{ x $ y }}", "{{ }}", "{% %}", "{{ x", "{{ 'a\\q' }}"):
        out.append(_outcome(tokenize, bad))
    return out


# --- expressions ---------------------------------------------------------------
def probe_expression_arithmetic():
    out = [_r("{{ 1 + 2 * 3 - 4 }}|{{ 2 * (3 + 4) }}|{{ 7 / 2 }}|{{ 7 // 2 }}|{{ 7 % 3 }}|{{ -3 + 1 }}"),
           _r("{{ price * qty }}|{{ 1.10 + 2.25 }}|{{ 10 - 2 - 3 }}|{{ 2 * 3 % 4 }}", price=Decimal("2.50"), qty=3),
           _r("{{ 'a' ~ 1 + 2 ~ 'b' }}|{{ -x }}", x=4)]
    for bad in ("{{ 1 / 0 }}", "{{ 'a' + 1 }}", "{{ true + 1 }}", "{{ 1 +  }}", "{{ (1 + 2 }}"):
        out.append(_render_outcome(bad))
    return out


def probe_boolean_operands():
    template = "{{ a and b or c }}|{{ not a or b }}|{{ not (a or b) }}|{{ a and not b }}|{{ (a or b) and c }}"
    out = []
    for a, b, c in ((1, 0, "c"), (0, "b", 0), ("a", "b", "c"), (0, 0, 0), ("a", 0, "c")):
        out.append(_r(template, a=a, b=b, c=c))
    strict = _env(strict=True)
    out.append(_render_outcome("{{ ok or missing }}|{{ nope and missing }}|{% if missing %}y{% else %}n{% endif %}",
                               strict, ok="ok", nope=0))
    out.append(_render_outcome("{{ not missing }}", strict))
    return out


def probe_comparisons_membership():
    out = [_r("{{ 1 < 2 }} {{ 2 <= 2 }} {{ 'b' > 'a' }} {{ 1 == 1.0 }} {{ x != 3 }} {{ 3 >= 4 }}", x=3),
           _r("{{ 'b' in 'abc' }} {{ 2 not in xs }} {{ 'k' in m }} {{ not 1 in xs }} {{ 1 + 1 == 2 }}",
              xs=[1, 2], m={"k": 1}),
           _render_outcome("{{ 1 < 'a' }}"), _render_outcome("{{ 1 in 5 }}")]
    return out


def probe_lookup_and_undefined_lenient():
    class Card:
        title = "Ace"
        _secret = "hidden"

        def shout(self):
            return "!"

    data = {"user": {"name": "Ann", "tags": ["x", "y"]}, "card": Card(), "seq": [10, 20, 30]}
    return [_r("[{{ user.name }}][{{ user.tags[1] }}][{{ user['name'] }}][{{ user.nope.deeper }}]", **data),
            _r("[{{ card.title }}][{{ card._secret }}][{{ card.shout }}][{{ seq[-1] }}][{{ seq[5] }}]", **data),
            _r("[{% for x in missing %}x{% else %}empty{% endfor %}][{{ missing|default('-') }}][{{ true }}{{ none }}]"),
            _r("{{ [1, 'a', none, false] }}")]


def probe_strict_mode():
    env = _env(strict=True)
    cases = ["{{ ghost }}", "{% for x in ghost %}{% endfor %}", "{{ ghost|upper }}", "{{ ghost == 1 }}",
             "{{ ghost.attr }}", "{{ user.ghost }}", "{{ ghost|default('d') }}", "{{ 1 + ghost }}",
             "{% if ghost %}y{% else %}n{% endif %}", "{{ user.name|default('x') }}", "{{ ghost ~ 'a' }}"]
    return [_render_outcome(source, env, user={"name": "Ann"}) for source in cases]


# --- statements ------------------------------------------------------------------
def probe_if_for_statements():
    rows = [{"n": "a", "q": 0}, {"n": "b", "q": 2}, {"n": "c", "q": 5}, {"n": "d", "q": 0}]
    loop = ("{% for r in rows if r.q > 0 %}{{ loop.index }}/{{ loop.index0 }}/{{ loop.revindex }}/"
            "{{ loop.first }}/{{ loop.last }}/{{ loop.length }}:{{ r.n }};{% endfor %}")
    return [_r(loop, rows=rows),
            _r("{% for r in rows if r.q > 9 %}x{% else %}none{% endfor %}", rows=rows),
            _r("{% for a, b in pairs %}{{ a }}{{ b }},{% endfor %}", pairs=[[1, 2], ["x", "y"]]),
            _render_outcome("{% for a, b in pairs %}{% endfor %}", pairs=[[1, 2, 3]]),
            _r("{% for k in m %}{{ k }}{% endfor %}", m={"z": 1, "y": 2}),
            [_r("{% if n == 1 %}one{% elif n == 2 %}two{% elif n %}many{% else %}zero{% endif %}", n=n)
             for n in (1, 2, 7, 0)],
            _render_outcome("{% for x in 5 %}{% endfor %}"),
            _r("{% for x in outer %}{% for y in x %}{{ loop.index }}{% endfor %}{{ loop.index }}|{% endfor %}",
               outer=[[7, 8], [9]])]


def probe_set_scoping():
    variables = {"x": 1, "items": [1, 2, 3]}
    env = _env(globals={"site": "S", "x": 0},
               templates={"part": "{% set x = 99 %}[{{ x }}{{ site }}]", "page": "{{ x }}{% include 'part' %}{{ x }}"})
    out = [env.from_string("{% set x = x + 1 %}{{ x }}{% for i in items %}{% set x = i * 10 %}{{ x }},{% endfor %}{{ x }}")
           .render(variables), variables, env.globals, env.render("page", {"x": 5}), env.render("page")]
    out.append(_r("{% set a = [1, 2] %}{% set b = a|length %}{{ b }}{{ a }}"))
    out.append(_render_outcome("{% set = 1 %}"))
    out.append(_render_outcome("{% set x 1 %}"))
    return out


def probe_include():
    from inkwell import TemplateNotFound
    env = _env(templates={"head": "<{{ title }}>", "list": "{% for t in titles %}{% set title = t %}{% include 'head' %}{% endfor %}",
                          "loop": "{% include 'loop' %}"})
    out = [env.render("list", titles=["a", "b"]),
           env.from_string("{% include name %}|{% include 'nope' ignore missing %}|").render(name="head", title="t")]
    try:
        env.from_string("{% include 'nope' %}").render()
        out.append(None)
    except TemplateNotFound as exc:
        out.append(["TemplateNotFound", exc.name])
    out.append(_outcome(env.render, "loop")[0])
    env.add_template("head", "[{{ title|upper }}]")
    out.append(env.render("list", titles=["c"]))
    out.append(_render_outcome("{% include 5 %}", env))
    return out


def probe_whitespace_control():
    cases = ["a  {{- x -}}  b", "a\n  {%- if x %}\n  yes\n  {%- endif %}\n  b", "a {#- c -#} b",
             "{% for i in [1, 2] -%}\n  {{ i }}\n{%- endfor %}", "a\n{{ x }}\nb", "{{ x -}}\n\n\n{{ x }}",
             "  {%- if false %}x{% else -%}  y  {%- endif -%}  "]
    return [_r(source, x="X") for source in cases]


def probe_autoescape_markup():
    from inkwell import Markup, escape
    env = _env(autoescape=True)
    out = [env.from_string("{{ s }}|{{ m }}|{{ s|safe }}|{{ s|e }}|{{ tags|join(' & ') }}|{{ m ~ s }}").render(
        s="<a href='x'>&\"", m=Markup("<b>ok</b>"), tags=["<i>", Markup("<u>")])]
    out.append(_r("{{ s }}|{{ tags|join('-') }}", s="<p>", tags=["<i>", 1]))
    joined = Markup("<br>") + "<script>"
    out += [str(joined), type(joined).__name__, str("<x>" + Markup("<y>")), str(Markup(", ").join(["<", Markup(">")])),
            str(escape(None)), str(escape(Markup("&amp;")))]
    return out


# --- filters ---------------------------------------------------------------------
def probe_text_filters():
    return [_r("{{ 'hELLO wORLD'|capitalize }}|{{ 'the cat  sat'|title }}|{{ '  pad  '|trim }}|{{ 'aXbX'|replace('X', '-') }}"),
            _r("{{ s|truncate(13) }}|{{ s|truncate(12) }}|{{ s|truncate(16) }}|{{ s|truncate(12, killwords=true) }}"
               "|{{ s|truncate(6, end='~') }}|{{ 'short'|truncate(5) }}", s="alpha beta gamma"),
            _r("{{ 'one two  three'|wordcount }}|{{ 1|pluralize }}|{{ 2|pluralize('y', 'ies') }}|{{ 'ab'|upper|lower }}"),
            _render_outcome("{{ 5|length }}")]


def probe_sequence_filters():
    people = [{"n": "bo", "a": 3}, {"n": "Al", "a": 1}, {"n": "cy", "a": 3}, {"n": "al", "a": 2}, {"n": "Zed", "a": 1}]
    return [_r("{{ p|sort(attribute='n')|map('n')|join(',') }}", p=people),
            _r("{{ p|sort(attribute='n', case_sensitive=true)|map('n')|join(',') }}", p=people),
            _r("{{ p|sort(attribute='a', reverse=true)|map('n')|join(',') }}", p=people),
            _r("{{ [3, 1, 2]|sort }}|{{ [3, 1, 2]|sort(reverse=true) }}|{{ p|unique(attribute='a')|map('n')|join }}", p=people),
            _r("{{ [1, 2, 3, 4, 5]|batch(2) }}|{{ [1, 2, 3]|batch(2, 0) }}|{{ [1, 2]|first }}{{ [1, 2]|last }}{{ []|first }}"),
            _r("{{ p|sum(attribute='a') }}|{{ [1.5, 2]|sum }}|{{ 'abc'|reverse }}|{{ [1, 2]|reverse }}|{{ m|items }}",
               p=people, m={"b": 2, "a": 1}),
            _render_outcome("{{ p|map('zzz') }}", p=people), _render_outcome("{{ [1]|batch(0) }}")]


def probe_number_filters_no_ties():
    return [_r("{{ 1234567.891|number }}|{{ x|number(0) }}|{{ y|number(3, sep=' ', point=',') }}|{{ 999.999|number(2) }}",
               x=Decimal("-9876543.21"), y=12345.6789),
            _r("{{ 2.344|round(2) }}|{{ 2.346|round(2) }}|{{ 7|round(1) }}|{{ -0.001|round(2) }}|{{ x|round(3) }}",
               x=1.23456),
            _r("{{ 0.4567|percent(1) }}|{{ 1|percent }}|{{ '0.25'|percent }}|{{ -7.9|int }}|{{ x|abs }}", x=Decimal("-3.5")),
            _render_outcome("{{ true|round }}"), _render_outcome("{{ 'abc'|number }}"), _render_outcome("{{ 1|round(-1) }}")]


def probe_custom_filters_and_api():
    from inkwell import InkwellError, render_string
    env = _env(filters={"twice": lambda value, sep="": f"{value}{sep}{value}"})
    out = [env.from_string("{{ 'ab'|twice('-') }}").render(), render_string("{{ a }}{{ b }}", {"a": 1}, b=2)]
    out.append(_outcome(env.add_filter, "bad name", len))
    out.append(_render_outcome("{{ 1|twice(1, 2, 3) }}", env))
    out.append(issubclass(type(_outcome(env.add_filter, "x", 5)), list))
    out.append(isinstance(InkwellError("x"), Exception))
    return out


def probe_lookup_and_filter_edges():
    class Box:
        def __init__(self, label, inner=None):
            self.label, self.inner, self._hidden = label, inner, "h"

    seq, boxes = [10, 20, 30], [Box("b", Box("y")), Box("a", Box("z"))]
    return [_r("[{{ s[2] }}][{{ s[3] }}][{{ s[-3] }}][{{ s[-4] }}][{{ s[true] }}][{{ t[0] }}][{{ 'abc'[1] }}][{{ m[1] }}]",
               s=seq, t=(7, 8), m={1: "one"}),
            _r("{{ b|sort(attribute='inner.label', reverse=true)|map('label')|join }}|{{ d|map('k.v')|join(',') }}",
               b=boxes, d=[{"k": {"v": 1}}, {"k": {"v": 2}}]),
            _render_outcome("{{ b|map('_hidden') }}", b=boxes), _render_outcome("{{ d|map('k.w') }}", d=[{"k": {"v": 1}}]),
            _render_outcome("{{ b|map('nope') }}", b=boxes),
            _r("{{ n|number(0) }}|{{ x|number(0) }}|{{ 'abc   def'|truncate(8) }}|{{ 7.0 / 2 }}|{{ x / 3 }}", x=0.1, n=Decimal("-0.4")),
            _r("[{{ 0|default('z') }}][{{ 0|default('z', true) }}][{{ ''|default('z', boolean=true) }}][{{ none|default('n') }}]"),
            _r("{{ [1, 2, 3]|batch(1) }}|{{ 1|round(12) }}|{{ 2|replace(a, b) }}", a=2, b="two"),
            [_render_outcome(source) for source in ("{{ [1]|batch(true) }}", "{{ 1|round(13) }}", "{{ 1|round(true) }}",
                                                     "{{ 'x'|abs }}", "{{ true|abs }}", "{{ x|abs }}")]]


def probe_lexer_and_statement_edges():
    from inkwell import Environment
    chain = {f"t{i}": "{% include 't" + str(i + 1) + "' %}" for i in range(17)}
    chain["t17"] = "end"
    env = Environment(templates=chain)
    sources = ["  {{ x }}  ", "{# it's fine #}ok", '{{ "}}" ~ x }}', "{{ 'x%}' }}", "{{ 'a\nb' }}", '{{ "a}}b" }}',
               "{% set x 1 2 %}"]
    out = [_render_outcome(source, x="X") for source in sources]
    out.append(_outcome(env.render, "t0"))
    out.append(_outcome(env.render, "t1"))
    bad = ["{% for x, %}{% endfor %}", "{% for x y in z %}{% endfor %}", "{% for x %}{% endfor %}", "{% set x = %}",
           "{% set 1 = 2 %}", "{% set x == 1 %}", "{% include 'a' ignore %}", "{% include ignore missing %}",
           "{% for in in xs %}{% endfor %}", "{% for x in xs if %}{% endfor %}"]
    out += [_render_outcome(source, xs=[1]) for source in bad]
    out.append(_r("{% for a, b in [[1, 2]] %}{{ b }}{{ a }}{% endfor %}|{% include 'a' ignore missing %}|{% set y = 2 %}{{ y }}"))
    return out


# --- errors ------------------------------------------------------------------------
def probe_syntax_errors_plain():
    cases = ["a\n{% frob %}", "{% endif %}", "x\n\n{% for x in xs %}\n{{ x }}", "{% if %}x{% endif %}",
             "{% for in xs %}{% endfor %}", "{% for x of xs %}{% endfor %}", "{{ a b }}", "\n{% if x %}{% else y %}{% endif %}",
             "{% if x %}{% endfor %}", "{{ x|'f' }}", "{{ x.1 }}", "{% include %}"]
    return [_render_outcome(source) for source in cases]


def probe_error_lines_multiline_constructs():
    strict = _env(strict=True)
    return [_render_outcome("{# one\ntwo\nthree #}\n{% endfor %}"),
            _render_outcome("{% if\nx\n%}\n{% bogus %}{% endif %}"),
            _render_outcome("{{ 1\n+\n2 }} {{ a b }}"),
            _render_outcome("a\n{{ 'x'\n|upper }}\n{{ nope }}", strict),
            _render_outcome("{{ 1\n+ ghost }}", strict)]


# --- target probes: rounding --------------------------------------------------------
def probe_round_half_up_ties():
    return [_r("{{ 2.345|round(2) }}|{{ 2.5|round }}|{{ 0.125|round(2) }}|{{ x|round(2) }}|{{ y|round(1) }}|{{ z|round(2) }}",
               x=Decimal("-2.345"), y=0.25, z=Decimal("1.0050")),
            _r("{{ (0 - 0.5)|round }}|{{ 4.5|round }}|{{ 0.0625|round(3) }}")]


def probe_number_half_up_ties():
    return [_r("{{ 1234.565|number(2) }}|{{ x|number(1) }}|{{ 2.5|number(0) }}|{{ y|number(2, sep='.', point=',') }}",
               x=Decimal("-1000.25"), y=Decimal("9876543.125"))]


def probe_percent_half_up_ties():
    return [_r("{{ 0.12345|percent(2) }}|{{ 0.005|percent }}|{{ x|percent(2) }}", x=Decimal("0.00125"))]


# --- target probes: operator precedence ---------------------------------------------
def probe_or_and_precedence_output():
    out = []
    for a in (0, "A"):
        for b in (0, "B"):
            for c in (0, "C"):
                out.append(_r("{{ a or b and c }}", a=a, b=b, c=c))
    return out


def probe_or_and_in_conditions():
    source = ("{% if user.admin or user.owner and doc.shared %}edit{% elif doc.public or user.staff and doc.draft %}"
              "view{% else %}deny{% endif %}")
    cases = [({"admin": True, "owner": False, "staff": False}, {"shared": False, "public": False, "draft": False}),
             ({"admin": False, "owner": True, "staff": False}, {"shared": False, "public": True, "draft": False}),
             ({"admin": False, "owner": True, "staff": True}, {"shared": True, "public": False, "draft": False}),
             ({"admin": False, "owner": False, "staff": True}, {"shared": False, "public": False, "draft": True}),
             ({"admin": False, "owner": False, "staff": False}, {"shared": True, "public": True, "draft": False})]
    return [_r(source, user=user, doc=doc) for user, doc in cases]


def probe_or_not_and_mixed():
    rows = [{"v": 1, "hidden": True, "pinned": False}, {"v": 2, "hidden": False, "pinned": False},
            {"v": 3, "hidden": True, "pinned": True}]
    return [_r("{{ a or not b and c }}", a=1, b=0, c=0),
            _r("{{ x == 1 or y == 2 and z == 3 }}", x=1, y=0, z=0),
            _r("{% for r in rows if r.pinned or not r.hidden and r.v > 1 %}{{ r.v }}{% endfor %}", rows=rows),
            _r("{% set flag = a or b and c %}{{ flag }}", a="first", b=1, c=0)]


# --- target probes: line numbers after whitespace control ------------------------------
def probe_trim_syntax_error_line():
    return [_render_outcome("<ul>\n\n  {%- for x in xs -%}\n\n  <li>{{ x }}</li>\n{% endfor %}\n</ul>\n{% endif %}"),
            _render_outcome("a\n\n\n{%- if x %}\nb\n{% frob %}{% endif %}"),
            _render_outcome("{{ x -}}\n\n\n\n{% if y %}never closed")]


def probe_trim_undefined_line_strict():
    env = _env(strict=True)
    return [_render_outcome("Hello\n  {{- name }}\n\n{%- if show -%}\n\n  {{ missing }}\n{%- endif %}", env,
                            name="Ann", show=True),
            _render_outcome("{#- header\n -#}\n\n\n{{ user.name }} {{ total + ghost }}", env, user={"name": "x"}, total=1)]


def probe_trim_error_in_include():
    env = _env(strict=True, templates={"item": "<li>\n  {{- item.name -}}\n</li>\n{{ item.price|number(2) }}",
                                       "list": "{% for item in items -%}\n\n{% include 'item' %}\n{%- endfor %}"})
    return [_outcome(env.render, "list", items=[{"name": "Tea", "price": 4}, {"name": "Cup"}]),
            _outcome(env.render, "list", items=[{"name": "Tea", "price": 4}])]


def probe_trim_token_lines():
    from inkwell.lexer import tokenize
    tokens = tokenize("a\n\n{%- if x -%}\n\n{{ y }}\n{#- c -#}\n\n{% endif %}")
    return [[token.kind, token.line] for token in tokens]
