"""Harvest counterexample findings from prove-session tool output into dossier artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from opentorus.agent.session import SessionMessage, read_messages
from opentorus.research.dossier import store
from opentorus.research.dossier.claims import add_claim, add_evidence, add_proof_attempt
from opentorus.research.dossier.experiments import create_experiment, experiment_dir


@dataclass
class ShellFinding:
    command: str
    stdout: str


@dataclass
class HarvestOutcome:
    harvested: bool = False
    experiment_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    proof_ids: list[str] = field(default_factory=list)


_COUNTEREXAMPLE_RE = re.compile(
    r"(counterexample\s+found|submodularity\s+violation|violation\s+details|"
    r"found\s+submodularity\s+violation|\"violation\"\s*:\s*true)",
    re.IGNORECASE,
)


def _session_messages(ot_dir: Path, session_id: str | None) -> list[SessionMessage]:
    messages = read_messages(ot_dir)
    if not session_id:
        return messages
    return [m for m in messages if m.metadata.get("session_id") == session_id]


def _extract_shell_runs(messages: list[SessionMessage]) -> list[ShellFinding]:
    pending_cmd = ""
    runs: list[ShellFinding] = []
    for msg in messages:
        if msg.role == "assistant":
            for call in msg.metadata.get("tool_calls") or []:
                if call.get("name") == "run_shell":
                    pending_cmd = str(call.get("args", {}).get("command", "")).strip()
        if msg.role != "tool" or msg.metadata.get("name") != "run_shell":
            continue
        content = msg.content.strip()
        stdout = content
        if "stdout:" in content:
            _, _, tail = content.partition("stdout:")
            stdout = tail.strip()
        runs.append(ShellFinding(command=pending_cmd or "(run_shell)", stdout=stdout))
    return runs


def _extract_exp_run_outputs(ot_dir: Path, messages: list[SessionMessage]) -> list[ShellFinding]:
    from opentorus.research.experiments import list_experiments

    by_id = {exp.id: exp for exp in list_experiments(ot_dir)}
    pending_exp_id = ""
    runs: list[ShellFinding] = []
    for msg in messages:
        if msg.role == "assistant":
            for call in msg.metadata.get("tool_calls") or []:
                if call.get("name") == "exp_run":
                    pending_exp_id = str(call.get("args", {}).get("exp_id", "")).strip().upper()
        if msg.role != "tool" or msg.metadata.get("name") != "exp_run":
            continue
        exp_id = pending_exp_id
        if not exp_id:
            match = re.search(r"\b(EXP-\d{4})\b", msg.content)
            exp_id = match.group(1).upper() if match else ""
        exp = by_id.get(exp_id)
        stdout_path = ot_dir / exp.path / "results" / "stdout.txt" if exp else None
        if stdout_path is not None and stdout_path.is_file():
            stdout = stdout_path.read_text(encoding="utf-8")
        else:
            stdout = msg.content
            if "stdout:" in stdout:
                _, _, stdout = stdout.partition("stdout:")
                stdout = stdout.strip()
        command = exp.command if exp and exp.command else f"exp_run({exp_id})"
        runs.append(ShellFinding(command=command, stdout=stdout))
    return runs


def _session_runs(ot_dir: Path, messages: list[SessionMessage]) -> list[ShellFinding]:
    return _extract_shell_runs(messages) + _extract_exp_run_outputs(ot_dir, messages)


def _counterexample_runs(runs: list[ShellFinding]) -> list[ShellFinding]:
    return [run for run in runs if _COUNTEREXAMPLE_RE.search(run.stdout)]


def _matrix_from_stdout(stdout: str) -> str:
    match = re.search(
        r"Matrix L:\s*\n(\[\[.+?\]\])",
        stdout,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1).strip())
    lines: list[str] = []
    capture = False
    for line in stdout.splitlines():
        if re.match(r"Matrix L:", line, re.IGNORECASE):
            capture = True
            if "[[" in line:
                lines.append(line.split(":", 1)[-1].strip())
            continue
        if capture:
            if line.strip().startswith("[") or line.strip().startswith("]"):
                lines.append(line.strip())
            if "]]" in line:
                break
    if lines:
        return " ".join(lines)
    block = re.search(r"L\s*=\s*(\[\[.+?\]\])", stdout, re.DOTALL)
    return block.group(1).strip() if block else ""


def _violation_from_stdout(stdout: str) -> str:
    match = re.search(r"Violation details:\s*(\{.+?\})", stdout, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"Total violations:\s*(\d+)", stdout, re.IGNORECASE)
    if match:
        return f"total_violations={match.group(1)}"
    return ""


def _record_experiment_stdout(
    ot_dir: Path,
    problem_id: str,
    *,
    title: str,
    command: str,
    stdout: str,
) -> str:
    exp = create_experiment(
        ot_dir,
        problem_id,
        title=title,
        command=command,
    )
    edir = experiment_dir(ot_dir, problem_id, exp.experiment_id)
    (edir / "stdout.log").write_text(stdout, encoding="utf-8")
    (edir / "stderr.log").write_text("", encoding="utf-8")
    exp.status = "succeeded"
    exp.result_summary = "Harvested from prove-session run_shell output (counterexample search)."
    from opentorus.research.dossier.experiments import _save_manifest

    _save_manifest(ot_dir, exp)
    (edir / "result.md").write_text(
        f"# {exp.experiment_id} — {title}\n\n"
        f"_Status: succeeded (harvested evidence, not proof)._\n\n"
        f"- command: `{command}`\n\n"
        f"## stdout\n\n```\n{stdout.strip()}\n```\n",
        encoding="utf-8",
    )
    return exp.experiment_id


def _refutation_proof_body(
    *,
    statement: str,
    exp_id: str,
    command: str,
    matrix: str,
    violation: str,
    stdout: str,
) -> str:
    matrix_block = matrix or "(see experiment stdout)"
    violation_block = violation or "(see experiment stdout)"
    return (
        f"## Theorem\n\n"
        f"{statement}\n\n"
        f"## Definitions\n\n"
        f"- **SDDM:** symmetric diagonally dominant M-matrix (non-positive off-diagonal, "
        f"diagonal strictly dominant).\n"
        f"- **Nuclear Nyström error:** "
        f"‖K − K_{{:,I}} K_{{I,I}}^{{-1}} K_{{I,:}}‖_* for K = (L + γI)^{{-1}}.\n"
        f"- **Submodularity:** diminishing returns "
        f"f(A∪{{i}})−f(A) ≥ f(B∪{{i}})−f(B) for A ⊆ B and i ∉ B.\n\n"
        f"## Main proof\n\n"
        f"1. Run `{command}` ({exp_id}) — finite exhaustive search in the script's stated domain.\n"
        f"2. Output records a concrete matrix L:\n\n"
        f"```\n{matrix_block}\n```\n\n"
        f"3. Violation of submodularity (diminishing returns):\n\n"
        f"```\n{violation_block}\n```\n\n"
        f"4. Therefore the SDDM/positive-definite case is **refuted** by this counterexample.\n"
        f"5. The SDD (non-M) case may remain open — separate search required. [GAP-1]\n\n"
        f"## Gaps and limitations\n\n"
        f"- [GAP-1] SDD positive-definite case not fully searched in {exp_id}.\n"
        f"- [GAP-2] Script domain is finite (small matrix enumeration); general theorem "
        f"not proved for all sizes.\n"
        f"- [GAP-3] SDDM/PD certification is computational in the script, not a separate "
        f"formal certificate.\n\n"
        f"## Supporting evidence (not proof)\n\n"
        f"- {exp_id} stdout (harvested):\n\n"
        f"```\n{stdout.strip()[:4000]}\n```\n"
    )


def harvest_prove_session(
    ot_dir: Path,
    problem_id: str,
    *,
    session_id: str | None = None,
    create_proof: bool = True,
) -> HarvestOutcome:
    """Persist counterexample runs from session tool output into the dossier."""
    pid = problem_id.strip().upper()
    store.require_dossier(ot_dir, pid)
    outcome = HarvestOutcome()

    if store.list_claims(ot_dir, pid):
        return outcome

    runs = _counterexample_runs(_session_runs(ot_dir, _session_messages(ot_dir, session_id)))
    if not runs:
        return outcome

    run = runs[-1]
    matrix = _matrix_from_stdout(run.stdout)
    violation = _violation_from_stdout(run.stdout)
    exp_id = _record_experiment_stdout(
        ot_dir,
        pid,
        title="Counterexample search (harvested from prove session)",
        command=run.command,
        stdout=run.stdout,
    )
    outcome.experiment_ids.append(exp_id)

    claim = add_claim(
        ot_dir,
        pid,
        claim_type="COUNTEREXAMPLE_CANDIDATE",
        statement=(
            "The nuclear Nyström error is not submodular for SDDM positive-definite "
            f"matrices; counterexample matrix L = {matrix or 'see EXP stdout'}."
        ),
        source_artifacts=[exp_id],
    )
    outcome.claim_ids.append(claim.id)

    evidence, _ = add_evidence(
        ot_dir,
        pid,
        claim.id,
        evidence_type="COMPUTATION",
        summary=(
            f"{exp_id} found a submodularity violation for an SDDM PD matrix "
            f"({violation or 'see stdout'})."
        ),
        direction="supports",
        source_artifacts=[exp_id],
        limitations=[
            "Finite search in script domain only",
            "SDD (non-M) case not covered by this run",
        ],
    )
    outcome.evidence_ids.append(evidence.id)

    if create_proof and not store.list_proof_attempts(ot_dir, pid):
        proof = add_proof_attempt(
            ot_dir,
            pid,
            title="Refutation sketch — SDDM counterexample (harvested)",
            body=_refutation_proof_body(
                statement=(
                    "The nuclear Nyström error is **not** submodular on column subsets "
                    "when L is SDDM and positive-definite."
                ),
                exp_id=exp_id,
                command=run.command,
                matrix=matrix,
                violation=violation,
                stdout=run.stdout,
            ),
            gaps=[
                "SDD positive-definite case still open",
                "Search domain is finite / script-bounded",
                "No formal SDDM/PD certificate separate from script",
            ],
            claim_links=[claim.id],
        )
        outcome.proof_ids.append(proof.id)

    outcome.harvested = True
    return outcome
