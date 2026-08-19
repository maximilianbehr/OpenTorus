"""The LLM-composed narrative .tex must pass the same honesty gate as the PDF.

Pins the fix for the narrative bypass: ``opentorus problem report`` writes
``PROBLEM-XXXX-narrative.tex`` via ``compose_narrative_tex``, which used to skip
every honesty check that ``report.md`` (linted on build) and the composed PDF
(``enforce_export_honesty``) go through. The narrative now:

* refuses the same hard overclaim kinds the PDF gate refuses
  (experiment_proof / proof_claim / result_claim) — loudly, with the findings;
* carries the linter's soft findings inside the document as an
  "Honesty warnings" section, mirroring report.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.agent.session import SessionMessage
from opentorus.errors import OpenTorusError
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.dossier import claims, store
from opentorus.research.dossier.pdf_export import (
    compose_narrative_tex,
    enforce_narrative_honesty,
)
from opentorus.workspace import init_workspace, workspace_dir


class _FakeProvider(BaseProvider):
    # A non-"mock" name so _llm_usable() routes composition through this provider.
    name = "fake"

    def __init__(self, content: str) -> None:
        self._content = content

    def generate(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(kind="message", content=self._content)


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    pid = store.create_dossier(base, "A conjecture about X.").id
    # An unlicensed CONJECTURE: no verified proof, no supported THEOREM, no reference.
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    return base, pid


def test_gate_refuses_hard_overclaim_with_findings(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    document = "\\section{Result} We prove that X holds for every n.\n"
    with pytest.raises(OpenTorusError) as excinfo:
        enforce_narrative_honesty(base, pid, document)
    message = str(excinfo.value)
    # The refusal is loud: it names the kind and quotes the offending phrase.
    assert "proof_claim" in message
    assert "we prove" in message.lower()


def test_gate_refuses_experiment_as_proof(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    document = "\\section{Results} The experiment proves the conjecture.\n"
    with pytest.raises(OpenTorusError) as excinfo:
        enforce_narrative_honesty(base, pid, document)
    assert "experiment_proof" in str(excinfo.value)


def test_gate_appends_soft_warnings_before_end_document(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    document = (
        "\\documentclass{opentorus}\n\\begin{document}\n"
        "The bound obviously holds in the tested range.\n"
        "\\end{document}\n"
    )
    out = enforce_narrative_honesty(base, pid, document)
    assert "Honesty warnings" in out
    assert "obviously" in out
    # The section is part of the document body, not dangling after \end{document}.
    assert out.index("Honesty warnings") < out.rindex("\\end{document}")


def test_compose_narrative_refuses_model_overclaim(tmp_path: Path) -> None:
    # End-to-end wiring pin: an overclaiming model body must never come back from
    # compose_narrative_tex — the exact bypass the CLI used to write to disk.
    base, pid = _problem(tmp_path)
    provider = _FakeProvider("\\section{Summary} We prove that X holds for every n.")
    with pytest.raises(OpenTorusError) as excinfo:
        compose_narrative_tex(base, pid, provider=provider, compose_llm=True)
    assert "proof_claim" in str(excinfo.value)


def test_compose_narrative_clean_passes_and_carries_soft_warnings(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    provider = _FakeProvider("\\section{Summary} The bound obviously holds for small cases.")
    doc = compose_narrative_tex(base, pid, provider=provider, compose_llm=True)
    assert "\\begin{document}" in doc
    assert "Honesty warnings" in doc
    assert "[weasel]" in doc or "weasel" in doc
    assert doc.index("Honesty warnings") < doc.rindex("\\end{document}")


def test_compose_narrative_clean_without_findings_has_no_warning_section(
    tmp_path: Path,
) -> None:
    base, pid = _problem(tmp_path)
    provider = _FakeProvider(
        "\\section{Summary} Numerical evidence supports the conjecture in the tested range."
    )
    doc = compose_narrative_tex(base, pid, provider=provider, compose_llm=True)
    assert "\\begin{document}" in doc
    assert "Honesty warnings" not in doc


def test_report_command_survives_a_refused_narrative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused narrative must not cost the caller report.md, the lint or the rest of
    a script. A live driver (barnette, round 5) lost its verdict and PDF because one
    model overclaim made `problem report` exit non-zero under `set -e`."""
    from typer.testing import CliRunner

    from opentorus.cli import app

    base, pid = _problem(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "opentorus.providers.registry.get_provider",
        lambda *a, **k: _FakeProvider("\\section{Summary} We prove that X holds for every n."),
    )
    result = CliRunner().invoke(app, ["problem", "report", pid])
    assert result.exit_code == 0, result.output
    assert "Narrative report refused" in result.output
    # the reason travels with it (console wrapping makes long tokens unreliable)
    assert "unlicensed" in result.output and "overclaim" in result.output
    # the honest artifact was still written, and no narrative reached the disk
    assert (store.dossier_dir(base, pid) / "report.md").is_file()
    assert not (store.dossier_dir(base, pid) / f"{pid}-narrative.tex").is_file()
