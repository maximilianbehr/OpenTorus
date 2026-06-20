"""Digest pinning for reproducible images (Milestone 64).

Reproducibility is enforced by policy: every shipped (open-licensed) environment
must reference its image by an immutable ``@sha256:`` digest, not a mutable tag.
This module verifies pinning, pins an environment by writing a digest into the
workspace ``environments.yaml``, and runs a build/publish pipeline that resolves
tags to digests via an injected resolver (so it is testable offline, with no real
registry pull).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import yaml

from opentorus.errors import OpenTorusError
from opentorus.execution.environments import (
    ENVIRONMENTS_FILENAME,
    ToolEnvironment,
    list_environments,
)

# A digest reference: ``repo[:tag]@sha256:<64 hex>``.
_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
_DIGEST_ONLY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

DigestResolver = Callable[[ToolEnvironment], str]


def is_digest_pinned(image: str | None) -> bool:
    """True if ``image`` is pinned by an immutable ``@sha256:`` digest."""
    return bool(image) and _DIGEST_RE.search(image or "") is not None


def image_digest(image: str | None) -> str | None:
    """Return the ``sha256:...`` digest of a pinned image, else ``None``."""
    if not image:
        return None
    match = _DIGEST_RE.search(image)
    return match.group(0)[1:] if match else None


def _strip_digest(image: str) -> str:
    return _DIGEST_RE.sub("", image)


def pinned_reference(image: str, digest: str) -> str:
    """Combine a base image ref with a digest into a pinned reference."""
    digest = digest if digest.startswith("sha256:") else f"sha256:{digest}"
    if not _DIGEST_ONLY_RE.match(digest):
        raise OpenTorusError(f"Invalid image digest '{digest}'; expected 'sha256:' + 64 hex chars.")
    return f"{_strip_digest(image)}@{digest}"


def unpinned_environments(ot_dir: Path) -> list[ToolEnvironment]:
    """Open-licensed environments whose image is not digest-pinned.

    Bring-your-own (proprietary, image-less) environments are exempt: they ship
    no image, so there is nothing to pin.
    """
    unpinned: list[ToolEnvironment] = []
    for env in list_environments(ot_dir).values():
        if env.is_bring_your_own:
            continue
        if not is_digest_pinned(env.image):
            unpinned.append(env)
    return unpinned


def verify_pinned(ot_dir: Path) -> None:
    """Raise if any shipped environment is not digest-pinned."""
    unpinned = unpinned_environments(ot_dir)
    if unpinned:
        names = ", ".join(sorted(e.name for e in unpinned))
        raise OpenTorusError(
            f"Environments not digest-pinned: {names}. Pin them with "
            "'opentorus env pin' so every run is reproducible."
        )


def _workspace_env_file(ot_dir: Path) -> Path:
    return ot_dir / ENVIRONMENTS_FILENAME


def _load_overrides(path: Path) -> dict:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, dict) and "environments" in raw:
        return raw
    return {"environments": raw if isinstance(raw, dict) else {}}


def pin_environment(ot_dir: Path, name: str, digest: str) -> ToolEnvironment:
    """Pin one environment's image to ``digest`` in the workspace overrides."""
    envs = list_environments(ot_dir)
    env = envs.get(name)
    if env is None:
        valid = ", ".join(sorted(envs)) or "(none)"
        raise OpenTorusError(f"Unknown tool environment '{name}'. Known: {valid}")
    if env.image is None:
        raise OpenTorusError(f"Environment '{name}' is bring-your-own (no image); nothing to pin.")
    pinned = pinned_reference(env.image, digest)

    path = _workspace_env_file(ot_dir)
    data = _load_overrides(path)
    environments = data.setdefault("environments", {})
    entry = environments.get(name) or {}
    entry["image"] = pinned
    environments[name] = entry
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    return env.model_copy(update={"image": pinned})


def resolve_and_pin(ot_dir: Path, resolver: DigestResolver) -> dict[str, str]:
    """Build/publish pipeline: resolve every unpinned environment to a digest.

    ``resolver`` maps an environment to its published ``sha256:...`` digest (in
    production it runs ``docker build``/``push`` and reads the digest back; in
    tests it is a fixture). Returns the ``{name: pinned_reference}`` map written.
    """
    written: dict[str, str] = {}
    for env in unpinned_environments(ot_dir):
        digest = resolver(env)
        pinned = pin_environment(ot_dir, env.name, digest)
        written[env.name] = pinned.image or ""
    return written


def sif_cache_path(digest: str) -> Path:
    """Deterministic Apptainer SIF cache path for a published OCI digest."""
    bare = digest.split(":", 1)[1] if ":" in digest else digest
    return Path.home() / ".opentorus" / "sif" / f"{bare}.sif"
