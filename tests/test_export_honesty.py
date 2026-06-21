"""The composed-PDF path must refuse to typeset overclaims or an INVALID dossier."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.algebra_check import check_optimizer
from opentorus.research.dossier import claims, store
from opentorus.research.dossier.algebra_link import record_algebra_check
from opentorus.research.dossier.pdf_export import enforce_export_honesty
from opentorus.workspace import init_workspace, workspace_dir


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    return base, store.create_dossier(base, "A conjecture about X.").id


def test_enforce_rejects_unlicensed_overclaim(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    document = "\\section{Result} We prove that X holds for every n. \\(x \\in C\\)\n"
    with pytest.raises(OpenTorusError):
        enforce_export_honesty(base, pid, document)
    # --force overrides.
    enforce_export_honesty(base, pid, document, allow_overclaims=True)


def test_enforce_allows_honest_prose(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    document = "\\section{Status} We provide numerical evidence supporting the conjecture.\n"
    enforce_export_honesty(base, pid, document)  # must not raise


def test_enforce_refuses_invalid_status(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CLAIM", statement="optimal m is 10")
    res = check_optimizer("5*m + 3", variable="m", claimed_optimizer="10", domain=("1", "1000"))
    record_algebra_check(base, pid, res, claim_id=c.id)  # -> status INVALID
    document = "\\section{Summary} The evidence is mixed.\n"  # honest prose, but status INVALID
    with pytest.raises(OpenTorusError):
        enforce_export_honesty(base, pid, document)
    enforce_export_honesty(base, pid, document, allow_overclaims=True)  # --force
