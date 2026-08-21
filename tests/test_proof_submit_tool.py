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


def test_rejection_teaches_certificate_format_by_example(tmp_path: Path) -> None:
    # Benchmark finding (wave 1): both capable models submitted malformed
    # certificates and then SWITCHED BACKENDS, because the rejection never showed
    # a valid shape. The failure text must carry a minimal valid example for the
    # JSON-certificate backends and tell the model to stay on the same backend.
    ot = _ot(tmp_path)

    class _SympyStub(StubVerifier):
        name = "sympy"

    tool = ProofSubmitTool(ot, default_config(), resolver=lambda name: _SympyStub())
    result = tool.run(_call(backend="sympy", source="not json"))
    assert result.ok is False
    assert '"lhs"' in result.content and '"relation"' in result.content
    assert "do not switch backends" in result.content

    # Non-certificate backends (stub name) keep their original, un-suffixed text.
    plain = _tool(ot).run(_call(backend="lean4", source="theorem t : nonsense"))
    assert "minimal VALID example" not in plain.content


# --- verifier timeout: the ceiling that used to be unreachable ------------------


def test_resolve_timeout_uses_config_default() -> None:
    from opentorus.research.verifiers.registry import resolve_timeout

    config = default_config()
    config.tools.verifiers.timeout_seconds = 300
    assert resolve_timeout(config) == (300, None)


def test_resolve_timeout_honours_a_larger_request() -> None:
    """The whole point: a finite-but-large check may ask for more than the default."""
    from opentorus.research.verifiers.registry import resolve_timeout

    config = default_config()
    config.tools.verifiers.timeout_seconds = 120
    config.tools.verifiers.max_timeout_seconds = 10800
    seconds, note = resolve_timeout(config, 7200)
    assert seconds == 7200
    assert note is None


def test_resolve_timeout_clamps_and_says_so() -> None:
    """A clamp is reported, never silent — a checker quietly given less time than
    asked for is indistinguishable from a proof that failed."""
    from opentorus.research.verifiers.registry import resolve_timeout

    config = default_config()
    config.tools.verifiers.max_timeout_seconds = 600
    seconds, note = resolve_timeout(config, 10800)
    assert seconds == 600
    assert note and "clamped to 600s" in note


def test_resolve_timeout_zero_ceiling_refuses_requests() -> None:
    from opentorus.research.verifiers.registry import resolve_timeout

    config = default_config()
    config.tools.verifiers.timeout_seconds = 90
    config.tools.verifiers.max_timeout_seconds = 0
    seconds, note = resolve_timeout(config, 3600)
    assert seconds == 90
    assert note and "max_timeout_seconds is 0" in note


def test_registry_passes_the_timeout_to_the_backend() -> None:
    """The bug was that nothing plumbed it: every backend got the 120s constructor
    default no matter what config said."""
    from opentorus.research.verifiers.registry import get_verifier

    config = default_config()
    config.tools.verifiers.smt = True
    config.tools.verifiers.timeout_seconds = 900
    smt = get_verifier(config, "smt")
    assert smt is not None
    assert smt.timeout == 900
    assert get_verifier(config, "smt", timeout=45).timeout == 45


def test_proof_submit_reports_the_clamp_to_the_model(tmp_path: Path) -> None:
    """An over-large request still runs, and the tool result says it was cut down."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.tools.verifiers.max_timeout_seconds = 600

    tool = ProofSubmitTool(ot, config, resolver=lambda name: StubVerifier())
    result = tool.run(
        ToolCall(
            name="proof_submit",
            args={"backend": "stub", "source": "VALID", "timeout": 10800},
        )
    )
    assert result.ok
    assert "clamped to 600s" in result.content
    assert result.metadata["timeout_seconds"] == 600


def test_proof_submit_rejects_a_non_integer_timeout(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    tool = ProofSubmitTool(ot, default_config(), resolver=lambda name: StubVerifier())
    result = tool.run(
        ToolCall(
            name="proof_submit",
            args={"backend": "stub", "source": "VALID", "timeout": "a while"},
        )
    )
    assert not result.ok
    assert "must be an integer" in result.content
