"""Research agent tools: papers, memory, claims, evidence, experiments.

These wrap the same functions the CLI uses so the agent can manage the research
artifact graph without shelling out to ``opentorus paper …`` / ``claim …`` etc.
"""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.tools._examples import ex
from opentorus.tools.base import Tool, ToolCall, ToolResult


def _active_problem(ot_dir: Path) -> str | None:
    """The workspace's current problem, used to attribute agent-created artifacts.

    Claims, evidence, and experiments the agent records live in the workspace-global
    research store; stamping them with the active problem id lets `problem show`
    report accurate per-dossier counts instead of workspace-wide totals.
    """
    from opentorus.research.dossier.store import get_active_problem

    return get_active_problem(ot_dir)


def _as_str_list(value: object) -> list[str]:
    """Coerce a tool argument into a clean list of non-empty strings.

    LLMs frequently pass array arguments as a JSON-encoded string (e.g.
    ``'["a","b"]'``) or as a single multi-line string rather than a real list.
    Iterating such a string would split it character-by-character and corrupt
    the data (e.g. a single gap turning into 372 one-character "gaps"), so we
    normalise the shape here.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text[0] in "[(":
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, (list, tuple)):
                return [str(x).strip() for x in parsed if str(x).strip()]
        return [line.strip() for line in text.splitlines() if line.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _paper_line(paper, ot_dir: Path | None = None) -> str:
    from opentorus.research.papers import format_paper_agent_line

    return format_paper_agent_line(paper, ot_dir)


class PaperListTool(Tool):
    name = "paper_list"
    description = (
        "List registered PAPER-* artifacts in .opentorus/papers/ (not workspace papers/). "
        "Shows [parsed] vs [UNREAD]. Use paper_read to open a reading note." + ex()
    )
    input_schema: dict = {"type": "object", "properties": {}}
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.research.papers import list_papers

        papers = list_papers(self._ot_dir)
        if not papers:
            return self.ok(call, "No papers registered yet.")
        return self.ok(
            call,
            "\n".join(_paper_line(p, self._ot_dir) for p in papers),
            count=len(papers),
        )


class PaperAddTool(Tool):
    name = "paper_add"
    description = (
        "Register a local PDF (copied into .opentorus/papers/PAPER-*/). "
        "Path may be workspace-relative or absolute." + ex(path="papers/inbox/my.pdf")
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to a PDF file. Example: papers/inbox/my.pdf",
            },
        },
        "required": ["path"],
    }
    risk_level = "medium"
    permission = "write"

    def __init__(self, root: Path, ot_dir: Path) -> None:
        self._root = root
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.paths import resolve_workspace_path
        from opentorus.research.papers import add_paper

        raw = str(call.args.get("path", "")).strip()
        if not raw:
            return self.fail(call, "paper_add requires a 'path' argument.")
        candidate = Path(raw).expanduser()
        if not candidate.is_file():
            try:
                candidate = resolve_workspace_path(self._root, raw)
            except OpenTorusError:
                pass
        try:
            paper = add_paper(self._ot_dir, str(candidate))
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        return self.ok(call, _paper_line(paper), paper_id=paper.id)


class PaperFetchTool(Tool):
    name = "paper_fetch"
    description = (
        "Fetch legal full text for a DOI or arXiv id, cache as PAPER-*, and parse a reading note. "
        "Copy the identifier exactly from lit_search, paper_list, or the arXiv/DOI URL — "
        "do not invent or permute digits. URLs are accepted and normalized."
        + ex(identifier="2504.01500")
        + " Also valid: "
        + ex(identifier="10.1137/0612020")
        + " or "
        + ex(identifier="https://arxiv.org/abs/2504.01500")
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": (
                    "Bare arXiv id (YYMM.NNNNN, e.g. 2504.01500), bare DOI (10.x/…), "
                    "or full https://arxiv.org/abs/… / https://doi.org/… URL. "
                    "Not PAPER-0001 — use paper_read for cached artifacts."
                ),
            }
        },
        "required": ["identifier"],
    }
    risk_level = "medium"
    permission = "external"

    def __init__(self, ot_dir: Path, config) -> None:
        self._ot_dir = ot_dir
        self._config = config

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.egress import EgressBlocked, EgressGuard
        from opentorus.research.identifiers import IdentifierError, normalize_paper_identifier
        from opentorus.research.papers import acquire_paper, describe_fetched_paper
        from opentorus.research.sources.base import SourceRecord
        from opentorus.research.sources.crossref import API as CROSSREF_API
        from opentorus.research.sources.crossref import CrossrefSource

        raw = str(call.args.get("identifier", "")).strip()
        if not raw:
            return self.fail(call, "paper_fetch requires an 'identifier'.")
        try:
            kind, ident = normalize_paper_identifier(raw)
        except IdentifierError as exc:
            return self.fail(call, str(exc))
        lit = self._config.tools.literature
        guard = EgressGuard(
            self._config.permissions.mode,
            style=self._config.agent.style,
            review=self._config.agent.mode == "review",
            rate_limit_per_minute=lit.rate_limit_per_minute,
            daily_request_budget=lit.daily_request_budget,
            ledger_path=self._ot_dir / "egress.json",
            dlp=self._config.governance.dlp,
        )
        try:
            if kind == "doi":
                guard.authorize(CROSSREF_API)
                record = CrossrefSource(contact_email=lit.contact_email).lookup_doi(ident)
                if record is None:
                    record = SourceRecord(source="manual", title=ident, doi=ident)
            else:
                record = SourceRecord(source="arxiv", title=f"arXiv:{ident}", arxiv_id=ident)
            paper = acquire_paper(
                self._ot_dir, record, contact_email=lit.contact_email, egress=guard
            )
        except EgressBlocked as exc:
            return self.fail(call, f"Network egress denied: {exc}")
        except OpenTorusError as exc:
            return self.fail(call, str(exc))

        body = describe_fetched_paper(self._ot_dir, paper)
        return self.ok(call, body, paper_id=paper.id)


class PaperReadTool(Tool):
    name = "paper_read"
    description = (
        "Return metadata and the structured reading note for a cached PAPER-* artifact. "
        "Use instead of read_file on .opentorus/summaries/. If [UNREAD], call paper_fetch "
        "with the paper's DOI or arXiv id from paper_list." + ex(paper_id="PAPER-0001")
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": "Local artifact id from paper_list, e.g. PAPER-0001.",
            },
        },
        "required": ["paper_id"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.papers import describe_fetched_paper, get_paper

        paper_id = str(call.args.get("paper_id", "")).strip().upper()
        if not paper_id:
            return self.fail(call, "paper_read requires 'paper_id'.")
        paper = get_paper(self._ot_dir, paper_id)
        if paper is None:
            return self.fail(
                call,
                f"No {paper_id} in .opentorus/papers/. Call paper_list or paper_fetch first.",
            )
        try:
            body = describe_fetched_paper(self._ot_dir, paper)
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        return self.ok(call, body, paper_id=paper.id)


class PaperIngestInboxTool(Tool):
    name = "paper_ingest_inbox"
    description = (
        "Register every PDF in papers/inbox/ as PAPER-* and parse reading notes when possible."
        + ex()
    )
    input_schema: dict = {"type": "object", "properties": {}}
    risk_level = "medium"
    permission = "write"

    def __init__(self, root: Path, ot_dir: Path) -> None:
        self._root = root
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.papers import ingest_inbox

        try:
            papers = ingest_inbox(self._ot_dir, self._root)
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        if not papers:
            return self.ok(call, "papers/inbox/ is empty — no PDFs to ingest.")
        lines = [_paper_line(p) for p in papers]
        return self.ok(call, "Ingested:\n" + "\n".join(lines), count=len(papers))


class PaperExtractProblemsTool(Tool):
    name = "paper_extract_problems"
    description = (
        "Extract open problems from a parsed PAPER-* and register PROBLEM-* dossiers."
        + ex(paper_id="PAPER-0001")
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": "Local PAPER-* id, e.g. PAPER-0001.",
            },
        },
        "required": ["paper_id"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path, config) -> None:
        self._ot_dir = ot_dir
        self._config = config

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError, ProviderError
        from opentorus.providers.registry import get_provider
        from opentorus.research.problem_extraction import (
            extract_problems_from_paper,
            problems_to_json,
        )

        paper_id = str(call.args.get("paper_id", "")).strip()
        if not paper_id:
            return self.fail(call, "paper_extract_problems requires 'paper_id'.")
        provider = None
        try:
            provider = get_provider(self._config)
        except ProviderError:
            provider = None
        try:
            outcome = extract_problems_from_paper(
                self._ot_dir,
                paper_id,
                provider=provider,
            )
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        if not outcome.problems:
            return self.ok(call, f"No open-problem headings found in {paper_id}.")
        body = problems_to_json(self._ot_dir, outcome.problems)
        return self.ok(
            call,
            f"method={outcome.method}\n{body}",
            count=len(outcome.problems),
        )


class MemoryAddTool(Tool):
    name = "memory_add"
    description = (
        "Add structured project memory (facts, hypotheses, decisions, observations, …)."
        + ex(
            kind="observations",
            text="PAPER-0002 Thm 3.1: rational iteration for matrix sign function.",
        )
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Memory entry text."},
            "kind": {
                "type": "string",
                "description": (
                    "facts | hypotheses | decisions | observations | … "
                    "Prove runs: observations should cite PAPER-* ids."
                ),
            },
        },
        "required": ["text"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.research.memory import VALID_KINDS, add_memory

        text = str(call.args.get("text", "")).strip()
        if not text:
            return self.fail(call, "memory_add requires non-empty 'text'.")
        kind = call.args.get("kind", "facts")
        if kind not in VALID_KINDS:
            return self.fail(call, f"Unknown memory kind '{kind}'.")
        entry = add_memory(self._ot_dir, kind, text)
        return self.ok(call, f"{entry.id} ({kind}): {entry.text}", entry_id=entry.id)


class ClaimNewTool(Tool):
    name = "claim_new"
    description = "Create a CLAIM-* artifact with status 'idea'." + ex(
        statement="The ratio is at most 2."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "statement": {"type": "string", "description": "Claim statement in one sentence."},
        },
        "required": ["statement"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.research.claims import new_claim

        statement = str(call.args.get("statement", "")).strip()
        if not statement:
            return self.fail(call, "claim_new requires a 'statement'.")
        claim = new_claim(self._ot_dir, statement, problem_id=_active_problem(self._ot_dir))
        return self.ok(
            call,
            f"{claim.id} [{claim.status}]: {claim.statement}",
            claim_id=claim.id,
        )


class EvidenceAddTool(Tool):
    name = "evidence_add"
    description = "Link EXP-*, PAPER-*, or other evidence to a CLAIM-*." + ex(
        claim_id="CLAIM-0001",
        source_type="experiment",
        source_id="EXP-0001",
        summary="Ran without counterexample for n≤100.",
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "claim_id": {"type": "string", "description": "Target CLAIM-* id."},
            "source_type": {
                "type": "string",
                "description": "experiment | paper | observation | code | proof | …",
            },
            "source_id": {
                "type": "string",
                "description": "Source artifact id, e.g. EXP-0001 or PAPER-0001.",
            },
            "summary": {"type": "string", "description": "Short evidence summary."},
            "direction": {
                "type": "string",
                "description": "supports | contradicts | neutral | mixed (default supports).",
            },
            "strength": {
                "type": "string",
                "description": "weak | moderate | strong (default moderate).",
            },
        },
        "required": ["claim_id", "source_type"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.evidence import add_evidence

        claim_id = str(call.args.get("claim_id", "")).strip()
        source_type = str(call.args.get("source_type", "")).strip()
        if not claim_id or not source_type:
            return self.fail(call, "evidence_add requires 'claim_id' and 'source_type'.")
        try:
            evidence, advisory = add_evidence(
                self._ot_dir,
                claim_id,
                source_type=source_type,
                source_id=call.args.get("source_id"),
                summary=str(call.args.get("summary", "")),
                direction=str(call.args.get("direction", "supports")),
                strength=str(call.args.get("strength", "moderate")),
                problem_id=_active_problem(self._ot_dir),
            )
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        body = (
            f"{evidence.id} → {claim_id} ({evidence.direction}, "
            f"{evidence.strength}): {evidence.summary}"
        )
        if advisory:
            body += f"\nNote: {advisory}"
        return self.ok(call, body, evidence_id=evidence.id)


class ExpNewTool(Tool):
    name = "exp_new"
    description = (
        "Create a reproducible EXP-* manifest; then call exp_run. "
        "Container environments require a user-built image: "
        "opentorus env prepare python-sci --file docker/Dockerfile first."
        + ex(
            title="Sign error sweep",
            command="python scripts/sweep.py --m 8",
            environment="python-sci",
        )
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short experiment title."},
            "command": {
                "type": "string",
                "description": (
                    "Command to run, e.g. python scripts/verify_counterexamples.py --all. "
                    "Runs from workspace root when it references paths outside .opentorus/."
                ),
            },
            "environment": {
                "type": "string",
                "description": (
                    "Container environment name (python-sci, julia, …). "
                    "Requires opentorus env prepare ENV --file docker/Dockerfile first."
                ),
            },
            "run_from": {
                "type": "string",
                "enum": ["experiment", "workspace"],
                "description": (
                    "Use workspace when command references scripts/ or other root paths."
                ),
            },
        },
        "required": ["title"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.experiments import find_experiment_by_command, new_experiment

        title = str(call.args.get("title", "")).strip()
        if not title:
            return self.fail(call, "exp_new requires a 'title' argument.")
        command = str(call.args.get("command", "")).strip() or None
        environment = str(call.args.get("environment", "")).strip() or None
        run_from = str(call.args.get("run_from", "experiment")).strip()
        if run_from not in ("experiment", "workspace"):
            return self.fail(call, "run_from must be 'experiment' or 'workspace'.")
        if command:
            existing = find_experiment_by_command(self._ot_dir, command)
            if existing is not None:
                body = (
                    f"reusing {existing.id} (same command; not creating a duplicate)\n"
                    f"command={existing.command}\n"
                    f"status={existing.status}\n"
                    f"run_from={existing.run_from}\n"
                )
                if existing.status == "completed":
                    body += (
                        "Run already completed — cite this EXP-* in claims; do not exp_run again."
                    )
                else:
                    body += "Call exp_run with this id to execute and capture results."
                return self.ok(call, body, exp_id=existing.id)
        try:
            experiment = new_experiment(
                self._ot_dir,
                title,
                command=command,
                environment=environment,
                run_from=run_from,  # type: ignore[arg-type]
                problem_id=_active_problem(self._ot_dir),
            )
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        body = (
            f"created {experiment.id} at .opentorus/{experiment.path}\n"
            f"command={experiment.command}\n"
            f"run_from={experiment.run_from}\n"
        )
        if experiment.environment:
            body += f"environment={experiment.environment} (container)\n"
        body += "Call exp_run with this id to execute and capture results."
        return self.ok(call, body, exp_id=experiment.id)


class DossierKnownResultAddTool(Tool):
    name = "dossier_known_result_add"
    description = (
        "Record a known result in a PROBLEM-* dossier, citing local PAPER-* sources."
        + ex(
            problem_id="PROBLEM-0001",
            statement="Best polynomial sign error is minimax on I.",
            source_artifacts=["PAPER-0002", "Theorem 3.1"],
        )
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "problem_id": {"type": "string", "description": "Dossier id, e.g. PROBLEM-0001."},
            "statement": {"type": "string", "description": "What is known (one sentence)."},
            "source_artifacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Local sources, e.g. ['PAPER-0001', 'Theorem 2.1'].",
            },
            "note": {"type": "string", "description": "Optional page/section context."},
        },
        "required": ["problem_id", "statement", "source_artifacts"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.dossier import store

        problem_id = str(call.args.get("problem_id", "")).strip().upper()
        statement = str(call.args.get("statement", "")).strip()
        sources = _as_str_list(call.args.get("source_artifacts"))
        note = str(call.args.get("note", "")).strip()
        if not problem_id or not statement:
            return self.fail(call, "dossier_known_result_add requires problem_id and statement.")
        try:
            rec = store.add_known_result(
                self._ot_dir,
                problem_id,
                statement,
                source_artifacts=sources,
                note=note,
            )
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        return self.ok(
            call,
            f"{rec.id} → {problem_id}: {rec.statement}\n  sources: "
            f"{', '.join(rec.source_artifacts)}",
            known_result_id=rec.id,
            problem_id=problem_id,
        )


class DossierRelatedPaperAddTool(Tool):
    name = "dossier_related_paper_add"
    description = "Link a fetched PAPER-* to a PROBLEM-* dossier with a relevance note." + ex(
        problem_id="PROBLEM-0001",
        paper_id="PAPER-0002",
        relevance="Rational iterations for matrix sign — constrains polynomial degree.",
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "problem_id": {"type": "string", "description": "Dossier id, e.g. PROBLEM-0001."},
            "paper_id": {"type": "string", "description": "Local PAPER-* id."},
            "relevance": {
                "type": "string",
                "description": "How this paper supports, constrains, or relates to the problem.",
            },
            "title": {"type": "string", "description": "Optional title override."},
        },
        "required": ["problem_id", "paper_id", "relevance"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.dossier import store
        from opentorus.research.papers import get_paper

        problem_id = str(call.args.get("problem_id", "")).strip().upper()
        paper_id = str(call.args.get("paper_id", "")).strip().upper()
        relevance = str(call.args.get("relevance", "")).strip()
        if not problem_id or not paper_id or not relevance:
            return self.fail(
                call,
                "dossier_related_paper_add requires problem_id, paper_id, and relevance.",
            )
        paper = get_paper(self._ot_dir, paper_id)
        if paper is None:
            return self.fail(call, f"No paper with id {paper_id}.")
        title = str(call.args.get("title", "")).strip() or (paper.title or "")
        source = paper.arxiv_id or paper.doi or paper.source or paper_id
        try:
            rec = store.add_related_paper(
                self._ot_dir,
                problem_id,
                title=title,
                source=source,
                paper_artifact=paper_id,
                relevance=relevance,
                year=paper.year,
            )
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        return self.ok(
            call,
            f"{rec.id} → {problem_id}: {paper_id} — {relevance}",
            related_paper_id=rec.id,
            problem_id=problem_id,
            paper_id=paper_id,
        )


class ProofWriteTool(Tool):
    name = "proof_write"
    description = (
        "Write a natural-language proof sketch to proof_attempts/PROOF-*.md. "
        "Use scope=primary for the dossier answer; scope=exploration for speculative side threads."
        + ex(
            problem_id="PROBLEM-0001",
            scope="primary",
            title="Sign approximation sketch",
            theorem="What is epsilon_m^* for sign on I=[-1,-delta]∪[delta,1]?",
            main_proof="By minimax theory … [GAP-1] sharp asymptotics in m.",
        )
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "problem_id": {
                "type": "string",
                "description": "Dossier id, e.g. PROBLEM-0001.",
            },
            "title": {"type": "string", "description": "Short title for this proof attempt."},
            "body": {
                "type": "string",
                "description": "Full markdown proof (optional if structured sections are given).",
            },
            "theorem": {"type": "string", "description": "Theorem or goal statement."},
            "definitions": {
                "type": "string",
                "description": "Definitions and standing assumptions.",
            },
            "lemmas": {"type": "string", "description": "Supporting lemmas with proofs."},
            "main_proof": {
                "type": "string",
                "description": "Main logical argument (use [GAP-n] for gaps).",
            },
            "gaps_markdown": {
                "type": "string",
                "description": "Section listing open gaps and limitations.",
            },
            "evidence_notes": {
                "type": "string",
                "description": "EXP-*/PAPER-* citations as corroboration only, not proof.",
            },
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit gap strings (also scans body for [GAP-n]).",
            },
            "claim_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional CLAIM-* ids this proof bears on.",
            },
            "kind": {
                "type": "string",
                "enum": ["sketch", "formal"],
                "description": "sketch (default) or formal attempt.",
            },
            "scope": {
                "type": "string",
                "enum": ["primary", "exploration"],
                "description": (
                    "primary (default): direct answer to the dossier — required deliverable. "
                    "exploration: speculative side thread; requires connection_to_dossier."
                ),
            },
            "connection_to_dossier": {
                "type": "string",
                "description": (
                    "Required for scope=exploration: hypothesized link to the dossier "
                    "problem (≥60 chars, mention dossier terms). Ignored for primary."
                ),
            },
        },
        "required": ["problem_id", "title"],
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.dossier import claims as claim_ops
        from opentorus.research.dossier.nl_proof import assemble_nl_proof_body, explicit_gaps

        problem_id = str(call.args.get("problem_id", "")).strip().upper()
        title = str(call.args.get("title", "")).strip()
        if not problem_id or not title:
            return self.fail(call, "proof_write requires 'problem_id' and 'title'.")

        body = assemble_nl_proof_body(
            body=str(call.args.get("body", "")),
            theorem=str(call.args.get("theorem", "")),
            connection_to_dossier=str(call.args.get("connection_to_dossier", "")),
            definitions=str(call.args.get("definitions", "")),
            lemmas=str(call.args.get("lemmas", "")),
            main_proof=str(call.args.get("main_proof", "")),
            gaps_markdown=str(call.args.get("gaps_markdown", "")),
            evidence_notes=str(call.args.get("evidence_notes", "")),
        )
        if len(body) < 40:
            return self.fail(
                call,
                "Proof body too short. Provide body or fill "
                "theorem/definitions/main_proof sections.",
            )

        from opentorus.research.paper_citations import validate_proof_citations

        cite_errors, cite_warnings = validate_proof_citations(self._ot_dir, body)
        if cite_errors:
            return self.fail(
                call,
                "Paper citation check failed:\n- " + "\n- ".join(cite_errors),
            )

        from opentorus.research.dossier import store
        from opentorus.research.dossier.nl_proof import validate_proof_relevance

        try:
            store.require_dossier(self._ot_dir, problem_id)
            statement = store.statement_body_for_display(
                store.read_statement(self._ot_dir, problem_id)
            )
        except OpenTorusError:
            statement = ""
        scope = str(call.args.get("scope", "primary")).strip() or "primary"
        if scope not in ("primary", "exploration"):
            return self.fail(call, "scope must be 'primary' or 'exploration'.")
        rel_errors, rel_warnings = validate_proof_relevance(
            statement,
            body,
            title=title,
            scope=scope,  # type: ignore[arg-type]
            connection_to_dossier=str(call.args.get("connection_to_dossier", "")),
        )
        if rel_errors:
            return self.fail(
                call,
                "Proof relevance check failed:\n- " + "\n- ".join(rel_errors),
            )

        kind = str(call.args.get("kind", "sketch")).strip() or "sketch"
        gaps = explicit_gaps(gaps=_as_str_list(call.args.get("gaps")), body=body)
        claim_links = _as_str_list(call.args.get("claim_ids"))

        try:
            proof = claim_ops.add_proof_attempt(
                self._ot_dir,
                problem_id,
                title=title,
                body=body,
                kind=kind,
                scope=scope,
                gaps=gaps,
                claim_links=claim_links,
            )
        except OpenTorusError as exc:
            return self.fail(call, str(exc))

        gap_line = f"\nGaps recorded: {len(gaps)}" if gaps else ""
        scope_line = f"\nScope: {scope}" + (
            " (does not complete prove run — also need scope=primary)"
            if scope == "exploration"
            else ""
        )
        warn_line = ""
        extra_warn = cite_warnings + rel_warnings
        if extra_warn:
            warn_line = "\nCitation/relevance notes:\n- " + "\n- ".join(extra_warn)
        return self.ok(
            call,
            f"created {proof.id} [{proof.status}] at "
            f".opentorus/problems/{problem_id}/{proof.body_path}"
            f"{gap_line}{scope_line}{warn_line}\n"
            "Natural-language sketch saved (NOT formally_verified). "
            "Use read_file on that path to review the full body.",
            proof_id=proof.id,
            problem_id=problem_id,
            scope=scope,
        )


class ExpRunTool(Tool):
    name = "exp_run"
    description = "Run an EXP-* experiment and return stdout summary." + ex(exp_id="EXP-0001")
    input_schema: dict = {
        "type": "object",
        "properties": {
            "exp_id": {
                "type": "string",
                "description": "Experiment id from exp_new, e.g. EXP-0001.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 120).",
            },
        },
        "required": ["exp_id"],
    }
    risk_level = "medium"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.research.experiments import run_experiment, summarize_experiment

        exp_id = str(call.args.get("exp_id", "")).strip()
        if not exp_id:
            return self.fail(call, "exp_run requires an 'exp_id' argument.")
        timeout = int(call.args.get("timeout", 120))
        try:
            experiment, code = run_experiment(self._ot_dir, exp_id, timeout=timeout)
            summarize_experiment(self._ot_dir, exp_id)
            summary_path = self._ot_dir / experiment.path / "summary.md"
            summary = (
                summary_path.read_text(encoding="utf-8")[:4000] if summary_path.is_file() else ""
            )
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        body = f"exit_code={code}\nstatus={experiment.status}\n\n{summary}"
        if code == 0:
            return self.ok(call, body, exit_code=code, exp_id=exp_id)
        return self.fail(call, body, exit_code=code, exp_id=exp_id)


def register_research_tools(registry, root: Path, ot_dir: Path, config) -> None:
    """Register paper + research artifact tools when enabled in config."""
    if config is None:
        return
    lit = config.tools.literature
    if lit.enabled:
        registry.register(PaperListTool(ot_dir))
        registry.register(PaperAddTool(root, ot_dir))
        registry.register(PaperIngestInboxTool(root, ot_dir))
        registry.register(PaperFetchTool(ot_dir, config))
        registry.register(PaperReadTool(ot_dir))
        registry.register(PaperExtractProblemsTool(ot_dir, config))
    registry.register(MemoryAddTool(ot_dir))
    registry.register(ClaimNewTool(ot_dir))
    registry.register(EvidenceAddTool(ot_dir))
    registry.register(DossierKnownResultAddTool(ot_dir))
    registry.register(DossierRelatedPaperAddTool(ot_dir))
    registry.register(ProofWriteTool(ot_dir))
    registry.register(ExpNewTool(ot_dir))
    registry.register(ExpRunTool(ot_dir))
