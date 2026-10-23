"""Executed architecture check: import direction between OpenTorus units.

A *unit* is a top-level entry of ``src/opentorus``: a subpackage (``agent``,
``research``, ``providers`` …) or a top-level module (``config``, ``jsonl`` …).
Every import in the package is parsed with :mod:`ast` — including the lazy,
function-local ones, because a lazy import is still a dependency — and checked
against the rules below.

The rules encode the architecture as it is, not as a refactor would like it to
be: a few existing exceptions are listed explicitly in ``ALLOWED_EXCEPTIONS``,
each with the reason it is there. A *new* edge that breaks a rule fails, and so
does a new top-level unit that nobody wrote a rule for — adding one means
deciding where it sits.

The headline guarantee is the one CLAUDE.md states: the provider never leaks
into core logic. ``research`` and ``campaign`` talk to models through the
``providers.base`` / ``providers.pool`` interfaces, never through a concrete
provider module, and nothing below the front ends imports the front ends.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "opentorus"

# Units that present OpenTorus to a person. They may import anything; nothing
# else may import them (see the per-unit rules and the few exceptions below).
FRONT_ENDS = ("cli", "repl", "tui", "dashboard", "__main__")

# The concrete provider implementations. Core code reaches models through
# ``providers.base`` (the interface), ``providers.pool`` (routing) and the small
# capability/vision helpers — never through one vendor's module.
PROVIDER_IMPLEMENTATIONS = (
    "providers.openai_provider",
    "providers.anthropic_provider",
    "providers.ollama_provider",
    "providers.mistral_provider",
    "providers.mock_provider",
    "providers._convert",
)

# Low-level infrastructure: imported by everything, so it must import none of
# the layers above it (an upward import here is how cycles start).
_UPPER_LAYERS = (
    "agent",
    "campaign",
    "research",
    "tools",
    "providers",
    "execution",
    "permissions",
    "evals",
    *FRONT_ENDS,
)

# unit -> forbidden import prefixes (relative to ``opentorus``). A prefix
# forbids the module itself and everything under it. An empty tuple is a
# deliberate "no extra restriction" — it still counts as a written rule.
# ``textual`` (the optional dashboard dependency) is forbidden everywhere except
# the dashboard by the separate check below.
RULES: dict[str, tuple[str, ...]] = {
    # --- core research stack: no front ends, no vendor provider modules -------
    "research": (*FRONT_ENDS, *PROVIDER_IMPLEMENTATIONS, "evals"),
    "campaign": (*FRONT_ENDS, *PROVIDER_IMPLEMENTATIONS, "evals"),
    "agent": (*FRONT_ENDS, *PROVIDER_IMPLEMENTATIONS, "evals"),
    "tools": (*FRONT_ENDS, "evals"),
    # --- providers: below research/campaign/cli; only the shared message schema
    # from agent (``agent.session``, see the exception list) ----------------------
    "providers": (
        *FRONT_ENDS,
        "research",
        "campaign",
        "agent",
        "tools",
        "execution",
        "permissions",
        "evals",
    ),
    # --- the permission gate depends on nothing it gates ------------------------
    "permissions": (
        *FRONT_ENDS,
        "agent",
        "research",
        "campaign",
        "tools",
        "providers",
        "execution",
        "evals",
    ),
    "execution": (*FRONT_ENDS, "agent", "research", "campaign", "providers", "evals"),
    "governance": (*FRONT_ENDS, "agent", "research", "campaign", "tools", "evals"),
    "privacy": (*FRONT_ENDS, "research", "campaign", "tools", "providers", "evals"),
    "approvals": (*FRONT_ENDS, "agent", "research", "campaign", "tools", "providers"),
    "bundle": (*FRONT_ENDS, "research", "campaign", "evals"),
    "quality": (*FRONT_ENDS, "agent", "research", "campaign", "providers", "evals"),
    "suggest": (*FRONT_ENDS, "campaign", "providers", "evals"),
    "doctor": (*FRONT_ENDS, "agent", "campaign", "evals"),
    "ux": (*FRONT_ENDS, "research", "campaign", "tools", "evals"),
    "actions": _UPPER_LAYERS,
    "workspace": _UPPER_LAYERS,
    "notifications": _UPPER_LAYERS,
    "completion": _UPPER_LAYERS,
    "replhistory": _UPPER_LAYERS,
    # --- infrastructure leaves --------------------------------------------------
    "__init__": _UPPER_LAYERS,
    "errors": (*_UPPER_LAYERS, "config"),
    "paths": _UPPER_LAYERS,
    "config": _UPPER_LAYERS,
    "dotenv": _UPPER_LAYERS,
    "jsonl": _UPPER_LAYERS,
    "atomicio": _UPPER_LAYERS,
    "textnorm": _UPPER_LAYERS,
    "mathtext": _UPPER_LAYERS,
    "usage": _UPPER_LAYERS,
    # --- evaluation harness: drives the REPL dispatch core (see exceptions) -----
    "evals": ("cli", "tui", "dashboard", "__main__"),
    # --- front ends -------------------------------------------------------------
    "cli": (),
    "repl": ("tui", "dashboard", "__main__"),
    "tui": ("cli", "dashboard", "__main__"),
    "dashboard": ("cli", "repl", "tui", "__main__"),
    "__main__": (),
}

# (importing module prefix, imported module prefix) pairs that break a rule
# today and are accepted on purpose. Keep this list short and explained; a new
# entry is an architecture decision, not a way to make the test pass.
ALLOWED_EXCEPTIONS: dict[tuple[str, str], str] = {
    # The embeddings client reuses the OpenAI provider's client construction
    # (base_url / api key / timeout handling) for OpenAI-compatible embedding
    # endpoints instead of duplicating it. Lazy import, only on the embeddings path.
    ("research.embeddings", "providers.openai_provider"): "shared OpenAI client kwargs",
    # ``SessionMessage`` is the provider-neutral message schema every provider
    # consumes; it lives in agent.session for historical reasons. Only that one
    # module is allowed — the agent loop itself stays out of reach of providers.
    ("providers", "agent.session"): "shared message schema",
    # The golden-transcript harness drives the REPL's testable dispatch core.
    ("evals", "repl"): "golden transcripts replay the REPL dispatch",
    # The REPL reuses CLI command helpers (rendering of status/check output).
    ("repl", "cli"): "REPL reuses CLI helpers",
    # The TUI is a skin over the REPL dispatch core.
    ("tui", "repl"): "TUI wraps the REPL dispatch",
}


def _units() -> set[str]:
    units = {"__init__"}
    for entry in PACKAGE_DIR.iterdir():
        if entry.is_dir() and (entry / "__init__.py").exists():
            units.add(entry.name)
        elif entry.suffix == ".py" and entry.name != "__init__.py":
            units.add(entry.stem)
    return units


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE_DIR).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)  # "" is the package itself


def _known_modules() -> set[str]:
    return {_module_name(p) for p in PACKAGE_DIR.rglob("*.py")}


def _resolve(name: str, known: set[str]) -> str:
    """The deepest real module named by ``name`` (``a.b.Symbol`` -> ``a.b``)."""
    parts = name.split(".")
    while parts and ".".join(parts) not in known:
        parts.pop()
    return ".".join(parts)


def _imports(path: Path, known: set[str]) -> set[str]:
    return _imports_in(
        path.read_text(encoding="utf-8"),
        _module_name(path),
        is_package=path.name == "__init__.py",
        known=known,
    )


def _imports_in(source: str, own: str, *, is_package: bool, known: set[str]) -> set[str]:
    """Every ``opentorus``-internal module (relative to the package) ``source`` imports,
    plus a ``<textual>`` marker for the optional dashboard dependency."""
    tree = ast.parse(source)
    own_pkg = [p for p in (own.split(".") if is_package else own.split(".")[:-1]) if p]
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = own_pkg[: len(own_pkg) - (node.level - 1)]
                module = ".".join(["opentorus", *base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            names = [module] + [f"{module}.{alias.name}" for alias in node.names]
        for name in names:
            if name == "textual" or name.startswith("textual."):
                found.add("<textual>")
            elif name == "opentorus" or name.startswith("opentorus."):
                rel = name.removeprefix("opentorus").removeprefix(".")
                found.add(_resolve(rel, known))
    return found


def _unit_of(module: str) -> str:
    return module.split(".")[0] if module else "__init__"


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _excepted(source: str, target: str) -> bool:
    return any(_matches(source, src) and _matches(target, dst) for src, dst in ALLOWED_EXCEPTIONS)


def _all_edges() -> list[tuple[str, str]]:
    known = _known_modules()
    edges: list[tuple[str, str]] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        source = _module_name(path)
        for target in sorted(_imports(path, known)):
            edges.append((source, target))
    return edges


def test_every_top_level_unit_has_a_rule() -> None:
    missing = sorted(_units() - set(RULES))
    assert not missing, (
        f"New top-level unit(s) {missing} have no import rule in tests/test_architecture.py. "
        "Decide which layers they may depend on and add a RULES entry."
    )


def test_rules_name_only_existing_units() -> None:
    # A rule for a unit that no longer exists is dead weight that hides typos.
    # ``memory_consolidation`` and ``skills`` are listed ahead of time only if present.
    stale = sorted(set(RULES) - _units())
    assert not stale, f"RULES entries for missing units: {stale}"


def test_import_direction() -> None:
    violations: list[str] = []
    for source, target in _all_edges():
        if target == "<textual>":
            continue
        src_unit = _unit_of(source)
        if _unit_of(target) == src_unit:
            continue
        for forbidden in RULES.get(src_unit, ()):
            if _matches(target, forbidden) and not _excepted(source, target):
                violations.append(f"opentorus.{source} -> opentorus.{target} (rule: {forbidden})")
    assert not violations, "Forbidden imports:\n  " + "\n  ".join(violations)


def test_core_does_not_import_textual() -> None:
    offenders = sorted(
        source
        for source, target in _all_edges()
        if target == "<textual>" and _unit_of(source) != "dashboard"
    )
    assert not offenders, f"textual imported outside opentorus.dashboard: {offenders}"


def test_allowed_exceptions_are_still_needed() -> None:
    # An exception nobody uses anymore should be deleted, so the list stays honest.
    edges = _all_edges()
    unused = [
        pair
        for pair in ALLOWED_EXCEPTIONS
        if not any(_matches(s, pair[0]) and _matches(t, pair[1]) for s, t in edges)
    ]
    assert not unused, f"Stale ALLOWED_EXCEPTIONS entries: {unused}"


def test_the_checker_sees_lazy_and_relative_imports() -> None:
    # Guard the guard: a function-local import is a dependency too, a relative
    # import resolves against the importing package, and a symbol import counts
    # as an import of the module that defines it.
    known = {"", "research", "research.x", "providers", "providers.openai_provider"}
    source = (
        "def f():\n"
        "    from opentorus.providers.openai_provider import Thing\n"
        "    from . import x\n"
        "    import textual.app\n"
    )
    found = _imports_in(source, "research.probe", is_package=False, known=known)
    assert found == {"providers.openai_provider", "research.x", "research", "<textual>"}
