"""Worker roles and the registry the engine dispatches through.

``DEFAULT_WORKERS`` maps every :class:`WorkerRole` to the worker that serves it. Each
worker is a narrow role with a deterministic offline behaviour under the mock provider
and a bounded, routed loop under a real one; a role with no worker (a caller-supplied
registry) makes the engine record a ``worker_failed`` with ``tool_unavailable`` rather
than crash.
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
from opentorus.campaign.workers.critic import CriticWorker
from opentorus.campaign.workers.falsifier import FalsifierWorker
from opentorus.campaign.workers.formalizer import FormalizerWorker
from opentorus.campaign.workers.librarian import LibrarianWorker
from opentorus.campaign.workers.numerical import NumericalWorker
from opentorus.campaign.workers.prover import ProverWorker
from opentorus.campaign.workers.strategist import StrategistWorker
from opentorus.campaign.workers.symbolic import SymbolicWorker
from opentorus.campaign.workers.synthesizer import SynthesizerWorker
from opentorus.campaign.workers.verifier import VerifierCoordinatorWorker

DEFAULT_WORKERS: dict[WorkerRole, Worker] = {
    WorkerRole.strategist: StrategistWorker(),
    WorkerRole.prover: ProverWorker(),
    WorkerRole.falsifier: FalsifierWorker(),
    WorkerRole.librarian: LibrarianWorker(),
    WorkerRole.symbolic_experimenter: SymbolicWorker(),
    WorkerRole.numerical_experimenter: NumericalWorker(),
    WorkerRole.formalizer: FormalizerWorker(),
    WorkerRole.critic: CriticWorker(),
    WorkerRole.verifier_coordinator: VerifierCoordinatorWorker(),
    WorkerRole.synthesizer: SynthesizerWorker(),
}

__all__ = [
    "DEFAULT_WORKERS",
    "CriticWorker",
    "FalsifierWorker",
    "FormalizerWorker",
    "LibrarianWorker",
    "NumericalWorker",
    "ProverWorker",
    "StrategistWorker",
    "SymbolicWorker",
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
