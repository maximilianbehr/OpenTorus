"""File-based persistence for problem dossiers.

Everything is plain YAML / JSONL / Markdown on disk so a dossier is fully
inspectable and Git-friendly. There is no database. A dossier lives under
``.opentorus/problems/PROBLEM-XXXX/`` with this layout::

    PROBLEM-0001/
      statement.md
      problem.yaml
      definitions.yaml
      assumptions.yaml
      known_results.yaml
      related_papers.jsonl
      approaches.jsonl
      failed_attempts.jsonl
      claims.jsonl
      experiments/
      proof_attempts/
      counterexample_search/
      evidence/
      report.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from opentorus.atomicio import atomic_write_text
from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_id, next_sequential_id, read_jsonl, rewrite_jsonl
from opentorus.research.dossier.models import (
    Approach,
    Assumption,
    ClaimRecord,
    ClaimStatusChange,
    Definition,
    EvidenceRecord,
    FailedAttempt,
    KnownResult,
    ProblemDossier,
    ProofAttempt,
    RelatedPaper,
    TheoremRef,
    utcnow,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

_SUBDIRS = ("experiments", "proof_attempts", "counterexample_search", "evidence")


# --- Paths --------------------------------------------------------------------


def problems_root(ot_dir: Path) -> Path:
    return ot_dir / "problems"


def dossier_dir(ot_dir: Path, problem_id: str) -> Path:
    return problems_root(ot_dir) / problem_id


def _active_problem_path(ot_dir: Path) -> Path:
    return problems_root(ot_dir) / ".current"


def set_active_problem(ot_dir: Path, problem_id: str) -> None:
    """Record ``problem_id`` as the workspace's current problem."""
    root = problems_root(ot_dir)
    root.mkdir(parents=True, exist_ok=True)
    _active_problem_path(ot_dir).write_text(problem_id.strip().upper() + "\n", encoding="utf-8")


def get_active_problem(ot_dir: Path) -> str | None:
    """Return the current problem id, or None if unset or its dossier is gone."""
    path = _active_problem_path(ot_dir)
    if not path.is_file():
        return None
    pid = path.read_text(encoding="utf-8").strip()
    if not pid or get_dossier(ot_dir, pid) is None:
        return None
    return pid


def clear_active_problem(ot_dir: Path) -> None:
    """Unset the active problem.

    Used after bulk creation of several dossiers: leaving one of them arbitrarily
    "active" makes a later ``run``/``research`` silently attribute its claims and
    experiments to an unrelated problem. Clearing forces an explicit choice.
    """
    path = _active_problem_path(ot_dir)
    if path.is_file():
        path.unlink()


def _problem_yaml(ot_dir: Path, problem_id: str) -> Path:
    return dossier_dir(ot_dir, problem_id) / "problem.yaml"


# --- YAML list helpers --------------------------------------------------------


def _read_yaml_list(path: Path, model_cls: type[ModelT]) -> list[ModelT]:
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise OpenTorusError(f"Expected a YAML list in {path}.")
    return [model_cls.model_validate(item) for item in raw]


def _write_yaml_list(path: Path, models: list[BaseModel]) -> None:
    payload = [m.model_dump(mode="json") for m in models]
    atomic_write_text(path, yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


def _write_yaml(path: Path, model: BaseModel) -> None:
    atomic_write_text(
        path,
        yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
    )


# --- Dossier lifecycle --------------------------------------------------------


def list_dossiers(ot_dir: Path) -> list[ProblemDossier]:
    root = problems_root(ot_dir)
    if not root.is_dir():
        return []
    out: list[ProblemDossier] = []
    for child in sorted(root.iterdir()):
        meta = child / "problem.yaml"
        if meta.is_file():
            out.append(ProblemDossier.model_validate(yaml.safe_load(meta.read_text("utf-8"))))
    return out


def get_dossier(ot_dir: Path, problem_id: str) -> ProblemDossier | None:
    meta = _problem_yaml(ot_dir, problem_id)
    if not meta.is_file():
        return None
    return ProblemDossier.model_validate(yaml.safe_load(meta.read_text("utf-8")))


def require_dossier(ot_dir: Path, problem_id: str) -> ProblemDossier:
    dossier = get_dossier(ot_dir, problem_id)
    if dossier is None:
        raise OpenTorusError(f"No problem dossier with id '{problem_id}'.")
    return dossier


_PROBLEM_NUM = re.compile(r"(\d+)")


def canonical_problem_id(raw: str) -> str | None:
    """Best-effort canonical ``PROBLEM-NNNN`` from fuzzy input (e.g. ``problem 1``)."""
    match = _PROBLEM_NUM.search(raw or "")
    if not match:
        return None
    return f"PROBLEM-{int(match.group(1)):04d}"


def resolve_dossier_id(ot_dir: Path, raw: str) -> str | None:
    """Return an existing dossier id matching fuzzy/zero-unpadded input, else ``None``.

    Accepts the exact id, a differently zero-padded variant (``PROBLEM-1`` →
    ``PROBLEM-0001``), or bare numbers. Only returns ids that actually exist.
    """
    raw_norm = (raw or "").strip().upper()
    existing = {d.id for d in list_dossiers(ot_dir)}
    if raw_norm in existing:
        return raw_norm
    canon = canonical_problem_id(raw_norm)
    if canon and canon in existing:
        return canon
    return None


def _next_problem_id(ot_dir: Path) -> str:
    return next_sequential_id("PROBLEM", len(list_dossiers(ot_dir)))


def create_dossier(
    ot_dir: Path,
    statement: str,
    *,
    title: str = "",
    domain: str = "",
    tags: list[str] | None = None,
) -> ProblemDossier:
    """Create a new dossier directory with its full scaffold."""
    statement = statement.strip()
    if not statement:
        raise OpenTorusError("A problem needs a non-empty statement.")
    problem_id = _next_problem_id(ot_dir)
    if not title:
        title = statement if len(statement) <= 80 else statement[:77] + "…"
    dossier = ProblemDossier(id=problem_id, title=title, domain=domain, tags=tags or [])

    base = dossier_dir(ot_dir, problem_id)
    base.mkdir(parents=True, exist_ok=True)
    for sub in _SUBDIRS:
        (base / sub).mkdir(exist_ok=True)
        (base / sub / ".gitkeep").touch()

    _write_yaml(_problem_yaml(ot_dir, problem_id), dossier)
    (base / "statement.md").write_text(f"# {problem_id}\n\n{statement}\n", encoding="utf-8")
    # Seed empty ledgers so the layout is self-documenting.
    _write_yaml_list(base / "definitions.yaml", [])
    _write_yaml_list(base / "assumptions.yaml", [])
    _write_yaml_list(base / "known_results.yaml", [])
    (base / "related_papers.jsonl").touch()
    (base / "approaches.jsonl").touch()
    (base / "failed_attempts.jsonl").touch()
    (base / "claims.jsonl").touch()
    (base / "report.md").write_text(
        f"# {problem_id} — report not built yet\n\nRun `opentorus problem report {problem_id}`.\n",
        encoding="utf-8",
    )
    # A freshly created dossier becomes the active problem so subsequent commands
    # can omit the id (the most common case is working on the one just created).
    set_active_problem(ot_dir, problem_id)
    return dossier


def save_dossier(ot_dir: Path, dossier: ProblemDossier) -> ProblemDossier:
    dossier.updated_at = utcnow()
    _write_yaml(_problem_yaml(ot_dir, dossier.id), dossier)
    return dossier


def read_statement(ot_dir: Path, problem_id: str) -> str:
    path = dossier_dir(ot_dir, problem_id) / "statement.md"
    return path.read_text("utf-8") if path.is_file() else ""


def statement_body_for_display(raw: str) -> str:
    """Return full statement text for CLI display (drop ``# PROBLEM-*`` file header)."""
    lines = raw.strip().splitlines()
    if lines:
        first = lines[0].strip()
        if first.startswith("#") and "PROBLEM-" in first.upper():
            lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def write_statement(ot_dir: Path, problem_id: str, statement: str) -> None:
    """Replace ``statement.md`` for an existing dossier."""
    require_dossier(ot_dir, problem_id)
    body = statement.strip()
    if not body:
        raise OpenTorusError("A problem needs a non-empty statement.")
    path = dossier_dir(ot_dir, problem_id) / "statement.md"
    path.write_text(f"# {problem_id}\n\n{body}\n", encoding="utf-8")


# --- Sub-artifact accessors ---------------------------------------------------


def list_definitions(ot_dir: Path, problem_id: str) -> list[Definition]:
    return _read_yaml_list(dossier_dir(ot_dir, problem_id) / "definitions.yaml", Definition)


def add_definition(ot_dir: Path, problem_id: str, term: str, definition: str) -> Definition:
    require_dossier(ot_dir, problem_id)
    items = list_definitions(ot_dir, problem_id)
    rec = Definition(id=next_sequential_id("DEF", len(items)), term=term, definition=definition)
    items.append(rec)
    _write_yaml_list(dossier_dir(ot_dir, problem_id) / "definitions.yaml", list(items))
    return rec


def list_assumptions(ot_dir: Path, problem_id: str) -> list[Assumption]:
    return _read_yaml_list(dossier_dir(ot_dir, problem_id) / "assumptions.yaml", Assumption)


def add_assumption(
    ot_dir: Path, problem_id: str, statement: str, rationale: str = ""
) -> Assumption:
    require_dossier(ot_dir, problem_id)
    items = list_assumptions(ot_dir, problem_id)
    rec = Assumption(
        id=next_sequential_id("ASM", len(items)), statement=statement, rationale=rationale
    )
    items.append(rec)
    _write_yaml_list(dossier_dir(ot_dir, problem_id) / "assumptions.yaml", list(items))
    return rec


def list_known_results(ot_dir: Path, problem_id: str) -> list[KnownResult]:
    return _read_yaml_list(dossier_dir(ot_dir, problem_id) / "known_results.yaml", KnownResult)


def add_known_result(
    ot_dir: Path,
    problem_id: str,
    statement: str,
    *,
    source_artifacts: list[str] | None = None,
    note: str = "",
) -> KnownResult:
    """Record a known result. A result is only 'known' with a local source."""
    require_dossier(ot_dir, problem_id)
    sources = source_artifacts or []
    if not sources:
        raise OpenTorusError(
            "A known result must cite at least one local source artifact "
            "(PAPER-*, THEOREM ref, or verified local artifact). No source, not 'known'."
        )
    items = list_known_results(ot_dir, problem_id)
    rec = KnownResult(
        id=next_sequential_id("KR", len(items)),
        statement=statement,
        source_artifacts=sources,
        note=note,
    )
    items.append(rec)
    _write_yaml_list(dossier_dir(ot_dir, problem_id) / "known_results.yaml", list(items))
    return rec


# --- JSONL-backed ledgers -----------------------------------------------------


def _ledger_path(ot_dir: Path, problem_id: str, name: str) -> Path:
    return dossier_dir(ot_dir, problem_id) / name


def list_related_papers(ot_dir: Path, problem_id: str) -> list[RelatedPaper]:
    return read_jsonl(_ledger_path(ot_dir, problem_id, "related_papers.jsonl"), RelatedPaper)


def add_related_paper(
    ot_dir: Path,
    problem_id: str,
    *,
    title: str = "",
    authors: list[str] | None = None,
    year: int | None = None,
    source: str = "",
    paper_artifact: str | None = None,
    relevance: str = "",
) -> RelatedPaper:
    require_dossier(ot_dir, problem_id)
    existing = list_related_papers(ot_dir, problem_id)
    rec = RelatedPaper(
        id=next_sequential_id("RELP", len(existing)),
        title=title,
        authors=authors or [],
        year=year,
        source=source,
        paper_artifact=paper_artifact,
        relevance=relevance,
    )
    append_jsonl(_ledger_path(ot_dir, problem_id, "related_papers.jsonl"), rec)
    return rec


def list_approaches(ot_dir: Path, problem_id: str) -> list[Approach]:
    return read_jsonl(_ledger_path(ot_dir, problem_id, "approaches.jsonl"), Approach)


def add_approach(ot_dir: Path, approach: Approach) -> Approach:
    append_jsonl(_ledger_path(ot_dir, approach.problem_id, "approaches.jsonl"), approach)
    return approach


def list_failed_attempts(ot_dir: Path, problem_id: str) -> list[FailedAttempt]:
    return read_jsonl(_ledger_path(ot_dir, problem_id, "failed_attempts.jsonl"), FailedAttempt)


def add_failed_attempt(
    ot_dir: Path,
    problem_id: str,
    *,
    attempted_method: str,
    summary: str = "",
    reason_failed: str = "",
    artifacts: list[str] | None = None,
    reusable_obstruction: bool = False,
    tags: list[str] | None = None,
) -> FailedAttempt:
    require_dossier(ot_dir, problem_id)
    existing = list_failed_attempts(ot_dir, problem_id)
    rec = FailedAttempt(
        id=next_sequential_id("FAILED", len(existing)),
        problem_id=problem_id,
        attempted_method=attempted_method,
        summary=summary,
        reason_failed=reason_failed,
        artifacts=artifacts or [],
        reusable_obstruction=reusable_obstruction,
        tags=tags or [],
    )
    append_jsonl(_ledger_path(ot_dir, problem_id, "failed_attempts.jsonl"), rec)
    return rec


# --- Claims -------------------------------------------------------------------


def _claims_path(ot_dir: Path, problem_id: str) -> Path:
    return _ledger_path(ot_dir, problem_id, "claims.jsonl")


def list_claims(ot_dir: Path, problem_id: str) -> list[ClaimRecord]:
    return read_jsonl(_claims_path(ot_dir, problem_id), ClaimRecord)


def get_claim(ot_dir: Path, problem_id: str, claim_id: str) -> ClaimRecord | None:
    return next((c for c in list_claims(ot_dir, problem_id) if c.id == claim_id), None)


def append_claim(ot_dir: Path, claim: ClaimRecord) -> ClaimRecord:
    append_jsonl(_claims_path(ot_dir, claim.problem_id), claim)
    return claim


def rewrite_claims(ot_dir: Path, problem_id: str, claims: list[ClaimRecord]) -> None:
    rewrite_jsonl(_claims_path(ot_dir, problem_id), claims)


def next_claim_id(ot_dir: Path, problem_id: str) -> str:
    return next_id("CLAIM", (c.id for c in list_claims(ot_dir, problem_id)))


# --- Claim status changelog ---------------------------------------------------


def _status_changes_path(ot_dir: Path, problem_id: str) -> Path:
    return dossier_dir(ot_dir, problem_id) / "status_changes.jsonl"


def list_status_changes(ot_dir: Path, problem_id: str) -> list[ClaimStatusChange]:
    return read_jsonl(_status_changes_path(ot_dir, problem_id), ClaimStatusChange)


def append_status_change(ot_dir: Path, change: ClaimStatusChange) -> ClaimStatusChange:
    append_jsonl(_status_changes_path(ot_dir, change.problem_id), change)
    return change


# --- Evidence -----------------------------------------------------------------


def _evidence_path(ot_dir: Path, problem_id: str) -> Path:
    return dossier_dir(ot_dir, problem_id) / "evidence" / "index.jsonl"


def list_evidence(ot_dir: Path, problem_id: str) -> list[EvidenceRecord]:
    return read_jsonl(_evidence_path(ot_dir, problem_id), EvidenceRecord)


def append_evidence(ot_dir: Path, evidence: EvidenceRecord) -> EvidenceRecord:
    append_jsonl(_evidence_path(ot_dir, evidence.problem_id), evidence)
    return evidence


def next_evidence_id(ot_dir: Path, problem_id: str) -> str:
    return next_id("EVID", (e.id for e in list_evidence(ot_dir, problem_id)))


# --- Proof attempts -----------------------------------------------------------


def _proofs_path(ot_dir: Path, problem_id: str) -> Path:
    return dossier_dir(ot_dir, problem_id) / "proof_attempts" / "index.jsonl"


def list_proof_attempts(ot_dir: Path, problem_id: str) -> list[ProofAttempt]:
    return read_jsonl(_proofs_path(ot_dir, problem_id), ProofAttempt)


def append_proof_attempt(ot_dir: Path, proof: ProofAttempt) -> ProofAttempt:
    append_jsonl(_proofs_path(ot_dir, proof.problem_id), proof)
    return proof


def rewrite_proof_attempts(ot_dir: Path, problem_id: str, proofs: list[ProofAttempt]) -> None:
    """Overwrite the proof index (used to refine an existing attempt in place)."""
    rewrite_jsonl(_proofs_path(ot_dir, problem_id), proofs)


def next_proof_id(ot_dir: Path, problem_id: str) -> str:
    return next_id("PROOF", (p.id for p in list_proof_attempts(ot_dir, problem_id)))


# --- Theorem references -------------------------------------------------------


def _theoremrefs_path(ot_dir: Path, problem_id: str) -> Path:
    return dossier_dir(ot_dir, problem_id) / "theorem_refs.jsonl"


def list_theorem_refs(ot_dir: Path, problem_id: str) -> list[TheoremRef]:
    return read_jsonl(_theoremrefs_path(ot_dir, problem_id), TheoremRef)


def add_theorem_ref(
    ot_dir: Path,
    problem_id: str,
    *,
    paper_artifact: str,
    theorem_number: str | None = None,
    page: str | None = None,
    section: str | None = None,
    statement_summary: str = "",
    exact_quote: str | None = None,
) -> TheoremRef:
    require_dossier(ot_dir, problem_id)
    existing = list_theorem_refs(ot_dir, problem_id)
    rec = TheoremRef(
        id=next_sequential_id("THM", len(existing)),
        paper_artifact=paper_artifact,
        theorem_number=theorem_number,
        page=page,
        section=section,
        statement_summary=statement_summary,
        exact_quote=exact_quote,
    )
    append_jsonl(_theoremrefs_path(ot_dir, problem_id), rec)
    return rec
