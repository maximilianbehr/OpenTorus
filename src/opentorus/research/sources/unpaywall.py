"""Unpaywall connector: find a *legal* open-access PDF for a DOI.

Unpaywall only ever returns links that are legitimately open access, which makes
it the safe first stop in the full-text resolver chain. The API requires a
contact email; without one we skip it rather than guessing.
"""

from __future__ import annotations

from collections.abc import Callable

from opentorus.research.sources.base import build_url, http_get_json

API = "https://api.unpaywall.org/v2"


def best_oa_pdf(
    doi: str,
    email: str,
    *,
    fetch: Callable[[str], dict] = http_get_json,
) -> tuple[str | None, str | None]:
    """Return ``(pdf_url, license)`` for the best legal OA copy, or ``(None, None)``."""
    url = build_url(f"{API}/{doi}", {"email": email})
    data = fetch(url)
    if not data.get("is_oa"):
        return None, None
    location = data.get("best_oa_location") or {}
    pdf_url = location.get("url_for_pdf") or location.get("url")
    return pdf_url, location.get("license")
