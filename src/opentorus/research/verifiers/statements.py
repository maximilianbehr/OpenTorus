"""Frozen formal statements (``FSTMT-*``): what a formal proof must prove.

Without one, an accepted Lean/Coq file can be cited for *any* claim: the checker
says the file's theorem is proved, nothing says that theorem is the claim. A frozen
statement closes that gap. It is a complete formal file — preamble (imports, opens,
definitions), exactly one ``theorem``, and the placeholder proof ``sorry`` /
``Admitted`` — bound to one claim, digested with sha256, and **accepted by a human**
(``opentorus proof statement accept``) before it binds anything. The agent may only
*propose* one.

A ``proof_submit`` against a claim with an accepted frozen statement must

1. contain the statement verbatim (whitespace-normalized, outside comments),
2. begin with the frozen preamble (the checked file is rebuilt from the frozen
   preamble, so definitions cannot be redefined or continued), and
3. elaborate the theorem to the *same type* as the frozen statement checked with
   ``sorry`` (``#check @thm`` under ``pp.all``, the "pristine type").

Only such a statement-bound proof promotes a claim to ``formally_verified``; an
accepted but unbound Lean/Coq proof is recorded as support.
"""

from __future__ import annotations

import getpass
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_id, read_jsonl, rewrite_jsonl

StatementStatus = Literal["proposed", "accepted", "retired"]

# Backends whose accepted results need a frozen statement to promote a claim.
PROOF_ASSISTANT_BACKENDS: frozenset[str] = frozenset({"lean4", "lean", "coq"})


def backend_family(backend: str) -> str:
    b = backend.strip().lower()
    return "lean4" if b in ("lean", "lean4") else b


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FormalStatement(BaseModel):
    """A frozen formal statement bound to one claim."""

    id: str
    backend: str  # "lean4" | "coq"
    claim_id: str
    # Which claim store ``claim_id`` belongs to (``None``: the workspace ladder), the
    # same convention as ``ProofAttempt.problem_id``.
    problem_id: str | None = None
    theorem: str
    statement: str  # the extracted statement text (``theorem … :=``)
    source_path: str  # relative to .opentorus/
    sha256: str  # digest of the full frozen source
    status: StatementStatus = "proposed"
    proposed_by: str = "human"  # "human" | "agent"
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    # The frozen statement's elaborated type, computed by the checker on first use and
    # cached with the checker version it was computed under.
    pristine_type: str | None = None
    pristine_backend_version: str | None = None
    note: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


def statements_path(ot_dir: Path) -> Path:
    return ot_dir / "formal_statements.jsonl"


def statements_dir(ot_dir: Path) -> Path:
    return ot_dir / "formal_statements"


def list_statements(ot_dir: Path) -> list[FormalStatement]:
    return read_jsonl(statements_path(ot_dir), FormalStatement)


def get_statement(ot_dir: Path, statement_id: str) -> FormalStatement | None:
    sid = statement_id.strip().upper()
    return next((s for s in list_statements(ot_dir) if s.id == sid), None)


def statement_source(ot_dir: Path, statement: FormalStatement) -> str:
    return (ot_dir / statement.source_path).read_text(encoding="utf-8")


def digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _rules(backend: str):  # noqa: ANN202 — module
    if backend_family(backend) == "lean4":
        from opentorus.research.verifiers import lean_rules

        return lean_rules
    if backend_family(backend) == "coq":
        from opentorus.research.verifiers import coq_rules

        return coq_rules
    raise OpenTorusError(f"Frozen formal statements exist for lean4 and coq only, not '{backend}'.")


def propose_statement(
    ot_dir: Path,
    backend: str,
    source: str,
    *,
    claim_id: str,
    problem_id: str | None = None,
    proposed_by: str = "human",
    note: str = "",
) -> FormalStatement:
    """Record a frozen statement as *proposed*. It binds nothing until accepted."""
    from opentorus.atomicio import file_lock

    family = backend_family(backend)
    rules = _rules(family)
    objection = rules.frozen_objection(source)
    if objection:
        raise OpenTorusError(f"Cannot freeze this {family} statement: {objection}.")
    statement = rules.extract_statement(source)
    names = rules.theorem_names(source)
    if statement is None or not names:
        raise OpenTorusError("Cannot freeze: no theorem statement found.")
    with file_lock(statements_path(ot_dir)):
        existing = list_statements(ot_dir)
        sid = next_id("FSTMT", [s.id for s in existing])
        sdir = statements_dir(ot_dir)
        sdir.mkdir(parents=True, exist_ok=True)
        suffix = ".lean" if family == "lean4" else ".v"
        path = sdir / f"{sid}{suffix}"
        path.write_text(source, encoding="utf-8")
        record = FormalStatement(
            id=sid,
            backend=family,
            claim_id=claim_id.strip().upper(),
            problem_id=problem_id,
            theorem=names[0],
            statement=statement.strip(),
            source_path=f"formal_statements/{path.name}",
            sha256=digest(source),
            proposed_by=proposed_by,
            note=note,
        )
        append_jsonl(statements_path(ot_dir), record)
    return record


def accept_statement(
    ot_dir: Path,
    statement_id: str,
    *,
    confirm: Callable[[FormalStatement], bool] | None,
    accepted_by: str | None = None,
) -> FormalStatement:
    """Human acceptance: the statement now binds proofs of its claim.

    ``confirm`` must approve (the CLI shows the statement and asks); without it the
    acceptance is refused. The digest is re-checked against the file on disk, so an
    edited source cannot be accepted under an old review. Any earlier accepted
    statement for the same claim and backend is retired.
    """
    from opentorus.atomicio import file_lock

    with file_lock(statements_path(ot_dir)):
        records = list_statements(ot_dir)
        target = next((s for s in records if s.id == statement_id.strip().upper()), None)
        if target is None:
            raise OpenTorusError(f"No frozen statement '{statement_id}'.")
        if target.status == "accepted":
            return target
        if target.status == "retired":
            raise OpenTorusError(f"{target.id} is retired; propose a new statement.")
        on_disk = statement_source(ot_dir, target)
        if digest(on_disk) != target.sha256:
            raise OpenTorusError(
                f"{target.id}: the source file no longer matches its recorded sha256 — "
                "it was edited after it was proposed. Propose it again."
            )
        if confirm is None or not confirm(target):
            raise OpenTorusError(f"Accepting {target.id} requires explicit human confirmation.")
        for other in records:
            if (
                other.id != target.id
                and other.status == "accepted"
                and other.claim_id == target.claim_id
                and other.problem_id == target.problem_id
                and other.backend == target.backend
            ):
                other.status = "retired"
        target.status = "accepted"
        target.accepted_by = accepted_by or _whoami()
        target.accepted_at = _utcnow()
        rewrite_jsonl(statements_path(ot_dir), records)
    return target


def retire_statement(ot_dir: Path, statement_id: str) -> FormalStatement:
    from opentorus.atomicio import file_lock

    with file_lock(statements_path(ot_dir)):
        records = list_statements(ot_dir)
        target = next((s for s in records if s.id == statement_id.strip().upper()), None)
        if target is None:
            raise OpenTorusError(f"No frozen statement '{statement_id}'.")
        target.status = "retired"
        rewrite_jsonl(statements_path(ot_dir), records)
    return target


def record_pristine_type(
    ot_dir: Path, statement_id: str, pristine_type: str, backend_version: str | None
) -> None:
    from opentorus.atomicio import file_lock

    with file_lock(statements_path(ot_dir)):
        records = list_statements(ot_dir)
        for rec in records:
            if rec.id == statement_id:
                rec.pristine_type = pristine_type
                rec.pristine_backend_version = backend_version
        rewrite_jsonl(statements_path(ot_dir), records)


def active_statement(
    ot_dir: Path,
    claim_id: str | None,
    backend: str,
    *,
    problem_id: str | None = None,
    submitted_under: str | None = None,
) -> FormalStatement | None:
    """The accepted frozen statement binding proofs of ``claim_id`` on ``backend``.

    Matched in the proof's own claim namespace (``problem_id``); a submission made
    *under* a dossier (``submitted_under``) also finds a statement frozen for that
    dossier's claim of the same id.
    """
    if not claim_id:
        return None
    cid = claim_id.strip().upper()
    family = backend_family(backend)
    candidates = [
        s
        for s in list_statements(ot_dir)
        if s.status == "accepted" and s.claim_id == cid and s.backend == family
    ]
    match = [s for s in candidates if s.problem_id == problem_id]
    if not match and problem_id is None and submitted_under:
        match = [s for s in candidates if s.problem_id == submitted_under]
    return match[-1] if match else None


def _whoami() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no passwd entry in some containers
        return "human"


__all__ = [
    "FormalStatement",
    "PROOF_ASSISTANT_BACKENDS",
    "accept_statement",
    "active_statement",
    "backend_family",
    "digest",
    "get_statement",
    "list_statements",
    "propose_statement",
    "record_pristine_type",
    "retire_statement",
    "statement_source",
]
