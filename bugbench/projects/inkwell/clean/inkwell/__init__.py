"""inkwell: a small text template engine with filters, loops, includes and autoescaping."""
from .environment import Environment, Template
from .errors import (FilterError, InkwellError, TemplateError, TemplateNotFound, TemplateSyntaxError,
                     UndefinedError)
from .markup import Markup, escape

__version__ = "0.3.0"
__all__ = ["Environment", "FilterError", "InkwellError", "Markup", "Template", "TemplateError",
           "TemplateNotFound", "TemplateSyntaxError", "UndefinedError", "escape", "render_string"]


def render_string(source, variables=None, **kwargs):
    """Render ``source`` once with a default (lenient, non-escaping) environment."""
    return Environment().from_string(source).render(variables, **kwargs)
