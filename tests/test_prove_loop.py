"""Tests for opentorus prove command helpers."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opentorus.agent.prove_loop import build_prove_prompt
from opentorus.cli import app
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.dossier import store
from opentorus.workspace import init_workspace, workspace_dir

runner = CliRunner()


def test_build_prove_prompt_requires_proof_write() -> None:
    text = build_prove_prompt("PROBLEM-0001")
    assert "proof_write" in text
    assert "PROBLEM-0001" in text
    assert "[GAP-1]" in text
    assert "we prove" in text.lower()
    assert "paper_fetch" in text
    assert "claim_new and evidence_add alone are NOT sufficient" in text


def test_build_prove_prompt_includes_statement_focus() -> None:
    text = build_prove_prompt(
        "PROBLEM-0001",
        statement_focus="What is epsilon_m^* for matrix sign polynomial approximation?",
    )
    assert "epsilon_m" in text
    assert "scope=primary" in text
    assert "scope=exploration" in text
    assert "connection_to_dossier" in text


def test_build_prove_prompt_with_focus_skips_statement_read() -> None:
    text = build_prove_prompt(
        "PROBLEM-0001",
        statement_focus="Polynomial sign approximation error epsilon_m^*.",
    )
    assert "read_file .opentorus/problems/PROBLEM-0001/statement.md" not in text
    assert "use this EXACT problem_id" in text
    assert "Do NOT read_file the statement or guess the id" in text


def test_build_prove_prompt_without_focus_reads_statement() -> None:
    text = build_prove_prompt("PROBLEM-0001")
    assert "read_file .opentorus/problems/PROBLEM-0001/statement.md" in text


def test_build_prove_prompt_literature_first() -> None:
    text = build_prove_prompt("PROBLEM-0001", literature_first=True, min_papers=3)
    assert "[parsed]" in text
    assert "paper_fetch" in text
    assert "at least 3" in text


def test_build_prove_prompt_default_no_min_literature() -> None:
    text = build_prove_prompt("PROBLEM-0001")
    assert "PAPER-*" in text
    assert "paper_fetch every [UNREAD]" not in text
    assert "paper_fetch" in text
    assert "fetch at least" not in text


def test_build_literature_prompt() -> None:
    from opentorus.agent.prove_loop import build_literature_prompt

    text = build_literature_prompt(
        "PROBLEM-0001",
        min_papers=3,
        focus="Polytope diameter conjecture in dimension n.",
    )
    assert "phase 1" in text.lower()
    assert "paper_fetch" in text
    assert "Do NOT call proof_write" in text
    assert "dossier_known_result_add" in text
    assert "Polytope diameter" in text
    assert "Exploratory searches are welcome" in text
    assert "lit_search" in text


def test_build_literature_recovery_hint_observations(tmp_path: Path) -> None:
    from opentorus.agent.prove_loop import build_literature_recovery_hint
    from opentorus.research.papers import acquire_paper, read_paper
    from opentorus.research.sources.base import SourceRecord
    from opentorus.workspace import init_workspace, workspace_dir

    pages = ["Abstract\nWe study linear solvers.\n1 Introduction\nBackward error bounds.\n"]

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    for i, aid in enumerate(("2401.00001", "2401.00002"), start=1):
        paper = acquire_paper(
            ot,
            SourceRecord(source="arxiv", title=f"Paper {i}", arxiv_id=aid),
            downloader=lambda u: b"%PDF fake",
        )
        read_paper(ot, paper.id, page_extractor=lambda path: pages)
    hint = build_literature_recovery_hint(
        ot, min_papers=2, obs_before=0, tools_used={"lit_search", "paper_fetch"}
    )
    assert "Do NOT run lit_search" not in hint
    assert "memory_add" in hint
    assert "paper_fetch" in hint or "paper_read" in hint or "lit_search" in hint


def test_build_prove_prompt_no_literature() -> None:
    text = build_prove_prompt("PROBLEM-0001", literature_first=False)
    assert "fetch at least" not in text


def test_build_prove_prompt_disprove_mode() -> None:
    text = build_prove_prompt("problem-0002", disprove=True)
    assert "counterexample" in text.lower()
    assert "PROBLEM-0002" in text


def test_prove_cli_missing_dossier(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    init_workspace(tmp_path)
    res = runner.invoke(app, ["prove", "PROBLEM-0001"])
    assert res.exit_code != 0


def test_build_prove_prompt_mentions_gap_continuation() -> None:
    text = build_prove_prompt("PROBLEM-0001", literature_first=False)
    assert "keep working while gaps remain" in text.lower()


def test_run_prove_continues_after_proof_with_gaps(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    statement = (
        "What is the Krylov backward error lower bound for ill-conditioned systems "
        "in terms of the condition number kappa?"
    )
    store.create_dossier(ot, statement, title="Krylov backward error")

    class GapFillProvider:
        def __init__(self) -> None:
            self._n = 0

        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            from opentorus.providers.base import ProviderResponse

            self._n += 1
            if self._n == 1:
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="proof_write",
                    tool_args={
                        "problem_id": "PROBLEM-0001",
                        "title": "First sketch",
                        "theorem": statement,
                        "main_proof": (
                            "For Krylov backward error, the lower bound scales with kappa. "
                            "Step one. [GAP-1] missing."
                        ),
                        "gaps_markdown": "[GAP-1] justify step.",
                        "gaps": ["Step one"],
                    },
                )
            if self._n == 2:
                return ProviderResponse(kind="message", content="All done now.")
            return ProviderResponse(
                kind="tool_call",
                content="",
                tool_name="proof_write",
                tool_args={
                    "problem_id": "PROBLEM-0001",
                    "title": "Filled sketch",
                    "theorem": statement,
                    "main_proof": (
                        "For Krylov backward error, the lower bound scales with kappa. "
                        "Complete argument without gaps."
                    ),
                    "gaps_markdown": "None.",
                    "gaps": [],
                },
            )

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 12
    config.agent.prove_gap_fill_max_steps = 8
    config.agent.prove_until_gaps_closed = True
    outcome = run_prove(root, ot, GapFillProvider(), config, "PROBLEM-0001", literature_first=False)
    assert outcome.tool_calls >= 2
    # A dossier has ONE primary answer: gap-fill REFINES it in place rather than
    # accumulating near-duplicate primary sketches (the amnesia loop). So the second
    # proof_write updates PROOF-0001 instead of creating PROOF-0002.
    from opentorus.research.dossier import store as _store

    primaries = [p for p in _store.list_proof_attempts(ot, "PROBLEM-0001") if p.scope == "primary"]
    assert len(primaries) == 1
    assert outcome.gaps_remaining == 0  # the single primary was refined to gap-free


def test_run_prove_stops_early_when_gaps_disabled(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    store.create_dossier(ot, "For all n, S(n)=n².", title="Gauss sum")

    class ProofProvider:
        def __init__(self) -> None:
            self._n = 0

        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            from opentorus.providers.base import ProviderResponse

            self._n += 1
            if self._n == 1:
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="proof_write",
                    tool_args={
                        "problem_id": "PROBLEM-0001",
                        "title": "Induction proof",
                        "theorem": "S(n)=n² for all n≥1.",
                        "definitions": "S(n) is the sum of the first n odd integers.",
                        "main_proof": "By induction on n. [GAP-1] algebra detail.",
                        "gaps_markdown": "[GAP-1] expand inductive algebra.",
                        "gaps": ["Inductive step algebra"],
                    },
                )
            return ProviderResponse(kind="message", content="Proof draft recorded.")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 4
    config.agent.prove_until_gaps_closed = False
    outcome = run_prove(
        root,
        ot,
        ProofProvider(),
        config,
        "PROBLEM-0001",
        literature_first=False,
    )
    assert outcome.proof_ids == ["PROOF-0001"]
    assert outcome.gap_count >= 1
    assert len(store.list_proof_attempts(ot, "PROBLEM-0001")) == 1


def test_run_prove_no_progress_backstop_stops_unbounded_gap_fill(tmp_path: Path) -> None:
    # A model that writes a gapped sketch and never reduces the gap count must not grind
    # forever, even with inf caps (the random_nla workspace config). The no-progress
    # backstop ends gap-fill after a window of steps with no gap reduction. The model
    # alternates proof_write/message so the chat-only stall guard never fires — only the
    # no-progress guard can terminate the run.
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    store.create_dossier(ot, "Is P=NP?", title="P vs NP")

    stuck_proof = {
        "problem_id": "PROBLEM-0001",
        "title": "Sketch",
        "theorem": "P=NP.",
        "main_proof": "Consider a reduction. [GAP-1] the hard direction is unresolved.",
        "gaps_markdown": "[GAP-1] hard direction.",
        "gaps": ["hard direction"],
    }

    class StuckProvider:
        def __init__(self) -> None:
            self._n = 0

        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            self._n += 1
            if self._n % 2 == 1:  # odd: rewrite the same gapped sketch (no progress)
                return ProviderResponse(
                    kind="tool_call", content="", tool_name="proof_write", tool_args=stuck_proof
                )
            return ProviderResponse(kind="message", content="Still working on the gap.")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = float("inf")  # the unbounded config that caused the 80-min grind
    config.agent.prove_gap_fill_max_steps = float("inf")
    config.agent.prove_gap_fill_no_progress_steps = 4
    config.agent.prove_until_gaps_closed = True
    # If the backstop is broken this run never returns (inf caps). It returning is the test.
    outcome = run_prove(root, ot, StuckProvider(), config, "PROBLEM-0001", literature_first=False)
    assert outcome.gaps_remaining >= 1  # stopped with the gap still open, not forced to 0
    assert outcome.gap_fill_exhausted  # reported as a no-progress / cap stop, not a clean close
    assert outcome.proof_ids == ["PROOF-0001"]
    # Terminated by the no-progress window, not after thousands of steps.
    assert outcome.tool_calls <= 6


def test_no_progress_window_resets_on_new_evidence(tmp_path: Path, monkeypatch) -> None:
    # A model that keeps gathering NEW evidence (experiments / parsed papers) toward a gap
    # must NOT be cut off by the no-progress backstop, even though the gap COUNT has not
    # dropped yet. Without this, a model running experiments to close a gap is killed
    # mid-work (the user's "terminates early with a gapped proof"). Contrast with the
    # stuck test above, where evidence is constant and the window fires at tool_calls<=6.
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    store.create_dossier(ot, "Is P=NP?", title="P vs NP")

    gapped = {
        "problem_id": "PROBLEM-0001",
        "title": "Sketch",
        "theorem": "P=NP.",
        "main_proof": "Consider a reduction. [GAP-1] the hard direction is unresolved.",
        "gaps_markdown": "[GAP-1] hard direction.",
        "gaps": ["hard direction"],
    }

    # Simulate evidence that grows on every check (the model is actively gathering it).
    grow = {"n": 0}

    def _growing_experiments(ot_dir, problem_id=None, **kwargs):
        grow["n"] += 1
        return [object()] * grow["n"]

    monkeypatch.setattr(
        "opentorus.research.dossier.experiments.list_experiments", _growing_experiments
    )
    monkeypatch.setattr("opentorus.research.papers.list_papers", lambda ot_dir: [])

    class GatheringProvider:
        def __init__(self) -> None:
            self._n = 0

        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            self._n += 1
            if self._n % 2 == 1:
                return ProviderResponse(
                    kind="tool_call", content="", tool_name="proof_write", tool_args=gapped
                )
            return ProviderResponse(kind="message", content="Gathering more evidence.")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 30  # finite hard backstop so the test cannot hang
    config.agent.prove_gap_fill_max_steps = float("inf")
    config.agent.prove_gap_fill_no_progress_steps = 4  # small window
    config.agent.prove_until_gaps_closed = True
    outcome = run_prove(
        root, ot, GatheringProvider(), config, "PROBLEM-0001", literature_first=False
    )
    # Evidence kept resetting the window, so the run ran far past the 4-step window
    # (to the max_steps backstop) instead of stopping early like the stuck case.
    assert outcome.gaps_remaining >= 1
    assert outcome.tool_calls > 6


def test_run_prove_creates_proof_artifact(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    store.create_dossier(ot, "For all n, S(n)=n².", title="Gauss sum")

    class ProofProvider:
        def __init__(self) -> None:
            self._n = 0

        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            from opentorus.providers.base import ProviderResponse

            self._n += 1
            if self._n == 1:
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="proof_write",
                    tool_args={
                        "problem_id": "PROBLEM-0001",
                        "title": "Induction proof",
                        "theorem": "S(n)=n² for all n≥1.",
                        "definitions": "S(n) is the sum of the first n odd integers.",
                        "main_proof": (
                            "By induction on n. Base n=1. Step n→n+1. [GAP-1] algebra detail."
                        ),
                        "gaps_markdown": "[GAP-1] expand inductive algebra.",
                        "gaps": ["Inductive step algebra"],
                    },
                )
            return ProviderResponse(kind="message", content="Proof draft recorded.")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 4
    config.agent.prove_until_gaps_closed = False
    outcome = run_prove(
        root,
        ot,
        ProofProvider(),
        config,
        "PROBLEM-0001",
        literature_first=False,
    )
    assert outcome.proof_ids == ["PROOF-0001"]
    assert outcome.gap_count >= 1
    assert len(store.list_proof_attempts(ot, "PROBLEM-0001")) == 1


def test_literature_requirements_zero_min_always_met(tmp_path: Path) -> None:
    from opentorus.agent.prove_loop import literature_requirements_met
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    ok, detail = literature_requirements_met(ot, min_papers=0, obs_before=0, tools_used=set())
    assert ok is True
    assert "No minimum" in detail


def test_build_literature_prompt_zero_min_no_quota() -> None:
    from opentorus.agent.prove_loop import build_literature_prompt

    text = build_literature_prompt("PROBLEM-0001", min_papers=0)
    assert "no fixed minimum" in text.lower()
    assert "at least 0" not in text


def test_literature_requirements_need_observations(tmp_path: Path) -> None:
    from opentorus.agent.prove_loop import literature_requirements_met
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    ok, detail = literature_requirements_met(
        ot, min_papers=1, obs_before=0, tools_used={"paper_fetch"}
    )
    assert not ok
    assert "parsed" in detail.lower() or "observation" in detail.lower()


def test_build_prove_prompt_open_problem() -> None:
    text = build_prove_prompt("PROBLEM-0001", open_problem=True)
    assert "open" in text.lower()
    assert "status sketch" in text.lower()
    assert "Do NOT claim" in text


def test_lint_proof_sketch_flags_log_polynomial_in_hirsch_context() -> None:
    from opentorus.research.dossier.nl_proof import lint_proof_sketch

    body = (
        "The polytope graph diameter bound (n-d) log d is polynomial in n and d, "
        "establishing the polynomial Hirsch conjecture."
    )
    warnings = lint_proof_sketch(body, open_problem=True)
    assert any("Hirsch" in w for w in warnings)


def test_lint_proof_sketch_polynomial_log_unrelated_no_warning() -> None:
    from opentorus.research.dossier.nl_proof import lint_proof_sketch

    body = (
        "For every square matrix A and polynomial p, we bound log||p(A)|| on the grid. "
        "This is unrelated to polytope diameters."
    )
    assert lint_proof_sketch(body, open_problem=True) == []


def test_run_prove_bootstraps_proof_write_after_write_file_without_proof(tmp_path: Path) -> None:
    """Model may call write_file then chat — prove must still get proof_write."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    store.create_dossier(ot, "Matrix sign function error vs budget.", title="Sign function")

    class WriteThenChatProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def __init__(self) -> None:
            self._n = 0

        def generate(self, messages, tools=None):
            self._n += 1
            if self._n == 1:
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="write_file",
                    tool_args={
                        "path": "analysis.md",
                        "content": "# Summary\n\nError drops with budget.\n",
                    },
                )
            return ProviderResponse(
                kind="message",
                content="I wrote analysis.md. Let me know if you want a proof sketch.",
            )

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 12
    config.agent.prove_until_gaps_closed = False
    outcome = run_prove(
        root,
        ot,
        WriteThenChatProvider(),
        config,
        "PROBLEM-0001",
        literature_first=False,
    )
    assert outcome.proof_ids == ["PROOF-0001"]
    assert outcome.tool_calls >= 1
    assert len(store.list_proof_attempts(ot, "PROBLEM-0001")) == 1


def test_run_prove_bootstraps_proof_write_on_chat_only(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    store.create_dossier(
        ot, "Is the nuclear Nyström error submodular for SDDM L?", title="Submodularity"
    )

    class ChatOnlyProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            return ProviderResponse(
                kind="message",
                content="I'm ready to help! What would you like to work on?",
            )

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 6
    config.agent.prove_until_gaps_closed = False
    outcome = run_prove(
        root,
        ot,
        ChatOnlyProvider(),
        config,
        "PROBLEM-0001",
        literature_first=False,
    )
    assert outcome.proof_ids == ["PROOF-0001"]
    assert outcome.tool_calls >= 1


def test_reopen_referee_gaps_blocks_overclaiming_gapfree_proof(tmp_path: Path) -> None:
    """A gap-free proof that overclaims is not 'done': the referee reopens its gaps.

    Pins the fix for the trace where the prove loop stopped very early — the model had
    emptied `gaps` (relabelling unresolved steps as prose 'Open Problems') while the body
    still asserted an unsupported result, and the loop accepted it.
    """
    from opentorus.agent.prove_loop import _REFEREE_GAP_PREFIX, reopen_referee_gaps
    from opentorus.research.dossier import claims

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dossier = store.create_dossier(ot, "Does property P hold for all matrices A?", title="P")
    pid = dossier.id

    # Gap-free sketch, but the body asserts an unsupported result with no verification.
    claims.add_proof_attempt(
        ot,
        pid,
        title="overclaiming sketch",
        body="We prove that property P holds for all matrices A. QED.",
        kind="sketch",
        gaps=[],
    )
    reopened = reopen_referee_gaps(ot, pid)
    assert reopened, "the hostile referee must reopen gaps on a gap-free overclaiming proof"
    assert all(g.startswith(_REFEREE_GAP_PREFIX) for g in reopened)
    assert store.list_proof_attempts(ot, pid)[-1].gaps == reopened  # written back onto the proof

    # Idempotent: re-running on the unchanged proof reproduces the same gaps (no growth).
    assert reopen_referee_gaps(ot, pid) == reopened
    assert store.list_proof_attempts(ot, pid)[-1].gaps == reopened

    # Fixing the body (honest language) lets the referee pass; stale referee gaps are cleared.
    latest = store.list_proof_attempts(ot, pid)[-1]
    assert latest.body_path is not None
    (store.dossier_dir(ot, pid) / latest.body_path).write_text(
        "# fixed\n\nWe conjecture that property P holds; a sketch argues the main step.\n",
        encoding="utf-8",
    )
    assert reopen_referee_gaps(ot, pid) == []
    assert store.list_proof_attempts(ot, pid)[-1].gaps == []


def test_run_prove_continues_when_referee_blocks_gapfree_proof(tmp_path: Path) -> None:
    """End-to-end: the loop does NOT stop at the first gap-free 'done' if the referee blocks;
    it reopens gaps, keeps working, and finishes once the overclaim is fixed."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    statement = "Is there an optimal restart length m* for restarted Arnoldi f(A)b methods?"
    store.create_dossier(ot, statement, title="Restart length")

    class OverclaimThenFixProvider:
        def __init__(self) -> None:
            self._n = 0

        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            from opentorus.providers.base import ProviderResponse

            self._n += 1
            if self._n == 1:
                # Gap-free, but overclaims ("we prove") with no verification artifact.
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="proof_write",
                    tool_args={
                        "problem_id": "PROBLEM-0001",
                        "title": "Restart length sketch",
                        "theorem": "An optimal restart length m* exists for restarted Arnoldi.",
                        "main_proof": (
                            "For restarted Arnoldi f(A)b methods we prove that an optimal "
                            "restart length m* exists and is finite. QED."
                        ),
                        "gaps_markdown": "None.",
                        "gaps": [],
                    },
                )
            if self._n == 2:
                # First "done": the referee blocks (we prove) → it reopens gaps → loop continues.
                return ProviderResponse(kind="message", content="Proof complete; no gaps.")
            if self._n == 3:
                # After the referee reopened gaps, fix the overclaim and stay gap-free.
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="proof_write",
                    tool_args={
                        "problem_id": "PROBLEM-0001",
                        "title": "Restart length sketch (honest)",
                        "theorem": "An optimal restart length m* for restarted Arnoldi.",
                        "main_proof": (
                            "For restarted Arnoldi f(A)b methods we conjecture an optimal restart "
                            "length m*; a sketch argues it balances per-cycle cost against decay."
                        ),
                        "gaps_markdown": "None.",
                        "gaps": [],
                    },
                )
            # Second "done": the honest body passes the referee → the run settles cleanly.
            return ProviderResponse(kind="message", content="Honest sketch recorded.")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 12
    config.agent.prove_gap_fill_max_steps = 8
    config.agent.prove_until_gaps_closed = True
    outcome = run_prove(
        root, ot, OverclaimThenFixProvider(), config, "PROBLEM-0001", literature_first=False
    )
    # Two proof_writes ran: the loop continued past the first overclaiming "done" because
    # the referee reopened gaps, and only settled once the body was made honest.
    assert outcome.tool_calls >= 2
    assert outcome.gaps_remaining == 0
    assert outcome.referee_verdict != "block"


def test_run_prove_referee_reopen_can_be_disabled(tmp_path: Path) -> None:
    """With prove_referee_reopens_gaps=False the loop keeps the old behavior: a gap-free
    proof ends the run even if it overclaims (the referee only records, post-hoc)."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    store.create_dossier(ot, "Does property P hold for all matrices A?", title="P")

    class OverclaimProvider:
        def __init__(self) -> None:
            self._n = 0

        @property
        def name(self) -> str:
            return "mock"

        @property
        def supports_streaming(self) -> bool:
            return False

        def generate(self, messages, tools=None):
            from opentorus.providers.base import ProviderResponse

            self._n += 1
            if self._n == 1:
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="proof_write",
                    tool_args={
                        "problem_id": "PROBLEM-0001",
                        "title": "Overclaim sketch",
                        "theorem": "Property P holds for all matrices A.",
                        "main_proof": "We prove that property P holds for all matrices A. QED.",
                        "gaps_markdown": "None.",
                        "gaps": [],
                    },
                )
            return ProviderResponse(kind="message", content="Done; no gaps.")

        def respond(self, messages, tools=None, **kwargs):
            return self.generate(messages, tools)

    from opentorus.agent.prove_loop import run_prove
    from opentorus.config import default_config

    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = 12
    config.agent.prove_until_gaps_closed = True
    config.agent.prove_referee_reopens_gaps = False
    outcome = run_prove(
        root, ot, OverclaimProvider(), config, "PROBLEM-0001", literature_first=False
    )
    assert outcome.tool_calls == 1  # stopped at the first gap-free "done"
    assert outcome.gaps_remaining == 0
