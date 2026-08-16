"""The one report design system, shared by the PDF and the HTML export.

The dossier report is emitted two ways — typeset LaTeX when a TeX toolchain and a
model are available, standalone HTML otherwise — and the two used to look nothing
alike. Both now draw their palette and their status semantics from here.

The LaTeX side cannot import Python, so ``templates/opentorus.cls`` repeats these
hex values as ``\\definecolor`` lines. ``tests/test_pdf_export.py`` pins the two to
the same values, so they cannot drift apart silently.
"""

from __future__ import annotations

# --------------------------------------------------------------------- palette
# Mirrored in templates/opentorus.cls — change both or neither.
PALETTE: dict[str, str] = {
    "otaccent": "#1B4965",  # headings, links, artifact ids
    "otaccentlt": "#7FA3BC",  # rules on output blocks
    "otmuted": "#5A6672",  # secondary labels
    "otrule": "#D3DAE1",  # hairlines
    "otsurface": "#F4F6F8",  # panel / output background
    "otwarn": "#9A5B0A",  # caveats, gap markers, "open"
    "otwarnbg": "#FCF6EA",
    "otok": "#176B3A",  # supported / verified / succeeded
    "otbad": "#9B2226",  # refuted / failed / invalid
}

# The PDF uses Libertinus; the HTML must not fetch a web font (this project is
# local-first, and the report is a file on disk), so it names the closest
# systemic equivalents and degrades through a plain serif stack.
SERIF_STACK = (
    '"Libertinus Serif", "Linux Libertine O", Libertine, '
    '"Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif'
)
SANS_STACK = (
    '"Libertinus Sans", "Linux Biolinum O", "Fira Sans", '
    '"Helvetica Neue", Helvetica, Arial, sans-serif'
)
MONO_STACK = '"Libertinus Mono", "DejaVu Sans Mono", "SFMono-Regular", Consolas, monospace'


# ------------------------------------------------------------ status semantics
# Covers ProblemStatus, ClaimStatus, ExperimentStatus and ProofAttemptStatus.
# Anything absent falls through to the neutral kind on purpose: colour must never
# upgrade a claim, so "unverified" and "unknown" stay grey rather than borrowing
# the look of a settled result.
STATUS_KIND: dict[str, str] = {
    # settled, and settled in a way the artifacts actually license
    "supported": "ok",
    "verified": "ok",
    "formally_verified": "ok",
    "succeeded": "ok",
    "solved_externally": "ok",
    # open / in flight / needs a human
    "open": "warn",
    "sketch": "warn",
    "in_progress": "warn",
    "running": "warn",
    "planned": "warn",
    "partially_resolved": "warn",
    "needs_review": "warn",
    "inconclusive": "warn",
    # negative outcomes
    "refuted": "bad",
    "contradicted": "bad",
    "failed": "bad",
    "blocked": "bad",
    "abandoned": "bad",
    "invalid": "bad",
}

#: Neutral grey — the default for any status not in :data:`STATUS_KIND`.
NEUTRAL_KIND = "neutral"

#: Palette key carrying each status kind's colour.
KIND_COLOR: dict[str, str] = {
    "ok": "otok",
    "warn": "otwarn",
    "bad": "otbad",
    NEUTRAL_KIND: "otmuted",
}


def status_kind(status: str) -> str:
    """The chip kind for a status string (``ok`` / ``warn`` / ``bad`` / ``neutral``)."""
    return STATUS_KIND.get((status or "").strip().lower(), NEUTRAL_KIND)


def _mix(hex_color: str, ratio: float, other: str = "#FFFFFF") -> str:
    """Blend *hex_color* toward *other*; mirrors LaTeX's ``color!pct!white``."""
    a = hex_color.lstrip("#")
    b = other.lstrip("#")
    parts = (
        round(int(a[i : i + 2], 16) * ratio + int(b[i : i + 2], 16) * (1 - ratio))
        for i in (0, 2, 4)
    )
    return "#{:02X}{:02X}{:02X}".format(*parts)


def report_css() -> str:
    """The stylesheet for the standalone HTML report.

    Deliberately mirrors ``templates/opentorus.cls``: same palette, same heading
    treatment (accent sans headings, a hairline under each section), same tinted
    output panels with an accent left rule, same status chips, same booktabs-style
    tables. It is inlined into the page — the report is a local file, so it must
    not depend on a stylesheet fetch.
    """
    p = PALETTE
    chip_bg = {kind: _mix(p[key], 0.12) for kind, key in KIND_COLOR.items()}
    chip_fg = {kind: _mix(p[key], 0.85, "#000000") for kind, key in KIND_COLOR.items()}
    chips = "".join(
        f".chip-{kind}{{background:{chip_bg[kind]};color:{chip_fg[kind]}}}" for kind in KIND_COLOR
    )
    return f"""\
:root{{
  --accent:{p["otaccent"]};--accent-lt:{p["otaccentlt"]};--muted:{p["otmuted"]};
  --rule:{p["otrule"]};--surface:{p["otsurface"]};--warn:{p["otwarn"]};
  --warn-bg:{p["otwarnbg"]};--ok:{p["otok"]};--bad:{p["otbad"]};
}}
*{{box-sizing:border-box}}
body{{
  max-width:46rem;margin:3rem auto;padding:0 1.5rem;
  font-family:{SERIF_STACK};font-size:1.05rem;line-height:1.55;
  color:#111;background:#fff;text-rendering:optimizeLegibility;
}}
h1,h2,h3,h4,h5,h6{{font-family:{SANS_STACK};color:var(--accent);line-height:1.25}}
h1{{font-size:1.9rem;text-align:center;margin:0 0 .4rem}}
h2{{font-size:1.35rem;margin:2.4rem 0 .8rem;padding-bottom:.3rem;
   border-bottom:.7px solid var(--rule)}}
h3{{font-size:1.13rem;margin:1.8rem 0 .5rem}}
h4,h5,h6{{font-size:1rem;margin:1.4rem 0 .4rem}}
p{{margin:.65rem 0}}
a{{color:var(--accent)}}
/* Display math gets its own centred line, as \\[…\\] does in the PDF. */
.ot-display{{text-align:center;margin:1rem 0;overflow-x:auto}}
hr{{border:0;border-top:.7px solid var(--rule);margin:2rem 0}}

/* Title block + metadata strip — the HTML twin of \\maketitle + \\otdossierpanel. */
.ot-subtitle{{text-align:center;color:var(--muted);font-size:.95rem;margin:0 0 1.6rem}}
.ot-panel{{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.9rem 1.2rem;
  background:var(--surface);border:.7px solid var(--rule);
  padding:.9rem 1.1rem;margin:1.6rem 0 2rem;font-size:.92rem;
}}
.ot-meta-label{{
  font-family:{SANS_STACK};font-size:.68rem;letter-spacing:.06em;
  text-transform:uppercase;color:var(--muted);display:block;margin-bottom:.2rem;
}}

/* Captured program output: tinted panel, accent left rule, wrapping. */
pre{{
  background:var(--surface);border-left:2px solid var(--accent-lt);
  padding:.7rem .9rem;margin:.9rem 0;overflow-x:auto;
  font-family:{MONO_STACK};font-size:.82rem;line-height:1.45;
  white-space:pre-wrap;overflow-wrap:anywhere;
}}
pre code{{background:none;padding:0;font-size:inherit;color:inherit}}
code{{
  font-family:{MONO_STACK};font-size:.88em;
  background:var(--surface);padding:.08em .3em;border-radius:2px;
}}
.ot-cmd{{
  background:var(--surface);border-left:2px solid var(--accent-lt);
  padding:.5rem .9rem;margin:.8rem 0;font-family:{MONO_STACK};font-size:.85rem;
}}
.ot-cmd::before{{content:"$";color:var(--muted);margin-right:.5em}}

/* Artifact ids and gap markers. */
.artifact{{font-family:{MONO_STACK};font-size:.88em;color:var(--accent);white-space:nowrap}}
.gapmarker{{font-family:{MONO_STACK};font-size:.88em;color:var(--warn);white-space:nowrap}}

/* Status chips. Colour never upgrades a claim — see theme.STATUS_KIND. */
.chip{{
  display:inline-block;font-family:{SANS_STACK};font-weight:700;
  font-size:.7rem;letter-spacing:.02em;padding:.1em .45em;border-radius:2px;
  white-space:nowrap;vertical-align:.05em;
}}
{chips}

/* Epistemic caveats get a box a skimming reader cannot miss. */
.ot-caution,blockquote{{
  background:var(--warn-bg);border-left:2.5px solid var(--warn);
  padding:.7rem .95rem;margin:1rem 0;font-size:.95rem;
}}
blockquote{{color:#3b3b3b}}
.ot-caution-title{{
  display:block;font-family:{SANS_STACK};font-weight:700;font-size:.72rem;
  letter-spacing:.06em;text-transform:uppercase;color:var(--warn);margin-bottom:.3rem;
}}

/* booktabs-style tables: horizontal rules only. */
table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.94rem}}
th,td{{text-align:left;vertical-align:top;padding:.4rem .5rem}}
th{{
  font-family:{SANS_STACK};font-size:.78rem;font-weight:700;color:var(--accent);
  border-bottom:1px solid var(--accent);
}}
thead tr:first-child th{{border-top:1.2px solid #111}}
tbody tr:last-child td{{border-bottom:1.2px solid #111}}
tbody td{{border-bottom:.7px solid var(--rule)}}

ul,ol{{padding-left:1.4rem}}
li{{margin:.2rem 0}}
.ot-index{{font-size:.92rem;line-height:1.9}}
footer.ot-foot{{
  margin-top:3rem;padding-top:.6rem;border-top:.7px solid var(--rule);
  display:flex;justify-content:space-between;
  font-size:.8rem;font-style:italic;color:var(--muted);
}}
@media print{{body{{margin:0;max-width:none}}}}
"""
