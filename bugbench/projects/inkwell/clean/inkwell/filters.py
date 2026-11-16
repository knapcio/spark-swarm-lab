"""Built-in filters.

Number filters accept ``int``, ``float``, ``Decimal`` and numeric strings
(never ``bool``) and work in exact decimal arithmetic; a float is converted
through its shortest ``repr``.  Every rounding filter rounds half up, that
is, a final 5 rounds away from zero: ``2.345|round(2)`` is ``2.35`` and
``-0.5|round`` is ``-1``.  A result that rounds to zero never shows a minus
sign.

Sorting is stable: items that compare equal keep their input order, also with
``reverse=true``.  Strings sort case-insensitively unless
``case_sensitive=true``.
"""
import decimal
from decimal import Decimal

from .context import Undefined
from .errors import FilterError
from .markup import Markup, escape, to_text


def needs_env(function):
    """Mark a filter that receives the environment as its first argument."""
    function.needs_env = True
    return function


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise FilterError(f"not a number: {to_text(value)!r}")
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except decimal.InvalidOperation:
        raise FilterError(f"not a number: {value!r}") from None
    if not number.is_finite():
        raise FilterError(f"not a finite number: {value!r}")
    return number


def _places(places):
    if isinstance(places, bool) or not isinstance(places, int) or not 0 <= places <= 12:
        raise FilterError("places must be an int from 0 to 12")
    return places


def _quantize(value, places):
    exponent = Decimal(1).scaleb(-_places(places))
    result = _decimal(value).quantize(exponent, rounding=decimal.ROUND_HALF_UP)
    return result.copy_abs() if result.is_zero() else result


def _same_kind(original, text):
    return Markup(text) if isinstance(original, Markup) else text


def _attr(item, path):
    for part in str(path).split("."):
        if isinstance(item, dict) and part in item:
            item = item[part]
        elif not isinstance(item, dict) and not part.startswith("_") and hasattr(item, part):
            item = getattr(item, part)
        else:
            raise FilterError(f"item has no attribute {part!r}")
    return item


def _sort_key(case_sensitive):
    def key(value):
        return value.lower() if isinstance(value, str) and not case_sensitive else value
    return key


# --- numbers -------------------------------------------------------------------
def do_round(value, places=0):
    """Round to ``places`` decimals, half up; returns a Decimal."""
    return _quantize(value, places)


def do_number(value, places=2, sep=",", point="."):
    """Fixed decimals, half up, with ``sep`` between groups of three digits."""
    rounded = _quantize(value, places)
    digits = f"{rounded.copy_abs():f}"
    whole, _, fraction = digits.partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    text = sep.join(groups) + (point + fraction if fraction else "")
    return ("-" if rounded < 0 else "") + text


def do_percent(value, places=0):
    """``0.125|percent(1)`` is ``12.5%``: the value times 100, half up."""
    return do_number(_decimal(value) * 100, places) + "%"


def do_int(value):
    """Integer part, truncated toward zero."""
    return int(_decimal(value))


def do_abs(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise FilterError("abs needs a number")
    return abs(value)


def do_sum(value, attribute=None, start=0):
    total = start
    for item in value:
        total = total + (_attr(item, attribute) if attribute is not None else item)
    return total


# --- text ----------------------------------------------------------------------
def do_upper(value):
    return _same_kind(value, to_text(value).upper())


def do_lower(value):
    return _same_kind(value, to_text(value).lower())


def do_capitalize(value):
    text = to_text(value)
    return _same_kind(value, text[:1].upper() + text[1:].lower())


def do_title(value):
    """Upper-case the first letter of every space-separated word."""
    words = to_text(value).split(" ")
    return _same_kind(value, " ".join(word[:1].upper() + word[1:].lower() for word in words))


def do_trim(value):
    return _same_kind(value, to_text(value).strip())


def do_replace(value, old, new, count=-1):
    return to_text(value).replace(to_text(old), to_text(new), count)


def do_truncate(value, length=80, end="...", killwords=False):
    """At most ``length`` characters including ``end``; cuts back to a space unless ``killwords``."""
    text = to_text(value)
    if len(text) <= length:
        return text
    keep = text[:max(0, length - len(end))]
    if not killwords and text[len(keep)] != " " and " " in keep:
        keep = keep[:keep.rindex(" ")]
    return keep.rstrip() + end


def do_wordcount(value):
    return len(to_text(value).split())


def do_pluralize(value, singular="", plural="s"):
    return singular if value == 1 else plural


@needs_env
def do_join(env, value, sep="", attribute=None):
    """Join items; with autoescaping, items are escaped and the result is safe."""
    items = [_attr(item, attribute) if attribute is not None else item for item in value]
    if env.autoescape:
        return escape(sep).join(items)
    return to_text(sep).join(to_text(item) for item in items)


def do_escape(value):
    return escape(value)


def do_safe(value):
    return Markup(to_text(value))


def do_default(value, fallback="", boolean=False):
    """``fallback`` for an undefined value, or for any false value with ``boolean=true``."""
    if isinstance(value, Undefined) or (boolean and not value):
        return fallback
    return value


# --- sequences -----------------------------------------------------------------
def do_length(value):
    if not isinstance(value, (str, list, tuple, dict)):
        raise FilterError("length needs a string, list or mapping")
    return len(value)


def do_first(value):
    return next(iter(value), None)


def do_last(value):
    items = list(value)
    return items[-1] if items else None


def do_sort(value, attribute=None, reverse=False, case_sensitive=False):
    key = _sort_key(case_sensitive)
    if attribute is None:
        return sorted(value, key=key, reverse=reverse)
    return sorted(value, key=lambda item: key(_attr(item, attribute)), reverse=reverse)


def do_reverse(value):
    if isinstance(value, str):
        return _same_kind(value, value[::-1])
    return list(value)[::-1]


def do_unique(value, attribute=None):
    """Items in input order, dropping later duplicates."""
    seen, result = [], []
    for item in value:
        marker = _attr(item, attribute) if attribute is not None else item
        if marker not in seen:
            seen.append(marker)
            result.append(item)
    return result


def do_map(value, attribute):
    return [_attr(item, attribute) for item in value]


def do_items(value):
    """``[key, value]`` pairs of a mapping, in insertion order."""
    if not isinstance(value, dict):
        raise FilterError("items needs a mapping")
    return [[key, item] for key, item in value.items()]


def do_batch(value, size, fill=None):
    """Lists of ``size`` items; the last one is padded with ``fill`` unless it is none."""
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise FilterError("batch size must be a positive int")
    items, batches = list(value), []
    for start in range(0, len(items), size):
        batch = items[start:start + size]
        if fill is not None:
            batch += [fill] * (size - len(batch))
        batches.append(batch)
    return batches


FILTERS = {
    "abs": do_abs, "batch": do_batch, "capitalize": do_capitalize, "default": do_default, "e": do_escape,
    "escape": do_escape, "first": do_first, "int": do_int, "items": do_items, "join": do_join,
    "last": do_last, "length": do_length, "lower": do_lower, "map": do_map, "number": do_number,
    "percent": do_percent, "pluralize": do_pluralize, "replace": do_replace, "reverse": do_reverse,
    "round": do_round, "safe": do_safe, "sort": do_sort, "sum": do_sum, "title": do_title,
    "trim": do_trim, "truncate": do_truncate, "unique": do_unique, "upper": do_upper,
    "wordcount": do_wordcount,
}
