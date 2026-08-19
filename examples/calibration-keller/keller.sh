#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Keller's conjecture (resolved, per dimension)
#
# KNOWN ground truth (see README.md): fully resolved, with a dimension split
# the report must get exactly right. TRUE for n <= 6 (Perron 1940) and n = 7
# (Brakensiek-Heule-Mackey-Narvaez, IJCAR 2020 / JAR 2022 - SAT with
# certified DRAT proofs; end-to-end Lean 4 verification for all dimensions:
# ITP 2026). FALSE for n >= 8 (Mackey 2002: an explicit 256-clique in the
# Keller graph G_{8,2}; Lagarias-Shor 1992 for n >= 10). The verification
# target: reproduce Mackey's counterexample as an explicit clique and verify
# the clique property exactly (32,640 pairs) - a finite, certifiable check.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./keller.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set model.timeout_seconds 1200
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted

# --- 3. Numerical experiment environment ------------------------------------
# Keller-graph construction and exact clique verification (numpy/itertools),
# small-dimension max-clique sanity checks (networkx), SAT if wanted.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy networkx python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/1910.03740
opentorus paper add https://arxiv.org/abs/math/9210222
opentorus paper add https://arxiv.org/abs/1304.1639

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Keller's conjecture — determine the status per dimension and verify the dimension-8 counterexample

**Setup.** Keller conjectured (1930): in every tiling of $\mathbb{R}^n$ by translates of
the unit cube, some two cubes share a full $(n-1)$-dimensional face. The combinatorial
reformulation (Corrádi–Szabó 1990) runs through the Keller graphs: $G_{n,s}$ has vertex
set $\{0, \dots, 2s-1\}^n$, two vertices adjacent iff they differ in at least two
coordinates and differ by exactly $s$ in at least one coordinate; a clique of size $2^n$
yields a faceshare-free tiling of $\mathbb{R}^n$ (and refutes the conjecture there).

**Task for this dossier.** Determine the *per-dimension* status from the literature and
produce an honest status sketch — then verify the refutation side computationally:

1. **Status map.** Which dimensions are settled true, which false, by whom, and by what
   kind of proof (classical / explicit construction / SAT with certified proofs /
   formalized). Distinguish: the classical layer ($n \le 6$), the computer-assisted layer
   ($n = 7$ — SAT with DRAT certificates, later formally verified end to end), and the
   counterexample layer ($n \ge 8$: an explicit clique for $n = 8$ lifts to all higher
   dimensions; $n \ge 10$ had been settled earlier). Do NOT report a blanket
   "true"/"false" without the dimension split.
2. **Verify the dimension-8 counterexample.** Reproduce Mackey's 256-clique in
   $G_{8,2}$: obtain or reconstruct the 256 vertices (the construction is published; a
   machine-readable copy exists in the public Keller-encode repository), then verify
   EXACTLY that all $\binom{256}{2} = 32{,}640$ pairs are adjacent in $G_{8,2}$ (differ
   in $\ge 2$ coordinates; differ by exactly 2 in some coordinate) — a finite integer
   check, certifiable via proof_submit. This is the COUNTEREXAMPLE_VERIFIED pathway for
   the dimension-8 instance.
3. **Sanity layer.** Compute maximum cliques of small Keller graphs exactly
   ($\omega(G_{2,2}) = 2$, $\omega(G_{3,2}) = 5$ — both below $2^n$, consistent with
   truth in low dimensions); state honestly which computations were completed and which
   were not (e.g. $G_{4,2}$ may already be expensive).
4. **Honest scope.** Local checks verify the counterexample and the encodings; they do
   NOT re-establish the $n = 7$ truth (the published SAT proofs are hundreds of CPU
   hours and hundreds of GB of certificate — cite them as KNOWN_RESULTs with their
   verification pedigree, do not claim to have re-run them).

**Honesty requirements.** "Keller's conjecture is false" without a dimension qualifier
fails this dossier; so does attributing $n = 8$ to Lagarias–Shor (they settled
$n \ge 10$; Mackey settled 8 and 9), confusing the problem with Minkowski's lattice
conjecture (proved by Hajós 1941/42), or claiming the clique verification without an
actual recorded check of all pairs.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + verification run --------------------------------------------
opentorus --verbose prove "${TARGET}" --disprove --min-papers 3

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: per-dimension status map (true n <= 7: Perron + certified SAT;"
echo "false n >= 8: Mackey 256-clique, Lagarias-Shor n >= 10), the 256-clique verified"
echo "pairwise as an exact recorded check (COUNTEREXAMPLE_VERIFIED for the n = 8"
echo "instance), and no unqualified 'true'/'false' anywhere."
