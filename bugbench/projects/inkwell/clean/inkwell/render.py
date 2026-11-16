"""Evaluate expressions and render statement nodes.

Arithmetic accepts ``int``, ``float`` and ``Decimal`` (never ``bool``); ``/``
on two integers gives a ``Decimal``.  ``~`` joins the text form of both
sides.  Comparisons of values that cannot be ordered, division by zero and
other operand problems raise :class:`~inkwell.errors.TemplateError` with the
line of the operator.
"""
from decimal import Decimal, DivisionByZero, InvalidOperation
import operator

from .context import LoopInfo, Undefined, truthy
from .errors import TemplateError, TemplateNotFound
from .expr import Attr, Binary, Filter, Item, ListLit, Literal, Name, Unary
from .markup import to_text
from .parser import For, If, Include, Output, Set, Text

_ARITHMETIC = {"+": operator.add, "-": operator.sub, "*": operator.mul, "//": operator.floordiv,
               "%": operator.mod}
_COMPARE = {"==": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
            ">": operator.gt, ">=": operator.ge}


def _number(value, line, ctx):
    ctx.require(value, line)
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TemplateError(f"expected a number, got {type(value).__name__}", line, ctx.name)
    return value


def _binary(node, ctx):
    op = node.op
    if op in ("and", "or"):
        left = evaluate(node.left, ctx)
        if truthy(left) == (op == "or"):
            return left
        return evaluate(node.right, ctx)
    left, right = evaluate(node.left, ctx), evaluate(node.right, ctx)
    if op == "~":
        return to_text(ctx.require(left, node.line)) + to_text(ctx.require(right, node.line))
    if op in ("in", "not in"):
        container = ctx.require(right, node.line)
        try:
            found = ctx.require(left, node.line) in container
        except TypeError:
            raise TemplateError(f"cannot test membership in {type(container).__name__}", node.line, ctx.name)
        return found if op == "in" else not found
    if op in _COMPARE:
        left, right = ctx.require(left, node.line), ctx.require(right, node.line)
        try:
            return _COMPARE[op](left, right)
        except TypeError:
            raise TemplateError(f"cannot compare {type(left).__name__} and {type(right).__name__}",
                                node.line, ctx.name)
    left, right = _number(left, node.line, ctx), _number(right, node.line, ctx)
    try:
        if op == "/":
            if isinstance(left, float) or isinstance(right, float):
                return left / right
            return Decimal(left) / Decimal(right)
        return _ARITHMETIC[op](left, right)
    except (ZeroDivisionError, DivisionByZero, InvalidOperation):
        raise TemplateError("division by zero", node.line, ctx.name)
    except TypeError:
        raise TemplateError(f"unsupported operands for {op!r}", node.line, ctx.name)


def evaluate(node, ctx):
    """The value of expression ``node`` in ``ctx``."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Name):
        return ctx.lookup(node.name, node.line)
    if isinstance(node, Attr):
        return ctx.attribute(evaluate(node.obj, ctx), node.name, node.line)
    if isinstance(node, Item):
        return ctx.item(evaluate(node.obj, ctx), evaluate(node.key, ctx), node.line)
    if isinstance(node, ListLit):
        return [evaluate(item, ctx) for item in node.items]
    if isinstance(node, Unary):
        value = evaluate(node.operand, ctx)
        if node.op == "not":
            return not truthy(value)
        return -_number(value, node.line, ctx)
    if isinstance(node, Binary):
        return _binary(node, ctx)
    if isinstance(node, Filter):
        value = evaluate(node.value, ctx)
        args = [evaluate(arg, ctx) for arg in node.args]
        kwargs = {name: evaluate(arg, ctx) for name, arg in node.kwargs}
        return ctx.env.call_filter(node.name, value, args, kwargs, node.line, ctx)
    raise TypeError(f"not an expression node: {node!r}")


def _bind(ctx, frame, targets, item, line):
    if len(targets) == 1:
        frame[targets[0]] = item
        return
    try:
        values = list(item)
    except TypeError:
        values = None
    if values is None or len(values) != len(targets):
        raise TemplateError(f"cannot unpack {to_text(item)!r} into {len(targets)} names", line, ctx.name)
    frame.update(zip(targets, values))


def _iterate(node, ctx):
    value = ctx.require(evaluate(node.iterable, ctx), node.line)
    if isinstance(value, Undefined):
        return []
    if isinstance(value, (str, int, float, Decimal)) or value is None:
        raise TemplateError(f"cannot iterate over {type(value).__name__}", node.line, ctx.name)
    items = list(value)
    if node.condition is None:
        return items
    kept = []
    for item in items:
        frame = ctx.push()
        try:
            _bind(ctx, frame, node.targets, item, node.line)
            if truthy(evaluate(node.condition, ctx)):
                kept.append(item)
        finally:
            ctx.pop()
    return kept


def render_nodes(nodes, ctx, out):
    """Append the rendered text of ``nodes`` to the list ``out``."""
    for node in nodes:
        if isinstance(node, Text):
            out.append(node.text)
        elif isinstance(node, Output):
            out.append(ctx.env.finalize(ctx.require(evaluate(node.expr, ctx))))
        elif isinstance(node, If):
            for condition, body in node.branches:
                if truthy(evaluate(condition, ctx)):
                    render_nodes(body, ctx, out)
                    break
            else:
                render_nodes(node.else_body, ctx, out)
        elif isinstance(node, For):
            items = _iterate(node, ctx)
            if not items:
                render_nodes(node.else_body, ctx, out)
            for index, item in enumerate(items):
                frame = ctx.push({"loop": LoopInfo(index, len(items))})
                try:
                    _bind(ctx, frame, node.targets, item, node.line)
                    render_nodes(node.body, ctx, out)
                finally:
                    ctx.pop()
        elif isinstance(node, Set):
            ctx.set(node.target, evaluate(node.expr, ctx))
        elif isinstance(node, Include):
            _include(node, ctx, out)
        else:
            raise TypeError(f"not a statement node: {node!r}")


def _include(node, ctx, out):
    name = ctx.require(evaluate(node.template, ctx), node.line)
    if not isinstance(name, str):
        raise TemplateError("include needs a template name string", node.line, ctx.name)
    try:
        template = ctx.env.get_template(name)
    except TemplateNotFound:
        if node.ignore_missing:
            return
        raise
    render_nodes(template.nodes, ctx.derive(name), out)
