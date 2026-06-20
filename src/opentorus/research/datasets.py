"""Dataset acquisition with the same provenance discipline as papers (M71).

A dataset is resolved to a ``DATASET-*`` artifact recording its source,
version/DOI, license, and a SHA-256 content hash of exactly what was fetched.
Downloads route through the :class:`EgressGuard` and respect licenses: a fetch
is refused when the resolved license is not allowed. Datasets link into the
artifact graph as inputs to experiments, and an experiment's manifest records
the dataset hash it consumed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import yaml
from pydantic import BaseModel, Field

from opentorus.config import Config
from opentorus.errors import OpenTorusError
from opentorus.jsonl import next_sequential_id

if TYPE_CHECKING:
    from opentorus.research.egress import EgressGuard


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DatasetResolution(BaseModel):
    """Resolved metadata + a single fetchable file for one dataset id."""

    source: str
    external_id: str
    title: str | None = None
    version: str | None = None
    doi: str | None = None
    license: str | None = None
    url: str | None = None
    file_url: str | None = None
    file_name: str = "dataset.bin"
    size_bytes: int | None = None


class Dataset(BaseModel):
    id: str
    source: str
    external_id: str
    title: str | None = None
    version: str | None = None
    doi: str | None = None
    license: str | None = None
    url: str | None = None
    file_name: str | None = None
    local_path: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    retrieved_at: datetime | None = None
    access_note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class DatasetSource(Protocol):
    name: str
    host: str

    def resolve(self, identifier: str) -> DatasetResolution: ...


class LicenseError(OpenTorusError):
    """Raised when a dataset's license disallows fetching it."""


def datasets_dir(ot_dir: Path) -> Path:
    return ot_dir / "datasets"


def _meta_path(ds_dir: Path) -> Path:
    return ds_dir / "metadata.yaml"


def list_datasets(ot_dir: Path) -> list[Dataset]:
    base = datasets_dir(ot_dir)
    if not base.is_dir():
        return []
    out: list[Dataset] = []
    for child in sorted(base.iterdir()):
        meta = _meta_path(child)
        if child.is_dir() and meta.is_file():
            data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            out.append(Dataset.model_validate(data))
    return out


def get_dataset(ot_dir: Path, dataset_id: str) -> Dataset | None:
    for ds in list_datasets(ot_dir):
        if ds.id == dataset_id:
            return ds
    return None


def _save_meta(ot_dir: Path, dataset: Dataset) -> None:
    ds_dir = datasets_dir(ot_dir) / dataset.id
    ds_dir.mkdir(parents=True, exist_ok=True)
    _meta_path(ds_dir).write_text(
        yaml.safe_dump(dataset.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )


def license_allowed(license_name: str | None, config: Config) -> bool:
    """Return whether ``license_name`` permits fetching, per configuration."""
    cfg = config.tools.datasets
    if not license_name:
        return cfg.allow_unknown_license
    lowered = license_name.lower()
    return any(allowed.lower() in lowered for allowed in cfg.allowed_licenses)


def _find_cached(ot_dir: Path, source: str, external_id: str) -> Dataset | None:
    for ds in list_datasets(ot_dir):
        if ds.source == source and ds.external_id == external_id:
            return ds
    return None


def acquire_dataset(
    ot_dir: Path,
    connector: DatasetSource,
    identifier: str,
    *,
    config: Config,
    downloader: Callable[[str], bytes] | None = None,
    egress: EgressGuard | None = None,
) -> Dataset:
    """Resolve and fetch a dataset into a hash + license-pinned ``DATASET-*``.

    A cached artifact for the same source+id is returned without re-downloading.
    The fetch is blocked (no bytes leave or arrive) when the license is not
    allowed or the file exceeds the configured size cap.
    """
    cached = _find_cached(ot_dir, connector.name, identifier)
    if cached is not None:
        return cached

    resolution = connector.resolve(identifier)

    if not license_allowed(resolution.license, config):
        raise LicenseError(
            f"Refusing to fetch dataset '{identifier}' from {connector.name}: "
            f"license '{resolution.license or 'unknown'}' is not allowed. "
            "Add it to config.tools.datasets.allowed_licenses to permit."
        )

    cap = config.tools.datasets.max_file_bytes
    if resolution.size_bytes is not None and resolution.size_bytes > cap:
        raise OpenTorusError(
            f"Dataset file is {resolution.size_bytes} bytes, exceeding the "
            f"{cap}-byte cap (config.tools.datasets.max_file_bytes)."
        )

    dataset_id = next_sequential_id("DATASET", len(list_datasets(ot_dir)))
    ds_dir = datasets_dir(ot_dir) / dataset_id
    ds_dir.mkdir(parents=True, exist_ok=True)

    dataset = Dataset(
        id=dataset_id,
        source=connector.name,
        external_id=identifier,
        title=resolution.title,
        version=resolution.version,
        doi=resolution.doi,
        license=resolution.license,
        url=resolution.url,
        file_name=resolution.file_name,
        retrieved_at=_utcnow(),
    )

    if resolution.file_url:
        download = downloader
        if download is None:
            from opentorus.research.sources.base import http_get_bytes

            download = http_get_bytes
        if egress is not None:
            egress.authorize(resolution.file_url)
        data = download(resolution.file_url)
        if len(data) > cap:
            raise OpenTorusError(
                f"Downloaded dataset is {len(data)} bytes, exceeding the "
                f"{cap}-byte cap (config.tools.datasets.max_file_bytes)."
            )
        dest = ds_dir / resolution.file_name
        dest.write_bytes(data)
        dataset.local_path = str(dest.relative_to(ot_dir))
        dataset.sha256 = hashlib.sha256(data).hexdigest()
        dataset.size_bytes = len(data)
        dataset.access_note = f"fetched via {connector.name}"
    else:
        dataset.access_note = "metadata only (no downloadable file resolved)"

    _save_meta(ot_dir, dataset)
    return dataset


def link_dataset_to_experiment(ot_dir: Path, dataset_id: str, exp_id: str) -> None:
    """Record a dataset as an input to an experiment (graph + manifest provenance).

    Adds an ``EXP depends_on DATASET`` edge and stores the dataset id + hash on
    the experiment so its result manifest references the data it consumed.
    """
    from opentorus.research.experiments import attach_dataset, get_experiment
    from opentorus.research.graph import add_edge

    dataset = get_dataset(ot_dir, dataset_id)
    if dataset is None:
        raise OpenTorusError(f"No dataset with id '{dataset_id}'.")
    if get_experiment(ot_dir, exp_id) is None:
        raise OpenTorusError(f"No experiment with id '{exp_id}'.")

    attach_dataset(ot_dir, exp_id, dataset_id=dataset.id, sha256=dataset.sha256)
    add_edge(
        ot_dir,
        exp_id,
        dataset_id,
        "depends_on",
        rationale=f"experiment consumes dataset {dataset_id} (sha256={dataset.sha256}).",
    )
