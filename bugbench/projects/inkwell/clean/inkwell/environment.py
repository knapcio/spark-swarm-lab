"""Environment (configuration, template store, filters) and compiled templates."""
from .context import Context
from .errors import FilterError, InkwellError, TemplateError, TemplateNotFound
from .filters import FILTERS
from .lexer import tokenize
from .markup import escape, to_text
from .parser import parse
from .render import render_nodes


class Environment:
    """Shared settings for a family of templates.

    ``templates`` maps names to source text and backs ``get_template`` and
    ``include``.  ``autoescape`` escapes every ``{{ ... }}`` value that is not
    :class:`~inkwell.markup.Markup`.  ``strict`` turns undefined values into
    errors (see :mod:`inkwell.context`).  ``globals`` are visible to every
    template, below the variables passed to ``render``.
    """

    def __init__(self, templates=None, *, autoescape=False, strict=False, globals=None, filters=None):
        self.templates = dict(templates or {})
        self.autoescape = autoescape
        self.strict = strict
        self.globals = dict(globals or {})
        self.filters = dict(FILTERS)
        for name, function in (filters or {}).items():
            self.add_filter(name, function)
        self._cache = {}

    def add_filter(self, name, function):
        if not isinstance(name, str) or not name.isidentifier() or not callable(function):
            raise InkwellError("a filter needs an identifier name and a callable")
        self.filters[name] = function

    def add_template(self, name, source):
        """Add or replace a named template; a replaced template is parsed again on next use."""
        self.templates[name] = source
        self._cache.pop(name, None)

    def get_template(self, name):
        if name not in self._cache:
            if name not in self.templates:
                raise TemplateNotFound(name)
            self._cache[name] = Template(self, self.templates[name], name)
        return self._cache[name]

    def from_string(self, source):
        return Template(self, source, None)

    def render(self, name, variables=None, **kwargs):
        return self.get_template(name).render(variables, **kwargs)

    def finalize(self, value):
        """The text written for one ``{{ ... }}`` value."""
        return escape(value) if self.autoescape else to_text(value)

    def call_filter(self, name, value, args, kwargs, line, ctx):
        function = self.filters.get(name)
        if function is None:
            raise FilterError(f"unknown filter {name!r}", line, ctx.name)
        if name != "default":
            ctx.require(value, line)
        args = [ctx.require(arg, line) for arg in args]
        kwargs = {key: ctx.require(arg, line) for key, arg in kwargs.items()}
        try:
            if getattr(function, "needs_env", False):
                return function(self, value, *args, **kwargs)
            return function(value, *args, **kwargs)
        except FilterError as exc:
            if exc.line is None:
                exc.line = line
            raise exc.locate(ctx.name)
        except TemplateError:
            raise
        except (TypeError, ValueError, ArithmeticError, LookupError) as exc:
            raise FilterError(f"{name}: {exc}", line, ctx.name) from exc


class Template:
    """A parsed template.  Syntax errors are raised when it is created."""

    def __init__(self, env, source, name):
        self.env = env
        self.name = name
        self.source = source
        try:
            self.nodes = parse(tokenize(source))
        except TemplateError as exc:
            raise exc.locate(name or "<string>")

    def render(self, variables=None, **kwargs):
        """Render with ``variables`` (a mapping, not modified) plus keyword variables."""
        values = dict(variables or {})
        values.update(kwargs)
        ctx = Context.root(self.env, values, self.name or "<string>")
        out = []
        try:
            render_nodes(self.nodes, ctx, out)
        except TemplateError as exc:
            raise exc.locate(ctx.name)
        return "".join(out)
