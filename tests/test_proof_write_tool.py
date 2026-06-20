"""Tests for proof_write agent tool and NL proof templates."""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import store
from opentorus.research.dossier.nl_proof import assemble_nl_proof_body, explicit_gaps
from opentorus.tools.base import ToolCall
from opentorus.tools.research import ProofWriteTool
from opentorus.workspace import init_workspace, workspace_dir


def test_assemble_nl_proof_sections() -> None:
    body = assemble_nl_proof_body(
        theorem="For all n, S(n)=n².",
        definitions="S(n) = sum of first n odd integers.",
        main_proof="By induction. [GAP-1] justify base case detail.",
        gaps_markdown="See [GAP-1].",
    )
    assert "## Theorem" in body
    assert "## Main proof" in body
    assert "[GAP-1]" in body
    gaps = explicit_gaps(gaps=[], body=body)
    assert any("GAP-1" in g for g in gaps)


def test_proof_write_tool_creates_dossier_artifact(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove X for all n.", title="Test")
    tool = ProofWriteTool(ot)
    result = tool.run(
        ToolCall(
            id="1",
            name="proof_write",
            args={
                "problem_id": "PROBLEM-0001",
                "title": "Induction on n",
                "theorem": "X holds for all n ≥ 1.",
                "definitions": "X(n) means …",
                "main_proof": "We prove X for all n ≥ 1. Base: n=1. Step: n→n+1. No gaps remain.",
                "evidence_notes": "EXP-0001 checked n≤100 (corroboration only).",
            },
        )
    )
    assert result.ok
    assert "PROOF-0001" in result.content
    assert "## Theorem" not in result.content
    proofs = store.list_proof_attempts(ot, "PROBLEM-0001")
    assert len(proofs) == 1
    body_path = store.dossier_dir(ot, "PROBLEM-0001") / proofs[0].body_path
    text = body_path.read_text(encoding="utf-8")
    assert "## Theorem" in text
    assert "NOT machine-checked" in text


def test_proof_write_requires_dossier(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    tool = ProofWriteTool(ot)
    result = tool.run(
        ToolCall(
            id="1",
            name="proof_write",
            args={
                "problem_id": "PROBLEM-0099",
                "title": "x",
                "theorem": "T",
                "main_proof": "P" * 20,
            },
        )
    )
    assert not result.ok


SIGN_STATEMENT = (
    "Let Pi be polynomials approximating the matrix sign function on "
    "I = [-1,-delta] union [delta,1]. What is the asymptotic error epsilon_m^* "
    "as a function of m and delta?"
)


def test_proof_write_rejects_off_topic_fredholm_primary(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, SIGN_STATEMENT, title="Sign function")
    tool = ProofWriteTool(ot)
    result = tool.run(
        ToolCall(
            id="1",
            name="proof_write",
            args={
                "problem_id": "PROBLEM-0001",
                "title": "Numerical Solution of Fredholm Integral Equation",
                "theorem": "Solve the Fredholm equation of the second kind.",
                "main_proof": (
                    "Discretize the Fredholm kernel K(x,t) and solve (I - lambda W K) phi = f. "
                    "Use quadrature on [a,b]."
                ),
            },
        )
    )
    assert not result.ok
    assert "scope=exploration" in result.content.lower() or "primary" in result.content.lower()


def test_proof_write_accepts_fredholm_exploration_with_bridge(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, SIGN_STATEMENT, title="Sign function")
    tool = ProofWriteTool(ot)
    bridge = (
        "Hypothesis: the minimax polynomial sign error epsilon_m^* on I=[-1,-delta] union "
        "[delta,1] might admit a Fredholm integral reformulation of the dual problem. "
        "[GAP-1] No literature link established yet."
    )
    result = tool.run(
        ToolCall(
            id="1",
            name="proof_write",
            args={
                "problem_id": "PROBLEM-0001",
                "scope": "exploration",
                "title": "Fredholm reformulation hypothesis for sign approximation",
                "theorem": (
                    "Explore Fredholm integral equation structure for dual minimax problems."
                ),
                "connection_to_dossier": bridge,
                "main_proof": (
                    "Standard Fredholm discretization yields (I - lambda W K) phi = f. "
                    "[GAP-2] Map this operator to epsilon_m^* for sign on I."
                ),
            },
        )
    )
    assert result.ok
    assert "scope: exploration" in result.content.lower()
    assert "does not complete prove run" in result.content.lower()
    proofs = store.list_proof_attempts(ot, "PROBLEM-0001")
    assert proofs[0].scope == "exploration"


def test_proof_write_coerces_stringified_gaps(tmp_path: Path) -> None:
    """An LLM that passes ``gaps`` as a JSON string must not corrupt them into
    one-character entries (regression: a single gap became 372 "gaps")."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, SIGN_STATEMENT, title="Sign function")
    tool = ProofWriteTool(ot)
    result = tool.run(
        ToolCall(
            id="1",
            name="proof_write",
            args={
                "problem_id": "PROBLEM-0001",
                "title": "Asymptotic polynomial sign approximation",
                "theorem": SIGN_STATEMENT,
                "main_proof": (
                    "We relate epsilon_m^* to the best polynomial approximation of sign on "
                    "I with gap delta. Sharp asymptotics in m remain open."
                ),
                "gaps": '["Precise constant factor unknown", "Exact degree relation unclear"]',
            },
        )
    )
    assert result.ok
    proofs = store.list_proof_attempts(ot, "PROBLEM-0001")
    assert proofs[0].gaps == [
        "Precise constant factor unknown",
        "Exact degree relation unclear",
    ]


def test_proof_write_accepts_on_topic_sign_sketch(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, SIGN_STATEMENT, title="Sign function")
    tool = ProofWriteTool(ot)
    result = tool.run(
        ToolCall(
            id="1",
            name="proof_write",
            args={
                "problem_id": "PROBLEM-0001",
                "title": "Asymptotic polynomial sign approximation",
                "theorem": SIGN_STATEMENT,
                "main_proof": (
                    "We relate epsilon_m^* to the best polynomial approximation of sign on "
                    "I with gap delta. [GAP-1] Sharp asymptotics in m remain open."
                ),
            },
        )
    )
    assert result.ok
    assert "PROOF-0001" in result.content
