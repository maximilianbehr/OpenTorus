"""Golden-transcript regression tests (Milestone 37)."""

from __future__ import annotations

from pathlib import Path

from opentorus.evals.golden import (
    GOLDEN_SCENARIOS,
    generate_transcript,
    record_goldens,
    verify_goldens,
)

GOLDEN_DIR = Path(__file__).parent / "golden"


def test_committed_goldens_match() -> None:
    results = verify_goldens(GOLDEN_DIR)
    failed = [r for r in results if not r.matched]
    assert not failed, "Golden mismatch:\n" + "\n".join(r.diff for r in failed)


def test_transcripts_are_deterministic() -> None:
    for scenario in GOLDEN_SCENARIOS:
        assert generate_transcript(scenario) == generate_transcript(scenario)


def test_behavior_change_is_detected(tmp_path: Path) -> None:
    # Record goldens, then tamper with one and confirm verify flags it.
    record_goldens(tmp_path)
    target = tmp_path / f"{GOLDEN_SCENARIOS[0].name}.txt"
    target.write_text("intentionally changed behavior\n", encoding="utf-8")
    results = verify_goldens(tmp_path)
    changed = [r for r in results if not r.matched]
    assert len(changed) == 1
    assert changed[0].name == GOLDEN_SCENARIOS[0].name
    assert changed[0].diff


def test_missing_golden_reported(tmp_path: Path) -> None:
    # No goldens recorded in this empty dir.
    results = verify_goldens(tmp_path)
    assert all(not r.matched for r in results)
    assert all("no golden recorded" in r.diff for r in results)
