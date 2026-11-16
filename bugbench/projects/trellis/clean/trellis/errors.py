"""Exception hierarchy for trellis.  All errors derive from :class:`TrellisError`."""


class TrellisError(Exception):
    """Base class for all errors raised by this package."""


class InvalidVersion(TrellisError):
    """A version string is malformed."""


class InvalidConstraint(TrellisError):
    """A version constraint is malformed."""


class UnknownPackage(TrellisError):
    """The registry has no package with this name."""


class DuplicateRelease(TrellisError):
    """The registry already has this version of this package."""


class FileFormatError(TrellisError):
    """A manifest, registry index or lock file line is malformed.

    ``line`` is the 1-based line number; ``source`` says which kind of file.
    """

    def __init__(self, source, line, message):
        super().__init__(f"{source} line {line}: {message}")
        self.source = source
        self.line = line


class CycleError(TrellisError):
    """The resolved packages depend on each other in a cycle; ``members`` lists them."""

    def __init__(self, members):
        super().__init__("dependency cycle among " + ", ".join(members))
        self.members = list(members)


class ResolutionImpossible(TrellisError):
    """No set of versions satisfies all requirements.

    ``lines`` explains the first dead end the resolver met: the package that
    could not be satisfied and every requirement on it, with who required it.
    """

    def __init__(self, lines):
        super().__init__("\n".join(lines))
        self.lines = list(lines)
