#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Real-rootedness of the Durfee polynomials
#                              (Canfield–Corteel–Savage 1998)
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Polyhedral geometry and partition theory"
#         (ed. M. Olsen; AIM workshop Nov 7-11, 2016, org. Ardila, Braun,
#         Paule, Savage), Problem 1.2; http://aimpl.org/polypartition/1/
#         (http only). Origin: Canfield, Corteel, Savage, "Durfee polynomials",
#         Electron. J. Combin. 5 (1998) #R32 (not on arXiv).
# Status audit 2026-08-17 (independently counter-checked): OPEN. CCS proved
# asymptotic log-concavity in the central range and |mean - mode| <= 1/2+o(1),
# verified real-rootedness for n <= 1000, and left the general statement open;
# the 2016 AIM working group tried a coefficient recursion and Brenti's
# Eulerian-transformation route with no concrete result; the Rogers-Ramanujan
# relative (family Z) has a non-real root already at n = 75. Re-verified at
# creation (exact Sturm counts) for every n <= 800, twice, independently.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./durfee_real_roots.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
opentorus config set model.provider "${OPENTORUS_PROVIDER:-ollama}"
opentorus config set model.name "${OPENTORUS_MODEL:-gemma4:31b}"
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 2400
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted
opentorus config set campaign.branch_step_budget "${OPENTORUS_BRANCH_STEPS:-40}"
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact integer coefficients from the q-series DP; exact real-rootedness
# certificates via Sturm sequences (sympy) or interlacing checks; mpmath for
# high-precision root tracking.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy mpmath
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# The primary source (Canfield-Corteel-Savage, EJC 5 (1998) #R32,
# DOI 10.37236/1370) is journal-only and is cited in the notes; the arXiv
# entries below are the survey/toolkit and the paper that restates the
# conjecture.
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/0711.1400
opentorus paper fetch https://arxiv.org/abs/1410.6601
opentorus paper fetch https://arxiv.org/abs/1208.3831
opentorus paper fetch https://arxiv.org/abs/1411.0002

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Real-rootedness of the Durfee polynomials

**Primary target (general).** For every positive integer $n$, the Durfee polynomial
$$D_n(x) := \sum_{\lambda \vdash n} x^{D(\lambda)}, \qquad D(\lambda) = \text{side of the Durfee square of } \lambda,$$
has only real roots. (AIM polypartition Problem 1.2: "Prove or disprove that $D_n(x)$ has
all real roots." Equivalently $D_n(x) = \sum_{d \ge 1} P(n,d)\,x^d$ with
$P(n,d) = [q^{n-d^2}]\,1/(q;q)_d^2$, $\deg D_n = \lfloor\sqrt n\rfloor$, $D_n(0) = 0$
for $n \ge 1$, so the content is that $D_n(x)/x$ of degree $\lfloor\sqrt n\rfloor - 1$
has only real — in fact negative, simple — roots.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
Origin: Canfield–Corteel–Savage, *Durfee polynomials*, Electron. J. Combin. 5 (1998)
#R32 (DOI 10.37236/1370; journal-only): they report that for the family of ordinary
partitions and seven relatives (families (1)–(8)) "all roots are real and negative for
$n \le 1000$", state the conjecture for ordinary partitions, and write in §6 that it
"remains open ... whether the Durfee polynomial has all roots real"; the ninth family
$Z$ (partitions whose number of parts equals the Durfee side — Rogers–Ramanujan) has a
non-real root at $n = 75$, so real-rootedness is not a generic feature of Durfee-type
polynomials. What CCS *proved*: an asymptotic formula for $P(n,d)$; for every
$\varepsilon > 0$ and $n \ge n_0(\varepsilon)$, log-concavity $P(n,d)^2 > P(n,d-1)P(n,d+1)$
only in the central range $\varepsilon\sqrt n \le d \le (1-\varepsilon)\sqrt n$; mode
$m(n) \sim (\sqrt6\,\log 2/\pi)\sqrt n$; $|a(n) - m(n)| \le 1/2 + o(1)$ for the mean;
asymptotic normality. Canfield (Adv. Appl. Math. 34 (2005) 768–797) settled CCS's
asymptotic conjectures for the other families, not the roots. Boyer–Goh
([arXiv:0711.1400](https://arxiv.org/abs/0711.1400)) restate the conjecture (only negative
real zeros) and note that Erdős–Turán-type equidistribution does not apply because the
degree is only $\lfloor\sqrt n\rfloor$. The 2016 AIM working group tried a coefficient
recursion and Brenti's Eulerian-transformation theorem "with no concrete results" (AIM
workshop report; the group cited a computer check only up to $n = 50$). Ekhad–Zeilberger
([arXiv:1411.0002](https://arxiv.org/abs/1411.0002)) re-derive asymptotic normality
empirically. Modern real-rootedness toolkit (interlacing, compatible polynomials,
multiplier sequences): Brändén's survey ([arXiv:1410.6601](https://arxiv.org/abs/1410.6601);
no Durfee mention) and Savage–Visontai ([arXiv:1208.3831](https://arxiv.org/abs/1208.3831);
note their real-rooted "$D_n(x)$" is the type-D Eulerian polynomial, a different object).
No proof, refutation, or claim found 1998–2026 (arXiv, Semantic Scholar citations of
CCS, AIM report). Creation-time computation, run twice independently: $D_n(x)/x$ is
real-rooted, certified by exact Sturm counts, for every $1 \le n \le 800$; roots negative
and simple; the CCS $Z$-family failure at $n = 75$ reproduced as a control; the minimum
absolute root gap decays like $\sim C/n^2$ (0.0216, 0.0052, 0.0013, 0.0003 at
$n = 100, 200, 400, 800$) and the minimum relative gap $\Delta/|\text{root}|$ decays
slowly (0.65, 0.53, 0.41, 0.31) — no sign of coalescence, but also no evidence that it stays bounded away
from zero either.

**Known partial results (classified, with sources).**
- Asymptotic central log-concavity, mean/mode, normality (KNOWN_RESULT; CCS 1998,
  journal-only — cite by DOI, do not paraphrase beyond the audit above).
- Restatement of the conjecture; Erdős–Turán inapplicable (KNOWN_RESULT; Boyer–Goh,
  parsed source).
- Failed routes: coefficient recursion, Brenti transformation (FAILED_ATTEMPT layer;
  AIM 2016 report).
- Verification $n \le 1000$ (CCS) and $n \le 800$ (creation-time — recompute here, do not
  cite).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/durfee.py — (a) exact coefficients $P(n,d)$ for all $n \le N$ via
   the DP $P(n,d) = [q^{n-d^2}]\,1/(q;q)_d^2$ (or by inserting Durfee squares into pairs
   of partitions with parts $\le d$); check $\sum_d P(n,d) = p(n)$; (b) an exact
   real-rootedness certificate per $n$: Sturm count of $D_n(x)/x$ on $(-\infty, 0)$ equals
   the degree, or $\deg$ sign changes at exact rational points; (c) root gaps and the
   interlacing test between $D_n$ and $D_{n+1}$ (does $D_{n+1}$ interlace $D_n$? — record
   where it fails).
2. exp_new(title="Durfee polynomials: exact real-rootedness certificates n <= 400",
   command="python scripts/durfee.py --max 400", environment="python-sci",
   run_from="workspace") then exp_run — extend to 800/1200 as budget allows; record the
   gap statistics and any interlacing pattern.
3. Submit exact facts via proof_submit (sympy backend): "$D_{100}(x)/x$ has 9 distinct
   negative real roots" (Sturm), and the small closed forms ($D_n(x)$ for $n \le 8$ with
   explicit real roots). Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: one $n$ with a pair of non-real roots — a finite, exactly
certifiable object (Sturm count strictly below the degree). Territory: $n > 1000$ (below
that CCS and the creation-time run leave no room), the values of $n$ where the degree
jumps ($n = k^2$ and $n = k^2 - 1$, where the leading coefficient is 1 or small — the
"new root" enters near $-\infty$ or near $0$), and any $n$ where consecutive polynomials
stop interlacing; track root trajectories in $n$ at high precision (mpmath) and look for
gap collapse. A verified counterexample claim must name the primary claim in
depends_on.

**Proof track.** Look for a mechanism, not a computation: (i) interlacing
$D_n \preceq D_{n+1}$ or a recurrence in $n$ with a compatible-polynomials structure
(Brändén §7, Savage–Visontai method); (ii) a Pólya–Schur multiplier or a total-positivity
argument on the array $P(n,d)$; (iii) an Eulerian-type transformation of a known
real-rooted family. Every unresolved inference is an explicit [GAP-n]. Real-rootedness
implies log-concavity of $P(n,\cdot)$ for every $n$ — check whether *that* weaker
statement can be established first (CCS only have it asymptotically in the central
range).

**Instance program (tools, not targets).** Exact certificates for $n \le 400$–$1200$,
gap and interlacing statistics, root-trajectory tracking near degree jumps. Instances can
refute (one certified $n$ suffices); they can never prove the all-$n$ statement.

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
  --statement "For every positive integer n, the Durfee polynomial D_n(x) = sum over partitions lambda of n of x^{D(lambda)}, where D(lambda) is the side of the Durfee square of lambda, has only real roots."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 4)
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
