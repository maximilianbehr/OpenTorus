"""The optional, read-only terminal dashboard for a campaign's proof tree.

Two things live at this level and nothing else:

* :func:`require_textual` — the one place that turns a missing optional dependency
  into an actionable :class:`~opentorus.errors.OpenTorusError` (``pip install
  'opentorus[dashboard]'``);
* :func:`run_dashboard` — the entry point the ``campaign dashboard`` command calls.
  It imports :mod:`opentorus.dashboard.app` *inside* the function, so importing this
  package (or :mod:`opentorus.dashboard.adapters`, the pure view-model layer) never
  imports ``textual``. A test pins that ``import opentorus.dashboard`` leaves
  ``textual`` out of ``sys.modules``, and CI checks the wheel the same way.

The dashboard is a *view*: it reads the campaign event log, the dossier and the
workspace ledgers through the same code paths as ``campaign status`` and ``campaign
tree`` and writes nothing back — no event, no snapshot, no usage record. Node
statuses are copies of what their ledgers say and the problem's status is derived
from dossier artifacts on every load; nothing shown here can upgrade either.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.errors import OpenTorusError

MISSING_TEXTUAL_MESSAGE = (
    "The dashboard needs the optional 'dashboard' extra: pip install 'opentorus[dashboard]'"
)


def require_textual() -> None:
    """Raise an actionable :class:`OpenTorusError` when ``textual`` is not importable.

    Only :class:`ImportError` is translated: any other failure while importing the
    dependency is a real bug in the environment and must surface as itself.
    """
    try:
        import textual  # noqa: F401
    except ImportError as exc:
        raise OpenTorusError(MISSING_TEXTUAL_MESSAGE) from exc


def run_dashboard(
    ot_dir: Path,
    campaign_id: str,
    *,
    live: bool = False,
    refresh_seconds: float = 2.0,
) -> None:
    """Open the interactive dashboard on ``campaign_id`` (blocks until the user quits).

    The first load happens *before* the terminal UI starts, so an unknown campaign or
    an unreadable workspace fails with a plain error message instead of inside a
    half-drawn screen. ``live`` starts the periodic re-read of the campaign files
    (``refresh_seconds`` between reads); the ``l`` key toggles it at runtime.
    """
    require_textual()
    from opentorus.dashboard.adapters import DashboardData, load_dashboard_data
    from opentorus.dashboard.app import CampaignDashboardApp

    campaign = campaign_id.strip().upper()

    def loader() -> DashboardData:
        return load_dashboard_data(ot_dir, campaign)

    initial = loader()
    app = CampaignDashboardApp(
        loader, initial=initial, live=live, refresh_seconds=max(0.2, float(refresh_seconds))
    )
    app.run()


__all__ = ["MISSING_TEXTUAL_MESSAGE", "require_textual", "run_dashboard"]
