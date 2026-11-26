"""Exact checking of arithmetic statements "E = V" (one implementation for the pre-posting note verifier and the S0
checker; the night tree's inkling/exact_claims.py is byte-identical and the S0 report refuses a run whose worker copy
differs).

An expression is evaluated with exact rational arithmetic from a whitelisted Python AST: integer literals and decimal
literals (taken EXACTLY from their source text: 0.10000000000000001 is 10000000000000001/10^17, never a float), + - *
/ and powers (^ or **, integer exponents up to MAX_EXPONENT, bounded size), unary + and -, parentheses. No names, no
calls, no attributes, no comparisons, no float or exponent literals, no other node types. Multiplication signs x, ×, ·
and the division sign ÷ and the minus sign − are read as * / -. A statement is a chain E1 = E2 = ... = En (n >= 2):
true when every part evaluates and all values are equal; false when every part evaluates and two differ (or a part
divides by zero); unparseable when some part is not a whitelisted expression.

find_equations(text) extracts every maximal run of arithmetic characters that contains "=" (so "75+4*2=83" is checked
whole, never as "4*2=83", and "916=4*229=2*458" as one chain) and reports whether a run is ATTACHED to a name: a
name directly before or after it, or joined to it by an operator, "=" or a call parenthesis ("sqrt(4) = 4",
"x = 5 + 3", "index0=9", "2 = 5 - y"). check_claim never checks a sub-span of an attached run: such a statement is
UNPARSEABLE as a whole (unless another, clean equation of it is false).
"""
import ast
import re
from fractions import Fraction

MAX_EXPONENT = 64
MAX_DIGITS = 2000          # bound on intermediate numerator/denominator size (digits)
TRUE, FALSE, UNPARSEABLE = 'true', 'false', 'unparseable'
_SIGNS = str.maketrans({'×': '*', '·': '*', '÷': '/', '−': '-', '–': '-', '^': '^'})
_RUN = re.compile(r'[0-9.()+\-*/^×·÷−–=\s]+')
_X_MUL = re.compile(r'(?<=[0-9)])\s*[xX]\s*(?=[0-9(])')


_DECIMAL = re.compile(r'(?<![\w.])(\d+)\.(\d+)(?![\w.])')
_NAME = re.compile(r'[^\W\d][\w]*')
_OPS = '+-*/^=(×·÷−–'


class Unsupported(ValueError):
    pass


def _value(node):
    if isinstance(node, ast.Expression):
        return _value(node.body)
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return Fraction(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _value(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        a, b = _value(node.left), _value(node.right)
        if isinstance(node.op, ast.Add):
            out = a + b
        elif isinstance(node.op, ast.Sub):
            out = a - b
        elif isinstance(node.op, ast.Mult):
            out = a * b
        elif isinstance(node.op, ast.Div):
            if b == 0:
                raise ZeroDivisionError('division by zero')
            out = a / b
        else:
            if b.denominator != 1 or abs(b) > MAX_EXPONENT or (a == 0 and b < 0):
                raise Unsupported('exponent')
            out = a ** int(b)
        if len(str(out.numerator)) > MAX_DIGITS or len(str(out.denominator)) > MAX_DIGITS:
            raise Unsupported('number too large')
        return out
    raise Unsupported(type(node).__name__)


def normalize(text):
    text = _X_MUL.sub('*', str(text)).translate(_SIGNS)
    return text.replace('^', '**')


def _exact_decimals(expr):
    """Decimal literals as exact integer ratios from their digits (no float ever)."""
    return _DECIMAL.sub(lambda m: f'({int(m.group(1) + m.group(2))}/1{"0" * len(m.group(2))})', expr)


def evaluate(expr):
    """Exact value of one expression, or raises Unsupported / ZeroDivisionError / SyntaxError."""
    expr = normalize(expr).strip()
    if not expr or len(expr) > 400:
        raise Unsupported('empty or too long')
    return _value(ast.parse(_exact_decimals(expr), mode='eval'))


def check_statement(text):
    """TRUE / FALSE / UNPARSEABLE for a chain "E1 = E2 [= ...]"."""
    text = normalize(text)
    if re.search(r'[<>!]=|==', text):
        return UNPARSEABLE
    parts = text.split('=')
    if len(parts) < 2:
        return UNPARSEABLE
    values = []
    for part in parts:
        try:
            values.append(evaluate(part))
        except ZeroDivisionError:
            return FALSE
        except (Unsupported, SyntaxError, ValueError, TypeError, OverflowError, RecursionError, MemoryError):
            return UNPARSEABLE
    return TRUE if all(v == values[0] for v in values) else FALSE


def _balance(side):
    """One side of a run without surrounding whitespace, trailing sentence punctuation and unmatched parentheses at
    its ends (operators are never stripped: a dangling operator makes the side unparseable)."""
    side = side.strip()
    while True:
        before = side
        side = side.strip().rstrip('.')
        if side.startswith('(') and side.count('(') > side.count(')'):
            side = side[1:]
        if side.endswith(')') and side.count(')') > side.count('('):
            side = side[:-1]
        if side == before:
            return side


def scan(text):
    """[(run, attached)] for every arithmetic run of text that contains "=" and a digit."""
    text = _X_MUL.sub('*', str(text))
    masked = _NAME.sub(lambda m: '@' * len(m.group(0)), text)  # names keep their positions
    out = []
    for m in _RUN.finditer(masked):
        raw = m.group(0)
        if '=' not in raw or not re.search(r'\d', raw):
            continue
        start, end = m.start(), m.end()
        while start < end and (masked[start].isspace() or (masked[start] == '.' and not masked[start + 1:start + 2].isdigit())):
            start += 1  # sentence punctuation, not a decimal point
        while end > start and (masked[end - 1].isspace() or masked[end - 1] in '.,'):
            end -= 1
        if start >= end:
            continue
        core = masked[start:end]
        before = masked[:start].rstrip()
        after = masked[end:].lstrip()
        name_before = before.endswith('@')
        name_after = after.startswith('@')
        attached = ((name_before and (core[0] in _OPS or start == len(before)))
                    or (name_after and (core[-1] in _OPS or masked[end:end + 1] == '@')))
        out.append((text[start:end], attached))
    return out


def find_equations(text):
    """The clean (not attached) equation runs of text, as checked by check_statement."""
    out = []
    for run, attached in scan(text):
        if attached:
            continue
        sides = [_balance(x) for x in run.split('=')]
        out.append(' = '.join(sides))
    return out


def looks_arithmetic(text):
    """A statement with "=" and a digit (it claims an exact value): mechanically checkable or tagged UNVERIFIED."""
    return '=' in str(text) and bool(re.search(r'\d', str(text)))


def check_claim(text):
    """(status, equations): FALSE if a clean equation run evaluates and fails; else UNPARSEABLE if some run is attached
    to a name or does not parse, or the text only looks arithmetic; else TRUE if there is at least one equation (all
    hold); None if there is no arithmetic statement at all. Sub-spans of a run are never checked."""
    runs = scan(text)
    results = []
    for run, attached in runs:
        if attached:
            results.append((run, UNPARSEABLE))
            continue
        sides = [_balance(x) for x in run.split('=')]
        results.append((' = '.join(sides), UNPARSEABLE if any(not x for x in sides) else check_statement('='.join(sides))))
    if any(r == FALSE for _, r in results):
        return FALSE, results
    if results and all(r == TRUE for _, r in results):
        return TRUE, results
    if results or looks_arithmetic(text):
        return UNPARSEABLE, results
    return None, results
