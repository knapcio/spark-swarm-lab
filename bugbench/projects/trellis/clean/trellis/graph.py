"""The dependency graph of a resolution: install order, tree view and "why".

Install order: every package comes after all of its dependencies.  Among the
packages whose dependencies are all installed, the alphabetically first one
goes next.  A cycle raises :class:`CycleError` listing its members.

Tree view (ASCII)::

    shop
    +-- log 1.4.2 (>=1.0.0, <1.5.0)
    |   \\-- fmt 2.0.1 (>=2.0.0, <3.0.0)
    \\-- web 2.3.0 (>=2.1.0, <3.0.0)
        \\-- fmt 2.0.1 (>=2.0.0, <3.0.0) (*)

Children are listed alphabetically with the constraint that required them
(``any`` for ``*``); a package already shown earlier is marked ``(*)`` and
not expanded again.
"""
import bisect

from .errors import CycleError, UnknownPackage


def dependencies_of(resolution, registry, name):
    """{dependency: constraint} of the chosen release of ``name``."""
    if name not in resolution.versions:
        raise UnknownPackage(f"{name} is not part of the resolution")
    return registry.release(name, resolution.versions[name]).dependencies


def install_order(resolution, registry):
    names = sorted(resolution.versions)
    waiting = {name: len(dependencies_of(resolution, registry, name)) for name in names}
    dependents = {name: [] for name in names}
    for name in names:
        for dep in dependencies_of(resolution, registry, name):
            dependents[dep].append(name)
    ready = [name for name in names if waiting[name] == 0]
    order = []
    while ready:
        name = ready.pop(0)
        order.append(name)
        for dependent in dependents[name]:
            waiting[dependent] -= 1
            if waiting[dependent] == 0:
                bisect.insort(ready, dependent)
    if len(order) != len(names):
        raise CycleError(sorted(name for name in names if waiting[name] > 0))
    return order


def tree(resolution, registry):
    """The tree view as a list of lines."""
    lines, shown = [resolution.root], set()

    def walk(requirements, prefix):
        items = sorted(requirements.items())
        for index, (name, constraint) in enumerate(items):
            last = index == len(items) - 1
            label = f"{name} {resolution.versions[name]} ({'any' if str(constraint) == '*' else constraint})"
            if name in shown:
                lines.append(prefix + ("\\-- " if last else "+-- ") + label + " (*)")
                continue
            shown.add(name)
            lines.append(prefix + ("\\-- " if last else "+-- ") + label)
            walk(dependencies_of(resolution, registry, name), prefix + ("    " if last else "|   "))

    roots = {}
    for name, found in resolution.requirements.items():
        for constraint, source in found:
            if source == resolution.root:
                roots[name] = constraint
                break
    walk(roots, "")
    return lines


def why(resolution, registry, target):
    """Every path from the project to ``target``, as ``"shop -> web 2.3.0 -> fmt 2.0.1"``, sorted."""
    if target not in resolution.versions:
        raise UnknownPackage(f"{target} is not part of the resolution")
    paths = []

    def walk(name, trail):
        if name == target:
            paths.append(" -> ".join(trail))
            return
        for dep in sorted(dependencies_of(resolution, registry, name)):
            step = f"{dep} {resolution.versions[dep]}"
            if step not in trail:
                walk(dep, trail + [step])

    for name in sorted(resolution.versions):
        if any(source == resolution.root for _, source in resolution.requirements[name]):
            walk(name, [resolution.root, f"{name} {resolution.versions[name]}"])
    return sorted(paths)


def reverse_dependencies(resolution, registry):
    """{name: sorted names of the resolved packages that depend on it}."""
    found = {name: [] for name in resolution.versions}
    for name in sorted(resolution.versions):
        for dep in dependencies_of(resolution, registry, name):
            found[dep].append(name)
    return found
