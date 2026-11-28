"""The layering, enforced rather than described.

``isolator/executive.py`` says "Isolator never imports STOMP,
ActiveMQ, MAVLink, PX4, or Stub". That was true when written and
nothing checked it: the only guard was
``test_isolator_module_does_not_import_stub``, which asserts one name
is absent from one module's ``__dict__``. A docstring claiming a
guarantee the tests do not provide is the same failure this project
keeps finding elsewhere -- a claim outrunning its evidence.

So the rule is an allowlist, not a denylist. Each layer declares what
it may import and anything else fails, which catches the next bad
import rather than only the ones someone thought to forbid.

Deferred imports count. ``Px4MavlinkAdapter`` imports ``pymavlink``
inside functions to keep it an optional dependency, and the walk finds
those too, which is the point: moving an import into a function body
must not launder it.
"""

from __future__ import annotations

import ast
import collections
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "open_vi"
_ROOT = _SRC.parent

# What each layer may import, beyond its own subtree and the stdlib.
#
# `fa` is listed before it exists. The scope in docs/FLIGHT_AUTONOMY.md
# turns on `fa/` importing no codec and no bus, because that is what
# makes a later extraction into its own repo a move rather than a
# rewrite. An invariant added after the code is an invariant that has
# already been broken, so it goes in first and the entry is inert
# until the package appears.
ALLOWED: dict[str, frozenset[str]] = {
    "open_vi.domain": frozenset({"open_vi.identity"}),
    "open_vi.codec": frozenset({"open_vi.domain", "open_vi.identity"}),
    "open_vi.asb": frozenset({"open_vi.config"}),
    "open_vi.platform": frozenset({"open_vi.domain", "open_vi.identity"}),
    "open_vi.fa": frozenset(
        {"open_vi.domain", "open_vi.identity", "open_vi.platform.port"}
    ),
    "open_vi.isolator": frozenset(
        {
            "open_vi.asb.port",
            "open_vi.codec",
            "open_vi.config",
            "open_vi.domain",
            "open_vi.fa",
            "open_vi.identity",
            "open_vi.platform.port",
        }
    ),
}

# The package root is importable from anywhere because it holds only
# ``__version__``. ``test_the_package_root_holds_only_metadata`` keeps
# that true, so the exemption cannot become a back door into other
# layers via re-exports.
UNIVERSAL: frozenset[str] = frozenset({"open_vi"})

# Third-party packages that may only be imported by one layer. The
# names Isolator's docstring promises to stay away from.
VENDOR_LOCKED: dict[str, str] = {
    "stomp": "open_vi.asb",
    "pymavlink": "open_vi.platform",
}


def _module_name(path: pathlib.Path) -> str:
    parts = list(path.relative_to(_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: pathlib.Path) -> set[str]:
    """Every absolute module this file imports, at any nesting depth."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports stay inside their own package.
            if node.level == 0 and node.module:
                found.add(node.module)
    return found


def _graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = collections.defaultdict(set)
    for path in sorted(_SRC.rglob("*.py")):
        graph[_module_name(path)] |= _imports(path)
    return graph


def _covers(allowed: str, imported: str) -> bool:
    return imported == allowed or imported.startswith(allowed + ".")


def _layer_of(module: str) -> str | None:
    for layer in ALLOWED:
        if _covers(layer, module):
            return layer
    return None


def test_every_source_module_sits_in_a_declared_layer() -> None:
    """A new package must declare its layer, not inherit no rules.

    Without this, adding ``open_vi/whatever/`` would silently sit
    outside every rule and be free to import anything.
    """
    top_level = {"open_vi", "open_vi.config", "open_vi.identity"}
    stray = sorted(
        module
        for module in _graph()
        if module not in top_level
        and not module.endswith("__main__")
        and _layer_of(module) is None
    )
    assert not stray, f"modules in no declared layer: {stray}"


def test_layers_import_only_what_they_declare() -> None:
    """The allowlist, applied to every module in every layer."""
    violations: list[str] = []
    for module, imported in sorted(_graph().items()):
        layer = _layer_of(module)
        if layer is None:
            continue
        allowed = ALLOWED[layer]
        for target in sorted(imported):
            if not target.startswith("open_vi"):
                continue
            if _covers(layer, target):
                continue  # inside its own layer
            if target in UNIVERSAL:
                continue
            if any(_covers(ok, target) for ok in allowed):
                continue
            violations.append(f"{module} -> {target}")
    assert not violations, (
        "imports crossing a layer boundary:\n  " + "\n  ".join(violations)
    )


def test_the_package_root_holds_only_metadata() -> None:
    """``open_vi/__init__.py`` stays a version constant.

    Every layer may import the root, because ``domain.status`` reads
    ``__version__`` from it to keep the wire's ``ServiceVersion`` in
    step with the release. That exemption is only safe while the root
    re-exports nothing: one ``from open_vi.platform import ...`` in
    there would open a path from any layer to any other.
    """
    tree = ast.parse((_SRC / "__init__.py").read_text())
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert assigned == {"__version__"}, (
        f"package root assigns more than __version__: {sorted(assigned)}"
    )
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not imports, "package root must import nothing"


def test_vendor_dependencies_stay_in_their_adapter() -> None:
    """STOMP and MAVLink reach exactly one layer each.

    This is the half of Isolator's docstring that names third parties.
    A deferred import inside a function does not escape it.
    """
    violations: list[str] = []
    for module, imported in sorted(_graph().items()):
        for target in sorted(imported):
            root = target.split(".")[0]
            owner = VENDOR_LOCKED.get(root)
            if owner is None:
                continue
            if not _covers(owner, module):
                violations.append(f"{module} -> {target} (only {owner} may)")
    assert not violations, (
        "vendor import outside its adapter:\n  " + "\n  ".join(violations)
    )


def test_the_isolator_docstring_claim_holds() -> None:
    """The specific sentence in ``executive.py``, as a check.

    "Isolator never imports STOMP, ActiveMQ, MAVLink, PX4, or Stub."
    """
    forbidden = (
        "stomp",
        "pymavlink",
        "open_vi.asb.stomp_amq",
        "open_vi.asb.memory",
        "open_vi.platform.px4",
        "open_vi.platform.stub",
    )
    violations = [
        f"{module} -> {target}"
        for module, imported in sorted(_graph().items())
        if module.startswith("open_vi.isolator")
        for target in sorted(imported)
        if any(
            target == bad or target.startswith(bad + ".") for bad in forbidden
        )
    ]
    assert not violations, "\n  ".join(violations)


def test_domain_is_a_leaf() -> None:
    """Domain is the shared vocabulary; it depends on no other layer.

    ``utc_now`` lives here for exactly this reason -- both the codec
    and a platform adapter need it and neither may import the other.
    """
    reaching_out = sorted(
        f"{module} -> {target}"
        for module, imported in sorted(_graph().items())
        if module.startswith("open_vi.domain")
        for target in sorted(imported)
        if target.startswith("open_vi.")
        and not target.startswith("open_vi.domain")
        and target != "open_vi.identity"
    )
    assert not reaching_out, "\n  ".join(reaching_out)
