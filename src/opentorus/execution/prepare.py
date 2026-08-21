"""One-command setup for local container tool environments.

OpenTorus does not ship container images. The user must supply a Dockerfile::

    opentorus env prepare python-sci --file docker/Dockerfile
    opentorus env prepare my-stack --file ./Containerfile --context ./docker

Paths are saved in ``.opentorus/environments.yaml`` for later rebuilds
(``opentorus env prepare python-sci --rebuild``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from opentorus.config import Config, default_config, load_config
from opentorus.errors import OpenTorusError
from opentorus.execution.environments import (
    ENVIRONMENTS_FILENAME,
    ToolEnvironment,
    list_environments,
    resolve_environment,
)
from opentorus.tools.shell import run_argv

_LOCAL_IMAGE_TAG = "opentorus-{name}:local"
_LOCAL_IMAGE_TAG_HASHED = "opentorus-{name}:{short}"
# How much of the Containerfile hash goes into the tag. 12 hex chars is git's
# short-sha convention and far beyond collision range for one machine's images.
_IMAGE_TAG_HASH_CHARS = 12
_CONTAINERFILE_NAMES = ("Dockerfile", "Containerfile", "dockerfile", "containerfile")
# Image label carrying the sha256 of the Containerfile the image was built from,
# so `env prepare` can tell a current image from a stale one instead of blindly
# reusing whatever carries the tag.
CONTAINERFILE_LABEL = "org.opentorus.containerfile-sha256"
_MISSING_DOCKERFILE = (
    "Pass --file path/to/Dockerfile (or Containerfile). OpenTorus does not ship container images."
)


@dataclass(frozen=True)
class PrepareResult:
    name: str
    runtime: str
    image: str
    built: bool
    config_path: Path
    containerfile: Path | None = None
    build_context: Path | None = None
    # Why the image was built or reused (hash match, hash mismatch, missing
    # label, missing image, --rebuild) — surfaced verbatim by the CLI.
    reason: str = ""


def local_image_tag(name: str, containerfile_hash: str | None = None) -> str:
    """Tag for a locally built environment image, addressed by build input.

    The tag carries the first :data:`_IMAGE_TAG_HASH_CHARS` hex chars of the
    Containerfile's sha256, so two workspaces that build *different*
    Containerfiles under the same environment name can never share one image.
    It used to be ``opentorus-{name}:local`` for every workspace on the machine,
    and all shipped examples call their environment ``python-sci``: a second
    workspace's ``env prepare`` then silently replaced the image the first one
    was pinned to, and the first one's experiments ran against another
    workspace's dependency set while its ``environments.yaml`` still named its
    own Containerfile. Identical Containerfiles still converge on one tag, so
    the common case shares an image instead of racing over it.

    ``containerfile_hash=None`` keeps the legacy unqualified tag, which is what
    an explicit ``--tag`` and pre-existing workspaces still resolve to.
    """
    if not containerfile_hash:
        return _LOCAL_IMAGE_TAG.format(name=name)
    return _LOCAL_IMAGE_TAG_HASHED.format(
        name=name, short=containerfile_hash[:_IMAGE_TAG_HASH_CHARS]
    )


def workspace_root(ot_dir: Path) -> Path:
    return ot_dir.resolve().parent


def _load_workspace_env_raw(ot_dir: Path) -> dict:
    path = ot_dir / ENVIRONMENTS_FILENAME
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    entries = raw.get("environments", raw)
    return entries if isinstance(entries, dict) else {}


def _resolve_user_path(root: Path, user_path: str | Path) -> Path:
    path = Path(user_path).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _rel_to_workspace(root: Path, path: Path) -> str:
    # POSIX form regardless of host OS: the string is persisted in workspace
    # state, so a dossier prepared on Windows must replay elsewhere.
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _find_containerfile_in_dir(directory: Path) -> Path | None:
    for name in _CONTAINERFILE_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _resolve_containerfile_and_context(
    root: Path,
    *,
    containerfile: Path | str,
    build_context: Path | str | None,
) -> tuple[Path, Path]:
    """Return absolute (context_dir, containerfile_path)."""
    cf = _resolve_user_path(root, containerfile)
    if cf.is_dir():
        found = _find_containerfile_in_dir(cf)
        if found is None:
            raise OpenTorusError(f"No Dockerfile or Containerfile found in directory '{cf}'.")
        cf = found

    if not cf.is_file():
        raise OpenTorusError(f"Containerfile not found: '{cf}'.")

    if build_context is not None:
        ctx = _resolve_user_path(root, build_context)
    else:
        ctx = cf.parent

    if not ctx.is_dir():
        raise OpenTorusError(f"Build context is not a directory: '{ctx}'.")
    return ctx, cf


def _saved_build_paths(ot_dir: Path, name: str) -> tuple[Path, Path] | None:
    root = workspace_root(ot_dir)
    entry = _load_workspace_env_raw(ot_dir).get(name)
    if not isinstance(entry, dict):
        return None
    cf = entry.get("containerfile")
    if not cf:
        return None
    ctx = entry.get("build_context")
    try:
        return _resolve_containerfile_and_context(
            root,
            containerfile=str(cf),
            build_context=str(ctx) if ctx else None,
        )
    except OpenTorusError:
        return None


def resolve_build_paths(
    ot_dir: Path,
    name: str,
    *,
    containerfile: Path | str | None = None,
    build_context: Path | str | None = None,
) -> tuple[Path, Path]:
    """Resolve build context + Dockerfile/Containerfile for ``env prepare``."""
    root = workspace_root(ot_dir)

    if containerfile is not None:
        return _resolve_containerfile_and_context(
            root,
            containerfile=containerfile,
            build_context=build_context,
        )

    saved = _saved_build_paths(ot_dir, name)
    if saved is not None:
        return saved

    raise OpenTorusError(
        f"Environment '{name}' has no Dockerfile configured. {_MISSING_DOCKERFILE}"
    )


def _pick_container_runtime(config: Config) -> str:
    from opentorus.execution.registry import make_backend

    for runtime in config.execution.auto_preference:
        if runtime not in ("docker", "podman"):
            continue
        backend = make_backend(runtime)
        if backend.is_available():
            return runtime
    raise OpenTorusError(
        "No container runtime found. Install Docker or Podman, then rerun "
        "'opentorus env prepare' with --file."
    )


def _resolve_image_id(runtime: str, tag: str) -> str | None:
    """The image id a tag resolves to, the way ``run`` resolves it.

    ``image inspect <tag>`` is not a reliable existence test: after several
    concurrent builds wrote the same tag, a stress run left a daemon where
    ``docker images -q`` and ``docker run`` both resolved the tag while
    ``docker image inspect <tag>`` answered "No such image". Asking for the id
    first, and inspecting *that*, keeps the check on the same lookup the run
    itself will use.
    """
    result = run_argv([runtime, "images", "-q", tag], timeout=30)
    if result.exit_code != 0:
        return None
    first = result.stdout.strip().splitlines()
    return first[0].strip() if first and first[0].strip() else None


def _image_exists(runtime: str, tag: str) -> bool:
    if _resolve_image_id(runtime, tag):
        return True
    result = run_argv([runtime, "image", "inspect", tag], timeout=30)
    return result.exit_code == 0


def containerfile_sha256(containerfile: Path) -> str:
    """sha256 of the Containerfile's content — the image's build-input identity."""
    return hashlib.sha256(containerfile.read_bytes()).hexdigest()


def environment_image_mismatch(env: ToolEnvironment, *, runtime: str) -> str | None:
    """Explain why ``env.image`` is not the image this workspace built, else ``None``.

    A locally built image is referenced by tag, and a tag is mutable: another
    workspace's ``env prepare`` can leave a different image under it. Comparing
    the recorded Containerfile hash against the label stamped on the image at
    build time turns that from a silent wrong-environment run into a refusal.

    Returns ``None`` when there is nothing to check (no recorded hash — an
    environment prepared before the hash was recorded, or a bring-your-own
    image) or when the image is the expected one.
    """
    expected = env.containerfile_sha256
    if not expected or not env.image:
        return None
    if runtime not in ("docker", "podman"):
        return None
    stored = _image_label(runtime, env.image, CONTAINERFILE_LABEL)
    if stored == expected:
        return None
    rebuild = f"Run: opentorus env prepare {env.name} --rebuild"
    if not _image_exists(runtime, env.image):
        return (
            f"Environment '{env.name}' points at image '{env.image}', which no longer "
            f"exists. Nothing was executed. {rebuild}"
        )
    if stored is None:
        return (
            f"Environment '{env.name}' points at image '{env.image}', which carries no "
            f"{CONTAINERFILE_LABEL} label, so it cannot be shown to be the image this "
            f"workspace built. Nothing was executed. {rebuild}"
        )
    return (
        f"Environment '{env.name}' points at image '{env.image}', but that image was "
        f"built from a different Containerfile (image {stored[:12]}, this workspace "
        f"{expected[:12]}) — another workspace on this machine most likely replaced it. "
        f"Nothing was executed, so no result is attributed to the wrong environment. "
        f"{rebuild}"
    )


def _image_label(runtime: str, tag: str, label: str) -> str | None:
    """Return ``label``'s value on the image, or ``None`` if image/label is absent.

    Parses ``image inspect`` JSON rather than a Go template so the same code
    reads Docker (``.Config.Labels``) and Podman (also top-level ``.Labels``).
    Inspects the *resolved id* where the daemon can give one — inspecting by tag
    alone has been seen to fail on a tag that ``run`` resolves perfectly well.
    """
    reference = _resolve_image_id(runtime, tag) or tag
    result = run_argv([runtime, "image", "inspect", reference], timeout=30)
    if result.exit_code != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    entry = data[0]
    config = entry.get("Config")
    labels = (config or {}).get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        labels = entry.get("Labels")
    if not isinstance(labels, dict):
        return None
    value = labels.get(label)
    return value if isinstance(value, str) and value else None


def _build_image(
    runtime: str,
    tag: str,
    *,
    context: Path,
    containerfile: Path,
    label_name: str,
    containerfile_hash: str | None = None,
) -> None:
    argv = [
        runtime,
        "build",
        "-f",
        str(containerfile),
        "-t",
        tag,
    ]
    if containerfile_hash:
        # Stamp the build input's hash on the image so a later `env prepare` can
        # detect a stale image instead of silently reusing it.
        argv += ["--label", f"{CONTAINERFILE_LABEL}={containerfile_hash}"]
    argv.append(str(context))
    result = run_argv(argv, timeout=600, label=f"{runtime} build -t {tag}")
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise OpenTorusError(
            f"Container build failed for '{label_name}' (exit {result.exit_code}).\n{detail}"
        )


def _default_command_for(ot_dir: Path, name: str, override: str | None) -> str:
    if override:
        return override
    try:
        return resolve_environment(ot_dir, name).default_command
    except OpenTorusError:
        return "python run.py"


def _write_workspace_override(
    ot_dir: Path,
    name: str,
    image: str,
    *,
    default_command: str,
    build_context: Path,
    containerfile: Path,
    containerfile_hash: str | None = None,
) -> Path:
    root = workspace_root(ot_dir)
    path = ot_dir / ENVIRONMENTS_FILENAME
    data: dict = {}
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            data = raw if "environments" in raw else {"environments": raw}
    environments = data.setdefault("environments", {})
    entry = dict(environments.get(name) or {})
    entry["image"] = image
    entry["default_command"] = default_command
    entry["build_context"] = _rel_to_workspace(root, build_context)
    entry["containerfile"] = _rel_to_workspace(root, containerfile)
    # Recorded so a later run can check that the image still is the one this
    # workspace built, rather than trusting the tag it happens to carry.
    if containerfile_hash:
        entry["containerfile_sha256"] = containerfile_hash
    environments[name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _ensure_prepare_allowed(
    ot_dir: Path,
    name: str,
    *,
    containerfile: Path | str | None,
) -> None:
    if containerfile is not None:
        return
    if _saved_build_paths(ot_dir, name) is not None:
        return
    if name in list_environments(ot_dir):
        raise OpenTorusError(f"Environment '{name}' has no Dockerfile yet. {_MISSING_DOCKERFILE}")
    valid = ", ".join(sorted(list_environments(ot_dir))) or "(none)"
    raise OpenTorusError(
        f"Unknown tool environment '{name}'. Known: {valid}. "
        f"Define a custom stack with --file path/to/Dockerfile."
    )


def prepare_environment(
    ot_dir: Path,
    name: str,
    *,
    rebuild: bool = False,
    config: Config | None = None,
    containerfile: Path | str | None = None,
    build_context: Path | str | None = None,
    image_tag: str | None = None,
    default_command: str | None = None,
) -> PrepareResult:
    """Build (or reuse) a user image and pin the workspace to it."""
    ot_dir = ot_dir.resolve()
    _ensure_prepare_allowed(ot_dir, name, containerfile=containerfile)

    cfg = config or (
        load_config(ot_dir / "config.yaml")
        if (ot_dir / "config.yaml").is_file()
        else default_config()
    )
    runtime = _pick_container_runtime(cfg)
    context, cf = resolve_build_paths(
        ot_dir,
        name,
        containerfile=containerfile,
        build_context=build_context,
    )
    cf_hash = containerfile_sha256(cf)
    # The tag is derived from the build input, so a differing Containerfile lands
    # on a differing tag instead of overwriting another workspace's image.
    tag = image_tag or local_image_tag(name, cf_hash)
    # Decide build-vs-reuse from the Containerfile hash stamped on the image at
    # build time — an image that merely carries the tag is not proof it was built
    # from the *current* Containerfile.
    needs_build = True
    if rebuild:
        reason = "--rebuild requested"
    elif not _image_exists(runtime, tag):
        reason = "image not found"
    else:
        stored = _image_label(runtime, tag, CONTAINERFILE_LABEL)
        if stored == cf_hash:
            needs_build = False
            reason = f"containerfile hash match ({cf_hash[:12]})"
        elif stored is None:
            reason = (
                f"existing image lacks the {CONTAINERFILE_LABEL} label "
                f"(current containerfile {cf_hash[:12]}); rebuilding"
            )
        else:
            reason = (
                f"containerfile hash mismatch (image label {stored[:12]}, "
                f"current {cf_hash[:12]}); rebuilding"
            )
    built = False
    if needs_build:
        _build_image(
            runtime,
            tag,
            context=context,
            containerfile=cf,
            label_name=name,
            containerfile_hash=cf_hash,
        )
        built = True
    cmd = _default_command_for(ot_dir, name, default_command)
    config_path = _write_workspace_override(
        ot_dir,
        name,
        tag,
        default_command=cmd,
        build_context=context,
        containerfile=cf,
        containerfile_hash=cf_hash,
    )
    return PrepareResult(
        name=name,
        runtime=runtime,
        image=tag,
        built=built,
        config_path=config_path,
        containerfile=cf,
        build_context=context,
        reason=reason,
    )
