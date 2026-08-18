#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Erdős–Straus conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): OPEN. Verified for
# all n <= 10^17 (Salez 2014, arXiv:1406.6307); a 2025 preprint claims 10^18
# (arXiv:2509.00128, unrefereed; erdosproblems.com has adopted the bound).
# A Feb 2026 claimed full proof (arXiv:2602.11774) is publicly doubted and
# unaccepted. Reduces to primes; polynomial identities
# cover every primitive residue class mod 840 except the six square classes
# 1, 121, 169, 289, 361, 529 (Mordell / Yamamoto / Rosati), and Schinzel's
# obstruction shows no finite identity system can ever cover n == 1 (mod q)
# (Elsholtz-Tao, arXiv:1107.1010). Exceptions have density zero (Vaughan 1970).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./erdos_straus.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set campaign.branch_step_budget "${OPENTORUS_BRANCH_STEPS:-40}"
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact integer arithmetic (sympy) for residue-class identities and CRT
# coverage; fast exhaustive solvers over ranges of n; z3 for bounded searches.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy gmpy2 z3-solver
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/1107.1010
opentorus paper add https://arxiv.org/abs/1406.6307
opentorus paper add https://arxiv.org/abs/2511.16817

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Erdős–Straus conjecture

**Primary target (general).** For every integer $n \ge 2$ there exist positive integers
$x, y, z$ with
$$\frac{4}{n} = \frac{1}{x} + \frac{1}{y} + \frac{1}{z}.$$
(Erdős–Straus, 1948. For $n \ge 3$ the three denominators can be taken distinct; $n = 2$
needs a repeated denominator.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
No accepted proof. A February 2026 preprint claims a full proof
([arXiv:2602.11774](https://arxiv.org/abs/2602.11774)) but is publicly doubted (the
covering system is challenged on the erdosproblems.com forum) and unaccepted — record it
as a claimed proof under dispute. The other 2024–2026 arXiv preprints are partial,
heuristic, or conditional. Erdős Problem #242 lists the conjecture open. Verified
computationally for all $n \le 10^{17}$ (Salez 2014,
[arXiv:1406.6307](https://arxiv.org/abs/1406.6307)); a 2025 preprint claims $10^{18}$
([arXiv:2509.00128](https://arxiv.org/abs/2509.00128), unrefereed, though
erdosproblems.com has adopted the bound — keep the label "claimed").
Structural picture: it suffices to prove the conjecture for primes; polynomial identities
in $n$ settle every primitive residue class mod $840$ except the six *square* classes
$n \equiv 1, 121, 169, 289, 361, 529 \pmod{840}$ (Mordell, after Yamamoto and Rosati;
the smallest prime in an uncovered class is $1009$), and the Schinzel/Yamamoto
obstruction (derived in Elsholtz–Tao from their Prop. 1.6) shows that a class
$n \equiv r^2 \pmod q$ — in particular $n \equiv 1 \pmod q$ — can never be covered by a
polynomial identity, so no finite system of identities can finish the proof (Elsholtz–Tao,
[arXiv:1107.1010](https://arxiv.org/abs/1107.1010), which also bounds the number of
solutions: $N\log^2 N \ll \sum_{p \le N} f(p) \ll N \log^2 N \log\log N$). The set of
exceptions has density zero (Vaughan 1970). For the generalization $m/n$, Schinzel *conjectured* solvability
for all $n \ge n_0(m)$; Pomerance–Weingartner
([arXiv:2511.16817](https://arxiv.org/abs/2511.16817)) show that any such threshold, if
it exists, is at least $\exp(m^{1/3+o(1)})$.

**Known partial results (classified, with sources).**
- Reduction to primes: a solution for $n$ yields one for every multiple of $n$
  (KNOWN_RESULT; classical).
- Residue-class identities: every primitive class mod 840 except the six square classes
  (KNOWN_RESULT; Mordell/Yamamoto/Rosati — cite the parsed source, not memory).
- Schinzel/Yamamoto obstruction: no polynomial identity covers a class
  $n \equiv r^2 \pmod q$ (KNOWN_RESULT; derived in Elsholtz–Tao arXiv:1107.1010).
- Density-zero exceptions (Vaughan); solution-count asymptotics (Elsholtz–Tao).
- Computational verification $n \le 10^{17}$ (Salez, arXiv:1406.6307) — a KNOWN_RESULT with
  an explicit bound; the $10^{18}$ claim stays "claimed, unrefereed".

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/erdos_straus.py — (a) an exact solver that, for a given $n$, finds
   $x \le y \le z$ with $4/n = 1/x + 1/y + 1/z$ by bounded search (integers only, no
   floats), and (b) a residue-class identity checker: for a polynomial family
   $(x(n), y(n), z(n))$ and a class $n \equiv r \pmod q$, verify the identity
   symbolically with sympy Rationals.
2. exp_new(title="Erdős–Straus: exhaustive range + residue coverage",
   command="python scripts/erdos_straus.py", environment="python-sci",
   run_from="workspace") then exp_run — every prime $n \le 10^5$ solved (record the bound
   you actually reached), plus the CRT coverage of the classes mod 840 by the identities
   you verified.
3. Submit each verified polynomial identity as a certificate via proof_submit (sympy
   backend): "for all $n \equiv r \pmod q$, $4/n = 1/x(n) + 1/y(n) + 1/z(n)$ with the
   three values positive integers". Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a single integer $n$ (necessarily a
prime in one of the six square classes mod 840, and $> 10^{17}$) with no representation.
For a FIXED $n$ non-existence is a finite check (bounded search over $x \le y \le z$ with
$x \le 3n/4$), so any candidate is a certificate. Generators: primes $p \equiv 1 \pmod{840}$
and the other square classes; primes with few solutions $f(p)$ (mine the Elsholtz–Tao
heuristics for where $f(p)$ is smallest). A verified counterexample claim must name the
primary claim in depends_on. Realistically the search cannot reach new territory; record
what it did reach.

**Proof track.** Reproduce the residue-class identity system and certify its coverage of
$\mathbb{Z}/840$ minus the square classes via proof_submit; formalize the Schinzel
obstruction on the parsed source (why $n \equiv 1 \pmod q$ resists identities); test
candidate identities of higher modulus against the square classes and record why each
fails; assemble the dependency graph; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exhaustive solving over ranges, certified
identities and their CRT union, $f(p)$ statistics for primes in the six hard classes.
Instances can refute (one certified $n$ suffices); they can never prove the
universally quantified statement.

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
  --statement "For every integer n >= 2 there exist positive integers x, y, z with 4/n = 1/x + 1/y + 1/z."
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
