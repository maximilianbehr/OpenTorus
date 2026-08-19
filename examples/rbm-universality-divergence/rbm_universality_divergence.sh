#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Two small restricted Boltzmann machines:
#                     is RBM_{4,3} a universal approximator, and what is
#                     the maximum divergence of RBM_{3,1}?
# Fixed-instance dossier (two specific models), NOT a campaign: there is no
# quantified general conjecture, so no primary-claim designation and no
# `problem verdict` gate; the deliverable is a status sketch with the parts
# labelled honestly and any exact fact machine-checked.
# Source: AIM Problem List "Boltzmann machines" (ed. T. Merkh; AIM workshop
#         Sept 2018), Problems 1.1 [G. Montufar] and 1.2;
#         http://aimpl.org/boltzmann/1/ (http only).
# Status audit 2026-08-17 (independently counter-checked): both OPEN.
# 1.1: the minimal universal hidden size for n = 4 satisfies 3 <= m <= 6
# (m = 6 from Montufar-Rauh; the page's "m >= 7" is the older Montufar-Ay
# bound); RBM_{4,3} has the expected dimension 15 (Montufar-Morton), and the
# page says simulations SUGGEST it fills the simplex - but exact maximum-
# likelihood fits at creation found "soft parity" targets that stall at a
# positive residual (about 0.077 bits at a = 0.8), i.e. numerical evidence
# AGAINST fullness. 1.2: D_{3,1} <= 1 bit (Montufar-Rauh-Ay); Montufar's 2018
# review conjectures -(3/4)log2(2sqrt3-3) ~ 0.8306 bits, attained at the
# uniform distribution on the even-parity strings {000,011,101,110} - the
# value was reproduced at creation to seven digits, and no larger value was
# found; a proof needs an exact projection plus a global bound.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./rbm_universality_divergence.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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

# --- 3. Numerical experiment environment ------------------------------------
# Exact 16-state (resp. 8-state) marginals, damped Newton / L-BFGS maximum-
# likelihood fits with many restarts, convex projections onto log-linear
# pieces, sympy for exact algebra of the conjectured value.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy mpmath
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/1806.07066
opentorus paper add https://arxiv.org/abs/1709.05276
opentorus paper add https://arxiv.org/abs/1406.3140
opentorus paper add https://arxiv.org/abs/1508.03606
opentorus paper add https://arxiv.org/abs/1305.0539

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Two small restricted Boltzmann machines — universality of $RBM_{4,3}$ and the maximum divergence of $RBM_{3,1}$

**Setting.** $RBM_{n,m}$ is the set of visible marginals of the pairwise binary model
on the complete bipartite graph $K_{n,m}$:
$q(v) \propto \exp(b\cdot v)\prod_{j=1}^m\bigl(1 + \exp(c_j + w_j\cdot v)\bigr)$,
$v \in \{0,1\}^n$; a subset of the simplex $\Delta_{2^n-1}$. $RBM_{n,1}$ equals the mixture
of two product distributions $\mathcal M_{n,2}$. Divergences are Kullback–Leibler in
**bits** ($\log_2$).

**Part 1 (AIM boltzmann Problem 1.1 [G. Montúfar], verbatim).** "Does the closure of
$RBM_{4,3}$ fill the simplex $\Delta_{15}$, making it a universal approximator?" Remark
on the page: universality needs $m \ge 3$ hidden units and holds for $m \ge 7$;
"simulations have suggested that $RBM_{4,3}$ fills the simplex."

**Part 2 (Problem 1.2, no named proposer, verbatim).** "Determine the maximum divergence
of $RBM_{3,1}$", $\mathcal D_{RBM_{3,1}} := \sup_{p \in \Delta_7}\inf_{q \in RBM_{3,1}}
D(p\,\|\,q)$.

Both parts are **fixed instances** — a specific model each — not quantified
conjectures; this dossier is a status sketch with machine-checked exact facts, not a
campaign.

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **both
open**; no 2019–2026 paper resolves either. Part 1: for $n = 4$ the minimal universal
$m$ satisfies $3 \le m \le 6$ — the upper bound from Montúfar–Rauh
([arXiv:1508.03606](https://arxiv.org/abs/1508.03606), Example 18: $RBM_{4,6}$ is
universal), so the page's "$m \ge 7$" (Montúfar–Ay, arXiv:1005.1593,
$m \ge 2^{n-1} - 1$) is outdated; $RBM_{4,3}$ has the expected dimension $15$
(Cueto–Morton–Sturmfels, arXiv:0908.4425; binary RBMs always have the expected dimension,
Montúfar–Morton, arXiv:1511.03570), so fullness is a question about the closure, not the
dimension; the 2018 AIM workshop report notes that $RBM_{4,3}$ attains every distribution
supported on the eight even-parity vertices (Montúfar's thesis) and planned an "eight
vertices plus one extra vertex" test; Montúfar's review ([arXiv:1806.07066](https://arxiv.org/abs/1806.07066))
says $RBM_{4,3}$ "might be the full simplex". Part 2: the general bound
$\mathcal D_{RBM_{n,m}} \le n - \lfloor\log_2(m+1)\rfloor - (m+1)/2^{\lfloor\log_2(m+1)\rfloor}$
(Montúfar–Rauh–Ay, [arXiv:1406.3140](https://arxiv.org/abs/1406.3140)) gives
$\mathcal D_{3,1} \le 1$ bit; the review's open problem 10 states "the first open case
is $\mathcal D_{3,1}$" and reports, from discussions with J. Rauh, the conjectured value
$-\tfrac34\log_2(2\sqrt3 - 3) \approx 0.8306$ bits. Adjacent solved cases:
$\mathcal D_{3,0} = 2$ bits; $\mathcal D_{3,2} = 1/2$ bit with the parity distributions as
maximisers, and $RBM_{3,2} = \mathcal M_{3,3}$ semialgebraically (Seigal–Montúfar,
[arXiv:1709.05276](https://arxiv.org/abs/1709.05276)); $RBM_{3,3}$ is full;
$RBM_{3,1} = \mathcal M_{3,2}$ is described exactly by Allman–Rhodes–Sturmfels–Zwiernik
([arXiv:1305.0539](https://arxiv.org/abs/1305.0539); nonnegative rank $\le 2$ =
supermodular **and** all flattenings of rank $\le 2$ — the rank condition is automatic
only for $n = 3$) — on the interior of $\Delta_7$ a union of four log-linear polyhedra
cut out by six binomial inequalities each. Creation-time computations, run twice independently: (i) the
uniform distribution on $\{000, 011, 101, 110\}$ projects onto $RBM_{3,1}$ at KL
$= 0.8306155$ bits $= -\tfrac34\log_2(2\sqrt3-3)$ to seven digits (projection ratios
$\sqrt3$ and $2+\sqrt3$), and gradient ascent from many random starts plus hundreds of
perturbations found no larger value (interior optima $\le 0.814$; the counter-audit's
apparent $0.8396$ from a hill-climb was an under-converged inner minimisation — thorough
inner fits of the same $p$ give $0.809$–$0.810$); (ii) exact
maximum-likelihood fits of $RBM_{4,3}$ (19 parameters, 128-state joint; optimizer
validated on $RBM_{3,2}$, which reproduces $0.5000$ bits on even parity, and on
$RBM_{3,3}$, which is full) fit parity targets, parity-plus-one-odd-vertex targets, and
generic Dirichlet targets to $10^{-11}$–$10^{-16}$ bits, **but the soft-parity targets**
$p_a = (1 + a(-1)^{|v|})/16$ **stall at a positive residual** — about $0.016$ bits at
$a = 0.3$, $0.041$ at $0.5$, $0.077$ at $0.8$, $0.015$ at $0.99$ — with parameters
that **diverge** (the minimiser is a closure point: $|\theta|_\infty$ grows from $\approx 90$
to several hundred as the iteration budget grows), identically across L-BFGS (150
restarts), damped Newton, continuation from the exact parity solution, differential
evolution, and — in the counter-audit — a second implementation with analytic
gradients (120 restarts, scales 0.1–30: $0.0770676$ at $a = 0.8$, $0.0418614$ at
$a = 0.5$, and $10^{-14}$ for hard parity $a = 1$) plus a bounded mixture-space
parametrisation that stalls too. That is **numerical evidence against fullness**,
contradicting the page's remark — but it is not a proof, and mind the direction: the
numerics certify only $\inf_q D(p_{0.8}\|q) \le 0.0771$ bits; the *lower* bound
$\mathcal D_{4,3} \ge 0.077$ would need global optimality of the inner fit, which is
unproven (a stall can be an optimizer artefact near a boundary point; parity is on the
boundary of the model, so residuals near it decay slowly).

**Known partial results (classified, with sources).**
- $3 \le m_{\min}(4) \le 6$; $\dim RBM_{4,3} = 15$; $\mathcal D_{3,1} \le 1$;
  $\mathcal D_{3,2} = 1/2$; $RBM_{3,1} = \mathcal M_{3,2}$ with its exact inequalities
  (KNOWN_RESULTs; parsed sources).
- The conjectured value of $\mathcal D_{3,1}$ (CONJECTURE; review, open problem 10 —
  never a theorem).
- The creation-time numerics (recompute here; they are evidence, not results).

**Research objectives.**
1. Part 2: (a) verify exactly, via proof_submit (sympy backend), that the KL projection
   of $u = \mathrm{Unif}\{000, 011, 101, 110\}$ onto $\mathcal M_{3,2}$ has value
   $-\tfrac34\log_2(2\sqrt3-3)$ — the candidate optimum has algebraic structure
   ($\sqrt3$), so an exact certificate of the *inner* infimum is plausible (KKT
   conditions on the relevant log-linear polyhedron); (b) attack the *outer* supremum:
   use the four-polyhedra description to bound $\inf_q D(p\|q)$ from above for every
   $p$ (a piecewise argument, or a symmetry reduction — the maximiser candidate is
   invariant under the parity-preserving symmetries); (c) run a global search over
   $\Delta_7$ (many restarts, symmetric and asymmetric starts) and record the best value
   found. Only ACCEPTED submissions are machine-checked; a value found numerically is
   `NUMERICAL_EVIDENCE`.
2. Part 1: (a) reproduce the fits — validate the optimizer on $RBM_{3,2}$ (must give
   exactly $0.5$ bit on even parity) and on in-model targets (must reach $\approx 0$);
   then fit $p_{0.8}$ and $p_{0.5}$ with $\ge 100$ restarts including large-scale
   initialisations and continuation from the exact parity solution; (b) if the stall
   persists, try to turn it into an obstruction: which inequality does $p_{0.8}$ violate
   as $|\theta| \to \infty$ (tropical / limit analysis of the model near the parity
   boundary; the closure of $RBM_{4,3}$ contains the limits of the parity solutions —
   characterise them); (c) if a fit succeeds, record the parameters as an explicit
   approximation family and check it exactly.
3. Keep the two parts apart: a resolution of one is not evidence for the other.

**Compute budget.** Fits are cheap (milliseconds each) — run thousands, not tens; pass
`timeout` explicitly to `exp_run` for the long global searches (e.g. 3600 s) and print
progress.

**Claim policy.** Every conclusion is exactly one of: verified construction /
machine-checked theorem / exhaustive certified result / numerical or computational
evidence / conjecture / failed attempt. Numerical stalls and numerically found suprema
are evidence; the conjectured value of $\mathcal D_{3,1}$ stays a conjecture until the
inner projection is certified *and* the outer supremum is bounded.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Run --------------------------------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 4

# --- 7. Honest report, PDF ---------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
