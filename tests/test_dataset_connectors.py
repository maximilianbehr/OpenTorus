"""Offline tests for dataset acquisition (Milestone 71).

Metadata resolution is tested against canned fixtures and downloads are stubbed;
no network access occurs. License gating, content hashing, the size cap, and the
experiment-provenance link are all exercised deterministically.
"""

from __future__ import annotations

import hashlib

import pytest
import yaml

from opentorus.config import default_config
from opentorus.research.dataset_sources import (
    HuggingFaceConnector,
    OsfConnector,
    ZenodoConnector,
    parse_huggingface,
    parse_zenodo,
)
from opentorus.research.datasets import (
    LicenseError,
    acquire_dataset,
    get_dataset,
    license_allowed,
    link_dataset_to_experiment,
    list_datasets,
)
from opentorus.research.experiments import get_experiment, new_experiment, run_experiment


def _ot(tmp_path):  # noqa: ANN001
    ot = tmp_path / ".opentorus"
    ot.mkdir()
    return ot


_ZENODO = {
    "doi": "10.5281/zenodo.123",
    "links": {"html": "https://zenodo.org/records/123"},
    "metadata": {
        "title": "Torus Point Cloud",
        "version": "2.0",
        "license": {"id": "cc-by-4.0"},
    },
    "files": [
        {"key": "points.csv", "size": 1024, "links": {"self": "https://zenodo.org/api/files/x"}}
    ],
}

_ZENODO_PROPRIETARY = {
    "doi": "10.5281/zenodo.999",
    "metadata": {"title": "Closed Data", "license": {"id": "all-rights-reserved"}},
    "files": [{"key": "secret.bin", "links": {"self": "https://zenodo.org/api/files/y"}}],
}


def test_parse_zenodo() -> None:
    res = parse_zenodo(_ZENODO, "123")
    assert res.source == "zenodo"
    assert res.title == "Torus Point Cloud"
    assert res.version == "2.0"
    assert res.license == "cc-by-4.0"
    assert res.file_name == "points.csv"
    assert res.file_url == "https://zenodo.org/api/files/x"


def test_parse_huggingface() -> None:
    data = {
        "id": "acme/torus",
        "sha": "abc123",
        "cardData": {"license": "mit"},
        "siblings": [{"rfilename": ".gitattributes"}, {"rfilename": "train.csv"}],
    }
    res = parse_huggingface(data, "acme/torus")
    assert res.license == "mit"
    assert res.file_name == "train.csv"
    assert res.file_url.endswith("/resolve/abc123/train.csv")


def test_license_allowed_blocks_unknown_by_default() -> None:
    config = default_config()
    assert license_allowed("CC-BY-4.0", config) is True
    assert license_allowed("all-rights-reserved", config) is False
    assert license_allowed(None, config) is False
    config.tools.datasets.allow_unknown_license = True
    assert license_allowed(None, config) is True


def test_acquire_dataset_hashes_and_pins(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    payload = b"x,y\n0,0\n1,1\n"
    connector = ZenodoConnector(fetcher=lambda url: _ZENODO)

    dataset = acquire_dataset(ot, connector, "123", config=config, downloader=lambda url: payload)
    assert dataset.id == "DATASET-0001"
    assert dataset.license == "cc-by-4.0"
    assert dataset.sha256 == hashlib.sha256(payload).hexdigest()
    assert dataset.size_bytes == len(payload)
    stored = (ot / dataset.local_path).read_bytes()
    assert stored == payload

    # Re-acquiring the same id reuses the artifact (no duplicate).
    again = acquire_dataset(ot, connector, "123", config=config, downloader=lambda url: payload)
    assert again.id == dataset.id
    assert len(list_datasets(ot)) == 1


def test_disallowed_license_blocks_fetch(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    downloads: list[str] = []

    def _download(url: str) -> bytes:
        downloads.append(url)
        return b"should not happen"

    connector = ZenodoConnector(fetcher=lambda url: _ZENODO_PROPRIETARY)
    with pytest.raises(LicenseError):
        acquire_dataset(ot, connector, "999", config=config, downloader=_download)
    assert downloads == []  # nothing was fetched
    assert list_datasets(ot) == []


def test_size_cap_blocks_oversized(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    config.tools.datasets.max_file_bytes = 4
    connector = ZenodoConnector(fetcher=lambda url: _ZENODO)
    with pytest.raises(Exception):  # noqa: B017,PT011 - oversized declared size cap
        acquire_dataset(ot, connector, "123", config=config, downloader=lambda url: b"toolong")


def test_experiment_records_dataset_hash(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    payload = b"data"
    connector = ZenodoConnector(fetcher=lambda url: _ZENODO)
    dataset = acquire_dataset(ot, connector, "123", config=config, downloader=lambda url: payload)

    exp = new_experiment(ot, "Uses a dataset")
    link_dataset_to_experiment(ot, dataset.id, exp.id)

    refreshed = get_experiment(ot, exp.id)
    assert refreshed.datasets[0].dataset_id == dataset.id
    assert refreshed.datasets[0].sha256 == dataset.sha256

    run_experiment(ot, exp.id)
    manifest = yaml.safe_load(
        (ot / exp.path / "results" / "manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["datasets"][0]["dataset_id"] == dataset.id
    assert manifest["datasets"][0]["sha256"] == dataset.sha256


def test_osf_connector_resolves_metadata_only(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    config.tools.datasets.allow_unknown_license = True
    data = {"data": {"attributes": {"title": "OSF Project", "license": "CC0 1.0"}}}
    connector = OsfConnector(fetcher=lambda url: data)
    dataset = acquire_dataset(ot, connector, "abcd", config=config)
    assert dataset.source == "osf"
    assert dataset.title == "OSF Project"
    assert dataset.local_path is None  # metadata only
    assert get_dataset(ot, dataset.id) is not None


def test_huggingface_connector_end_to_end(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    data = {
        "id": "acme/torus",
        "sha": "main",
        "cardData": {"license": "apache-2.0"},
        "siblings": [{"rfilename": "data.json"}],
    }
    connector = HuggingFaceConnector(fetcher=lambda url: data)
    dataset = acquire_dataset(
        ot, connector, "acme/torus", config=config, downloader=lambda u: b"{}"
    )
    assert dataset.license == "apache-2.0"
    assert dataset.file_name == "data.json"
    assert dataset.sha256 == hashlib.sha256(b"{}").hexdigest()
