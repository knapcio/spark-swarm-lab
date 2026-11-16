# inkwell

A small text template engine: output expressions with filters, `if`/`for`
statements, `set`, includes, whitespace control, optional HTML autoescaping
and a strict mode for undefined variables. Standard library only, Python 3.10+.

```python
from inkwell import Environment

env = Environment({"row": "{{ item.name }}: {{ item.price|number(2) }}"}, autoescape=True)
page = env.from_string("{% for item in items if item.price > 0 %}{% include 'row' %}\n{% endfor %}")
print(page.render(items=[{"name": "Tea", "price": 4.5}]))
```

## Modules

| Module | Responsibility |
|---|---|
| `lexer.py` | Splits source into text, output and tag tokens with line numbers |
| `expr.py` | Expression syntax tree, operator precedence, expression parser |
| `parser.py` | Statement nodes (`if`, `for`, `set`, `include`) and the template parser |
| `context.py` | Scopes, `Undefined`, strict mode, `loop` information |
| `render.py` | Expression evaluation and statement rendering |
| `filters.py` | Built-in filters |
| `markup.py` | `Markup` safe strings and HTML escaping |
| `environment.py` | `Environment`, template store and cache, `Template` |
| `errors.py` | Exception hierarchy |

## Language rules

- `{{ expr }}` writes a value; `none` writes nothing, booleans write `true`/`false`.
- Operators from lowest to highest: `or`, `and`, `not`, comparisons and `in`,
  `~`, `+ -`, `* / // %`, unary minus, then `.attr`, `[key]` and `|filter`.
  `a or b and c` means `a or (b and c)`, as in Python.
- `{% for x in items if cond %}` filters before looping; `loop.index`,
  `loop.index0`, `loop.revindex`, `loop.first`, `loop.last` and `loop.length`
  describe the filtered sequence. `{% else %}` runs when nothing is left.
- `set` binds in the innermost scope: a `set` inside a loop body lasts for that
  iteration only. Included templates see the includer's variables, and their
  own `set` does not leak back.
- A `-` inside a delimiter (`{%-`, `-%}`, `{{-`, `-}}`, `{#-`, `-#}`) strips all
  whitespace, newlines included, on that side.
- Every rounding filter (`round`, `number`, `percent`) rounds half up: a
  final 5 rounds away from zero, so `2.345|round(2)` is `2.35`.
- Errors carry the template name and the 1-based line in the original source
  where the problem is. Whitespace control never changes reported line numbers.
- Strict environments raise `UndefinedError` when an undefined value is
  written, iterated, filtered (except by `default`), used in a comparison or
  arithmetic, or has an attribute looked up. Testing it in `if` is allowed
  and false.

Run the tests with `python -m unittest discover -s tests`.
