#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The 3/4 density threshold for global
#                              synchronization (Kuramoto oscillators)
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: Randomstrasse101 open-problems blog (ETH Zurich), "Global
#         Synchronization (problems 3-5)", A. S. Bandeira, 2024-10-16;
#         https://randomstrasse101.math.ethz.ch/posts/global-synchronization/
#         Archived as arXiv:2504.20539 (Open Problems of 2024).
# Status audit 2026-08-17 (independently counter-checked): Conjecture 5 is
# OPEN. Upper half is a theorem: min degree >= 0.75(n-1) forces global
# synchrony (Kassabov-Strogatz-Townsend 2021, arXiv:2105.11406) and 0.75 is
# the limit of linear-stability arguments; lower half (dense graphs that do
# NOT synchronize) stands at mu_c > 0.6838 (Yoneda-Tatsukawa-Teramae 2021),
# after 0.6828 (Townsend-Stillman-Strogatz, arXiv:1906.10627). Neighbors:
# Conjecture 3 (random cubic graphs synchronize whp) OPEN, d >= 35 known
# (McRae 2025, arXiv:2503.18801, down from 600); Conjecture 4 (signed
# Kuramoto at the Z2-synchronization threshold) RESOLVED by McRae 2025.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./kuramoto_density_threshold.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Kuramoto energy landscapes: gradient flow / ODE (scipy), exact Hessian
# spectra of twisted states on circulant graphs (sympy), interval Newton
# certification (mpmath), graph handling (networkx).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy mpmath networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2105.11406
opentorus paper add https://arxiv.org/abs/1906.10627
opentorus paper add https://arxiv.org/abs/2503.18801
opentorus paper add https://arxiv.org/abs/2504.20539

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The 3/4 density threshold for global synchronization

**Primary target (general).** For every $\varepsilon > 0$ there exist $n$ and a graph $G$
on $n$ nodes with minimum degree at least $(\tfrac34 - \varepsilon)\,n$ that is **not**
globally synchronizing. Here a symmetric weight matrix $A$ (in particular a graph's
adjacency matrix) is *globally synchronizing* if the only local minima of the Kuramoto
energy
$$\mathcal{E}(\theta) = \tfrac12 \sum_{i,j} A_{ij}\bigl(1 - \cos(\theta_i - \theta_j)\bigr),
\qquad \theta \in [0, 2\pi)^n,$$
are the fully synchronized states $\theta_i \equiv c$. (Randomstrasse101 Conjecture 5;
equivalently: the critical connectivity $\mu_c$ — the least $\mu$ such that min degree
$\ge \mu(n-1)$ forces global synchrony — equals exactly $3/4$; the open half is the
lower bound.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
The upper half is a theorem: minimum degree $\ge 0.75(n-1)$ forces global synchrony
(Kassabov–Strogatz–Townsend, Chaos 31 (2021),
[arXiv:2105.11406](https://arxiv.org/abs/2105.11406)), who also explain why $0.75$ is
the best a purely linear-stability argument can give — the reason the threshold is
conjectured to be exactly $3/4$. The lower half — dense graphs that fail to synchronize —
stands at $\mu_c > 0.6838$ (Yoneda–Tatsukawa–Teramae 2021), after $0.6828$ by
Townsend–Stillman–Strogatz ([arXiv:1906.10627](https://arxiv.org/abs/1906.10627)),
whose circulant families with density $\to 0.75$ carry spurious *second-order critical
points* that are empirically unstable — degenerate, not strict minima, so they do NOT
witness non-synchrony under the definition above. McRae's 2025 Laplacian method
([arXiv:2503.18801](https://arxiv.org/abs/2503.18801), §3.4.3) re-derives $0.75$ and
states it cannot go below it. The gap $0.6838 < \mu_c \le 0.75$ stands. Neighbors from
the same post: Conjecture 3 (a uniform random 3-regular graph is globally synchronizing
whp) is **open** — random $d$-regular graphs are known to synchronize whp for
$d \ge 35$ (McRae 2025, §3.4.4, from his expander criterion Cor. 3.6 with $\alpha < 1/3$;
down from $d \ge 600$ in Abdalla–Bandeira–Kassabov–Souza–Strogatz–Townsend,
arXiv:2210.12788, Adv. Math. 2026), and $G(n,p)$ for
$p \ge (1+\varepsilon)\log n / n$; the random-graph *process* synchronizes at
connectivity (Jain–Mizgerd–Sawhney, arXiv:2501.12205). Conjecture 4 (signed Kuramoto
with $\pm1$ weights, bias $\delta \ge (1+\varepsilon)\sqrt{\log n/(2n)}$) was **resolved
positively** by McRae 2025 (Thm 3.2, $r = 2$, $p = 1$; McRae cites it as "Conj. 9" of
Bandeira's Oberwolfach 2024 problem list, where the cubic conjecture is "Conj. 8" — the blog
numbers them 4 and 3) — record it as a settled neighbor, minding the two $\delta$
conventions (factor 2). The $0.6838$ bound comes from integer programming over circulant
twisted states (YTT, arXiv:2104.05954, Chaos 31).

**Known partial results (classified, with sources).**
- $\mu_c \le 0.75$: KNOWN_RESULT (KST 2021, arXiv:2105.11406) — the upper half.
- $\mu_c > 0.6838$ (YTT 2021, arXiv:2104.05954), $> 0.6828$ (TSS, arXiv:1906.10627):
  KNOWN_RESULTs — certified dense non-synchronizing graphs.
- Random regular $d \ge 35$, $G(n,p)$ above connectivity: KNOWN_RESULTs (neighbors).
- Conjecture 4 resolved (McRae 2025): KNOWN_RESULT (neighbor; preprint status of the
  venue to be checked at run time).
- Complete algebraic classification of stable states for all networks on $\le 8$
  vertices (Harrington–Schenck–Stillman, arXiv:2312.16069) — a METHOD anchor.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/kuramoto_landscape.py — (a) the energy, gradient and Hessian of
   $\mathcal E$ for a given weight matrix; (b) circulant graphs $C_n(S)$ (connection set
   $S \subset \{1..\lfloor n/2\rfloor\}$) and their twisted states $\theta_j = 2\pi k j/n$
   — exact equilibria whose Hessian eigenvalues are explicit trigonometric sums
   $\lambda_m = \sum_{s \in S} \cos(2\pi k s/n)\,(1 - \cos(2\pi m s/n))$ (implement in
   sympy for exact rational/algebraic evaluation), and (c) a stability test: Hessian
   positive definite on the orthogonal complement of the rotation direction $\mathbf 1$.
2. exp_new(title="Kuramoto: twisted-state stability on circulant graphs",
   command="python scripts/kuramoto_landscape.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce a known dense non-synchronizing
   circulant family from the parsed papers (record its density and the certified
   stable twisted state), then sweep $n \le 60$ and connection sets by density,
   recording for each the highest density at which some twisted state is a STRICT
   local minimum.
3. Submit each certified instance via proof_submit (sympy backend): "the twisted state
   $k$ on $C_n(S)$ has Hessian eigenvalues $\lambda_1..\lambda_{n-1} > 0$ (exact values),
   so $C_n(S)$ with minimum degree $2|S| = \mu(n-1)$ is not globally synchronizing".
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track (of the conjecture) is the hard direction here:** refuting means
proving every graph of density $\ge (3/4-\varepsilon)n$ synchronizes for some
$\varepsilon > 0$ — a global landscape theorem, not a finite check. Record honestly that
no finite computation can do this.

**Constructive track (the conjecture's own direction).** Each certified dense
non-synchronizing graph is a first-class result: (a) circulant twisted states with exact
Hessian certificates; (b) beyond circulants — lifts/blow-ups of small graphs, the
YTT/TSS constructions and local search over dense graphs maximizing the stability margin
of the best spurious equilibrium, with general equilibria certified by interval Newton
(mpmath) plus interval Hessian bounds; (c) for $n \le 10$, exhaustive enumeration of
dense graphs with algebraic equilibrium classification. A certified graph with minimum
degree above $0.6838\,(n-1)$ that is not globally synchronizing is a NEW LOWER BOUND on
$\mu_c$ — genuine progress, though not a resolution (that needs a family approaching
$3/4$). Any candidate must be exactly re-verified and certified via proof_submit; a
verified-construction claim must name the primary claim in depends_on.

**Instance program (tools, not targets).** Twisted-state stability tables over
circulant graphs, density-vs-stability frontiers, exhaustive small-$n$ classification,
and the second-order-vs-strict-minimum distinction made explicit on the TSS near-0.75
examples. Instances can push the lower bound; only a $\to 3/4$ family with proof
resolves the campaign.

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
  --statement "For every epsilon > 0 there exist n and a graph on n nodes with minimum degree at least (3/4 - epsilon) n whose Kuramoto energy has a local minimum that is not a fully synchronized state (i.e. the graph is not globally synchronizing)."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 8. Honest report, verdict, PDF ------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
