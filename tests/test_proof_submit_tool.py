"""The proof_submit agent tool: the model-facing route to formal verification.

Pins the honest behavior of the round-trip loop (submit → verifier output →
resubmit): failed attempts are preserved, unavailable backends never read as
verification, an accepted attempt never promotes a claim by itself, and the
tool only exists when a verifier backend is enabled in config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.config import default_config
from opentorus.errors import OpenTorusError
from opentorus.research.claims import get_claim, new_claim, update_claim
from opentorus.research.graph import related
from opentorus.research.verifiers.base import VerificationResult
from opentorus.research.verifiers.proofs import list_proofs
from opentorus.tools.base import ToolCall
from opentorus.tools.research import ProofSubmitTool, enabled_verifier_backends
from opentorus.workspace import init_workspace, workspace_dir


class StubVerifier:
    """Accepts iff the source contains 'VALID'; optionally unavailable/inconclusive."""

    name = "stub"

    def __init__(self, available: bool = True, inconclusive: bool = False) -> None:
        self._available = available
        self._inconclusive = inconclusive

    def is_available(self) -> bool:
        return self._available

    def version(self) -> str | None:
        return "stub-1.0" if self._available else None

    def verify(self, source: str) -> VerificationResult:
        if not self._available:
            return VerificationResult(
                backend=self.name, accepted=False, available=False, output="not installed"
            )
        if self._inconclusive:
            return VerificationResult(
                backend=self.name, accepted=False, inconclusive=True, output="timeout after 60s"
            )
        ok = "VALID" in source
        return VerificationResult(
            backend=self.name,
            backend_version="stub-1.0",
            accepted=ok,
            output="QED" if ok else "error: unknown identifier 'nonsense'",
        )


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _tool(ot: Path, **stub_kwargs) -> ProofSubmitTool:
    return ProofSubmitTool(ot, default_config(), resolver=lambda name: StubVerifier(**stub_kwargs))


def _call(**args) -> ToolCall:
    return ToolCall(name="proof_submit", args=args)


def test_accept_records_artifact_and_validates_edge(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "VALID lemma holds.")
    result = _tool(ot).run(
        _call(backend="lean4", source="theorem t : VALID := rfl", claim_id=claim.id)
    )
    assert result.ok is True
    assert "ACCEPTED" in result.content
    proofs = list_proofs(ot)
    assert len(proofs) == 1 and proofs[0].accepted
    edges = related(ot, proofs[0].id)
    assert any(e.relation == "validates" and e.target_id == claim.id for e in edges)


def test_accept_never_promotes_the_claim_by_itself(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "VALID lemma holds.")
    _tool(ot).run(_call(backend="lean4", source="theorem t : VALID := rfl", claim_id=claim.id))
    refreshed = get_claim(ot, claim.id)
    assert refreshed is not None and refreshed.status == "idea"


def test_accept_unlocks_gated_promotion_only(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "VALID lemma holds.")
    # Without an accepted proof, formally_verified must be unreachable.
    with pytest.raises(OpenTorusError):
        update_claim(ot, claim.id, status="formally_verified", confirm=lambda old, new: True)
    _tool(ot).run(_call(backend="lean4", source="theorem t : VALID := rfl", claim_id=claim.id))
    promoted = update_claim(ot, claim.id, status="formally_verified", confirm=lambda old, new: True)
    assert promoted.status == "formally_verified"


def test_rejection_returns_verifier_output_and_retry_hint(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    result = _tool(ot).run(_call(backend="lean4", source="theorem t : nonsense"))
    assert result.ok is False
    assert "REJECTED" in result.content
    assert "unknown identifier" in result.content  # verbatim verifier output fed back
    assert "proof_submit again" in result.content


def test_retry_after_rejection_preserves_the_failed_attempt(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    tool = _tool(ot)
    first = tool.run(_call(backend="lean4", source="theorem t : nonsense"))
    second = tool.run(_call(backend="lean4", source="theorem t : VALID := rfl"))
    assert first.ok is False and second.ok is True
    proofs = list_proofs(ot)
    assert [p.accepted for p in proofs] == [False, True]  # failure kept, not overwritten


def test_unavailable_backend_is_not_verification(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    result = _tool(ot, available=False).run(
        _call(backend="lean4", source="theorem t : VALID := rfl")
    )
    assert result.ok is False
    assert "did NOT run" in result.content


def test_inconclusive_is_not_a_rejection(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    result = _tool(ot, inconclusive=True).run(
        _call(backend="lean4", source="theorem t : VALID := rfl")
    )
    assert result.ok is False
    assert "INCONCLUSIVE" in result.content
    assert "NOT a mathematical rejection" in result.content
    assert list_proofs(ot)[0].inconclusive is True


def test_unconfigured_backend_fails_cleanly(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    tool = ProofSubmitTool(ot, default_config())  # no resolver, no enabled backends
    result = tool.run(_call(backend="lean4", source="theorem t : VALID := rfl"))
    assert result.ok is False
    assert "not enabled" in result.content


def test_unknown_claim_rejected_before_submission(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    result = _tool(ot).run(
        _call(backend="lean4", source="theorem t : VALID := rfl", claim_id="CLAIM-9999")
    )
    assert result.ok is False
    assert list_proofs(ot) == []  # nothing recorded for a dangling claim id


def test_registered_only_when_a_backend_is_enabled(tmp_path: Path) -> None:
    from opentorus.tools.builtin import build_default_registry

    ot = _ot(tmp_path)
    config = default_config()
    config.tools.verifiers.interval = False
    config.tools.verifiers.sympy = False
    assert enabled_verifier_backends(config) == []
    registry = build_default_registry(tmp_path, ot, config)
    assert registry.get("proof_submit") is None

    # The default config ships interval + sympy enabled → tool present by default.
    assert enabled_verifier_backends(default_config()) == ["interval", "sympy"]
    registry = build_default_registry(tmp_path, ot, default_config())
    tool = registry.get("proof_submit")
    assert tool is not None
    assert "interval, sympy" in tool.description


def test_literature_phase_blocks_proof_submit() -> None:
    from opentorus.agent.literature_gate import literature_tool_gate

    gate = literature_tool_gate()
    message = gate("proof_submit", {"backend": "lean4", "source": "theorem t : VALID := rfl"})
    assert message is not None and "literature phase" in message


def test_prove_prompt_mentions_formal_step_only_when_enabled() -> None:
    from opentorus.agent.prove_loop import build_prove_prompt

    plain = build_prove_prompt("PROBLEM-0001")
    assert "proof_submit" not in plain
    formal = build_prove_prompt("PROBLEM-0001", formal_backends=["lean4", "smt"])
    assert "proof_submit" in formal
    assert "lean4, smt" in formal
