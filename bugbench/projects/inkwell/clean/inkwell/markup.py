"""HTML-safe strings.

A :class:`Markup` is a ``str`` that is already safe to insert into HTML.  With
autoescaping on, every value written by ``{{ ... }}`` is escaped unless it is
a ``Markup``.  Operations that combine a ``Markup`` with plain text escape
the plain text first, so the result stays safe.
"""

_REPLACEMENTS = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&#34;"), ("'", "&#39;"))


class Markup(str):
    """A string that must not be escaped again."""

    __slots__ = ()

    def __new__(cls, value=""):
        return super().__new__(cls, value)

    def __add__(self, other):
        if isinstance(other, str):
            return Markup(str.__add__(self, escape(other)))
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, str):
            return Markup(str.__add__(escape(other), self))
        return NotImplemented

    def join(self, items):
        return Markup(str.join(self, (escape(item) for item in items)))

    def __repr__(self):
        return f"Markup({str.__repr__(self)})"


def escape(value):
    """Return ``value`` as Markup, escaping it unless it already is Markup."""
    if isinstance(value, Markup):
        return value
    text = to_text(value)
    for old, new in _REPLACEMENTS:
        text = text.replace(old, new)
    return Markup(text)


def to_text(value):
    """The text form used for output: ``none`` renders as an empty string.

    Booleans render as ``true``/``false`` and everything else uses ``str``.
    Lists render like ``[1, 2]`` using the text form of their items.
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(to_text(item) for item in value) + "]"
    return str(value)
