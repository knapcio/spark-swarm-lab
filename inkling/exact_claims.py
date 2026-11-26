"""Exact checking of arithmetic statements "E = V" (one implementation for the pre-posting note verifier and the S0
checker; the night tree's inkling/exact_claims.py is byte-identical and the S0 report refuses a run whose worker copy
differs).

An expression is evaluated with exact rational arithmetic from a whitelisted Python AST: integer and decimal literals
(as Fractions), + - * / and powers (^ or **, integer exponents up to MAX_EXPONENT, bounded size), unary + and -,
parentheses. No names, no calls, no attributes, no comparisons, no other node types. Multiplication signs x, ×, ·
and the division sign ÷ and the minus sign − are read as * / -. A statement is a chain E1 = E2 = ... = En (n >= 2):
true when every part evaluates and all values are equal; false when every part evaluates and two differ (or a part
divides by zero); unparseable when some part is not a whitelisted expression.

find_equations(text) extracts every maximal run of arithmetic characters (identifiers such as "index0" break a run)
that contains "=" with a digit on both sides, so "75+4*2=83" is checked whole (never as "4*2=83") and "916=4*229=2*458" as one chain.
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


class Unsupported(ValueError):
    pass


def _value(node):
    if isinstance(node, ast.Expression):
        return _value(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float) and not isinstance(node.value, bool):
        return Fraction(str(node.value)) if isinstance(node.value, float) else Fraction(node.value)
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


def evaluate(expr):
    """Exact value of one expression, or raises Unsupported / ZeroDivisionError / SyntaxError."""
    expr = normalize(expr).strip()
    if not expr or len(expr) > 400:
        raise Unsupported('empty or too long')
    return _value(ast.parse(expr, mode='eval'))


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
    """One side of a run without dangling operators and without unmatched parentheses at its ends."""
    side = side.strip()
    while True:
        before = side
        side = re.sub(r'^[\s+*/^.)]+|[\s+\-*/^.(]+$', '', side)
        if side.startswith('(') and side.count('(') > side.count(')'):
            side = side[1:]
        if side.endswith(')') and side.count(')') > side.count('('):
            side = side[:-1]
        if side == before:
            return side


def find_equations(text):
    """Every maximal arithmetic run of text with "=" and digits on both sides of some "=", stripped of dangling
    operators at its ends."""
    out = []
    words = re.sub(r'[^\W\d][\w]*', ' @ ', _X_MUL.sub('*', str(text)))  # identifiers (with digits) break runs
    for m in _RUN.finditer(words):
        run = m.group(0).strip()
        sides = [_balance(x) for x in run.split('=')]
        while sides and not re.search(r'\d', sides[0]):
            sides.pop(0)
        while sides and not re.search(r'\d', sides[-1]):
            sides.pop()
        if len(sides) >= 2 and all(re.search(r'\d', x) for x in sides):
            out.append(' = '.join(sides))
    return out


def looks_arithmetic(text):
    """A statement with "=" and a digit (it claims an exact value): mechanically checkable or tagged UNVERIFIED."""
    return '=' in str(text) and bool(re.search(r'\d', str(text)))


def check_claim(text):
    """(status, equations): status TRUE (every equation run in text evaluates and holds, at least one), FALSE (one
    evaluates and fails), UNPARSEABLE (arithmetic-looking, nothing evaluable or something unparseable) or None (no
    arithmetic statement at all)."""
    runs = find_equations(text)
    results = [(run, check_statement(run)) for run in runs]
    if any(r == FALSE for _, r in results):
        return FALSE, results
    if results and all(r == TRUE for _, r in results):
        return TRUE, results
    if results or looks_arithmetic(text):
        return UNPARSEABLE, results
    return None, results
