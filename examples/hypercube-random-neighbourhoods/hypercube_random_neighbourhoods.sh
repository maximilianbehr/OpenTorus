#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Lovett's hypercube set system: discrepancy of
#                              random neighbourhood subsets
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Hereditary discrepancy and factorization norms"
#         (ed. S. Garg; AIM workshop Feb 29-Mar 4, 2016, org. Nikolov,
#         Talwar), Problem 1.25 [Shachar Lovett];
#         http://aimpl.org/hereddiscrep/1/ (http only).
# Status audit 2026-08-17 (independently counter-checked): OPEN. The page asks
# "What is the discrepancy?"; no paper treats this system. The bracket at
# audit time is Theta~(sqrt n): O~(sqrt n) follows from the 2025 Bansal-Jiang
# Beck-Fiala bound (this system sits exactly at the logarithmic-sparsity
# boundary, k = n = log_2 N, that Altschuler-Tikhomirov 2026 do NOT cover),
# and Omega(sqrt n) w.h.p. from a first-moment + Littlewood-Offord argument
# derived (and independently re-checked) at creation, not found in the
# literature. Exact SAT discrepancies for n <= 9 were computed at creation,
# twice, independently. Whether the polylog gap closes - disc = Theta(sqrt n)
# - is the campaign target.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./hypercube_random_neighbourhoods.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set tools.verifiers.smt "${OPENTORUS_SMT:-false}"   # z3 on PATH: set OPENTORUS_SMT=true to let the formalizer use it
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted
opentorus config set campaign.branch_step_budget "${OPENTORUS_BRANCH_STEPS:-40}"
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact discrepancy of sampled systems via SAT with cardinality constraints
# (python-sat / CaDiCaL: disc <= D iff satisfiable), brute force for n <= 4,
# numpy for heuristic colourings at larger n.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2508.03961
opentorus paper fetch https://arxiv.org/abs/1511.00583
opentorus paper fetch https://arxiv.org/abs/2102.07342
opentorus paper fetch https://arxiv.org/abs/1907.04117
opentorus paper fetch https://arxiv.org/abs/2508.01937

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Lovett's hypercube set system — discrepancy of random neighbourhood subsets

**Primary target (general).** For every $n$, let the elements be the vertices of the
hypercube $\{0,1\}^n$ and, for each vertex $v$, let $S_v$ be a uniformly random subset of
the $n$ neighbours of $v$, independently over $v$. Then, with high probability, the
discrepancy $\mathrm{disc} = \min_{\chi : \{0,1\}^n \to \{\pm1\}} \max_v
\bigl|\sum_{u \in S_v} \chi(u)\bigr|$ satisfies
$$c\sqrt n \;\le\; \mathrm{disc} \;\le\; C\sqrt n$$
for universal constants $0 < c \le C$ — i.e. the answer to AIM hereddiscrep Problem 1.25
("What is the discrepancy of this set system?") is $\Theta(\sqrt n)$ with **no**
polylogarithmic factor. (The page does not fix $p = 1/2$ or independence; the reading
above is the natural one and must be stated as an interpretation. Verbatim: "Given a set
system where the elements are the vertices of the hypercube $\{0,1\}^n$. Corresponding to
each vertex $v$, there is a set $S_v$ which is generated by picking a random subset of the
neighbours of $v$ in the hypercube. What is the discrepancy of this set system?" Remark
on the page: with $S_v$ = the *full* neighbourhood, colouring by the parity of the first
$n/2$ bits gives discrepancy $\le 1$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**
— no paper treats this specific system (2016–2026). What general theory gives: $N = 2^n$
elements, $N$ sets, $|S_v| \sim \mathrm{Bin}(n, 1/2)$, each element in $\sim n/2$ sets,
max degree $k \le n = \log_2 N$. **Upper bound** $\tilde O(\sqrt n)$: Bansal–Jiang
([arXiv:2508.03961](https://arxiv.org/abs/2508.03961), Thm 1.4: Beck–Fiala
$\tilde O(\sqrt k + \sqrt{\log N})$ for all $k$, $\tilde O$ hiding $\mathrm{poly}(\log\log N)
= \mathrm{poly}(\log n)$; the intermediate FOCS 2025 step is
[arXiv:2508.01937](https://arxiv.org/abs/2508.01937)); the older tools give only $O(n)$
(Beck–Fiala $2k - 1$; Banaszczyk $\sqrt{k \log N} = n$; random colouring). Altschuler–
Tikhomirov (arXiv:2607.14238, Jul 2026) prove Beck–Fiala for $k \ge (\log N)^{1+o(1)}$ —
this system sits *exactly* at the logarithmic-sparsity boundary they do not cover, which is
why the polylog gap is genuinely open. **Lower bound** $\Omega(\sqrt n)$ w.h.p. — a
creation-time derivation, independently re-checked, **not found in the literature**: fix
$\chi$; the sums over the $S_v$ are independent across $v$ (disjoint randomness) and each
is a sum of $n$ independent $\{0, \pm1\}$ variables, so by Littlewood–Offord its largest
atom is $\le \binom{n}{\lfloor n/2\rfloor}/2^n \le \sqrt{2/(\pi n)}$; hence
$\Pr[\mathrm{disc} \le D] \le \bigl[2(2D+1)\sqrt{2/(\pi n)}\bigr]^{2^n}$ by a union bound
over the $2^{2^n}$ colourings, and $\mathrm{disc} > D$ w.h.p. whenever
$D < (\sqrt{\pi n/8} - 1)/2 \approx 0.31\sqrt n$ (so $\ge 2$ for $n \ge 23$, $\ge 3$ for
$n \ge 64$). Same idea as MacRury–Masařík–Pai–Pérez-Giménez
([arXiv:2102.07342](https://arxiv.org/abs/2102.07342)) for edge-independent random
hypergraphs, whose theorem does not literally cover this structured model. **Random
incidence models that do not apply verbatim** (do not cite them as applying): Ezra–Lovett
([arXiv:1511.00583](https://arxiv.org/abs/1511.00583); $O(\sqrt{t \log t})$ for $m \ge n$),
Bansal–Meka (arXiv:1810.03374; $O(\sqrt t)$ for $t = \Omega((\log\log m)^2)$), Potukuchi
(arXiv:1811.01491; [arXiv:1907.04117](https://arxiv.org/abs/1907.04117), spectral
$O(\sqrt t + \lambda)$ — useless here since $\lambda \approx n/2$ from the cube adjacency),
Hoberg–Rothvoss (arXiv:1806.04484; disc $\le 1$ needs $N \gg m \log m$, here $m = N$),
Altschuler–Niles-Weed (arXiv:2101.04036). Survey: Bansal–Nikolov monograph
(arXiv:2608.00140). Creation-time computation, run twice independently (exact SAT,
$p = 1/2$, independent $S_v$; brute force agrees for $n \le 4$): sampled discrepancies are
$1$ or $2$ for $n = 3, \dots, 8$ (e.g. $n = 7$: $174\times 1$, $26\times 2$ of $200$
samples; $n = 3$: one sample with disc $0$), skewing to $2$ at $n = 9$ ($N = 512$:
$5\times 1$, $25\times 2$ of $30$); $n = 10$ ($N = 1024$) did not finish in 16 min per
instance. Small-$n$ values say nothing about the asymptotics.

**Known partial results (classified, with sources).**
- $\tilde O(\sqrt n)$ upper bound (KNOWN_RESULT; Bansal–Jiang, parsed source — state
  the $\mathrm{poly}(\log\log N)$ loss).
- $\Omega(\sqrt n)$ lower bound (creation-time derivation — **re-derive and proof_submit
  it here**; it is a candidate machine-checked lemma, not a citation).
- Full-neighbourhood version disc $\le 1$ (KNOWN_RESULT; the aimpl remark — prove it, it
  is one line).
- Random-hypergraph theorems (KNOWN_RESULTs; related, hypotheses do not match).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/hcube.py — (a) sample the system for given $n$, $p$, seed;
   (b) exact discrepancy: SAT with cardinality constraints per set ("disc $\le D$" iff
   satisfiable; bisection over $D$), brute force for $n \le 4$; (c) heuristic colourings
   (random restarts + local search, parity-based colourings) for $n = 10$–$16$ to
   upper-bound disc; (d) output colourings as certificates and verify them.
2. exp_new(title="Hypercube random neighbourhoods: exact discrepancy n <= 9",
   command="python scripts/hcube.py --exact --max-n 9 --samples 30",
   environment="python-sci", run_from="workspace") then exp_run — reproduce the
   $\{1, 2\}$ pattern; then heuristic upper bounds for $n = 10$–$16$ and the ratio
   $\mathrm{disc}/\sqrt n$.
3. Submit exact facts via proof_submit (sympy backend): the Littlewood–Offord atom
   bound $\binom{n}{\lfloor n/2\rfloor}/2^n \le \sqrt{2/(\pi n)}$ for $n \ge 1$; the
   union-bound inequality $\Pr[\mathrm{disc} \le D] \le [2(2D+1)\sqrt{2/(\pi n)}]^{2^n}$;
   the full-neighbourhood parity colouring. Only ACCEPTED submissions are
   machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: either the discrepancy is $o(\sqrt n)$ w.h.p. (impossible
given the lower bound, if it is verified — check the derivation first) or it is
$\omega(\sqrt n)$ w.h.p. — a genuine possibility at the logarithmic-sparsity boundary,
where Beck–Fiala itself is open. Territory: track $\mathrm{disc}/\sqrt n$ across
$n = 6$–$16$ with exact and heuristic values; test whether structured colourings (parity
of bit subsets, Hadamard-type) beat random ones; compare with the same statistics for a
fully random $k$-sparse system on $2^n$ elements. Instances cannot decide an asymptotic
statement; they can expose a drift.

**Proof track.** (i) Verify and tighten the lower bound (the union bound is crude — the
constant $0.31$ can likely be raised, and the same argument bounds the *hereditary*
discrepancy). (ii) For the upper bound, exploit the structure the general Beck–Fiala
proof ignores: the incidence matrix is a random sparsification of the cube adjacency
$A_n$; try a partial-colouring / Lovett–Meka walk with the cube's Fourier basis, or a
decoupling over the $n$ directions (each direction $i$ contributes an independent random
matching); the parity colouring kills the full-neighbourhood system exactly — measure
how much of the sparsified system it kills. Every unresolved inference is an explicit
[GAP-n].

**Instance program (tools, not targets).** Exact discrepancies for $n \le 9$–$10$,
heuristic bounds to $n \approx 16$, colouring-family comparisons, constant tracking.
Instances can neither prove nor refute an asymptotic statement.

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
  --statement "For every n, with high probability over the random hypercube set system in which each vertex v of {0,1}^n gets a set S_v drawn as a uniformly random subset of the n neighbours of v (independently over v), the discrepancy of the system is at least c*sqrt(n) and at most C*sqrt(n) for universal constants 0 < c <= C."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 5)
# The campaign engine replaces the single prove session: a portfolio of branches
# (proof, counterexample, literature, formalization, ...) against the designated
# primary claim, scheduled and budgeted, pausable and resumable, replayable. The
# budget below bounds the run; every axis can be overridden from the environment.
# A finished campaign is orchestration state -- the mathematical status still comes
# from `opentorus problem verdict` (derived from accepted dossier artifacts only).
# Stress/coverage runs may adjust the workspace (budgets, profiles, backends) before the start.
[ -n "${OPENTORUS_PRESTART_HOOK:-}" ] && source "$OPENTORUS_PRESTART_HOOK"
opentorus --verbose campaign start "${TARGET}" --mode "${OPENTORUS_MODE:-prove-or-refute}" \
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
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
