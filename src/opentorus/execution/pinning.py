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


def resolve_local_image_id(runtime: str, image: str | None) -> str | None:
    """Best-effort ``sha256:`` image ID of a local image via the container runtime.

    Locally-built images (e.g. ``opentorus-python-sci:local``) carry no repo
    digest, so :func:`image_digest` records nothing for them; the runtime image
    ID still pins exactly which image content executed a run. Docker/Podman only;
    never raises — provenance capture must not break a run.
    """
    if not image or runtime not in ("docker", "podman"):
        return None
    import subprocess

    try:
        out = subprocess.run(
            [runtime, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    image_id = out.stdout.strip()
    return image_id if out.returncode == 0 and _DIGEST_ONLY_RE.match(image_id) else None


def _strip_digest(image: str) -> str:
    return _DIGEST_RE.sub("", image)


def pinned_reference(image: str, digest: str) -> str:
    """Combine a base image ref with a digest into a pinned reference."""
    digest = digest if digest.startswith("sha256:") else f"sha256:{digest}"
    if not _DIGEST_ONLY_RE.match(digest):
        raise OpenTorusError(f"Invalid image digest '{digest}'; expected 'sha256:' + 64 hex chars.")
    return f"{_strip_digest(image)}@{digest}"


def is_locally_built(env: ToolEnvironment) -> bool:
    """True for an environment ``env prepare`` built here from a recorded Containerfile.

    Such an image exists only in the local store: it has no registry digest to pin
    to (``RepoDigests`` is empty), and its reference is a content-addressed tag
    carrying the Containerfile's hash. That is a reproducibility statement of its
    own — stronger than a mutable tag, and checkable against the image's build-time
    label — so it is not the "unpinned shipped image" this policy is about.
    """
    return bool(env.containerfile_sha256)


def unpinned_environments(ot_dir: Path) -> list[ToolEnvironment]:
    """Open-licensed environments whose image is not digest-pinned.

    Bring-your-own (proprietary, image-less) environments are exempt: they ship
    no image, so there is nothing to pin. Locally built ones are exempt too — see
    :func:`is_locally_built`. Without that exemption ``env verify`` failed on every
    workspace the shipped examples produce, and its advice ("pin it") could not be
    followed for a local image at all.
    """
    unpinned: list[ToolEnvironment] = []
    for env in list_environments(ot_dir).values():
        if env.is_bring_your_own or is_locally_built(env):
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
    if is_locally_built(env):
        # `env verify` used to flag these and tell the user to pin them. Following
        # that advice wrote `repo:tag@sha256:<local image id>` into the workspace —
        # a reference docker then tries to *pull*, failing with "pull access denied",
        # so the workspace's experiments stopped running. A local image has no
        # registry digest to pin to; refuse rather than break the workspace.
        raise OpenTorusError(
            f"Environment '{name}' was built locally by 'env prepare' and has no registry "
            f"digest to pin to — its image exists only in this machine's image store, and a "
            f"'@sha256:' reference to a local image id is not runnable (docker would try to "
            f"pull it). It is already addressed by the Containerfile hash "
            f"{env.containerfile_sha256[:12] if env.containerfile_sha256 else ''}; "
            f"'env verify' accepts it as reproducible. Push the image to a registry first "
            f"if you need a registry digest."
        )
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
