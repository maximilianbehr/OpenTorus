"""Dataset connectors: Zenodo, Hugging Face Datasets, and OSF (M71).

Each connector resolves a dataset identifier to a :class:`DatasetResolution`
(metadata + one fetchable file). Metadata fetching is separated from parsing so
connectors are testable offline with canned fixtures, mirroring the literature
connectors. Downloading happens in :func:`acquire_dataset`, gated by egress.
"""

from __future__ import annotations

from collections.abc import Callable

from opentorus.research.datasets import DatasetResolution
from opentorus.research.sources.base import build_url, http_get_json

JsonFetcher = Callable[[str], dict]


def parse_zenodo(data: dict, identifier: str) -> DatasetResolution:
    meta = data.get("metadata") or {}
    license_obj = meta.get("license")
    if isinstance(license_obj, dict):
        license_name = license_obj.get("id") or license_obj.get("name")
    else:
        license_name = license_obj
    files = data.get("files") or []
    file_url = file_name = None
    size = None
    if files:
        first = files[0]
        file_url = (first.get("links") or {}).get("self") or (first.get("links") or {}).get(
            "download"
        )
        file_name = first.get("key") or first.get("filename")
        size = first.get("size") or first.get("filesize")
    return DatasetResolution(
        source="zenodo",
        external_id=identifier,
        title=meta.get("title"),
        version=meta.get("version"),
        doi=data.get("doi") or meta.get("doi"),
        license=license_name,
        url=(data.get("links") or {}).get("html") or f"https://zenodo.org/records/{identifier}",
        file_url=file_url,
        file_name=file_name or "dataset.bin",
        size_bytes=size,
    )


def parse_huggingface(data: dict, identifier: str) -> DatasetResolution:
    card = data.get("cardData") or {}
    license_name = card.get("license") or data.get("license")
    if isinstance(license_name, list):
        license_name = license_name[0] if license_name else None
    revision = data.get("sha") or "main"
    siblings = data.get("siblings") or []
    file_name = None
    for sib in siblings:
        name = sib.get("rfilename")
        if name and not name.startswith("."):
            file_name = name
            break
    file_url = None
    if file_name:
        file_url = f"https://huggingface.co/datasets/{identifier}/resolve/{revision}/{file_name}"
    return DatasetResolution(
        source="huggingface",
        external_id=identifier,
        title=data.get("id") or identifier,
        version=revision,
        license=license_name,
        url=f"https://huggingface.co/datasets/{identifier}",
        file_url=file_url,
        file_name=file_name or "dataset.bin",
    )


def parse_osf(data: dict, identifier: str) -> DatasetResolution:
    attrs = (data.get("data") or {}).get("attributes") or {}
    rel = (data.get("data") or {}).get("relationships") or {}
    license_rel = (rel.get("license") or {}).get("data") or {}
    license_name = license_rel.get("name") if isinstance(license_rel, dict) else None
    license_name = license_name or attrs.get("license")
    return DatasetResolution(
        source="osf",
        external_id=identifier,
        title=attrs.get("title"),
        doi=attrs.get("doi"),
        license=license_name,
        url=f"https://osf.io/{identifier}/",
        file_url=None,  # OSF files live behind a storage provider; resolved separately.
        file_name="osf-metadata.json",
    )


class ZenodoConnector:
    name = "zenodo"
    host = "zenodo.org"

    def __init__(self, fetcher: JsonFetcher | None = None) -> None:
        self._fetch = fetcher or http_get_json

    def resolve(self, identifier: str) -> DatasetResolution:
        url = build_url(f"https://zenodo.org/api/records/{identifier}", {})
        return parse_zenodo(self._fetch(url), identifier)


class HuggingFaceConnector:
    name = "huggingface"
    host = "huggingface.co"

    def __init__(self, fetcher: JsonFetcher | None = None) -> None:
        self._fetch = fetcher or http_get_json

    def resolve(self, identifier: str) -> DatasetResolution:
        url = build_url(f"https://huggingface.co/api/datasets/{identifier}", {})
        return parse_huggingface(self._fetch(url), identifier)


class OsfConnector:
    name = "osf"
    host = "api.osf.io"

    def __init__(self, fetcher: JsonFetcher | None = None) -> None:
        self._fetch = fetcher or http_get_json

    def resolve(self, identifier: str) -> DatasetResolution:
        url = build_url(f"https://api.osf.io/v2/nodes/{identifier}/", {})
        return parse_osf(self._fetch(url), identifier)
