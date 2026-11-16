"""Split template source into tokens.

A template is plain text with three kinds of constructs::

    {{ expression }}    output
    {% tag ... %}       statement (if, elif, else, endif, for, endfor, set, include)
    {# comment #}       ignored

A ``-`` directly inside a delimiter (``{%-``, ``-%}``, ``{{-``, ``-}}``,
``{#-``, ``-#}``) removes all whitespace, newlines included, from the text on
that side.  Whitespace control changes only the rendered text: every token
keeps the line number of the place where it starts in the original source.

Inside output and tags, the source is split into expression tokens: names,
integer and decimal literals, quoted strings and operators.  Quoted strings
may contain closing delimiters such as ``%}``; they may not span lines.
"""
from dataclasses import dataclass
from decimal import Decimal
import re

from .errors import TemplateSyntaxError

OPENERS = {"{{": "output", "{%": "tag", "{#": "comment"}
CLOSERS = {"output": "}}", "tag": "%}", "comment": "#}"}
OPERATORS = ("//", "==", "!=", "<=", ">=", "(", ")", "[", "]", ",", ".", "|", "=", "<", ">",
             "+", "-", "*", "/", "%", "~")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"\d+(\.\d+)?")
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'"}


@dataclass(frozen=True)
class ExprToken:
    kind: str  # "name", "int", "decimal", "string" or "op"
    value: object
    line: int


@dataclass(frozen=True)
class Token:
    kind: str  # "text", "output" or "tag"
    value: object  # str for text, a list of ExprToken otherwise
    line: int


def _find_opener(source, pos):
    """Index of the next ``{{``, ``{%`` or ``{#`` at or after ``pos``, or -1."""
    best = -1
    for opener in OPENERS:
        index = source.find(opener, pos)
        if index != -1 and (best == -1 or index < best):
            best = index
    return best


def _find_closer(source, start, kind, line):
    """Index of the delimiter that closes the construct whose body starts at ``start``."""
    closer = CLOSERS[kind]
    if kind == "comment":
        index = source.find(closer, start)
        if index == -1:
            raise TemplateSyntaxError("unclosed comment", line)
        return index
    index, quote = start, None
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif source.startswith(closer, index):
            return index
        index += 1
    raise TemplateSyntaxError(f"missing {closer!r}", line)


def _string(text, index, line):
    """Parse a quoted string starting at ``text[index]``; returns (value, next index)."""
    quote, chars, index = text[index], [], index + 1
    while index < len(text):
        char = text[index]
        if char == "\n":
            break
        if char == "\\" and index + 1 < len(text):
            escaped = text[index + 1]
            if escaped not in _ESCAPES:
                raise TemplateSyntaxError(f"unknown escape \\{escaped}", line)
            chars.append(_ESCAPES[escaped])
            index += 2
            continue
        if char == quote:
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    raise TemplateSyntaxError("unterminated string literal", line)


def lex_expression(text, line):
    """Expression tokens of one output or tag body that starts on ``line``."""
    items, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
            continue
        if char.isspace():
            index += 1
            continue
        match = _NAME.match(text, index)
        if match:
            items.append(ExprToken("name", match.group(), line))
            index = match.end()
            continue
        match = _NUMBER.match(text, index)
        if match:
            raw = match.group()
            if match.group(1):
                items.append(ExprToken("decimal", Decimal(raw), line))
            else:
                items.append(ExprToken("int", int(raw), line))
            index = match.end()
            continue
        if char in "\"'":
            value, index = _string(text, index, line)
            items.append(ExprToken("string", value, line))
            continue
        for operator in OPERATORS:
            if text.startswith(operator, index):
                items.append(ExprToken("op", operator, line))
                index += len(operator)
                break
        else:
            raise TemplateSyntaxError(f"unexpected character {char!r}", line)
    return items


def tokenize(source):
    """Tokens of ``source`` in order; comments are dropped and text tokens are never empty."""
    tokens, pos, line, trim_next = [], 0, 1, False
    while True:
        stop = _find_opener(source, pos)
        if stop == -1:
            stop = len(source)
        text = source[pos:stop]
        if trim_next:
            text = text.lstrip()
        if stop < len(source) and source.startswith("-", stop + 2):
            text = text.rstrip()
        if text:
            tokens.append(Token("text", text, line))
        line += source.count("\n", pos, stop)
        if stop == len(source):
            return tokens
        kind = OPENERS[source[stop:stop + 2]]
        body = stop + 3 if source.startswith("-", stop + 2) else stop + 2
        close = _find_closer(source, body, kind, line)
        trim_next = close > body and source[close - 1] == "-"
        if kind != "comment":
            items = lex_expression(source[body:close - 1 if trim_next else close], line)
            if kind == "tag" and (not items or items[0].kind != "name"):
                raise TemplateSyntaxError("expected a tag name", line)
            if kind == "output" and not items:
                raise TemplateSyntaxError("empty output expression", line)
            tokens.append(Token(kind, items, line))
        line += source.count("\n", stop, close)
        pos = close + 2
