"""Offline consistency checks on the documentation.

The docs are part of the product surface: the README's documentation list is the
entry point, and the campaign docs carry an epistemic statement -- a campaign can
finish without solving the problem -- that must never quietly disappear. These
checks pin the shape (every listed doc exists, relative links resolve, ASCII
diagrams rather than Mermaid, one ``[Unreleased]`` section) without reading the
prose for the reader.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_README = _ROOT / "README.md"
_CHANGELOG = _ROOT / "CHANGELOG.md"
_DOCS = _ROOT / "docs"

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")

# The docs written for the campaign engine that must state, in so many words, that
# finishing a campaign is not solving the problem.
_CAMPAIGN_DOCS = (
    _DOCS / "campaign-engine.md",
    _DOCS / "campaign-persistence.md",
    _DOCS / "portfolio-scheduler.md",
    _DOCS / "proof-tree.md",
)
_COMPLETION_PHRASES = (
    "can finish without solving the problem",
    "does not mean the problem is solved",
    "completed campaign",
    "problem verdict",
)

# New docs are ASCII only (repo convention: ASCII diagrams, no Unicode dashes).
_ASCII_DOCS = (
    _DOCS / "campaign-engine.md",
    _DOCS / "campaign-persistence.md",
    _DOCS / "model-routing.md",
    _DOCS / "release.md",
)


def _documentation_section(text: str) -> str:
    start = text.index("## Documentation")
    rest = text[start + len("## Documentation") :]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _prose(path: Path) -> str:
    """The file's text with line wraps collapsed, so a phrase can be matched across them."""
    return " ".join(path.read_text(encoding="utf-8").split())


def _relative_links(text: str) -> list[str]:
    return [
        target
        for target in _MD_LINK.findall(text)
        if not target.startswith(("http://", "https://", "mailto:"))
    ]


def test_readme_documentation_list_resolves() -> None:
    section = _documentation_section(_README.read_text(encoding="utf-8"))
    links = _relative_links(section)
    assert links, "the README documentation list has no links"
    missing = [link for link in links if not (_ROOT / link).is_file()]
    assert not missing, f"README documentation list points at missing files: {missing}"


def test_readme_documentation_list_names_the_campaign_docs() -> None:
    section = _documentation_section(_README.read_text(encoding="utf-8"))
    for name in (
        "docs/campaign-engine.md",
        "docs/campaign-persistence.md",
        "docs/model-routing.md",
        "docs/proof-tree.md",
        "docs/portfolio-scheduler.md",
        "docs/theorem-references.md",
        "docs/release.md",
    ):
        assert name in section, name


@pytest.mark.parametrize(
    "path",
    sorted(_DOCS.rglob("*.md")) + [_README, _CHANGELOG, _ROOT / "CONTRIBUTING.md"],
    ids=lambda p: str(p.relative_to(_ROOT)),
)
def test_no_mermaid_fences(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "```mermaid" not in text.lower(), f"{path.name} uses a Mermaid fence"


@pytest.mark.parametrize(
    "path", sorted(_DOCS.rglob("*.md")), ids=lambda p: str(p.relative_to(_ROOT))
)
def test_relative_links_in_docs_resolve(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    broken = []
    for target in _relative_links(text):
        candidate = (path.parent / target).resolve()
        if not candidate.exists():
            broken.append(target)
    assert not broken, f"{path.relative_to(_ROOT)} has broken links: {broken}"


@pytest.mark.parametrize("path", _CAMPAIGN_DOCS, ids=lambda p: p.name)
def test_campaign_docs_state_that_completion_is_not_settlement(path: Path) -> None:
    text = _prose(path)
    assert any(phrase in text for phrase in _COMPLETION_PHRASES), (
        f"{path.name} does not state that a campaign can finish without solving the problem"
    )


def test_flagship_docs_state_the_rule_verbatim() -> None:
    for path in (_DOCS / "campaign-engine.md", _README, _CHANGELOG):
        assert "can finish without solving the problem" in _prose(path), path.name


@pytest.mark.parametrize("path", _ASCII_DOCS, ids=lambda p: p.name)
def test_new_docs_are_ascii(path: Path) -> None:
    assert path.is_file(), path
    assert path.read_text(encoding="utf-8").isascii(), f"{path.name} is not ASCII-only"


def test_changelog_has_a_single_unreleased_section() -> None:
    text = _CHANGELOG.read_text(encoding="utf-8")
    headings = re.findall(r"^## \[Unreleased\]", text, flags=re.MULTILINE)
    assert len(headings) == 1, f"expected one [Unreleased] section, found {len(headings)}"
    # It sits above the first versioned section, as Keep a Changelog wants.
    unreleased = text.index("## [Unreleased]")
    versioned = re.search(r"^## \[\d+\.\d+\.\d+\]", text, flags=re.MULTILINE)
    assert versioned is not None and unreleased < versioned.start()


def test_campaign_config_keys_are_documented() -> None:
    """Every ``campaign.*`` scalar in the default config appears in the flagship doc."""
    import yaml

    default = yaml.safe_load(
        (_ROOT / "src" / "opentorus" / "default_config.yaml").read_text(encoding="utf-8")
    )
    doc = (_DOCS / "campaign-engine.md").read_text(encoding="utf-8")

    def leaves(prefix: str, node: object) -> list[str]:
        if isinstance(node, dict):
            out: list[str] = []
            for key, value in node.items():
                out.extend(leaves(f"{prefix}.{key}", value))
            return out
        return [prefix]

    missing = [key for key in leaves("campaign", default["campaign"]) if f"`{key}`" not in doc]
    assert not missing, f"campaign config keys undocumented in docs/campaign-engine.md: {missing}"
