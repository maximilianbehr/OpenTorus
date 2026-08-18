"""Worker roles and the registry the engine dispatches through.

``DEFAULT_WORKERS`` maps a :class:`WorkerRole` to the worker that serves it. M3
registers the offline librarian, the verifier-coordinator and the synthesizer; M4
registers the remaining roles (strategist, prover, falsifier, symbolic/numerical
experimenters, formalizer, critic) here — add the import and the mapping entry, and
the engine picks them up unchanged. A role with no worker makes the engine record a
``worker_failed`` with ``tool_unavailable`` rather than crash.
"""

from __future__ import annotations

from opentorus.campaign.models import WorkerContext, WorkerResult, WorkerRole
from opentorus.campaign.workers.base import (
    Worker,
    WorkerRuntime,
    bounded_loop,
    diff_artifacts,
    snapshot_artifacts,
    usage_tags,
)
from opentorus.campaign.workers.librarian import LibrarianWorker
from opentorus.campaign.workers.synthesizer import SynthesizerWorker
from opentorus.campaign.workers.verifier import VerifierCoordinatorWorker

DEFAULT_WORKERS: dict[WorkerRole, Worker] = {
    WorkerRole.librarian: LibrarianWorker(),
    WorkerRole.verifier_coordinator: VerifierCoordinatorWorker(),
    WorkerRole.synthesizer: SynthesizerWorker(),
}

__all__ = [
    "DEFAULT_WORKERS",
    "LibrarianWorker",
    "SynthesizerWorker",
    "VerifierCoordinatorWorker",
    "Worker",
    "WorkerContext",
    "WorkerResult",
    "WorkerRole",
    "WorkerRuntime",
    "bounded_loop",
    "diff_artifacts",
    "snapshot_artifacts",
    "usage_tags",
]
