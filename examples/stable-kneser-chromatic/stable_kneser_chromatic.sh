#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Meunier's conjecture on s-stable Kneser graphs
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Albertson conjecture and related problems"
#         (ed. J. Zeng; AIM workshop Oct 14-18, 2024), Section 8, Problem 8.1
#         [Shira Zerbib]; http://aimpl.org/albertson/8/ (http only). The
#         conjecture is Meunier's (JCTA 118 (2011)).
# Status audit 2026-08-17 (independently counter-checked): OPEN in general,
# partially resolved: s = 1 (Lovasz), s = 2 (Schrijver), all even s (Chen,
# JGT 2015), k = 2 (Daneshpajouh-Meunier-Mizrahi, arXiv:2003.08255), large n
# for s >= 4 (Jonsson 2012, unpublished), and - NEW, July 2026 - s = 3 with
# k = 3 for all n and with k >= 4 for n >= k^3 + 3k^2 (Chen-Parker-Zerbib,
# arXiv:2607.12912). Remaining: odd s >= 3, k >= 4, sk+1 < n below the
# large-n thresholds. Every instance is a finite chromatic-number computation
# (SAT); creation-time SAT runs confirmed eleven open (s=3) instances.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./stable_kneser_chromatic.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Graph construction (networkx), exact chromatic numbers by SAT with proof
# logging (python-sat / CaDiCaL), symmetry breaking on the cyclic action.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy networkx python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2607.12912
opentorus paper fetch https://arxiv.org/abs/2003.08255
opentorus paper fetch https://arxiv.org/abs/1904.08219
opentorus paper fetch https://arxiv.org/abs/1711.06621

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Meunier's conjecture on the chromatic number of s-stable Kneser graphs

**Primary target (general).** For integers $s, k \ge 1$ and $n \ge sk$, the $s$-stable
Kneser graph $KG_s(n,k)$ has as vertices the $k$-subsets $K \subseteq [n]$ whose elements
are pairwise at cyclic distance at least $s$ ($s \le |i - j| \le n - s$ for all
$i \ne j \in K$), two vertices adjacent iff the sets are disjoint. **Conjecture** (Meunier
2011; AIM albertson Problem 8.1): for every $s, k$ and every $n > sk$,
$$\chi(KG_s(n,k)) = n - sk + s.$$
(The upper bound is trivial — colour $A$ by $\min\{\min A,\ n-sk+s\}$; the content is the
lower bound. $s = 1$ is Lovász's theorem, $s = 2$ Schrijver's; $n = sk$ is trivially true.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open in
general, partially resolved, no refutation.** Proved: $s = 2$, all $n \ge 2k$ (Schrijver
1978); $n = sk+1$ (Meunier 2011); every even $s \ge 4$, all $n \ge sk$ (Chen, J. Graph
Theory 79 (2015) — journal-only); $s \ge 4$ and $n \ge 2s(k-1)+2$ (Jonsson 2012,
unpublished manuscript, no longer online); $k = 2$ for all $s \ge 2$, $n \ge 2s$
(Daneshpajouh–Meunier–Mizrahi, [arXiv:2003.08255](https://arxiv.org/abs/2003.08255),
JGT 2021); the off-by-one bound $\chi(KG_3(n,k)) \ge n - 3k + 2$ for $n \ge 3k$
(Daneshpajouh–Osztényi, [arXiv:1904.08219](https://arxiv.org/abs/1904.08219), Cor. 10); and, new
in July 2026, $s = 3$: $k = 3$ for all $n \ge 9$, and $k \ge 4$ for $n \ge k^3 + 3k^2$
(Chen–Parker–Zerbib, [arXiv:2607.12912](https://arxiv.org/abs/2607.12912) — a preprint;
label it). **Remaining open:** odd $s \ge 3$, $k \ge 4$, $sk + 1 < n$ below the large-$n$
thresholds ($k^3 + 3k^2$ for $s = 3$; $2s(k-1)+2$ for odd $s \ge 5$). Neighbors: the
almost-$s$-stable variant is fully solved (Chen, [arXiv:1711.06621](https://arxiv.org/abs/1711.06621):
$n - s(k-1)$); the $r$-uniform hypergraph version (Frick, arXiv:1710.09434) had its
$r$-stable conjecture refuted for $r \ge 3$ (Daneshpajouh, arXiv:2203.03019) — the graph
case is untouched by that refutation. Meunier's arXiv v1 (0912.4748) does not contain the
conjecture; cite the JCTA version. Creation-time SAT computation (CaDiCaL, clique-fixed
symmetry breaking; recompute, do not cite): all agree with $n - 3k + 3$ — theorem-covered
$KG_3(n,2)$, $n = 7..12$ and $KG_3(n,3)$, $n = 10..14$; OPEN cases $KG_3(14,4) = 5$,
$(15,4) = 6$, $(16,4) = 7$, $(17,5) = 5$, $(18,5) = 6$, $(20,6) = 5$, $(21,6) = 6$,
$(23,7) = 5$, $(24,7) = 6$, $(26,8) = 5$, $(29,9) = 5$ (each under 10 s; independently
re-run at creation), plus $KG_3(19,5) = 7$ (266 vertices, 183 s in the re-run);
$KG_3(17,4)$ (238 vertices, target 6) did not finish in 15 min with a naive encoding.
$|V(KG_s(n,k))| = \frac{n}{k}\binom{n - sk + k - 1}{k-1}$ ($= \frac nk\binom{n-2k-1}{k-1}$ for $s=3$).

**Known partial results (classified, with sources).**
- Lovász, Schrijver, Chen (even $s$), DMM ($k=2$), Meunier ($n = sk+1$) (KNOWN_RESULTs;
  journal-only ones marked, not reconstructed).
- Jonsson large-$n$ (KNOWN_RESULT with the caveat: unpublished, offline).
- Chen–Parker–Zerbib $s = 3$ results (KNOWN_RESULT from a July 2026 preprint — label).
- Daneshpajouh–Osztényi off-by-one bound (KNOWN_RESULT).
- SAT-verified open instances (recompute here; each is an exact finite theorem for that
  instance once the UNSAT side is certified).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/stable_kneser.py — (a) build $KG_s(n,k)$ (networkx), (b) exact
   $\chi$ by SAT: encode "$c$-colourable" (vertex-colour variables, edge constraints,
   symmetry breaking by fixing colours on a maximum clique / using the cyclic
   $\mathbb{Z}_n$ action), solve for $c = n - sk + s - 1$ (expect UNSAT — log a DRAT
   proof) and $c = n - sk + s$ (expect SAT — output the colouring), (c) an independent
   colouring verifier.
2. exp_new(title="s-stable Kneser: SAT chromatic numbers for open s=3 instances",
   command="python scripts/stable_kneser.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce the eleven open $s = 3$ instances above
   with certificates, then push: $KG_3(17,4)$ (better encoding / symmetry breaking),
   $KG_3(22,6)$, $KG_3(20,5)$, and the smallest open $s = 5$ cases ($k \ge 4$, $n$ just
   above $5k+1$).
3. Submit exact facts via proof_submit (sympy backend for the colouring verifications):
   "$\chi(KG_3(15,4)) = 6$: this explicit 6-colouring is proper (verified), and the
   5-colouring instance is UNSAT (DRAT certificate checked)". Only ACCEPTED submissions
   are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: an $(n - sk + s - 1)$-colouring of some $KG_s(n,k)$ with
$n > sk$ — an exact, hand-checkable certificate. Territory: odd $s \ge 3$, $k \ge 4$, $n$
between $sk + 2$ and the thresholds; SAT-guided search for colourings just below the
conjectured value, exploiting the cyclic symmetry (try $\mathbb{Z}_n$-invariant
colourings first, then general). A verified counterexample claim must name the primary
claim in depends_on.

**Proof track.** Reproduce the topological lower-bound machinery from the parsed papers
at the level of the neighbourhood complex / box complex for small instances (compute
connectivity numerically where feasible); test the Chen–Parker–Zerbib reduction lemma on
instances; identify why odd $s$ resists the even-$s$ argument; every unresolved inference
is an explicit [GAP-n].

**Instance program (tools, not targets).** Certified chromatic numbers for open
instances, encoding improvements to reach larger $(n,k)$, $\mathbb{Z}_n$-invariant
colouring searches. Instances can refute (one certified colouring suffices); they can
never prove the all-$(s,k,n)$ statement.

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
  --statement "For every s >= 1, every k >= 1 and every n > sk, the chromatic number of the s-stable Kneser graph KG_s(n,k) equals n - sk + s."
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
