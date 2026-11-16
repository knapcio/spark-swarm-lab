"""Template statements and the parser that builds them from tokens.

Statements::

    {% if cond %} ... {% elif cond %} ... {% else %} ... {% endif %}
    {% for item in items %} ... {% else %} ... {% endfor %}
    {% for key, value in mapping|items if value > 0 %} ... {% endfor %}
    {% set name = expression %}
    {% include "name" %}   {% include name_expression ignore missing %}

The ``else`` part of a ``for`` runs when no item is left after the optional
``if`` filter.  Syntax errors point at the offending token; a block that is
never closed is reported at the line of its opening tag.
"""
from dataclasses import dataclass

from .errors import TemplateSyntaxError
from .expr import KEYWORDS, ExpressionParser, parse_expression

END_TAGS = frozenset({"elif", "else", "endif", "endfor"})


@dataclass(frozen=True)
class Text:
    text: str
    line: int


@dataclass(frozen=True)
class Output:
    expr: object
    line: int


@dataclass(frozen=True)
class If:
    branches: tuple  # ((condition, body), ...)
    else_body: tuple
    line: int


@dataclass(frozen=True)
class For:
    targets: tuple
    iterable: object
    condition: object
    body: tuple
    else_body: tuple
    line: int


@dataclass(frozen=True)
class Set:
    target: str
    expr: object
    line: int


@dataclass(frozen=True)
class Include:
    template: object
    ignore_missing: bool
    line: int


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0
        self.handlers = {"if": self._if, "for": self._for, "set": self._set, "include": self._include}

    def parse(self):
        nodes, end = self._block(())
        return nodes

    def _block(self, stop):
        """Nodes up to a tag named in ``stop``; returns (nodes, that tag token or None at the end)."""
        nodes = []
        while self.index < len(self.tokens):
            token = self.tokens[self.index]
            if token.kind == "text":
                nodes.append(Text(token.value, token.line))
                self.index += 1
                continue
            if token.kind == "output":
                nodes.append(Output(parse_expression(token.value, token.line), token.line))
                self.index += 1
                continue
            tag = token.value[0].value
            if tag in stop:
                return tuple(nodes), token
            self.index += 1
            if tag in END_TAGS:
                raise TemplateSyntaxError(f"unexpected {tag!r}", token.line)
            handler = self.handlers.get(tag)
            if handler is None:
                raise TemplateSyntaxError(f"unknown tag {tag!r}", token.line)
            nodes.append(handler(token))
        return tuple(nodes), None

    def _close(self, opener, stop):
        body, end = self._block(stop)
        if end is None:
            raise TemplateSyntaxError(f"unclosed {opener.value[0].value!r}", opener.line)
        self.index += 1
        return body, end

    @staticmethod
    def _no_arguments(token):
        if len(token.value) > 1:
            raise TemplateSyntaxError(f"{token.value[0].value!r} takes no arguments", token.value[1].line)

    def _if(self, token):
        branches = []
        condition = parse_expression(token.value[1:], token.line)
        while True:
            body, end = self._close(token, ("elif", "else", "endif"))
            branches.append((condition, body))
            name = end.value[0].value
            if name == "elif":
                condition = parse_expression(end.value[1:], end.line)
                continue
            else_body = ()
            if name == "else":
                self._no_arguments(end)
                else_body, end = self._close(token, ("endif",))
            self._no_arguments(end)
            return If(tuple(branches), else_body, token.line)

    def _for(self, token):
        items, pos, targets = token.value, 1, []
        while True:
            if pos >= len(items) or items[pos].kind != "name" or items[pos].value in KEYWORDS:
                raise TemplateSyntaxError("expected a loop variable", token.line)
            targets.append(items[pos].value)
            pos += 1
            if pos < len(items) and items[pos].kind == "op" and items[pos].value == ",":
                pos += 1
                continue
            break
        if pos >= len(items) or items[pos].kind != "name" or items[pos].value != "in":
            raise TemplateSyntaxError("expected 'in' after the loop variables", token.line)
        parser = ExpressionParser(items[pos + 1:], token.line)
        iterable, condition = parser.parse(), None
        if parser.is_word("if"):
            parser.next()
            condition = parser.parse()
        parser.fail_unless_end()
        body, end = self._close(token, ("else", "endfor"))
        else_body = ()
        if end.value[0].value == "else":
            self._no_arguments(end)
            else_body, end = self._close(token, ("endfor",))
        self._no_arguments(end)
        return For(tuple(targets), iterable, condition, body, else_body, token.line)

    def _set(self, token):
        items = token.value
        if len(items) < 4 or items[1].kind != "name" or items[1].value in KEYWORDS \
                or items[2].kind != "op" or items[2].value != "=":
            raise TemplateSyntaxError("expected 'set name = expression'", token.line)
        return Set(items[1].value, parse_expression(items[3:], token.line), token.line)

    def _include(self, token):
        items, ignore = list(token.value[1:]), False
        if len(items) >= 2 and items[-2].kind == "name" and items[-2].value == "ignore" \
                and items[-1].kind == "name" and items[-1].value == "missing":
            items, ignore = items[:-2], True
        if not items:
            raise TemplateSyntaxError("include needs a template name", token.line)
        return Include(parse_expression(items, token.line), ignore, token.line)


def parse(tokens):
    """Statement nodes for a token list produced by :func:`inkwell.lexer.tokenize`."""
    return Parser(tokens).parse()
