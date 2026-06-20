"""Workspace health checks for ``opentorus doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opentorus.config import Config, load_config
from opentorus.paths import resolve_cli_workspace_root


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_doctor(root: Path, ot_dir: Path, config: Config) -> list[CheckResult]:
    results: list[CheckResult] = []

    if (root / ".opentorus").is_dir():
        results.append(CheckResult("workspace", True, f".opentorus/ in {root}"))
    else:
        results.append(CheckResult("workspace", False, "Run opentorus init in this directory."))

    config_path = ot_dir / "config.yaml"
    if config_path.is_file():
        try:
            load_config(config_path)
            results.append(CheckResult("config", True, "config.yaml loads"))
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult("config", False, str(exc)))
    else:
        results.append(CheckResult("config", False, "Missing config.yaml"))

    provider = config.model.provider
    if provider == "mock":
        results.append(
            CheckResult(
                "model",
                True,
                "provider=mock (offline smoke test only — set a real provider for real work)",
            )
        )
    else:
        try:
            from opentorus.providers.registry import get_provider

            get_provider(config)
            results.append(
                CheckResult("model", True, f"provider={provider}, model={config.model.name}")
            )
            if provider == "ollama" and config.model.num_ctx is None:
                results.append(
                    CheckResult(
                        "ollama",
                        True,
                        "For tool calling, set model.num_ctx (e.g. 32768) and keep Ollama updated",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult("model", False, str(exc)))

    inbox = root / "papers" / "inbox"
    if inbox.is_dir():
        pdfs = list(inbox.glob("*.pdf"))
        results.append(
            CheckResult(
                "papers/inbox",
                True,
                f"{len(pdfs)} PDF(s) waiting" if pdfs else "empty (ready for drops)",
            )
        )
    else:
        results.append(CheckResult("papers/inbox", False, "Missing — run opentorus init"))

    from opentorus.research.index import index_status
    from opentorus.research.papers import list_papers

    papers = list_papers(ot_dir)
    idx = index_status(ot_dir)
    if papers and not idx.built_at:
        results.append(
            CheckResult(
                "index",
                False,
                f"{len(papers)} paper(s) but index not built — run opentorus index build",
            )
        )
    elif idx.built_at:
        results.append(CheckResult("index", True, f"built at {idx.built_at}"))
    else:
        results.append(CheckResult("index", True, "no papers yet (index optional)"))

    try:
        from opentorus.tools.builtin import build_default_registry

        reg = build_default_registry(root, ot_dir, config)
        n = len(reg.names())
        results.append(CheckResult("tools", True, f"{n} tool(s) registered"))
    except Exception as exc:  # noqa: BLE001
        results.append(CheckResult("tools", False, str(exc)))

    if config.quality.test_command:
        import shutil

        cmd = config.quality.test_command.split()[0]
        if shutil.which(cmd):
            results.append(CheckResult("quality", True, f"{config.quality.test_command}"))
        else:
            results.append(CheckResult("quality", False, f"'{cmd}' not on PATH"))
    else:
        results.append(CheckResult("quality", True, "test_command disabled"))

    return results


def doctor_for_cwd() -> tuple[Path | None, Path | None, list[CheckResult]]:
    cwd = Path.cwd().resolve()
    root = resolve_cli_workspace_root(cwd)
    if root is None:
        return (
            None,
            None,
            [CheckResult("workspace", False, f"No .opentorus/ in {cwd} — run opentorus init")],
        )
    ot_dir = root / ".opentorus"
    from opentorus.config import default_config, load_config

    config_path = ot_dir / "config.yaml"
    config = load_config(config_path) if config_path.is_file() else default_config()
    return root, ot_dir, run_doctor(root, ot_dir, config)
