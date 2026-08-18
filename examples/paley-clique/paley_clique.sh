#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The clique number of Paley graphs
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: Randomstrasse101 open-problems blog (ETH Zurich), "On the clique
#         number of the Paley Graph (problems 25-29)", A. S. Bandeira,
#         2025-12-15; https://randomstrasse101.math.ethz.ch/posts/PaleyGraph/
#         Archived as arXiv:2603.29571 (Open Problems of 2025).
# Status audit 2026-08-17 (independently counter-checked): Conjecture 25
# (omega(G_p) = O(polylog p)) is OPEN. Best upper bound sqrt(p/2)+1
# (Hanson-Petridis, arXiv:1905.09134); trivial sqrt(p) via the Lovasz theta
# function; lower bound only logarithmic. The blog's tools - localizations
# G_{p,1} (circulant, theta is an LP), G_{p,2} (SDP), degree-4 SoS
# (Kunisky-Yu arXiv:2211.02713: relaxation value >= Omega(p^{1/3})) - give
# per-p CERTIFIED clique bounds, which is where a run can make real progress.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./paley_clique.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
opentorus config set model.provider ollama
opentorus config set model.name "${OPENTORUS_MODEL:-gemma4:31b}"
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 2400
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact clique numbers (networkx / python-sat), LP for circulant theta
# (scipy HiGHS, exact rational re-check via sympy), SDP for 2-localizations
# and SoS (cvxpy + SCS/Clarabel).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy networkx python-sat cvxpy clarabel
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2303.16475
opentorus paper add https://arxiv.org/abs/1905.09134
opentorus paper add https://arxiv.org/abs/2211.02713
opentorus paper add https://arxiv.org/abs/1907.05971

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The clique number of Paley graphs

**Primary target (general).** For every prime $p \equiv 1 \pmod 4$ let $G_p$ be the
Paley graph on $\mathbb{Z}/p$ ($i \sim j$ iff $i - j$ is a nonzero quadratic residue; it
is $(p-1)/2$-regular and self-complementary, so $\omega(G_p) = \alpha(G_p)$). Then
$$\omega(G_p) = O(\mathrm{polylog}\,p).$$
(Randomstrasse101 Conjecture 25. Motivation: a random graph of the same density has
clique number $\approx 2\log_2 p$; Paley graphs are the canonical "pseudorandom" family
where every proof technique so far stalls at $\sqrt p$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
Upper bounds: $\omega(G_p) \le \sqrt p$ (spectral / Lovász $\vartheta(\overline{G_p}) =
\sqrt p$ exactly); the only improvement is Hanson–Petridis,
$\omega(G_p) \le \sqrt{p/2} + 1$
([arXiv:1905.09134](https://arxiv.org/abs/1905.09134), Proc. LMS 2021). Lower bounds are
only logarithmic: $\omega(G_p) \ge (\tfrac12 + o(1))\log_2 p$ for all $p$ (Ramsey/Cohen), and
$\ge c\log p\,\log\log\log p$ for infinitely many $p$ (Graham–Ringrose 1990; $\log p\log\log p$
under GRH, Montgomery) — an exponential gap. Survey and the "road map" of localizations:
Kunisky ([arXiv:2303.16475](https://arxiv.org/abs/2303.16475), Exp. Math. 34 (2025), online
2024). The blog's
instance tools, all still open as conjectures: (26) the 1-localization $G_{p,1}$
(neighbors of 0; circulant, so $\vartheta$ is a linear program —
Magsino–Mixon–Parshall, [arXiv:1907.05971](https://arxiv.org/abs/1907.05971)) has
$\vartheta(\overline{G_{p,1}}) \sim \sqrt{p/2}$, which would recover Hanson–Petridis;
(27) the 2-localization $G_{p,2}$ (common neighbors of 0 and 1; $(p-5)/4$ vertices, no
longer circulant) has $\vartheta(\overline{G_{p,2}}) \le \tfrac23\sqrt p$ for large $p$
(Kunisky observed $\omega(G_{p,2}) \sim (\sqrt{1/2} - \epsilon)\sqrt p$ empirically);
(28) degree-4 sum-of-squares certifies $O(p^{1/2-\epsilon})$ for some $\epsilon > 0$ —
Kunisky–Yu ([arXiv:2211.02713](https://arxiv.org/abs/2211.02713), CCC 2023) prove the
degree-4 value is at least $\Omega(p^{1/3})$ (a *lower* bound on the relaxation, so the
exponent can improve to at best $1/3$), with encouraging block-diagonal numerics
(Kobzar–Mody, arXiv:2304.08615); (29) the Paley ETF has RIP beyond the square-root
bottleneck (arXiv:1202.1234; conditional in arXiv:1410.6457) — connected to (25) in both
directions (Satake, arXiv:2011.02907, whose hypothesis is the character-sum form of the
Paley graph conjecture), neither direction unconditional. Related recent tools: the
exact-subgraph hierarchy stays at $\vartheta$ up to a threshold level for Paley stable sets
(Gaar–Pucher, arXiv:2412.12958). No 2025–2026 improvement of the $\sqrt{p/2}$ bound for
prime $p$ was found (Yip 2025 extends Hanson–Petridis to non-square prime powers).

**Known partial results (classified, with sources).**
- $\vartheta(\overline{G_p}) = \sqrt p$ exactly; Hanson–Petridis $\sqrt{p/2} + 1$
  (KNOWN_RESULTs; cite parsed sources; the bound is $\sqrt{p/2}+1$, not $\sqrt p/2$).
- Kunisky–Yu: degree-4 SoS $\ge \Omega(p^{1/3})$ (KNOWN_RESULT — a limitation).
- Conjectures 26–29: CONJECTURE layer, each with its empirical basis in the parsed papers.
- Exact $\omega(G_p)$ tables for small $p$ (classical computations; recompute, don't cite
  from memory).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/paley_tools.py — (a) $G_p$ and its localizations $G_{p,1}$,
   $G_{p,2}$ as explicit graphs; (b) exact clique number via a clique solver or SAT
   (exploit vertex-transitivity: $\omega(G_p) = 1 + \omega(G_{p,1})$); (c) $\vartheta$
   of the circulant $G_{p,1}$ as the frequency-domain LP over the $(p-1)/2$ Fourier
   coefficients (scipy HiGHS), with an exact rational re-check of the dual certificate
   (sympy Fractions on the cosine LP) so that $\lfloor\vartheta\rfloor + 1$ is a
   certified upper bound on $\omega(G_p)$.
2. exp_new(title="Paley: exact clique numbers and certified localization bounds",
   command="python scripts/paley_tools.py", environment="python-sci",
   run_from="workspace") then exp_run — exact $\omega(G_p)$ for all $p \equiv 1 \ (4)$
   up to the largest $p$ your budget allows (record the bound reached), and
   $\vartheta(\overline{G_{p,1}})/\sqrt{p/2}$ for $p$ up to $10^4$; tabulate against
   $\log p$, $\log^2 p$, $\sqrt p$.
3. Submit exact facts via proof_submit (sympy backend): "$\omega(G_{p}) = k$ for this p
   (clique listed; maximality by exhaustive search)"; "$\omega(G_p) \le
   \lfloor\vartheta(\overline{G_{p,1}})\rfloor + 1$ for this p (rational dual certificate)".
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: $\omega(G_p)$ grows faster than every polylog along some
sequence of primes. A single prime never refutes; a certified *family* would. Search:
exact $\omega(G_p)$ growth statistics, structure of maximum cliques (are they arithmetic
progressions / subfields-like?), record primes with unusually large cliques. Honest
scope: evidence only.

**Proof track (where certified progress is possible).** (a) The 2-localization SDP:
compute $\vartheta(\overline{G_{p,2}})$ for $p$ up to a few thousand and test the $2/3$
constant; any $p$ with $\lfloor\vartheta(\overline{G_{p,2}})\rfloor + 2 <
\lfloor\sqrt{p/2}\rfloor + 1$ is a certified improvement of the Hanson–Petridis bound at
that $p$ (dual certificate in exact arithmetic) — a real, if modest, deliverable.
(b) Degree-4 SoS with the affine-group symmetry reduction ($x \mapsto ax+b$, $a$ a QR)
for $p$ up to a few hundred; fit $\log(\mathrm{SoS}_4)/\log p$ against $1/2$ and $1/3$.
(c) Test the sharper MMP claim that Schrijver's $\vartheta'$ on $G_{p,1}$ beats
Hanson–Petridis infinitely often. Every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact clique numbers, LP/SDP localization
values with exact duals, SoS exponent fits. Instances certify per-$p$ bounds; they can
never prove the polylog statement (asymptotic) — and only a certified family refutes it.

**Claim policy.** Every conclusion is exactly one of: verified construction /
machine-checked theorem / exhaustive certified result / computational or numerical
evidence / conjecture / failed attempt. The campaign verdict is derived by
`opentorus problem verdict`; only GENERAL_CONJECTURE_PROVED or
GENERAL_CONJECTURE_REFUTED resolve the campaign.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Deterministic primary-claim designation ------------------------------
opentorus problem claim "${TARGET}" --type CONJECTURE \
  --statement "For every prime p congruent to 1 mod 4, the clique number of the Paley graph G_p is O(polylog p); i.e. there is a constant c such that omega(G_p) <= (log p)^c for all sufficiently large such p."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 5)
# The campaign engine replaces the single prove session: a portfolio of branches
# (proof, counterexample, literature, formalization, ...) against the designated
# primary claim, scheduled and budgeted, pausable and resumable, replayable. The
# budget below bounds the run; every axis can be overridden from the environment.
# A finished campaign is orchestration state -- the mathematical status still comes
# from `opentorus problem verdict` (derived from accepted dossier artifacts only).
opentorus --verbose campaign start "${TARGET}" --mode prove-or-refute \
  --branches "${OPENTORUS_BRANCHES:-4}" \
  --max-steps "${OPENTORUS_MAX_STEPS:-200}" \
  --max-wall-seconds "${OPENTORUS_MAX_WALL_SECONDS:-0}"
CAMPAIGN="$(opentorus campaign list --problem "${TARGET}" --json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["campaign_id"])')"
opentorus campaign status "${CAMPAIGN}"
opentorus campaign tree "${CAMPAIGN}"
opentorus campaign verify "${CAMPAIGN}"   # replay the event log against the snapshot

# --- 8. Honest report, verdict, PDF ------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
