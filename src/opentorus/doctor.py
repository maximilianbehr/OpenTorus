"""Workspace health checks for ``opentorus doctor``.

Every check is one :class:`CheckResult`; ``ok=False`` means *misconfiguration or a
broken workspace* (a route naming an unknown profile, an unwritable dossier dir, a
provider that cannot answer). An absent optional backend or extra is reported as
``ok=True`` with an informational detail — "none installed" is a fact about the
machine, not a fault, and doctor must stay green on a fresh mock workspace.
Secrets are never printed: credentials are reported by environment-variable
*name* and presence only.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from opentorus.config import Config, load_config
from opentorus.paths import resolve_cli_workspace_root

# Hard deadline for the doctor's provider probe: provider SDKs default to
# multi-minute read timeouts, which is unacceptable for a diagnostics command.
_PROBE_TIMEOUT_SECONDS = 20.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    # Structured payload for ``doctor --json`` (the tables the one-line detail summarises).
    data: dict[str, object] = field(default_factory=dict)


def _run_with_deadline(target: Callable[[], object], seconds: float) -> tuple[bool, object]:
    """Run ``target`` on a daemon thread; returns ``(finished, result_or_exception)``.

    Doctor is the command users run precisely when an endpoint is broken, so no
    probe may hang it: an accept-then-stall server is reported as a timeout.
    """
    outcome: list[object] = []

    def _work() -> None:
        try:
            outcome.append(target())
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller as a value
            outcome.append(exc)

    thread = threading.Thread(target=_work, daemon=True)
    thread.start()
    thread.join(seconds)
    if not outcome:
        return False, None
    return True, outcome[0]


def run_doctor(
    root: Path,
    ot_dir: Path,
    config: Config,
    *,
    capabilities: bool = False,
    probe: bool = False,
) -> list[CheckResult]:
    """All health checks. ``capabilities`` adds per-profile capability tables and
    route fallback availability; ``probe`` additionally probes each non-mock profile
    online for tool calling and caches the result. ``probe`` implies
    ``capabilities``: a probe whose findings are not shown would silently do
    nothing, which is exactly what ``doctor --probe`` used to do."""
    capabilities = capabilities or probe
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

            provider_obj = get_provider(config)
            # Run the same probe `prove` uses, so a provider that cannot actually
            # work (missing API key, unreachable server, missing model) fails here
            # instead of on the user's first real run. The probe runs on a daemon
            # thread with a hard deadline: SDK defaults allow multi-minute reads,
            # and doctor is the command users run precisely when the endpoint is
            # broken — it must never hang on an accept-then-stall server.
            probe_outcome: list[tuple[bool | None, str]] = []

            def _probe() -> None:
                from opentorus.providers.tool_support import provider_supports_tool_calling

                try:
                    probe_outcome.append(provider_supports_tool_calling(provider_obj, config))
                except Exception as probe_exc:  # noqa: BLE001
                    probe_outcome.append((None, f"probe request failed: {probe_exc}"))

            thread = threading.Thread(target=_probe, daemon=True)
            thread.start()
            thread.join(_PROBE_TIMEOUT_SECONDS)
            if not probe_outcome:
                results.append(
                    CheckResult(
                        "model",
                        False,
                        f"provider={provider}, model={config.model.name}: tool-calling "
                        f"probe timed out after {_PROBE_TIMEOUT_SECONDS}s — the endpoint "
                        "accepted the request but did not answer. Next action: check "
                        "model.base_url and network/proxy, or set "
                        "model.verify_tool_calling false.",
                    )
                )
            else:
                ok, detail = probe_outcome[0]
                if ok is False or (ok is None and "probe request failed" in detail):
                    from opentorus.ux import provider_error_cause

                    cause, action = provider_error_cause(detail)
                    results.append(
                        CheckResult(
                            "model",
                            False,
                            f"provider={provider}, model={config.model.name}: {detail} — "
                            f"{cause} Next action: {action}",
                        )
                    )
                else:
                    note = (
                        " (tool calling verified)"
                        if ok is True
                        else f" (unverified: {detail})"
                        if detail
                        else ""
                    )
                    results.append(
                        CheckResult(
                            "model", True, f"provider={provider}, model={config.model.name}{note}"
                        )
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
            from opentorus.ux import provider_error_cause

            cause, action = provider_error_cause(str(exc))
            results.append(CheckResult("model", False, f"{exc} — {cause} Next action: {action}"))

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

    # Verification backends: report which enabled rigor backends are actually
    # installed, so "formal verification available" is never advertised falsely.
    try:
        from opentorus.research.verifiers.registry import available_verifiers

        ready = sorted(available_verifiers(config))
        results.append(
            CheckResult(
                "verifiers",
                True,
                f"available: {', '.join(ready)}" if ready else "none installed (formal proof off)",
            )
        )
    except Exception as exc:  # noqa: BLE001
        results.append(CheckResult("verifiers", False, str(exc)))

    # Execution backends: which runtimes are installed for containerized experiments.
    try:
        from opentorus.execution.registry import available_backends

        ready_b = sorted(available_backends(config))  # already filtered to installed backends
        results.append(
            CheckResult(
                "execution",
                True,
                f"available: {', '.join(ready_b)}"
                if ready_b
                else "local only (no container runtime)",
            )
        )
    except Exception as exc:  # noqa: BLE001
        results.append(CheckResult("execution", False, str(exc)))

    results.extend(_routing_checks(ot_dir, config, capabilities=capabilities, probe=probe))
    results.append(_formal_systems_check(config))
    results.append(_dashboard_check())
    results.append(_paper_parsing_check())
    results.append(_dossier_state_check(ot_dir))
    results.append(_version_check())
    return results


def _routing_checks(
    ot_dir: Path, config: Config, *, capabilities: bool, probe: bool
) -> list[CheckResult]:
    """``profiles``, ``routes`` and ``credentials`` — configuration-only unless
    ``probe`` is set (then each non-mock profile is probed with a hard deadline)."""
    try:
        from opentorus.providers.pool import build_pool

        pool = build_pool(config, ot_dir)
        profile_reports, route_reports = pool.describe()
    except Exception as exc:  # noqa: BLE001
        detail = f"could not evaluate model profiles: {exc}"
        return [
            CheckResult("profiles", False, detail),
            CheckResult("routes", False, detail),
            CheckResult("credentials", False, detail),
        ]

    probe_notes: dict[str, str] = {}
    if capabilities and probe:
        probe_notes = _probe_profiles(ot_dir, config, pool.profiles())
        # Re-read so the reports reflect the freshly cached probes.
        pool = build_pool(config, ot_dir)
        profile_reports, route_reports = pool.describe()

    # profiles -------------------------------------------------------------------
    problems = [f"{r.name}: {p}" for r in profile_reports for p in r.problems]
    parts: list[str] = []
    for report in profile_reports:
        cred = ""
        if report.credential_env_var:
            state = "set" if report.credential_present else "missing"
            cred = f", {report.credential_env_var} {state}"
        caps = f", capabilities: {', '.join(report.capabilities) or '-'}" if capabilities else ""
        note = f", {probe_notes[report.name]}" if report.name in probe_notes else ""
        marker = " (default)" if report.is_default else ""
        parts.append(f"{report.name}{marker}={report.provider}/{report.model}{cred}{caps}{note}")
    detail = f"{len(profile_reports)} profile(s): " + "; ".join(parts)
    if problems:
        detail += " — problems: " + "; ".join(problems)
    results = [
        CheckResult(
            "profiles",
            not problems,
            detail,
            {
                "profiles": [r.model_dump(mode="json") for r in profile_reports],
                "probe_notes": probe_notes,
            },
        )
    ]

    # routes ---------------------------------------------------------------------
    routing = config.governance.routing
    # A report synthesised for an undefined ``models.default_profile`` is not a
    # known profile: routes that end in it must be flagged, even though acquire
    # falls back to the implicit ``default`` at run time.
    known_profiles = {r.name for r in profile_reports if r.source != "models.default_profile"}
    unknown_routes = [
        f"{r.task_class} → {', '.join(n for n in r.candidates if n not in known_profiles)}"
        for r in route_reports
        if any(n not in known_profiles for n in r.candidates)
    ]
    if not routing.enabled:
        detail = f"routing disabled: every task class uses '{pool.default_profile_name()}'"
    else:
        configured = [r for r in route_reports if len(r.candidates) > 1]
        detail = (
            f"routing enabled: {len(routing.task_routes)} task_routes, "
            f"{len(routing.task_models)} legacy task_models; "
            f"{len(configured)} task class(es) with a non-default route"
        )
        if not routing.task_routes and not routing.task_models:
            detail += " (none configured — edit config.yaml; `config set` cannot write mappings)"
    if capabilities and routing.enabled:
        with_fallback = sum(1 for r in route_reports if r.fallback_ok)
        detail += f"; fallback available for {with_fallback}/{len(route_reports)} task classes"
    if unknown_routes:
        detail += (
            " — unknown profile in route(s): "
            + "; ".join(unknown_routes)
            + " (edit config.yaml; `config set` cannot write mappings)"
        )
    results.append(
        CheckResult(
            "routes",
            not unknown_routes,
            detail,
            {
                "enabled": routing.enabled,
                "routes": [r.model_dump(mode="json") for r in route_reports],
            },
        )
    )

    # credentials ----------------------------------------------------------------
    reachable = {n for r in route_reports for n in r.candidates}
    needed = sorted({r.credential_env_var for r in profile_reports if r.credential_env_var})
    missing = sorted(
        {
            r.credential_env_var
            for r in profile_reports
            if r.credential_env_var and not r.credential_present and r.name in reachable
        }
    )
    unrouted_missing = sorted(
        {
            r.credential_env_var
            for r in profile_reports
            if r.credential_env_var
            and not r.credential_present
            and r.name not in reachable
            and r.credential_env_var not in missing
        }
    )
    if not needed:
        detail = "no provider credentials required (local/mock profiles only)"
    elif not missing:
        detail = f"present: {', '.join(needed)}"
        if unrouted_missing:
            detail += f"; missing for unrouted profile(s): {', '.join(unrouted_missing)}"
    else:
        detail = f"missing: {', '.join(missing)} (export it or add a .env entry)"
    results.append(
        CheckResult(
            "credentials",
            not missing,
            detail,
            {"required": needed, "missing": missing, "missing_unrouted": unrouted_missing},
        )
    )
    return results


def _probe_profiles(ot_dir: Path, config: Config, profiles: dict) -> dict[str, str]:
    """Online tool-calling probes for every non-mock profile (``--capabilities --probe``)."""
    from opentorus.providers.capabilities import (
        CapabilityCache,
        default_cache_path,
        probe_and_cache,
    )
    from opentorus.providers.pool import profile_config
    from opentorus.providers.registry import get_provider

    cache = CapabilityCache(default_cache_path(ot_dir))
    notes: dict[str, str] = {}
    for name, profile in profiles.items():
        if profile.provider.lower() == "mock":
            continue
        probe_one = functools.partial(
            lambda prof: probe_and_cache(get_provider(profile_config(config, prof)), prof, cache),
            profile,
        )
        finished, outcome = _run_with_deadline(probe_one, _PROBE_TIMEOUT_SECONDS)
        if not finished:
            notes[name] = f"probe timed out after {_PROBE_TIMEOUT_SECONDS}s"
        elif isinstance(outcome, Exception):
            notes[name] = f"probe failed: {outcome}"
        else:
            caps = list(getattr(outcome, "capabilities", []))
            reason = getattr(outcome, "note", None) or "no verdict"
            notes[name] = (
                f"probe confirmed: {', '.join(caps)}" if caps else f"probe inconclusive: {reason}"
            )
    return notes


def _formal_systems_check(config: Config) -> CheckResult:
    """Formal proof backends: enabled-and-installed vs enabled-but-absent (informational)."""
    try:
        from opentorus.research.verifiers.registry import available_verifiers
        from opentorus.tools.research import enabled_verifier_backends

        ready = sorted(available_verifiers(config))
        enabled = enabled_verifier_backends(config)
        absent = [name for name in enabled if name not in ready]
        detail = f"available: {', '.join(ready)}" if ready else "none installed (formal proof off)"
        if absent:
            detail += f"; enabled but not installed: {', '.join(absent)}"
        return CheckResult("formal-systems", True, detail, {"available": ready, "enabled": enabled})
    except Exception as exc:  # noqa: BLE001
        return CheckResult("formal-systems", False, str(exc))


def _dashboard_check() -> CheckResult:
    """The optional Textual dashboard: installed or not, both are fine."""
    import importlib.util

    installed = importlib.util.find_spec("textual") is not None
    if installed:
        return CheckResult("dashboard", True, "textual installed", {"textual": True})
    return CheckResult(
        "dashboard",
        True,
        "textual not installed (optional; the campaign dashboard needs it: "
        "pip install 'opentorus[dashboard]')",
        {"textual": False},
    )


def _paper_parsing_check() -> CheckResult:
    """PDF text extraction (core dependency) plus optional page rendering / OCR helpers."""
    import importlib.util

    from opentorus.research.pdf_text import ocr_tools_available, pdftoppm_available

    pypdf_ok = importlib.util.find_spec("pypdf") is not None
    render = pdftoppm_available()
    ocr = ocr_tools_available()
    parts = [
        "pypdf " + ("ok" if pypdf_ok else "missing"),
        "pdftoppm " + ("ok" if render else "absent (page rendering off)"),
        "tesseract " + ("ok" if ocr else "absent (OCR fallback off)"),
    ]
    return CheckResult(
        "paper-parsing",
        pypdf_ok,
        "; ".join(parts),
        {"pypdf": pypdf_ok, "pdftoppm": render, "ocr": ocr},
    )


def _dossier_state_check(ot_dir: Path) -> CheckResult:
    """Dossier store writable; count problems and any campaign directories."""
    import os

    problems_dir = ot_dir / "problems"
    if not problems_dir.exists():
        return CheckResult(
            "dossier-state",
            True,
            "no dossiers yet (problems/ is created by `opentorus problem new`)",
            {"problems": 0, "campaigns": 0, "writable": True},
        )
    if not problems_dir.is_dir() or not os.access(problems_dir, os.W_OK):
        return CheckResult(
            "dossier-state",
            False,
            f"{problems_dir} is not a writable directory",
            {"problems": 0, "campaigns": 0, "writable": False},
        )
    dossiers = sorted(p.name for p in problems_dir.iterdir() if p.is_dir())
    campaigns = sorted(
        c.name
        for d in problems_dir.iterdir()
        if (d / "campaigns").is_dir()
        for c in (d / "campaigns").iterdir()
        if c.is_dir()
    )
    detail = f"{len(dossiers)} dossier(s), {len(campaigns)} campaign(s); problems/ writable"
    return CheckResult(
        "dossier-state",
        True,
        detail,
        {"problems": len(dossiers), "campaigns": len(campaigns), "writable": True},
    )


def _version_check() -> CheckResult:
    import platform

    from opentorus import __version__

    python = platform.python_version()
    return CheckResult(
        "version",
        True,
        f"opentorus {__version__} · python {python}",
        {"opentorus": __version__, "python": python},
    )


def doctor_for_cwd(
    *, capabilities: bool = False, probe: bool = False
) -> tuple[Path | None, Path | None, list[CheckResult]]:
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
    return root, ot_dir, run_doctor(root, ot_dir, config, capabilities=capabilities, probe=probe)
