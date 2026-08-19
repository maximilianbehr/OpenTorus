"""Headless smoke of the Textual app (skipped when ``textual`` is not installed):
starts on a mock campaign, drives every key, and proves it writes nothing by
monkeypatching every writer to raise for the whole run and checking file mtimes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

textual = pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

import opentorus.usage as usage_module  # noqa: E402
from opentorus.campaign.proof_tree.models import ROOT_ID, ProofNodeKind  # noqa: E402
from opentorus.campaign.store import CampaignStore  # noqa: E402
from opentorus.dashboard.adapters import DashboardData, load_dashboard_data  # noqa: E402
from opentorus.dashboard.app import CampaignDashboardApp  # noqa: E402
from opentorus.dashboard.widgets import (  # noqa: E402
    DetailPane,
    DiagnosticsPanel,
    OverviewHeader,
    PlainStatic,
    StatusBar,
    TreePane,
)
from opentorus.errors import OpenTorusError  # noqa: E402
from support.campaign import make_engine, make_workspace  # noqa: E402


@pytest.fixture(scope="module")
def mock_campaign(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str, str]:
    tmp = tmp_path_factory.mktemp("dashboard-app")
    root, ot, pid = make_workspace(tmp)
    record = make_engine(root, ot).start(pid, mode="prove-or-refute", branches=2)
    return root, ot, pid, record.id


def _boom(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("the dashboard must never write")


def _snapshot_files(ot: Path, pid: str, cid: str) -> dict[str, tuple[int, int]]:
    cdir = ot / "problems" / pid / "campaigns" / cid
    return {
        str(p.relative_to(ot)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in [*cdir.rglob("*"), *(ot / "usage").rglob("*")]
        if p.is_file()
    }


def _plain(widget: PlainStatic) -> str:
    return widget.plain


def test_app_smoke_every_key_and_read_only(
    mock_campaign: tuple[Path, Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, ot, pid, cid = mock_campaign
    monkeypatch.setattr(CampaignStore, "append", _boom)
    monkeypatch.setattr(CampaignStore, "write_snapshot", _boom)
    monkeypatch.setattr(usage_module, "record_usage", _boom)
    before = _snapshot_files(ot, pid, cid)
    loads: list[int] = []

    def loader() -> DashboardData:
        loads.append(1)
        return load_dashboard_data(ot, cid)

    observed: dict[str, object] = {}

    async def drive() -> None:
        app = CampaignDashboardApp(loader, refresh_seconds=0.5)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.data is not None and app.data.campaign_id == cid
            rows = app.rows
            assert rows and rows[0].node_id == ROOT_ID
            observed["rows"] = len(rows)
            header = _plain(app.query_one(OverviewHeader))
            assert f"Campaign {cid} on {pid}" in header
            assert "Problem status (derived from dossier artifacts):" in header
            assert "no node status and no campaign state ever upgrades it" in header
            tree = app.query_one(TreePane)
            assert tree.option_count == len(rows) and tree.highlighted == 0
            assert app.focused is tree
            # every row shows its symbol and relation
            for row in rows:
                assert row.symbol and f"[{row.root_relation}]" in row.text()
            # j / k
            await pilot.press("j")
            await pilot.pause()
            assert app.state.cursor == 1 and app.state.current_id(app.rows) == rows[1].node_id
            assert rows[1].node_id in _plain(app.query_one(DetailPane))
            await pilot.press("k")
            await pilot.pause()
            assert app.state.cursor == 0
            # enter on the root collapses everything, enter again restores
            await pilot.press("enter")
            await pilot.pause()
            assert [r.node_id for r in app.rows] == [ROOT_ID] and ROOT_ID in app.state.collapsed
            await pilot.press("enter")
            await pilot.pause()
            assert len(app.rows) == len(rows) and not app.state.collapsed
            # / opens the search box, typing filters, enter applies, esc clears
            await pilot.press("slash")
            await pilot.pause()
            box = app.query_one("#search", Input)
            assert box.display and app.focused is box
            for ch in "obl":
                await pilot.press(ch)
            await pilot.pause()
            assert box.value == "obl"
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.search == "obl" and not box.display and app.focused is tree
            searched = [r.node_id for r in app.rows]
            assert any(nid.startswith("OBL-") for nid in searched)
            assert len(searched) < len(rows)
            assert "search='obl'" in _plain(app.query_one(StatusBar))
            await pilot.press("escape")
            await pilot.pause()
            assert app.state.search is None and len(app.rows) == len(rows)
            # o jumps to the next open obligation, g back to the root
            await pilot.press("o")
            await pilot.pause()
            current = app.state.current_id(app.rows)
            assert current is not None
            assert app.data.graph.nodes[current].kind is ProofNodeKind.obligation
            assert app.data.graph.nodes[current].status in {"open", "in_progress"}
            assert tree.highlighted == app.state.cursor
            await pilot.press("g")
            await pilot.pause()
            assert app.state.current_id(app.rows) == ROOT_ID and tree.highlighted == 0
            # f / s cycle the filters (and back to all)
            await pilot.press("f")
            await pilot.pause()
            assert app.state.kind_filter == "branch"
            assert all(r.kind in {"root", "branch"} for r in app.rows)
            assert "kind=branch" in _plain(app.query_one(StatusBar))
            await pilot.press("s")
            await pilot.pause()
            assert app.state.status_filter is not None
            assert "status=" + app.state.status_filter in _plain(app.query_one(StatusBar))
            while app.state.status_filter is not None:
                await pilot.press("s")
                await pilot.pause()
            while app.state.kind_filter is not None:
                await pilot.press("f")
                await pilot.pause()
            assert len(app.rows) == len(rows)
            # r reloads through the loader
            n_loads = len(loads)
            await pilot.press("r")
            await pilot.pause()
            assert len(loads) == n_loads + 1
            assert "reloaded" in _plain(app.query_one(StatusBar))
            # l toggles live refresh (a timer), twice = off again
            await pilot.press("l")
            await pilot.pause()
            assert app.state.live and "live=on" in _plain(app.query_one(StatusBar))
            await pilot.press("l")
            await pilot.pause()
            assert not app.state.live and "live=off" in _plain(app.query_one(StatusBar))
            # no graph issues on a healthy campaign: the diagnostics panel is hidden
            assert app.query_one(DiagnosticsPanel).display is False
            await pilot.press("q")
        observed["exit"] = True

    asyncio.run(drive())
    assert observed["exit"] is True and observed["rows"] > 1
    assert loads  # the loader ran at least once (mount) plus the reload
    assert _snapshot_files(ot, pid, cid) == before  # nothing on disk changed


def test_app_shows_diagnostics_and_survives_a_failing_reload(
    mock_campaign: tuple[Path, Path, str, str],
) -> None:
    from opentorus.campaign.proof_tree.models import ProofEdge, ProofNode
    from opentorus.campaign.proof_tree.validation import validate_graph

    _root, ot, _pid, cid = mock_campaign
    base = load_dashboard_data(ot, cid)
    # a malformed graph: a dangling parent and a two-node cycle
    graph = base.graph.model_copy(deep=True)
    graph.nodes["GHOST"] = ProofNode(
        node_id="GHOST", kind=ProofNodeKind.claim, status="unverified", parents=["NOPE"]
    )
    graph.nodes["A"] = ProofNode(node_id="A", kind=ProofNodeKind.claim, parents=["B"])
    graph.nodes["B"] = ProofNode(node_id="B", kind=ProofNodeKind.claim, parents=["A"])
    graph.edges.append(ProofEdge(source_id="A", target_id="B", relation="parent"))
    graph.edges.append(ProofEdge(source_id="B", target_id="A", relation="parent"))
    graph.issues.extend(validate_graph(graph))
    assert {i.code for i in graph.issues} >= {"missing_ref", "cycle"}
    broken = DashboardData(
        campaign_id=base.campaign_id,
        problem_id=base.problem_id,
        snapshot=base.snapshot,
        summary=base.summary,
        graph=graph,
        overview=base.overview.model_copy(update={"graph_errors": 2}),
    )
    calls: list[int] = []

    def loader() -> DashboardData:
        calls.append(1)
        if len(calls) > 1:
            raise OpenTorusError("workspace vanished")
        return broken

    async def drive() -> None:
        app = CampaignDashboardApp(loader)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one(DiagnosticsPanel)
            assert panel.display is True
            text = _plain(panel)
            assert "missing_ref" in text and "cycle" in text
            ids = [r.node_id for r in app.rows]
            assert {"GHOST", "A", "B"} <= set(ids)
            assert any(r.repeated for r in app.rows)
            await pilot.press("r")
            await pilot.pause()
            assert "reload failed: workspace vanished" in _plain(app.query_one(StatusBar))
            assert app.data is broken and len(app.rows) == len(ids)  # last good data kept
            await pilot.press("q")

    asyncio.run(drive())


def test_app_with_initial_data_and_live_flag(
    mock_campaign: tuple[Path, Path, str, str],
) -> None:
    _root, ot, _pid, cid = mock_campaign
    initial = load_dashboard_data(ot, cid)
    loads: list[int] = []

    def loader() -> DashboardData:
        loads.append(1)
        return load_dashboard_data(ot, cid)

    async def drive() -> None:
        app = CampaignDashboardApp(loader, initial=initial, live=True, refresh_seconds=0.05)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state.live and app.data is not None
            await pilot.pause(0.3)
            assert loads, "live refresh should have re-run the loader"
            assert app.data is not initial  # the timer replaced the initial data
            await pilot.press("q")

    asyncio.run(drive())
