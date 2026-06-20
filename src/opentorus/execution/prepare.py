"""One-command setup for local container tool environments.

OpenTorus does not ship container images. The user must supply a Dockerfile::

    opentorus env prepare python-sci --file docker/Dockerfile
    opentorus env prepare my-stack --file ./Containerfile --context ./docker

Paths are saved in ``.opentorus/environments.yaml`` for later rebuilds
(``opentorus env prepare python-sci --rebuild``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from opentorus.config import Config, default_config, load_config
from opentorus.errors import OpenTorusError
from opentorus.execution.environments import (
    ENVIRONMENTS_FILENAME,
    list_environments,
    resolve_environment,
)
from opentorus.tools.shell import run_argv

_LOCAL_IMAGE_TAG = "opentorus-{name}:local"
_CONTAINERFILE_NAMES = ("Dockerfile", "Containerfile", "dockerfile", "containerfile")
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


def local_image_tag(name: str) -> str:
    return _LOCAL_IMAGE_TAG.format(name=name)


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
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


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


def _image_exists(runtime: str, tag: str) -> bool:
    result = run_argv([runtime, "image", "inspect", tag], timeout=30)
    return result.exit_code == 0


def _build_image(
    runtime: str,
    tag: str,
    *,
    context: Path,
    containerfile: Path,
    label_name: str,
) -> None:
    argv = [
        runtime,
        "build",
        "-f",
        str(containerfile),
        "-t",
        tag,
        str(context),
    ]
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
    tag = image_tag or local_image_tag(name)
    context, cf = resolve_build_paths(
        ot_dir,
        name,
        containerfile=containerfile,
        build_context=build_context,
    )
    built = False
    if rebuild or not _image_exists(runtime, tag):
        _build_image(runtime, tag, context=context, containerfile=cf, label_name=name)
        built = True
    cmd = _default_command_for(ot_dir, name, default_command)
    config_path = _write_workspace_override(
        ot_dir,
        name,
        tag,
        default_command=cmd,
        build_context=context,
        containerfile=cf,
    )
    return PrepareResult(
        name=name,
        runtime=runtime,
        image=tag,
        built=built,
        config_path=config_path,
        containerfile=cf,
        build_context=context,
    )
