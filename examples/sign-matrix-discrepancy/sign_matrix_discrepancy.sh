#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — How many deviations? Discrepancy of +-1 matrices
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: Randomstrasse101 open-problems blog (ETH Zurich), "Did just a
#         couple of deviations suffice all along? (problems 10-14)",
#         A. S. Bandeira, 2024-12-19;
#         https://randomstrasse101.math.ethz.ch/posts/HowManyDeviations/
#         Archived as arXiv:2504.20539 (Open Problems of 2024, with Updates).
# Status audit 2026-08-17 (independently counter-checked): Conjecture 12 -
# limsup_n sup_{A in {+-1}^{nxn}} disc(A)/sqrt(n) > 1 - is OPEN, as is Open
# Problem 11 (the exact value of the sup; Spencer's 6 is the classical upper
# bound). Small cases computed exactly at creation: max disc over +-1 n x n
# matrices is 2,1,2,3,4 for n=2..6 (ratio 4/sqrt6 ~ 1.633 at n=6, already
# above the sqrt2 of the 2x2 example). Neighbor Conjecture 13 (Sylvester
# Hadamard, odd k) is REFUTED for all odd k >= 9 via Boolean nonlinearity -
# see calibration-sylvester-discrepancy; the Updates note stresses this does
# not rule out the H_k family for Conjecture 12.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./sign_matrix_discrepancy.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exhaustive sign minima (numpy), SAT/CP for "every sign vector has a large
# row" (python-sat, OR-Tools), fast Walsh-Hadamard transforms for Hadamard
# families, exact integer certificates (sympy).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy python-sat ortools
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2504.20539
opentorus paper fetch https://arxiv.org/abs/0808.0684
opentorus paper fetch https://arxiv.org/abs/2111.02974

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: How many deviations? The discrepancy of ±1 matrices

**Primary target (general).** For a $\pm1$ matrix $A$ let
$\mathrm{disc}(A) = \min_{x \in \{\pm1\}^n} \lVert Ax\rVert_\infty$. **Conjecture 12
(Randomstrasse101):** for every $c > 1$ close enough to 1 — precisely,
$$\limsup_{n\to\infty}\ \sup_{A \in \{\pm1\}^{n\times n}} \frac{\mathrm{disc}(A)}{\sqrt n} \;>\; 1,$$
i.e. there is an infinite family of $n \times n$ sign matrices whose discrepancy exceeds
$\sqrt n$ by a fixed factor. (Companion Open Problem 11: the exact value of
$\sup_n \sup_A \mathrm{disc}(A)/\sqrt n$ — Spencer's "six standard deviations" theorem gives
$\le 6$, since improved in constant; the $2\times2$ matrix $[[1,1],[1,-1]]$ gives $\sqrt2$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**
(both 11 and 12), unchanged in the March 2026 archive. Facts established at creation, by
exhaustive computation re-run independently: the maximum of $\mathrm{disc}(A)$ over all
$\pm1$ $n \times n$ matrices is $2, 1, 2, 3, 4$ for $n = 2, \dots, 6$; the $6\times6$ matrix
$$A_6 = \begin{bmatrix} 1&1&1&1&1&1\\ 1&-1&1&1&-1&-1\\ 1&1&-1&-1&1&-1\\ 1&1&-1&-1&-1&1\\ 1&-1&1&-1&1&1\\ 1&-1&-1&1&1&1\end{bmatrix}$$
has $\mathrm{disc} = 4$, ratio $4/\sqrt6 \approx 1.633$ (all 64 sign vectors checked) —
above the $\sqrt2$ of the classical $2\times2$ example (the post also mentions an unpublished
numerical construction of Spielman's slightly above $\sqrt2$). Structural anchor: Hadamard
matrices satisfy $\mathrm{disc}(H) \ge \sqrt n$ (since $\lVert Hx\rVert_2 = n$), with
equality for Sylvester $H_k$ at even $k$; for odd $k$ the identity
$\mathrm{disc}(H_k) = 2^k - 2\rho(\mathrm{RM}(1,k))$ ($\rho$ = covering radius of the
first-order Reed–Muller code = maximum nonlinearity of $k$-variable Boolean functions) ties
the question to a classical coding-theory problem: ratio $>1$ for all odd $k$ (bent bound
unattainable in odd dimension), $\sqrt2$ for $k \le 7$, and strictly less for every odd
$k \ge 9$ (Kavut–Maitra–Yücel 2007; Kavut–Yücel, [arXiv:0808.0684](https://arxiv.org/abs/0808.0684):
nonlinearity 242 at $k = 9$ gives $\mathrm{disc}(H_9) \le 28$; Patterson–Wiedemann 1983 at
$k = 15$: $\le 216$). Whether $\mathrm{disc}(H_k)/\sqrt{2^k}$ stays bounded away from 1 along
odd $k$ is exactly the open question of whether odd-variable nonlinearity approaches the bent
bound $2^{k-1} - 2^{k/2-1}$ asymptotically — the Updates of arXiv:2504.20539 note that the
refutation of Conjecture 13 "does not rule out that the $H_k$ family can be used to
establish Conjecture 12". Neighbor: the Komlós conjecture (Problem 10; see the
komlos-conjecture example — best lower bound $K \ge 1+\sqrt2$, Kunisky arXiv:2111.02974).

**Known partial results (classified, with sources).**
- Spencer 1985 upper bound $6\sqrt n$ (KNOWN_RESULT; journal-only, mark metadata).
- Exact small cases $n \le 6$ and $A_6$ (KNOWN_RESULT — recompute in this workspace and
  certify; do not cite from memory).
- Hadamard $\ge \sqrt n$; the Reed–Muller identity; nonlinearity records for
  $k = 9, 11, 13, 15$ (KNOWN_RESULTs; parsed sources / marked journal-only).
- Conjecture 13 refuted for odd $k \ge 9$ (KNOWN_RESULT via the parsed Updates + the
  reproducible Walsh–Hadamard certificate).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/sign_disc.py — (a) exact disc(A) by enumerating $2^{n-1}$ sign
   vectors (integer matvecs; symmetry $x \mapsto -x$); (b) exhaustive max over $\pm1$
   $n\times n$ matrices with first row/column normalized to $+1$ for $n \le 5$, and a
   local search / SAT-guided search for $n = 6..10$ ("every sign vector has some row with
   $|\langle a_i, x\rangle| \ge t$", parity: $\lVert Ax\rVert_\infty \equiv n \pmod 2$, so
   the targets are $t = 5$ at $n = 7$, $6$ at $n = 8$, $7$ at $n = 9$); (c) the fast
   Walsh–Hadamard transform for $H_k$ with $\mathrm{disc}(H_k)$ for $k \le 5$ exactly and
   the Kavut–Yücel $k = 9$ certificate.
2. exp_new(title="Sign-matrix discrepancy: exact records for small n",
   command="python scripts/sign_disc.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce $2,1,2,3,4$ for $n = 2..6$ and $A_6$;
   record the best ratio found for $n = 7..10$ with the search budget used; tabulate
   $\mathrm{disc}(H_k)/\sqrt{2^k}$ for $k \le 9$.
3. Submit exact facts via proof_submit (sympy backend): "$\mathrm{disc}(A_6) = 4$ (all 64
   sign vectors listed with their $\lVert A_6 x\rVert_\infty$)"; "$\lVert H_9 x\rVert_\infty = 28$
   for this explicit $x$"; exhaustive statements for $n \le 5$. Only ACCEPTED submissions
   are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: $\sup_A \mathrm{disc}(A)/\sqrt n \to 1$ — a theorem about
all sign matrices, not a finite check; record that no computation refutes.

**Constructive track (the conjecture's own direction).** A proof needs an infinite family
with ratio $\ge 1+\delta$: (a) mine the exact small-$n$ record matrices for structure
(are the $n = 5, 6$ optima Hadamard-like, circulant, conference-type?), (b) structured
families — circulant $\pm1$ matrices (disc via cyclic convolution), Paley/conference
matrices, tensor products (how does disc behave under $\otimes$? the $x^\natural$
construction shows sub-multiplicativity in one direction), (c) the Reed–Muller route:
disc$(H_k)/\sqrt{2^k}$ along odd $k$ from the nonlinearity literature. Every reported
value exactly re-verified; a verified-construction claim (an infinite family with proof)
must name the primary claim in depends_on — a table of records is evidence, not a family.

**Instance program (tools, not targets).** Exact records for $n \le 6$, searched records
for $n \le 10$–$12$, disc of structured families, the $H_k$/nonlinearity table.
Instances can never prove a limsup statement; a certified infinite family with a proof
would.

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
  --statement "There is a constant delta > 0 such that for infinitely many n there exists an n x n matrix A with entries +-1 whose discrepancy min over sign vectors x of the max-norm of Ax is at least (1 + delta) sqrt(n); i.e. limsup_n sup_A disc(A)/sqrt(n) > 1."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 3)
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
