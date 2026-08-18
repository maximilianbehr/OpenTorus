"""Theorem-level literature: validated theorem references (THMREF), relations,
applicability checks and category-based coverage.

A ``TheoremReference`` is a *located* pointer into a locally parsed paper: it
carries a source locator, a hash of the context actually found in the corpus and a
short excerpt, so a later reader can confirm the statement rather than trust a
number. Extraction (heuristic or LLM) only ever yields ``candidate`` references;
``store.set_review_status`` (the human ``theorem review`` command) is the only path
to ``accepted``, and only accepted references license knowledge-claim language in
reports (``dossier.report.honesty_context``). Applicability checks are computed
deterministically and are typed results, never claim promotions.

The ledgers are workspace-level (``.opentorus/theorems/``) so a reference to a
paper can be attributed to zero or one problem without duplicating the artifact.
"""

from opentorus.research.theorems.models import (
    ROOT_RELATIONS,
    ApplicabilityCheck,
    ApplicabilityResult,
    CheckItem,
    CoverageAssessment,
    CoverageCategory,
    CoverageEntry,
    CoverageLevel,
    SourceLocator,
    TheoremReference,
    TheoremRelation,
    TheoremRelationKind,
)

__all__ = [
    "ROOT_RELATIONS",
    "ApplicabilityCheck",
    "ApplicabilityResult",
    "CheckItem",
    "CoverageAssessment",
    "CoverageCategory",
    "CoverageEntry",
    "CoverageLevel",
    "SourceLocator",
    "TheoremReference",
    "TheoremRelation",
    "TheoremRelationKind",
]
