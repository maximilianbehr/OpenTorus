#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Kannan–Lovász–Simonovits (KLS) conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: Randomstrasse101 open-problems blog (ETH Zurich), "The KLS
#         Conjecture (problem 30)", A. Roedder, 2025-12-18;
#         https://randomstrasse101.math.ethz.ch/posts/KLSConjecture/
#         Archived as arXiv:2603.29571 (Open Problems of 2025).
# Status audit 2026-08-17 (independently counter-checked): KLS is OPEN, but
# two of its famous consequences are now THEOREMS with universal constants -
# Bourgain's slicing problem (Klartag-Lehec, arXiv:2412.15044, Dec 2024, via
# Guan arXiv:2412.09075; independently Bizeul arXiv:2501.06854) and the thin
# shell conjecture (Klartag-Lehec, arXiv:2507.15495). Best KLS bound in the
# literature: psi_n >= c (log n)^{-1/2} (Klartag 2023, arXiv:2303.14938). Two
# concurrent July-2026 preprints, both AI-assisted (GPT-5.6 Pro; chat logs /
# disclosure sections) - Chen-Klartag arXiv:2607.23307 (sharp thin-shell
# variance, third-moment tensor bound) and Letwin arXiv:2607.24164 - CLAIM
# the improvement to (log n)^{-1/4}; a 13-Aug-2026 preprint by E. Milman
# (arXiv:2608.13052) already cites it as known. Unrefereed.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./kls_conjecture.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact polynomial moments on polytopes (sympy rationals), rational
# generalized eigenproblems for Poincaré lower bounds, MCMC/Cheeger-cut
# numerics (numpy/scipy) for smooth bodies.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy mpmath
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2303.14938
opentorus paper fetch https://arxiv.org/abs/2412.15044
opentorus paper fetch https://arxiv.org/abs/2507.15495
opentorus paper fetch https://arxiv.org/abs/1807.03465
opentorus paper fetch https://arxiv.org/abs/2607.23307

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Kannan–Lovász–Simonovits (KLS) conjecture

**Primary target (general).** For a probability measure $\mu$ on $\mathbb{R}^n$ let
$\psi_\mu = \inf_S \mu^+(S)/\min\{\mu(S), \mu(S^c)\}$ be its Cheeger (isoperimetric)
constant, where $\mu^+(S) = \lim_{\varepsilon\to0}(\mu(S + \varepsilon B_n) - \mu(S))/\varepsilon$.
**KLS conjecture (1995).** There exists a universal constant $C > 0$ such that for every
log-concave probability measure $\mu$ on $\mathbb{R}^n$, for every $n$,
$$\psi_\mu \;\ge\; C \cdot \inf_{H \text{ halfspace}} \frac{\mu^+(H)}{\min\{\mu(H), \mu(H^c)\}}
\;\;\Big(\text{equivalently } \psi_\mu \ge C/\sqrt{\lVert \mathrm{Cov}(\mu)\rVert_{op}}\Big),$$
i.e. halfspaces are within a constant of the worst cuts; equivalently
$\psi_n := \inf\{\psi_\mu : \mu \text{ isotropic log-concave on } \mathbb{R}^n\}$ is bounded
below by a universal constant, equivalently a universal Poincaré constant for isotropic
log-concave measures. (Randomstrasse101 Conjecture 30.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**
— but its neighborhood changed decisively in 2024–2025 and a fresh claim appeared in July
2026. Lower-bound ladder for $\psi_n$: $n^{-1/2}$ (KLS 1995, localization),
$n^{-1/3}\log^{-1/2} n$ (Eldan 2013, stochastic localization), $n^{-1/4}$ (Lee–Vempala 2017,
[arXiv:1807.03465](https://arxiv.org/abs/1807.03465) survey),
$\exp(-\sqrt{\log n \log\log n})$ (Chen 2021), and $c(\log n)^{-1/2}$ (Klartag 2023,
[arXiv:2303.14938](https://arxiv.org/abs/2303.14938)) — the best established bound.
Two consequences are now theorems with universal constants: **Bourgain's slicing
problem** (Klartag–Lehec, [arXiv:2412.15044](https://arxiv.org/abs/2412.15044), Dec 2024,
using Guan's bound arXiv:2412.09075; independent second proof Bizeul arXiv:2501.06854) and
the **thin shell conjecture** $\mathbb E(\lVert X\rVert - \sqrt n)^2 \le C$
(Klartag–Lehec, [arXiv:2507.15495](https://arxiv.org/abs/2507.15495)); Eldan's 2013
stochastic localization gives KLS up to $\log n$ from thin shell alone (Thm 1.1) and up to
$\sqrt{\log n}$ with a third-moment-tensor bound (Prop. 1.7); the current $\sqrt{\log n}$
record is Klartag's 2023 route. **Claim (July 2026, unrefereed, AI-assisted):** two
concurrent preprints — Chen–Klartag, *Digesting the proof of the sharp thin-shell
inequality* ([arXiv:2607.23307](https://arxiv.org/abs/2607.23307), 25 Jul; sharp
$\mathrm{Var}|X|^2 \le 8n$ and a dimension-free bound on the third-moment tensor; the
abstract states the proof was found by GPT-5.6 Pro, chat log attached) and Letwin
([arXiv:2607.24164](https://arxiv.org/abs/2607.24164), 27 Jul; single author, AI-disclosure
section; sharp $\mathrm{Var}\langle MX, X\rangle \le 2\,\mathbb E|\nabla\langle MX,X\rangle|^2$) —
yield, via Klartag's improved Lichnerowicz inequality, $\psi_n \ge c(\log n)^{-1/4}$ (in
the reciprocal convention "the KLS constant is $O(\log^{1/4} n)$"). A 13-Aug-2026 preprint
by E. Milman (arXiv:2608.13052) already cites the $\log^{-1/4}$ bound as known, crediting
Chen–Klartag's tensor bound as recorded by Letwin — the first third-party expert citation,
still not a refereed confirmation.
Convention warning: the post's $\psi_n$ is the Cheeger constant (want a lower bound); many
papers use its reciprocal (want an upper bound); $\psi_\mu \ge C/\sqrt{\lVert A\rVert_{op}}$,
not $C/\lVert A\rVert_{op}$.

**Known partial results (classified, with sources).**
- The $\psi_n$ ladder above (KNOWN_RESULTs; journal-only entries marked; the Klartag 2023
  bound from the parsed source).
- Slicing and thin shell: KNOWN_RESULTs (theorems, universal constants) — neighbors, not
  the target; do not describe them as "up to polylog" (that was 2022–23). Bizeul's slicing
  proof is an alternative route that also uses Guan's bound.
- Eldan's thin-shell ⇒ KLS-up-to-$\log n$ (and $\sqrt{\log n}$ with the tensor bound)
  (KNOWN_RESULT).
- The July 2026 $(\log n)^{-1/4}$ preprints (Chen–Klartag; Letwin): CLAIMED — never
  KNOWN_RESULT until refereed or independently confirmed; note Letwin's own remark that his
  Lichnerowicz step is "not the final bound Klartag uses" (a soft spot to track).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/poincare_polytopes.py — for explicit isotropic convex bodies with
   exact rational moments (simplex, cube, cross-polytope, small products; all polynomial
   moments are exact rationals via sympy integration over the body), compute the best
   Poincaré-quotient lower bound
   $\min_f \mathbb E|\nabla f|^2 / \mathrm{Var} f$ over polynomials $f$ of degree $\le k$
   ($k = 1..4$): a generalized eigenproblem with rational entries — an EXACT lower bound on
   $C_P(K)$, i.e. an exact upper bound on $\psi_K$ (via Cheeger–Buser, state which
   direction is rigorous), per body; also the exact value of $\mathrm{Var}|X|^2/n$ per body
   against the claimed sharp constant 8.
2. exp_new(title="KLS: exact polynomial Poincaré bounds on isotropic polytopes",
   command="python scripts/poincare_polytopes.py", environment="python-sci",
   run_from="workspace") then exp_run — tabulate the bounds for $n = 2..8$ and degrees
   $k = 1..4$; separately test the July-2026 preprint's degree-4 inequality
   $\mathrm{Var}\langle MX,X\rangle \le 2\,\mathbb E|\nabla\langle MX,X\rangle|^2$ EXACTLY on each
   body for a batch of rational symmetric $M$ (a violation would be an exact refutation of
   the preprint; no violation is only support).
3. Submit exact facts via proof_submit (sympy backend): "for the isotropic n-cube and
   this rational M, Var⟨MX,X⟩ = a, 2E|∇⟨MX,X⟩|² = b, a ≤ b" (exact rationals); "the
   degree-2 polynomial Poincaré bound of the isotropic simplex in R^3 equals q". Only
   ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a family of isotropic log-concave measures with
$\psi \to 0$. Bodies with the worst known Cheeger constants (candidates from the parsed
literature — e.g. products/cones considered in the survey) as exact-moment instances;
polynomial test functions give certified UPPER bounds on $\psi$ per body; a family whose
certified bound decays would be strong evidence — but no finite family proves
$\psi_n \to 0$. Every reported value is exact. A verified counterexample claim must name
the primary claim in depends_on (and would need a proof for the family, not a table).

**Proof track.** Reproduce the reduction chain (thin shell ⇒ KLS up to $\sqrt{\log n}$;
KLS ⇒ thin shell ⇒ slicing) from the parsed papers as a dependency graph with the
established/claimed labels; test the July-2026 inequality exactly on the instance zoo;
identify precisely which step turns $\sqrt{\log n}$ into a constant and why the localization
methods stop there; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact polynomial Poincaré bounds on small
polytopes, exact checks of moment inequalities, MCMC Cheeger-cut heuristics on smooth
bodies (numerical only). Instances certify per-body facts; they can never prove the
universal statement, and only a proven family refutes it.

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
  --statement "There exists a universal constant C > 0 such that for every n and every isotropic log-concave probability measure on R^n, the Cheeger isoperimetric constant is at least C (equivalently, a universal Poincare constant holds for all isotropic log-concave measures)."
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
