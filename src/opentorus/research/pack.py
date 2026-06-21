"""Reviewer artifact pack (Milestone 69).

A *research pack* extends the session bundle (M40) into a self-contained,
shareable record of an investigation: the report, the LaTeX draft, figures,
claims/evidence, experiment manifests, pinned environment refs, and the journal.
It is privacy-clean (M20: sensitive paths excluded) and license-clean (M57: no
proprietary license material, and copyrighted full-text PDFs are left out).

A reproduce step re-runs the recorded experiments (Phase 21 cache/replay) and
diffs them against the recorded manifests, surfacing any mismatch as a
reproducibility flag (M41). A single experiment can also be exported as a Jupyter
notebook for interactive inspection.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

import opentorus
from opentorus.errors import OpenTorusError
from opentorus.permissions.policy import is_sensitive_path

_PACK_FILES = ("graph.jsonl", "evidence.jsonl", "proofs.jsonl", "environments.yaml")
_PACK_DIRS = (
    "memory",
    "figures",
    "experiments",
    "journal",
    "research",
    "reviews",
    "papers",
)
# Never redistributed in a pack: copyrighted full texts and large binaries.
_EXCLUDED_SUFFIXES = (".pdf",)


class PaperRef(BaseModel):
    """Enough to re-acquire a cited paper's legal copy and verify its content hash."""

    id: str
    title: str = ""
    doi: str = ""
    arxiv_id: str = ""
    sha256: str = ""
    license: str = ""


class PackManifest(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    opentorus_version: str = opentorus.__version__
    files: list[str] = Field(default_factory=list)
    pinned_environments: list[str] = Field(default_factory=list)
    experiment_count: int = 0
    # Copyrighted PDFs are excluded from the pack; this index lets a reviewer
    # re-acquire the open-access copy and verify it against the recorded hash.
    papers: list[PaperRef] = Field(default_factory=list)


def _pack_clean(path: Path) -> bool:
    return not is_sensitive_path(path) and path.suffix.lower() not in _EXCLUDED_SUFFIXES


def export_pack(ot_dir: Path, out_path: Path | None = None) -> Path:
    """Bundle an investigation into a privacy/license-clean reviewer pack."""
    from opentorus.execution.environments import list_environments
    from opentorus.research.experiments import list_experiments

    entries: list[tuple[str, bytes]] = []
    for rel in _PACK_FILES:
        path = ot_dir / rel
        if path.is_file() and _pack_clean(path):
            entries.append((f"pack/{rel}", path.read_bytes()))
    for dirname in _PACK_DIRS:
        directory = ot_dir / dirname
        if not directory.is_dir():
            continue
        for file in sorted(directory.rglob("*")):
            if file.is_file() and _pack_clean(file):
                arc = f"pack/{file.relative_to(ot_dir).as_posix()}"
                entries.append((arc, file.read_bytes()))

    pinned = [env.image for env in list_environments(ot_dir).values() if env.image is not None]
    from opentorus.research.papers import list_papers

    papers = [
        PaperRef(
            id=p.id,
            title=p.title or "",
            doi=p.doi or "",
            arxiv_id=p.arxiv_id or "",
            sha256=p.sha256 or "",
            license=p.license or "",
        )
        for p in list_papers(ot_dir)
    ]
    manifest = PackManifest(
        files=sorted(name for name, _ in entries),
        pinned_environments=sorted(pinned),
        experiment_count=len(list_experiments(ot_dir)),
        papers=papers,
    )

    out_path = out_path or ot_dir / "packs" / "research-pack.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pack.json", manifest.model_dump_json(indent=2))
        # A standalone, human-readable re-acquisition index alongside the manifest.
        zf.writestr(
            "pack/papers-manifest.json", json.dumps([p.model_dump() for p in papers], indent=2)
        )
        for name, data in entries:
            zf.writestr(name, data)
    return out_path


def read_pack_manifest(pack_path: Path) -> PackManifest:
    with zipfile.ZipFile(pack_path) as zf:
        return PackManifest.model_validate_json(zf.read("pack.json"))


def reproduce_pack(ot_dir: Path, exp_ids: list[str] | None = None, *, timeout: int = 120):
    """Re-run recorded experiments and return their reproducibility reports.

    Each report's ``reproducible`` flag is False when the fresh run diverges from
    the recorded manifest — a mismatch is surfaced, never hidden.
    """
    from opentorus.research.experiments import list_experiments
    from opentorus.research.repro import ReplayReport, replay_experiment

    if exp_ids is None:
        exp_ids = [e.id for e in list_experiments(ot_dir)]
    reports: list[ReplayReport] = []
    for exp_id in exp_ids:
        try:
            reports.append(replay_experiment(ot_dir, exp_id, timeout=timeout))
        except OpenTorusError:
            # No baseline manifest (never run) — skip rather than fail the pack.
            continue
    return reports


def export_experiment_notebook(ot_dir: Path, exp_id: str, out_path: Path | None = None) -> Path:
    """Export one experiment as a Jupyter notebook for interactive inspection."""
    from opentorus.research.experiments import get_experiment

    experiment = get_experiment(ot_dir, exp_id)
    if experiment is None:
        raise OpenTorusError(f"No experiment with id '{exp_id}'.")
    exp_dir = ot_dir / experiment.path
    run_py = exp_dir / "run.py"
    code = run_py.read_text(encoding="utf-8") if run_py.is_file() else "# (no run.py)\n"
    stdout_path = exp_dir / "results" / "stdout.txt"
    stdout = stdout_path.read_text(encoding="utf-8") if stdout_path.is_file() else ""

    notebook = {
        "cells": [
            _markdown_cell(
                [
                    f"# {experiment.id} — {experiment.title}\n",
                    "\n",
                    f"- Command: `{experiment.command}`\n",
                    f"- Status: {experiment.status}\n",
                    "\n",
                    "> Results are evidence, not final validation.\n",
                ]
            ),
            _code_cell(_as_lines(code)),
            _markdown_cell(["## Recorded stdout\n", "\n", "```\n", *_as_lines(stdout), "```\n"]),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out_path = out_path or exp_dir / f"{exp_id}.ipynb"
    out_path.write_text(json.dumps(notebook, indent=1), encoding="utf-8")
    return out_path


def _as_lines(text: str) -> list[str]:
    if not text:
        return [""]
    lines = text.splitlines(keepends=True)
    return lines or [text]


def _markdown_cell(source: list[str]) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def _code_cell(source: list[str]) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source,
    }
