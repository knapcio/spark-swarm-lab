"""Exception hierarchy for inkwell.

Every error derives from :class:`InkwellError`.  Errors that point at a place
in a template carry ``name`` (the template name, ``"<string>"`` for templates
built with ``from_string``) and ``line`` (1-based line in that template's
source text, counting every newline of the original source).
"""


class InkwellError(Exception):
    """Base class for all errors raised by this package."""


class TemplateError(InkwellError):
    """An error tied to a location in a template."""

    def __init__(self, message, line=None, name=None):
        self.message = message
        self.line = line
        self.name = name
        super().__init__(self._describe())

    def _describe(self):
        where = self.name or "<string>"
        if self.line is not None:
            where += f", line {self.line}"
        return f"{where}: {self.message}"

    def locate(self, name):
        """Fill in the template name if it is still unknown; returns self."""
        if self.name is None:
            self.name = name
            self.args = (self._describe(),)
        return self


class TemplateSyntaxError(TemplateError):
    """The template text cannot be tokenized or parsed."""


class UndefinedError(TemplateError):
    """A strict environment met a variable or attribute that does not exist."""


class FilterError(TemplateError):
    """A filter is unknown or was called with unusable arguments."""


class TemplateNotFound(InkwellError):
    """The loader has no template with this name."""

    def __init__(self, name):
        super().__init__(f"template {name!r} not found")
        self.name = name
