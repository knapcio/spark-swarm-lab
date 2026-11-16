"""Hidden behavioural probes for the trellis project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY c8d2f047-bugbench-trellis-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _resolve(index, requirements, locked=None, unlock=(), root="proj"):
    from trellis import ResolutionImpossible, parse_index, resolve
    try:
        resolution = resolve(parse_index(index), root, requirements, locked, unlock)
    except ResolutionImpossible as exc:
        return ["impossible", exc.lines]
    except Exception as exc:  # observation only
        return ["error", type(exc).__name__]
    return [[name, version] for name, version in resolution.as_text().items()]


def _requirements(resolution):
    return {name: [[str(c), source] for c, source in found] for name, found in sorted(resolution.requirements.items())}


MANIFEST = '[project]\nname = "shop"\n[dependencies]\n'


# --- versions and constraints -----------------------------------------------------------
def probe_version_parse_and_order():
    from trellis import Version
    from trellis.version import parse_partial, sort_versions
    texts = ["1.0.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
             "1.0.0-rc.1", "0.0.1", "0.10.0", "0.9.0", "2.0.0-0", "2.0.0-a-b", "10.0.0", "1.0.0-1.2", "1.0.0-1.a"]
    versions = [Version.parse(t) for t in texts]
    out = [[str(v) for v in sorted(versions)], [str(v) for v in sort_versions(texts[:5], newest_first=True)],
           [str(v) for v in sort_versions(texts[:5])]]
    out.append([_error(Version.parse, t) for t in ("1.0", "01.0.0", "1.0.0-", "1.0.0-01", "1.0.0+b", "v1.0.0", "1.0.0-a..b", 7)])
    v = Version.parse(" 3.4.5-rc.2 ")
    out += [str(v), list(v.release), v.is_prerelease, list(v.pre), str(v.next_major()), str(v.next_minor()), str(v.next_patch()),
            Version.parse("1.0.0") == Version(1, 0, 0), Version.parse("1.0.0-1") < Version.parse("1.0.0-a"),
            Version.parse("1.0.0-rc") < Version.parse("1.0.0-rc.0"), Version.parse("1.2.3") >= Version.parse("1.2.3-rc.9"),
            len({Version.parse("1.2.3"), Version(1, 2, 3)}), Version.parse(v) is v, Version(1, 2, 3).__lt__("x") is NotImplemented]
    out.append([[n, list(p)] for n, p in (parse_partial("4"), parse_partial("4.5"), parse_partial("4.5.6-b.1"))])
    out.append([_error(parse_partial, t) for t in ("4.5-b", "x", "", "4.")])
    return out


def probe_constraint_syntax():
    from trellis import Constraint
    texts = ["^1.2.3", "^0.2.3", "^1.2", "^0.2", "^0.0", "^0", "^1", "^2.0.0-rc.1", "~1.2.3", "~1.2", "~1", "~0.0.5",
             "1.2.*", "1.*", "1.2", "1", "*", "1.2.3", "=1.2.3", "==1.2.3", "==1.2", "=2", ">1.2", ">=1", "<2", "<=1.4.2",
             "!=1.3.0", ">=1.0, <2.0 || ^3.1", " >=1.0 ,<1.5|| 2.* ", "1.2.3-rc.1", "* || 1.0.0"]
    out = [str(Constraint.parse(text)) for text in texts]
    out.append([_error(Constraint.parse, t) for t in ("", "  ", ">=1,", "||", "^1.2-rc.1", "~x", "1.2.3.*", "1.2-rc.*",
                                                      ">>1", "1.x", None, "^", "=")])
    first = Constraint.parse("^1.2")
    out += [first == Constraint.parse(">=1.2.0, <2.0.0"), first == "^1.2", hash(first) == hash(Constraint.parse("^1.2.0")),
            repr(first), Constraint.parse(first) is first]
    return out


def probe_constraint_allows():
    from trellis import Constraint, Version
    versions = ["0.9.9", "1.0.0", "1.2.2", "1.2.3", "1.2.9", "1.3.0", "1.9.9", "2.0.0-rc.1", "2.0.0", "2.0.1", "3.0.0"]
    texts = ["^1.2.3", "~1.2.3", "1.2.*", "<2", "<=2.0.0", ">1.2.3", "!=2.0.0", ">=1.0, <2.0 || 3.0.0", "*", "1",
             ">=2.0.0-rc.1", "^2.0.0-rc.1", "^0.9", "=2.0.0-rc.1"]
    out = [[t, [v for v in versions if Constraint.parse(t).allows(v)]] for t in texts]
    pre = Constraint.parse(">=1.0.0-beta.2, <1.1.0 || >=2.1.0-rc.1")
    out.append([pre.allows(v) for v in ("1.0.0-beta.1", "1.0.0-beta.3", "1.0.1-beta.3", "1.0.5", "2.1.0-rc.5", "2.2.0-rc.1", "2.2.0")])
    out.append([str(v) for v in Constraint.parse("^1.0").filter([Version.parse("1.0.1"), Version.parse("2.0.0"), Version.parse("1.9.0")])])
    out.append(_error(Constraint.parse("^1").allows, "nope"))
    return out


# --- registry and file formats ---------------------------------------------------------------
def probe_registry_api():
    from trellis import Registry
    registry = Registry()
    registry.add("web", "2.0.0", {"fmt": "^1"})
    registry.add("web", "1.5.0")
    registry.add("fmt", "1.2.0")
    registry.add("fmt", "1.10.0", yanked=1)
    registry.add("fmt", "1.4.0-rc.1")
    out = [registry.names(), [str(r.version) for r in registry.releases("fmt")], str(registry.newest("fmt").version),
           str(registry.newest("fmt", ">=1.2.1").version) if registry.newest("fmt", ">=1.2.1") else None,
           registry.newest("fmt", ">=2"), "web" in registry, "nope" in registry, str(registry.newest("web").version),
           [[k, str(v)] for k, v in registry.release("web", "2.0.0").dependencies.items()], registry.release("fmt", "1.10.0").yanked]
    out.append([_error(registry.add, *args) for args in (("web", "2.0.0"), ("Web", "1.0.0"), ("web", "2.1"), ("web", "3.0.0", {"web": "*"}),
                                                          ("web", "3.0.0", {"bad name": "*"}), ("web", "3.0.0", {"fmt": "^^1"}),
                                                          ("a" * 41, "1.0.0"), ("9lives", "1.0.0"))])
    out += [_error(registry.releases, "nope"), _error(registry.release, "web", "9.9.9"), _error(registry.release, "nope", "1.0.0")]
    registry.yank("fmt", "1.2.0")
    out += [registry.newest("fmt"), [r.yanked for r in registry.releases("fmt")], _error(registry.yank, "fmt", "1.2.0"),
            _error(registry.yank, "fmt", "3.0.0"), [str(r.version) for r in registry.releases("web")]]
    return out


def probe_index_format():
    from trellis import FileFormatError, parse_index
    registry = parse_index("# index\n\nweb 2.3.0: fmt ^2.0; log >=1.0, <2\n  fmt 2.0.1  \nfmt 1.9.0 yanked\n"
                           "log 1.4.2: fmt ~2.0.0\nold 0.1.0 yanked: fmt *\n")
    out = [registry.names(), {r.name + " " + str(r.version): [r.yanked, sorted((k, str(v)) for k, v in r.dependencies.items())]
                              for name in registry.names() for r in registry.releases(name)}]
    for bad in ("web", "web 1.0.0 old", "web 1.0.0 yanked extra", "web 1.0.0: fmt", "web 1.0.0: fmt ^1; fmt ^2",
                "web 1.0.0: ; fmt ^1", "web 1.0.0\nweb 1.0.0", "\n\nweb x.y.z", "web 1.0.0: fmt ^1;", "web 1.0.0: web ^1"):
        try:
            parse_index(bad)
            out.append(None)
        except FileFormatError as exc:
            out.append([exc.line, exc.source])
    extra = parse_index("fmt 3.0.0\n", registry)
    out.append([extra is registry, [str(r.version) for r in registry.releases("fmt")]])
    return out


def probe_manifest_format():
    from trellis import FileFormatError, parse_manifest
    manifest = parse_manifest('# app\n[project]\nname = "shop-2"\n\n[dependencies]\nweb = "^2.1"\nlog = ">=1.0, <1.5 || 2.*"\n'
                              '[dev-dependencies]\ncheck = "~0.4"\n')
    out = [manifest.name, {k: str(v) for k, v in manifest.dependencies.items()}, {k: str(v) for k, v in manifest.dev_dependencies.items()},
           sorted(manifest.requirements()), sorted(manifest.requirements(dev=True))]
    for bad in ('web = "^1"', '[project]\nname = shop', '[project]\nname = "Shop"', '[project]\nversion = "1"', '[tools]',
                '[project]\nname = "p"\n[dependencies]\nweb = "^1"\nweb = "^2"', '[project]\nname = "p"\n[dependencies]\nweb = "^1"\n'
                '[dev-dependencies]\nweb = "^2"', '[project]\nname = "p"\n[dependencies]\nWeb = "^1"',
                '[project]\nname = "p"\n[dependencies]\nweb = "nope"', '[dependencies]\nweb = "^1"', '[project]\nname = "p"\n[dependencies]\np = "*"'):
        try:
            parse_manifest(bad)
            out.append(None)
        except FileFormatError as exc:
            out.append([exc.line, exc.source])
    return out


# --- resolver ----------------------------------------------------------------------------------
BASIC = """
web 2.3.0: fmt ^2.0; log >=1.0, <2
web 2.2.0: fmt ^2.0
web 2.1.0: fmt ^1.5
web 1.9.0
fmt 2.1.0
fmt 2.0.1
fmt 1.9.0 yanked
fmt 1.6.0
log 1.4.2: fmt ~2.0.0
log 1.5.0: fmt ^2.1
log 2.0.0
"""


def probe_resolve_newest_and_sources():
    from trellis import parse_index, resolve
    resolution = resolve(parse_index(BASIC), "shop", {"web": "^2.1", "log": "<1.5"})
    return [resolution.as_text(), _requirements(resolution), resolution.root, str(resolution["fmt"]),
            _resolve(BASIC, {"web": "<2.2"}), _resolve(BASIC, {"web": "2.2.0"}), _resolve(BASIC, {"web": "*", "fmt": "<2.1"}),
            _resolve(BASIC, {"log": "*"}), _resolve(BASIC, {}), _resolve(BASIC, {"nope": "*"}), _resolve(BASIC, {"Bad": "*"}),
            _resolve(BASIC, {"zzz-missing": "*", "Bad": "*"}), _resolve(BASIC, {"web": "*"}, root=""),
            _resolve(BASIC, {"web": "*"}, root=None)]


def probe_resolve_decision_order():
    index = """
    alpha 2.0.0: shared ^2
    alpha 1.0.0: shared ^1
    beta 1.0.0: shared *
    shared 1.0.0
    shared 2.0.0
    shared 3.0.0
    omega 2.0.0: alpha ^1
    omega 1.0.0
    """
    return [_resolve(index, {"alpha": "*", "beta": "*"}), _resolve(index, {"alpha": "*", "shared": "<3"}),
            _resolve(index, {"omega": "*", "alpha": "*"}), _resolve(index, {"omega": "*", "alpha": ">=2"}),
            _resolve(index, {"beta": "*", "shared": "1.*"})]


def probe_resolve_locked_and_yanked():
    from trellis import Version
    pins = {"web": "2.1.0", "fmt": "1.9.0", "log": "1.4.2"}
    return [_resolve(BASIC, {"web": "^2.1"}, pins), _resolve(BASIC, {"web": "^2.2"}, pins), _resolve(BASIC, {"web": "^2.1"}, pins, ["fmt"]),
            _resolve(BASIC, {"web": "^2.1"}, pins, ["web", "fmt"]), _resolve(BASIC, {"fmt": "^1"}),
            _resolve(BASIC, {"fmt": "^1"}, {"fmt": Version.parse("1.9.0")}), _resolve(BASIC, {"fmt": "1.9.0"}),
            _resolve(BASIC, {"web": "^2.1"}, {"web": "9.9.9"}), _resolve(BASIC, {"web": "1.9.0"}, {"fmt": "2.1.0"})]


def probe_resolve_prereleases():
    index = "lib 1.0.0\nlib 1.1.0-rc.1\nlib 1.1.0-rc.2\nlib 2.0.0-beta.1\napp 1.0.0: lib >=1.1.0-rc.1\napp 2.0.0-rc.1: lib ^2.0.0-beta.1\n"
    return [_resolve(index, {"lib": "^1"}), _resolve(index, {"lib": ">=1.1.0-rc.1"}), _resolve(index, {"app": "*"}),
            _resolve(index, {"app": ">=2.0.0-rc.1"}), _resolve(index, {"lib": "2.0.0-beta.1"}), _resolve(index, {"lib": ">1.0.0"})]


def probe_resolution_failures():
    index = """
    a 1.0.0: c ^1
    b 1.0.0: c ^2
    c 1.0.0
    c 2.0.0
    d 1.0.0: ghost ^1
    e 1.0.0: c 2.0.0
    f 2.0.0: c ^3
    f 1.0.0: c ^4
    """
    both = "x 1.0.0: zz ^2; aa ^2\nx 0.9.0: zz ^2; aa ^2\naa 1.0.0\nzz 1.0.0\n"
    return [_resolve(both, {"aa": "^1", "zz": "^1", "x": "*"}),
            _resolve(index, {"a": "*", "b": "*"}), _resolve(index, {"d": "*"}), _resolve(index, {"c": "^1", "e": "*"}),
            _resolve(index, {"f": "*"}), _resolve(index, {"a": "^2"}), _resolve(index, {"c": "^1", "f": "*", "a": "*"})]


def probe_tilde_wildcard_or_resolution():
    index = "x 1.2.3\nx 1.2.9\nx 1.3.0\nx 2.0.5\nx 3.1.0\ny 0.1.5\ny 0.2.0\ny 0.2.7\ny 0.3.0\ny 1.0.0\n"
    return [_resolve(index, {"x": "~1.2.3"}), _resolve(index, {"x": "1.*"}), _resolve(index, {"x": "<1.3 || 3.*"}),
            _resolve(index, {"x": "^1.2, !=1.3.0"}), _resolve(index, {"y": "^0.2"}), _resolve(index, {"y": "~0.1"}),
            _resolve(index, {"y": "^0"}), _resolve(index, {"y": "^0.0"}), _resolve(index, {"x": ">3.1.0 || <1.2.3"})]


# --- graph, lock files, workspace ------------------------------------------------------------------
DIAMOND = """
app 1.0.0: api ^1; cli ^1
api 1.2.0: core ^1; log ^1
cli 1.0.0: core ^1
core 1.1.0: log ^1
log 1.0.0
"""


def probe_tree_why_reverse():
    from trellis import parse_index, resolve, tree, why
    from trellis.graph import dependencies_of, reverse_dependencies
    registry = parse_index(DIAMOND + "top 1.0.0: zlib ^1; app ^1\nzlib 1.0.0\n")
    resolution = resolve(registry, "proj", {"app": "*", "log": "1.0.0"})
    other = resolve(registry, "proj", {"top": "*", "core": "*"})
    return [tree(resolution, registry), tree(other, registry), why(resolution, registry, "log"), why(resolution, registry, "app"),
            reverse_dependencies(resolution, registry), sorted(dependencies_of(resolution, registry, "api")),
            _error(why, resolution, registry, "nope"), _error(dependencies_of, resolution, registry, "nope")]


def probe_install_order_chains_and_cycles():
    from trellis import CycleError, install_order, parse_index, resolve
    registry = parse_index(DIAMOND)
    out = [install_order(resolve(registry, "p", {"app": "*"}), registry)]
    cyclic = parse_index("a 1.0.0: b *\nb 1.0.0: c *\nc 1.0.0: a *\nd 1.0.0\ne 1.0.0: d *\n")
    try:
        install_order(resolve(cyclic, "p", {"a": "*", "e": "*"}), cyclic)
        out.append(None)
    except CycleError as exc:
        out.append(exc.members)
    flat = parse_index("m 1.0.0\nb 1.0.0\nz 1.0.0\n")
    out.append(install_order(resolve(flat, "p", {"z": "*", "m": "*", "b": "*"}), flat))
    skewed = parse_index("abc 1.0.0\nabc 1.1.0\nabc 1.2.0\nzed 1.0.0: abc *\nmid 1.0.0\nmid 1.1.0\nuse 1.0.0: abc *; mid *\n"
                         "use 0.9.0: abc *; mid *\n")
    resolution = resolve(skewed, "p", {"abc": "*", "zed": "*", "mid": "*", "use": "*"})
    from trellis.graph import reverse_dependencies
    loose = parse_index("abc 1.0.0\nabc 1.1.0\nabc 1.2.0\nzed 1.0.0\nmid 1.0.0\nmid 1.1.0\n")
    unordered = resolve(loose, "p", {"abc": "*", "zed": "*", "mid": "*"})
    out += [list(resolution.versions), reverse_dependencies(resolution, skewed), list(unordered.versions),
            install_order(unordered, loose)]
    return out


def probe_lockfile_format_and_diff():
    from trellis import FileFormatError, Version, parse_index, resolve
    from trellis.lockfile import diff, dump, load
    resolution = resolve(parse_index(BASIC), "shop", {"web": "^2.1"})
    text = dump(resolution)
    out = [text, [load(text)[0], {k: str(v) for k, v in load(text)[1].items()}]]
    for bad in ("", "root x", "# trellis lock 1\nweb 1.0.0", "# trellis lock 1\nroot x\nweb", "# trellis lock 1\nroot x\nweb 1.0",
                "# trellis lock 1\nroot x\nweb 1.0.0\nweb 1.0.0", "# trellis lock 1\nroot x\nWeb 1.0.0", "# trellis lock 1\nroot x\nroot y"):
        try:
            load(bad)
            out.append(None)
        except FileFormatError as exc:
            out.append([exc.line, exc.source])
    out.append(load("# trellis lock 1\n\nroot x\n\nweb 1.0.0\n")[0])
    v = Version.parse
    out.append(diff({"a": v("1.0.0"), "b": v("2.0.0"), "c": v("1.0.0-rc.1"), "d": v("1.0.0")},
                    {"b": v("1.9.9"), "c": v("1.0.0"), "d": v("1.0.0"), "e": v("0.0.1")}))
    return out


def probe_lock_verify():
    from trellis import Constraint, Version, parse_index
    from trellis.lockfile import verify
    registry = parse_index(DIAMOND + "extra 1.0.0\n")
    v = Version.parse
    good = {"app": v("1.0.0"), "api": v("1.2.0"), "cli": v("1.0.0"), "core": v("1.1.0"), "log": v("1.0.0")}
    req = {"app": Constraint.parse("*")}
    return [verify(good, req, registry), verify(dict(good, extra=v("1.0.0")), req, registry, "proj"),
            verify({k: x for k, x in good.items() if k != "core"}, req, registry),
            verify(dict(good, log=v("2.0.0")), req, registry, "proj"), verify(dict(good, api=v("1.2.1")), req, registry),
            verify(good, {"app": Constraint.parse(">1")}, registry, "proj"), verify({}, req, registry),
            verify(dict(good, extra=v("1.0.0"), log=v("2.0.0"), cli=v("1.0.1"), zz=v("1.0.0"), aa=v("1.0.0")), req, registry)]


def probe_workspace_install_update():
    from trellis import Workspace
    manifest = MANIFEST + 'web = "^2.1"\n[dev-dependencies]\nlog = "^2"\n'
    lock = "# trellis lock 1\nroot shop\nweb 2.1.0\nfmt 1.6.0\n"
    workspace = Workspace(BASIC, manifest, lock)
    out = [workspace.check()]
    plan = workspace.install()
    out += [plan.changes, plan.order, plan.lock]
    plan = workspace.update(["fmt"])
    out += [plan.changes, _error(workspace.update, ["nope"])]
    plan = workspace.update()
    out += [plan.changes, plan.order, workspace.check()]
    dev = Workspace(BASIC, manifest, dev=True)
    out += [dev.install().resolution.as_text(), _error(Workspace, BASIC, manifest, "# trellis lock 1\nroot other\n")]
    stuck = Workspace(BASIC, MANIFEST + 'web = "^2.1"\nfmt = "1.9.0"\n', "# trellis lock 1\nroot shop\nweb 2.1.0\nfmt 1.9.0\n")
    out += [_error(stuck.update), {k: str(v) for k, v in stuck.pins.items()}, stuck.install().changes]
    return out


def probe_workspace_outdated_tree_why():
    from trellis import Workspace
    lock = "# trellis lock 1\nroot shop\nweb 2.1.0\nfmt 1.6.0\nlog 1.4.2\nnew 1.0.0\n"
    workspace = Workspace(BASIC + "fmt 3.0.0-rc.1\nlog 2.1.0 yanked\nnew 1.0.0\nnew 0.9.0\n",
                          MANIFEST + 'web = "^2.1"\nlog = "~1.4"\nnew = "*"\n', lock)
    return [workspace.outdated(), workspace.check(), workspace.tree(), workspace.why("fmt"), _error(workspace.why, "nope")]


# --- target probes: caret on 0.0.x -----------------------------------------------------------
def probe_caret_zero_zero_patch():
    from trellis import Constraint
    out = []
    for text in ("^0.0.3", "^0.0.0", "^0.0.3-rc.1", "^0.0.12"):
        constraint = Constraint.parse(text)
        out.append([str(constraint), [v for v in ("0.0.2", "0.0.3", "0.0.4", "0.0.9", "0.0.12", "0.0.13", "0.1.0")
                                      if constraint.allows(v)]])
    return out


def probe_caret_zero_zero_resolution():
    index = "tiny 0.0.3\ntiny 0.0.4\ntiny 0.0.9\ntiny 0.1.0\nuses 1.0.0: tiny ^0.0.4\nuses 0.9.0\n"
    return [_resolve(index, {"tiny": "^0.0.3"}), _resolve(index, {"uses": "*"}), _resolve(index, {"uses": "*", "tiny": "^0.0.3"})]


def probe_caret_zero_zero_workspace():
    from trellis import Workspace
    index = "tiny 0.0.3\ntiny 0.0.4\ntiny 0.0.9\nweb 1.0.0: tiny ^0.0.3\n"
    workspace = Workspace(index, MANIFEST + 'web = "^1"\n', "# trellis lock 1\nroot shop\nweb 1.0.0\ntiny 0.0.9\n")
    return [workspace.check(), workspace.install().changes, workspace.tree()]


# --- target probes: install order among ready packages ------------------------------------------------
def probe_install_order_ready_alphabetical():
    from trellis import install_order, parse_index, resolve
    registry = parse_index("core 1.0.0\nalpha 1.0.0: core ^1\nzeta 1.0.0\nmid 1.0.0\n")
    return install_order(resolve(registry, "p", {"alpha": "*", "zeta": "*", "mid": "*"}), registry)


def probe_install_order_layers():
    from trellis import install_order, parse_index, resolve
    index = ("base 1.0.0\nnet 1.0.0: base *\ncrypto 1.0.0: base *\nyaml 1.0.0\nhttp 1.0.0: net *; crypto *\n"
             "api 1.0.0: http *; yaml *\nwidgets 1.0.0\n")
    registry = parse_index(index)
    return install_order(resolve(registry, "p", {"api": "*", "widgets": "*"}), registry)


def probe_install_order_plan():
    from trellis import Workspace
    index = "fmt 2.0.0\nlog 1.0.0: fmt *\nweb 1.0.0: log *\nauth 1.0.0: fmt *\nzip 1.0.0\n"
    workspace = Workspace(index, MANIFEST + 'web = "*"\nauth = "*"\nzip = "*"\n')
    return [workspace.install().order, workspace.update().order]


# --- target probes: abandoned choices leave no requirement behind -----------------------------------------
LEAK = """
app-core 1.1.0: http <2.1; json ^3
app-core 1.0.0: json ^2
http 2.0.0
http 2.1.0
http 2.2.0
json 2.4.0
"""


def probe_backtrack_keeps_newest():
    from trellis import parse_index, resolve
    resolution = resolve(parse_index(LEAK), "shop", {"app-core": "^1", "http": "^2"})
    return [resolution.as_text(), _requirements(resolution)]


def probe_backtrack_no_false_conflict():
    index = "ui 1.1.0: theme ^2\nui 1.0.0: theme ^1\ntheme 1.0.0\ntheme 1.1.0\ntheme 1.2.0\ntheme 2.0.0\n"
    return [_resolve(index, {"ui": "*", "theme": "^1"}), _resolve(index, {"ui": "*", "theme": "<2", "extra": "*"}),
            _resolve(index + "extra 1.0.0: theme 1.0.0\n", {"ui": "*", "theme": "<2", "extra": "*"})]


def probe_backtrack_workspace_lock():
    from trellis import Workspace
    manifest = MANIFEST + 'app-core = "^1"\nhttp = "^2"\n'
    first = Workspace(LEAK, manifest).install()
    updated = Workspace(LEAK, manifest, "# trellis lock 1\nroot shop\napp-core 1.0.0\nhttp 2.0.0\njson 2.4.0\n").update(["http"])
    return [first.lock, updated.changes]
