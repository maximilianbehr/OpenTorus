"""Tests for batch-5 reproducibility/provenance fixes: cache key, sympy verifier, pack."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.research.experiments import DatasetRef, Experiment, _cache_key_for
from opentorus.workspace import init_workspace, workspace_dir


def _exp(dataset_sha: str) -> Experiment:
    return Experiment(
        id="EXP-0001",
        title="sweep",
        path="experiments/EXP-0001",
        command="python run.py",
        datasets=[DatasetRef(dataset_id="DS-0001", sha256=dataset_sha)],
    )


def test_cache_key_depends_on_dataset_digest(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    exp_dir = ot / "experiments" / "EXP-0001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "run.py").write_text("print('hi')\n", encoding="utf-8")

    key_a = _cache_key_for(ot, _exp("aaaa"), exp_dir)
    key_b = _cache_key_for(ot, _exp("bbbb"), exp_dir)
    assert key_a != key_b  # same script, different data => distinct key (no false cache hit)


# --- sympy verifier -----------------------------------------------------------


def test_sympy_verifier_accepts_identity() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    v = SymPyVerifier()
    assert v.is_available()
    res = v.verify('{"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq"}')
    assert res.accepted is True


def test_sympy_verifier_rejects_false_identity() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    res = SymPyVerifier().verify('{"lhs": "x + 1", "rhs": "x", "relation": "eq"}')
    assert res.accepted is False
    assert res.inconclusive is False  # a clean rejection, not "gave up"


def test_sympy_verifier_constant_inequality() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    assert SymPyVerifier().verify('{"lhs": "3", "rhs": "5", "relation": "le"}').accepted is True
    assert SymPyVerifier().verify('{"lhs": "5", "rhs": "3", "relation": "le"}').accepted is False


def test_sympy_verifier_inconclusive_on_nonconstant_inequality() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    # x**2 >= 0 is true but not via a constant-sign difference: honestly inconclusive.
    res = SymPyVerifier().verify(
        '{"lhs": "x**2", "rhs": "0", "relation": "ge", "vars": {"x": "real"}}'
    )
    assert res.inconclusive is True


def test_sympy_registered_when_enabled() -> None:
    from opentorus.research.verifiers.registry import available_verifiers

    assert "sympy" in available_verifiers(default_config())


# --- pack papers manifest -----------------------------------------------------


def test_pack_includes_papers_manifest(tmp_path: Path) -> None:
    import zipfile

    from opentorus.research.pack import export_pack, read_pack_manifest
    from opentorus.research.papers import Paper, _save_meta

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    _save_meta(
        ot,
        Paper(
            id="PAPER-0001",
            source="https://arxiv.org/abs/2002.01387",
            source_type="arxiv",
            title="A paper",
            arxiv_id="2002.01387",
            sha256="deadbeef",
        ),
    )
    pack = export_pack(ot)
    manifest = read_pack_manifest(pack)
    assert any(p.id == "PAPER-0001" and p.sha256 == "deadbeef" for p in manifest.papers)
    with zipfile.ZipFile(pack) as zf:
        assert "pack/papers-manifest.json" in zf.namelist()
