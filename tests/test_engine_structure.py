"""Structural guarantees of the campaign package: one method per phase, no
claim-status mutators, no clock/uuid leaks outside clock.py, pure reducer."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

from opentorus.campaign import engine as engine_module
from opentorus.campaign.engine import CampaignEngine
from opentorus.campaign.models import CampaignPhase
from opentorus.campaign.phases import TERMINAL_PHASES

PACKAGE = Path(engine_module.__file__).parent
SOURCES = sorted(p for p in PACKAGE.rglob("*.py"))

_STATUS_MUTATORS = (
    "set_claim_status",
    "verify_counterexample",
    "downgrade_claim_type",
    "record_validated_numerical",
    "append_status_change",
    "_log_status_change",
    "rewrite_claims",
    # Writers of the status changelog. The read side (``list_status_changes``) is
    # legitimate: settlement inspects recorded reasons for root-assumption mentions.
    "_status_changes_path",
    "update_claim(",
)


def test_engine_split_keeps_modules_readable() -> None:
    """The engine holds the phase handlers; worker execution / result recording live in
    ``execution.py`` and start-time rules in ``lifecycle.py`` (both must exist and be
    used by the engine)."""
    text = (PACKAGE / "engine.py").read_text(encoding="utf-8")
    assert "from opentorus.campaign.execution import" in text
    assert "from opentorus.campaign.lifecycle import" in text
    for name in ("execution.py", "lifecycle.py", "failures.py", "portfolio.py", "scheduler.py"):
        assert (PACKAGE / name).is_file(), name
    execution = (PACKAGE / "execution.py").read_text(encoding="utf-8")
    for method in (
        "def run_worker",
        "def record_result",
        "def worker_context",
        "def shared_artifacts",
    ):
        assert method in execution, method
    assert "def _run_worker" not in text and "def _record_result" not in text


def test_engine_defines_one_phase_method_per_non_terminal_phase() -> None:
    expected = {
        f"_phase_{phase.name.lower()}"
        for phase in CampaignPhase
        if phase not in TERMINAL_PHASES
        and phase not in (CampaignPhase.CREATED, CampaignPhase.PAUSED)
    }
    present = {name for name in dir(CampaignEngine) if name.startswith("_phase_")}
    assert present == expected
    engine_handlers = set(CampaignEngine.__init__.__code__.co_names)  # attribute names referenced
    for name in expected:
        assert name in engine_handlers, f"{name} not wired into the handler table"


def _code_only(text: str) -> str:
    """Source with comments and string literals (docstrings included) removed, so a
    prose mention of a forbidden name is not a violation — only code is."""
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def _module_sources(pattern: str) -> list[Path]:
    return [p for p in SOURCES if re.search(pattern, str(p.relative_to(PACKAGE)))]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_campaign_module_imports_claim_status_mutators(path: Path) -> None:
    """Every module of the campaign package — engine, execution, lifecycle, portfolio,
    scheduler, failures, importer, research bridge, workers, proof tree — references no
    claim-status mutator; the layer only ever *references* dossier artifacts."""
    text = path.read_text(encoding="utf-8")
    code = _code_only(text)
    for needle in _STATUS_MUTATORS:
        assert needle not in code, f"{path.name} uses {needle}"
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "dossier.claims" in node.module:
            names = {alias.name for alias in node.names}
            assert names <= {"add_claim", "latest_primary_proof"}, names
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("status_gate"):
            names = {alias.name for alias in node.names}
            assert names <= {"derive_status"}, names


_CLOCK_LEAKS = re.compile(r"\buuid\b|datetime\.now\(|time\.time\(|utcnow\(\)")


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_clock_or_uuid_outside_clock_module(path: Path) -> None:
    if path.name == "clock.py":
        return
    code = _code_only(path.read_text(encoding="utf-8"))
    hits = _CLOCK_LEAKS.findall(code)
    assert not hits, f"{path.name}: {hits}"


def test_reducer_is_pure_at_the_import_level() -> None:
    text = (PACKAGE / "reducer.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {"os", "pathlib", "json", "random", "uuid", "datetime", "time", "io"}
    assert not (imported & forbidden), imported & forbidden
    assert not any(name.startswith("opentorus.campaign.store") for name in imported)
    assert "open(" not in text


def test_snapshot_model_has_no_claim_status_or_root_status_fields() -> None:
    from opentorus.campaign.models import CampaignSnapshot

    fields = set(CampaignSnapshot.model_fields)
    for forbidden in (
        "claim_status",
        "claim_statuses",
        "root_status",
        "root_math_status",
        "report_status",
    ):
        assert forbidden not in fields


def test_campaign_dir_is_write_protected_by_the_filesystem_tools() -> None:
    from opentorus.tools.filesystem import _DOSSIER_MANAGED_ARTIFACTS

    assert "campaigns" in _DOSSIER_MANAGED_ARTIFACTS


def test_campaign_group_is_registered_first_and_sorted() -> None:
    import inspect

    import opentorus.cli as cli_pkg

    text = inspect.getsource(cli_pkg)
    body = text.split("from opentorus.cli import (", 1)[1].split(")", 1)[0]
    names = [
        line.strip().rstrip(",")
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert names[0] == "campaign"
    assert names == sorted(names)
