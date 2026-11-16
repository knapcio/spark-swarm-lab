"""Version constraints.

A constraint is one or more alternatives separated by ``||``.  An
alternative is one or more comparators separated by commas; all of them must
hold.

* ``*``: any version.
* ``1.2.3``, ``=1.2.3``, ``==1.2.3``: exactly that version.
* ``1.2.*`` (or the bare partial ``1.2``): ``>=1.2.0, <1.3.0``; ``1.*`` and
  ``1``: ``>=1.0.0, <2.0.0``.
* ``>``, ``>=``, ``<``, ``<=``, ``!=``: missing parts count as zeros, so
  ``<2`` means ``<2.0.0``.
* Caret ``^``: at least the given version and below the next version that
  changes its left-most non-zero part.  ``^1.2.3`` is ``>=1.2.3, <2.0.0``,
  ``^0.2.3`` is ``>=0.2.3, <0.3.0``, ``^0.0.3`` is ``>=0.0.3, <0.0.4``.  With
  missing parts: ``^1.2`` is ``<2.0.0``, ``^0.2`` is ``<0.3.0``, ``^0.0`` is
  ``<0.1.0`` and ``^0`` is ``<1.0.0``.
* Tilde ``~``: ``~1.2.3`` and ``~1.2`` are below ``1.3.0``; ``~1`` is below
  ``2.0.0``.

Pre-releases: a pre-release version satisfies an alternative only when one
of its comparators names a pre-release with the same MAJOR.MINOR.PATCH, so
``>=2.0.0-rc.1`` allows ``2.0.0-rc.3`` but neither ``2.1.0-beta`` nor, for
``^1.0``, ``1.5.0-rc.1``.
"""
from dataclasses import dataclass

from .errors import InvalidConstraint, InvalidVersion
from .version import Version, parse_partial

_OPS = (">=", "<=", "!=", "==", ">", "<", "=")
_TESTS = {">=": lambda v, w: v >= w, "<=": lambda v, w: v <= w, "!=": lambda v, w: v != w, "=": lambda v, w: v == w,
          ">": lambda v, w: v > w, "<": lambda v, w: v < w}


@dataclass(frozen=True)
class Comparator:
    op: str
    version: Version

    def test(self, version):
        return _TESTS[self.op](version, self.version)

    def __str__(self):
        return f"{self.op}{self.version}"


def _padded(numbers, pre=()):
    major, minor, patch = (numbers + [0, 0])[:3]
    return Version(major, minor, patch, pre)


def _next(numbers):
    """The first version after every version that starts with ``numbers``."""
    if len(numbers) == 1:
        return Version(numbers[0] + 1, 0, 0)
    return Version(numbers[0], numbers[1] + 1, 0)


def _caret(numbers, pre):
    major, minor, patch = (numbers + [0, 0])[:3]
    if major > 0 or len(numbers) == 1:
        high = Version(major + 1, 0, 0)
    elif minor > 0 or len(numbers) == 2:
        high = Version(0, minor + 1, 0)
    else:
        high = Version(0, 0, patch + 1)
    return [Comparator(">=", _padded(numbers, pre)), Comparator("<", high)]


def _tilde(numbers, pre):
    return [Comparator(">=", _padded(numbers, pre)), Comparator("<", _next(numbers[:2]))]


def _comparators(text):
    """The comparators of one comma-separated part of a constraint."""
    if text == "*":
        return []
    if text.startswith("^") or text.startswith("~"):
        numbers, pre = parse_partial(text[1:].strip())
        if pre and len(numbers) < 3:
            raise InvalidConstraint(f"pre-release needs a full version: {text!r}")
        return _caret(numbers, pre) if text[0] == "^" else _tilde(numbers, pre)
    for op in _OPS:
        if text.startswith(op):
            numbers, pre = parse_partial(text[len(op):].strip())
            if op in ("=", "==") and len(numbers) < 3:
                return [Comparator(">=", _padded(numbers)), Comparator("<", _next(numbers))]
            return [Comparator("=" if op == "==" else op, _padded(numbers, pre))]
    if text.endswith(".*"):
        numbers, pre = parse_partial(text[:-2])
        if pre or len(numbers) > 2:
            raise InvalidConstraint(f"bad wildcard {text!r}")
        return [Comparator(">=", _padded(numbers)), Comparator("<", _next(numbers))]
    numbers, pre = parse_partial(text)
    if len(numbers) < 3:
        return [Comparator(">=", _padded(numbers)), Comparator("<", _next(numbers))]
    return [Comparator("=", _padded(numbers, pre))]


class Constraint:
    """A parsed constraint; ``allows(version)`` tests a :class:`Version`."""

    def __init__(self, alternatives):
        self.alternatives = tuple(tuple(alternative) for alternative in alternatives)

    @classmethod
    def parse(cls, text):
        if isinstance(text, Constraint):
            return text
        if not isinstance(text, str) or not text.strip():
            raise InvalidConstraint(f"empty constraint: {text!r}")
        alternatives = []
        for alternative in text.split("||"):
            comparators = []
            parts = [part.strip() for part in alternative.split(",")]
            if any(not part for part in parts):
                raise InvalidConstraint(f"empty part in {text!r}")
            for part in parts:
                try:
                    comparators += _comparators(part)
                except InvalidVersion as exc:
                    raise InvalidConstraint(f"bad constraint {part!r}: {exc}") from None
            alternatives.append(comparators)
        return cls(alternatives)

    def allows(self, version):
        version = Version.parse(version)
        for alternative in self.alternatives:
            if not all(comparator.test(version) for comparator in alternative):
                continue
            if version.pre and not any(c.version.pre and c.version.release == version.release for c in alternative):
                continue
            return True
        return False

    def filter(self, versions):
        """The allowed versions, in the given order."""
        return [version for version in versions if self.allows(version)]

    def __str__(self):
        return " || ".join(", ".join(str(c) for c in alternative) or "*" for alternative in self.alternatives)

    def __repr__(self):
        return f"Constraint({str(self)!r})"

    def __eq__(self, other):
        return isinstance(other, Constraint) and self.alternatives == other.alternatives

    def __hash__(self):
        return hash(self.alternatives)
