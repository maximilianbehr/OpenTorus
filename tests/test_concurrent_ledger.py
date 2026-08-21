"""Two OpenTorus processes in one workspace must not lose each other's artifacts.

A mutable ledger is updated read-modify-write: read every record, add one, replace
the file. Concurrently that is a lost update — the second rename overwrites the
first writer's file — and since each writer derives the next artifact id from what
it just read, both mint the same id. Measured before the lock: four processes
appending fifteen claims each reported sixty successes and left sixteen records.

A REPL in one terminal and a CLI in another is an ordinary way to use this tool, so
these run real processes rather than threads: the failure is between processes, and
threads in one interpreter would not reproduce it.
"""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import pytest

from opentorus.atomicio import file_lock
from opentorus.errors import OpenTorusError
from opentorus.research.claims import list_claims, new_claim
from opentorus.workspace import init_workspace, workspace_dir

WRITERS = 4
PER_WRITER = 5


def _write_claims(root_str: str, writer: int) -> list[str]:
    """Create ``PER_WRITER`` claims in the workspace at ``root_str``."""
    ot_dir = workspace_dir(Path(root_str))
    return [new_claim(ot_dir, f"writer {writer} claim {i}").id for i in range(PER_WRITER)]


def test_concurrent_processes_do_not_lose_claims(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ctx = mp.get_context("spawn")  # matches how a second CLI invocation really starts
    with ctx.Pool(WRITERS) as pool:
        minted = pool.starmap(_write_claims, [(str(tmp_path), writer) for writer in range(WRITERS)])

    reported = [claim_id for batch in minted for claim_id in batch]
    stored = list_claims(workspace_dir(tmp_path))

    assert len(reported) == WRITERS * PER_WRITER
    # Every id the tool handed out is distinct …
    assert len(set(reported)) == len(reported), "ids were minted twice"
    # … and every claim it said it created is actually in the ledger.
    assert len(stored) == len(reported), "records were silently dropped"
    assert {c.id for c in stored} == set(reported)


def test_file_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    target = tmp_path / "ledger.jsonl"
    target.write_text("", encoding="utf-8")
    lock_file = target.with_name(target.name + ".lock")

    with file_lock(target):
        assert lock_file.exists()
        with pytest.raises(OpenTorusError, match="Timed out"):
            with file_lock(target, timeout=0.05):
                pass  # pragma: no cover - the lock must not be granted twice
    assert not lock_file.exists()

    # Released cleanly, so the next caller gets it straight away.
    with file_lock(target, timeout=0.05):
        pass


def test_file_lock_reclaims_a_lock_left_by_a_dead_holder(tmp_path: Path) -> None:
    """A crash must not wedge the workspace forever."""
    target = tmp_path / "ledger.jsonl"
    target.write_text("", encoding="utf-8")
    lock_file = target.with_name(target.name + ".lock")
    lock_file.write_text("999999\n", encoding="utf-8")

    with file_lock(target, timeout=0.05, stale_after=0.0):
        assert lock_file.exists()  # ours now
    assert not lock_file.exists()


def test_file_lock_released_even_when_the_body_raises(tmp_path: Path) -> None:
    target = tmp_path / "ledger.jsonl"
    target.write_text("", encoding="utf-8")
    lock_file = target.with_name(target.name + ".lock")

    with pytest.raises(ValueError):
        with file_lock(target):
            raise ValueError("boom")
    assert not lock_file.exists()
