"""Tokenizer for the SQL dialect.

Keywords and identifiers are case-insensitive; identifiers are returned in
lower case.  Strings use single quotes, with ``''`` for a quote inside.
Numbers are integers (``42``) or decimals with digits on both sides of the
dot (``4.5``).  ``--`` starts a comment that runs to the end of the line.
"""
from dataclasses import dataclass

from .errors import SqlSyntaxError

KEYWORDS = frozenset("""
    SELECT DISTINCT FROM WHERE GROUP BY HAVING ORDER ASC DESC LIMIT OFFSET AS AND OR NOT IS NULL IN BETWEEN LIKE
    JOIN INNER LEFT ON CREATE TABLE DROP INSERT INTO VALUES DELETE UPDATE SET PRIMARY KEY TRUE FALSE
    INTEGER REAL TEXT BOOLEAN
""".split())
OPERATORS = ("<>", "!=", "<=", ">=", "||", "=", "<", ">", "+", "-", "*", "/", "%")
PUNCTUATION = "(),.;"


@dataclass(frozen=True)
class Token:
    kind: str  # keyword, name, integer, real, string, op, punct, end
    value: object
    position: int

    def is_(self, kind, value=None):
        return self.kind == kind and (value is None or self.value == value)


def _number(text, start):
    index = start
    while index < len(text) and text[index].isdigit():
        index += 1
    if index + 1 < len(text) and text[index] == "." and text[index + 1].isdigit():
        index += 1
        while index < len(text) and text[index].isdigit():
            index += 1
        return Token("real", float(text[start:index]), start), index
    return Token("integer", int(text[start:index]), start), index


def _string(text, start):
    index, parts = start + 1, []
    while True:
        end = text.find("'", index)
        if end == -1:
            raise SqlSyntaxError("unterminated string", start)
        parts.append(text[index:end])
        if text.startswith("''", end):
            parts.append("'")
            index = end + 2
        else:
            return Token("string", "".join(parts), start), end + 1


def tokenize(text):
    """List of tokens ending with an ``end`` token."""
    if not isinstance(text, str):
        raise SqlSyntaxError("statement must be text", 0)
    tokens, index = [], 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif text.startswith("--", index):
            newline = text.find("\n", index)
            index = len(text) if newline == -1 else newline + 1
        elif char.isdigit():
            token, index = _number(text, index)
            tokens.append(token)
        elif char == "'":
            token, index = _string(text, index)
            tokens.append(token)
        elif char.isalpha() or char == "_":
            start = index
            while index < len(text) and (text[index].isalnum() or text[index] == "_"):
                index += 1
            word = text[start:index]
            if word.upper() in KEYWORDS:
                tokens.append(Token("keyword", word.upper(), start))
            else:
                tokens.append(Token("name", word.lower(), start))
        elif char in PUNCTUATION:
            tokens.append(Token("punct", char, index))
            index += 1
        else:
            for op in OPERATORS:
                if text.startswith(op, index):
                    tokens.append(Token("op", "<>" if op == "!=" else op, index))
                    index += len(op)
                    break
            else:
                raise SqlSyntaxError(f"unexpected character {char!r}", index)
    tokens.append(Token("end", None, len(text)))
    return tokens


def split_statements(text):
    """Split a script on ``;`` outside strings and comments; blank statements are dropped."""
    statements, current, index = [], [], 0
    while index < len(text):
        char = text[index]
        if char == "'":
            _, end = _string(text, index)
            current.append(text[index:end])
            index = end
        elif text.startswith("--", index):
            newline = text.find("\n", index)
            index = len(text) if newline == -1 else newline
        elif char == ";":
            statements.append("".join(current))
            current = []
            index += 1
        else:
            current.append(char)
            index += 1
    statements.append("".join(current))
    return [statement.strip() for statement in statements if statement.strip()]
