# OpenTorus examples

Real, runnable end-to-end workflows on actual open problems. Each example is a
driver script that sets up a fresh `.opentorus/` workspace, configures a model,
registers the source paper(s), creates the problem dossier(s), runs the agent,
and builds an honesty-linted report.

> OpenTorus is a research-engineering shell around a capable LLM: tools, papers,
> experiments, claims, and an audit trail under `.opentorus/`. The model does the
> reasoning; OpenTorus makes the work inspectable, reproducible, and honest.

> **Each driver resets the local workspace** (`rm -rf .opentorus`) and defaults to
> a local Ollama model on `http://localhost:11434`. Run it in a scratch directory;
> override the model or endpoint with `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`, or
> edit the `opentorus config set model.*` lines for your own provider.

---

## The examples

| Directory | Problem | Numerics | Run |
|-----------|---------|----------|-----|
| [simons-eigenvalue-problems](simons-eigenvalue-problems/) | Five small eigenvalue / linear-systems open problems from a Simons workshop (arXiv:2602.05394): Ritz-value conditioning, CG vs randomized coordinate descent, eigenvalue clustering vs GMRES, invariant-subspace Ritz approximation, deterministic diagonal gaps. | yes (containerized `scripts/`) | `./simons_open_problems.sh [PROBLEM-ID]` |
| [matrix-functions](matrix-functions/) | Five open problems on limited-memory polynomial methods for `f(A)b` (Güttel, Kressner, Lund; arXiv:2002.01682): optimal restart length, a posteriori error estimation, stable first column of `f(H_m)`, two-pass Lanczos orthogonality loss, spectrum-adaptive polynomial methods. | yes (agent-written, containerized) | `./matrix_functions_open_problems.sh [PROBLEM-ID]` |
| [polynomial-hirsch](polynomial-hirsch/) | Polynomial Hirsch Conjecture: does a polynomial `p(n,d)` bound the graph diameter of every `d`-dimensional polytope with `n` facets? Literature dossier + **polymake** experiments: certified diameters, Santos-record reproduction, and spindle search (a `d`-spindle of length `> d` is a finite Hirsch-violating certificate). | yes (agent-written, containerized **polymake**) | `bash poly_hirsch_sota.sh` |
| [backward-error-convergence](backward-error-convergence/) | Is randomness necessary for condition-number-independent backward-error convergence in general linear-system solvers? (arXiv:2604.16075) | no | `bash minberr_backward_error.sh` |
| [nystrom-submodularity](nystrom-submodularity/) | Is the nuclear-norm Nyström approximation error submodular for SDD/SDDM positive-definite matrices? Ships a finished [sample dossier](nystrom-submodularity/sample-output/). | yes (agent-written, containerized) | `bash nystroem_submodularity.sh` |
| [matrix-sign-approximation](matrix-sign-approximation/) | Asymptotic minimax error of the best degree-`2^m`-computable polynomial approximating the matrix sign function on `[-1,-δ] ∪ [δ,1]` (arXiv:2504.01500). | no | `bash sign.sh` |
| [random-nla](random-nla/) | Adaptive sketch size for randomized low-rank approximation: an a posteriori error estimate driving an adaptive `ℓ = k + p` in the randomized SVD / range finder, and the oversampling each spectral-decay profile needs (Martinsson & Tropp survey, arXiv:2002.01387). | yes (agent-written, containerized) | `bash adaptive_sketch_size.sh` |
| [tensor-concentration](tensor-concentration/) | The type-2 constant of tensors (Conjecture 16): does `E‖Σ gᵢTᵢ‖_{ℐₚ} ≤ Õ_{r,p}(d^{1/2−1/p}·√Σ‖Tᵢ‖_{ℐₚ}²)` for the symmetric injective `ℓₚ` norm? Settled for `p ≥ 2r` (arXiv:2411.10633); open for `p < 2r` and rank `r ≥ 3` (Lucca, randomstrasse101 blog). | yes (agent-written, containerized) | `bash tensor_concentration.sh` |
| [gecp-growth-factor](gecp-growth-factor/) | Wilkinson's 1961 question: is the maximum growth factor `g(n)` of Gaussian elimination with complete pivoting polynomial in `n`? Quasi-polynomial upper bound vs. linear lower bounds (arXiv:2303.04892, arXiv:2312.00994); even `g(5)` is unknown. | yes (agent-written, containerized) | `bash gecp_growth_factor.sh` |
| [matrix-spencer](matrix-spencer/) | Matrix Spencer conjecture: signs `εᵢ` with `‖Σ εᵢAᵢ‖ ≤ C√n` for symmetric norm-1 matrices? Known up to polylog rank (arXiv:2208.11286); open in general. | yes (agent-written, containerized) | `bash matrix_spencer.sh` |
| [marcus-de-oliveira](marcus-de-oliveira/) | Marcus–de Oliveira determinantal conjecture: `det(A+UBU*)` inside the hull of `Π(aᵢ+b_σ(i))` for normal `A,B`? Open 50+ years, even `n=4` with `A` Hermitian. A designated counterexample-verification workflow. | yes (agent-written, containerized) | `bash marcus_de_oliveira.sh` |
| [komlos-conjecture](komlos-conjecture/) | Komlós conjecture: a universal constant `K` bounding `min_ε ‖Σ εᵢvᵢ‖_∞` for unit vectors? Best known `O(√log n)` (Banaszczyk); implies Beck–Fiala. | yes (agent-written, containerized; z3 in container) | `bash komlos.sh` |
| [kalai-3d](kalai-3d/) | Kalai's `3^d` conjecture: every centrally symmetric `d`-polytope has `≥ 3^d` nonempty faces. True for `d ≤ 4`; open for `d ≥ 5` (`3^5 = 243`). | yes (agent-written, containerized) | `bash kalai_3d.sh` |
| [bollobas-nikiforov](bollobas-nikiforov/) | Bollobás–Nikiforov conjecture: `λ₁² + λ₂² ≤ 2m(1 − 1/ω)` for `G ≠ Kₙ`. Known triangle-free/regular/multipartite/dense-K₄-free; open in general. Candidate violations are finite certificates. | yes (agent-written, containerized; networkx) | `bash bollobas_nikiforov.sh` |
| [lehmer-problem](lehmer-problem/) | Lehmer's Mahler measure problem (1933): is `inf{M(p) : M(p) > 1} > 1`? Record `M ≈ 1.17628` unbeaten for 90+ years; nonreciprocal case settled (Smyth). | yes (agent-written, containerized) | `bash lehmer.sh` |
| [difference-triangle-set](difference-triangle-set/) | A `(7,5)`-difference triangle set with scope ≤ 111: seven rows, 105 pairwise-distinct differences; scope 112 known. The most certificate-friendly target — constructions need two independent validators + exact `proof_submit` re-check, nonexistence needs a DRAT/LRAT/SMT certificate, and the statement ships a five-phase workflow with a strict claim policy. | yes (agent-written, containerized; CP-SAT + z3 + python-sat) | `bash dts.sh` |

### Campaign examples (general-conjecture scope policy)

Built from [CAMPAIGN_TEMPLATE.md](CAMPAIGN_TEMPLATE.md): the primary target is the full
quantified conjecture (fixed instances are internal tools), the driver designates the
primary claim deterministically, the task text runs a dual research process (refutation +
proof track), and `opentorus problem verdict` derives the terminal classification. Status
audits are fresh, dated web checks at creation time.

| Directory | Conjecture | Audit (2026-08-14) | Run |
|-----------|-----------|--------------------|-----|
| [graceful-tree](graceful-tree/) | Every tree admits a graceful labeling (Ringel–Kotzig 1964). | Open; verified ≤ 35 vertices; "almost all trees almost graceful" (arXiv:1608.01577); a 2007 claimed proof is unaccepted. | `bash graceful_tree.sh` |
| [barnette](barnette/) | Every 3-connected cubic planar bipartite graph is Hamiltonian (Barnette 1969). | Open; verified n ≤ 90; the neighboring Barnette–Goodey conjecture was proved (Kardoš 2020) — recorded as a settled neighbor. | `bash barnette.sh` |
| [caccetta-haggkvist](caccetta-haggkvist/) | Min out-degree ≥ n/k forces a directed cycle of length ≤ k, for every k (1978). | Widely open, even k = 3; small independence number proved (arXiv:1908.02902); triangle frontier [n/3, 0.3465n]. | `bash caccetta_haggkvist.sh` |
| [frankl-union-closed](frankl-union-closed/) | Some element belongs to ≥ half the members of every union-closed family (Frankl 1979). | Open; Gilmer-line constant (3−√5)/2 ≈ 0.382 (arXiv:2211.11689 + refinements), proven optimal for the *approximate* version — new ideas needed for 1/2. | `bash frankl.sh` |
| [lonely-runner](lonely-runner/) | Every runner among k+1 with distinct speeds gets circular distance ≥ 1/(k+1) from all others, for every k (Wills 1967 / Cusick 1974). | Open in general; ≤ 13 runners settled (k ≤ 12), 8–13 all 2025/26 computer-assisted (Rosenfeld arXiv:2509.14111; arXiv:2511.22427; arXiv:2512.01912; arXiv:2604.23906) — the frontier method is itself computational. | `bash lonely_runner.sh` |
| [sidorenko](sidorenko/) | t_H(G) ≥ t_{K₂}(G)^{e(H)} for every bipartite H and every G (Sidorenko 1993). | Open; broad settled classes (suitable blow-ups arXiv:1809.01259, subdivisions arXiv:2408.03491), approximate version holds; simplest unknown case K₅,₅∖C₁₀ (the 10-vertex Möbius ladder). | `bash sidorenko.sh` |

### Calibration examples (known ground truth)

These dossiers have a *known* outcome and exist to regression-test the honesty pipeline:
the agent must discover the true status in the literature and label it correctly —
claimed proofs stay "under review", known refutations must be reproduced and verified,
and nothing gets upgraded past its artifacts.

| Directory | Ground truth | Expected honest outcome | Run |
|-----------|--------------|-------------------------|-----|
| [calibration-crouzeix](calibration-crouzeix/) | Crouzeix's conjecture received two independent claimed proofs in summer 2026 (Jin; Lorist–Schwenninger arXiv:2608.03841), under review. | Status "claimed / under review"; best peer-reviewed constant remains `1+√2`; numerics stay support-only. | `bash crouzeix.sh` |
| [calibration-casas-alvero](calibration-casas-alvero/) | Claimed proof (Ghosh, arXiv:2501.09272) under review; small degrees decidable per degree. | General claim "claimed / under review"; degrees `d ≤ 6` genuinely verified via sympy `proof_submit` as `PROOF-*` artifacts. | `bash casas_alvero.sh` |
| [calibration-perfect-mirsky](calibration-perfect-mirsky/) | Refuted for `n=5`: explicit doubly stochastic counterexample (Rivard–Mashreghi 2007, journal-only source). | `prove --disprove` finds, reproduces, and verifies the counterexample (`COUNTEREXAMPLE_VERIFIED` path); exact region `Θₙ` reported still unknown. | `bash perfect_mirsky.sh` |
| [calibration-brouwer](calibration-brouwer/) | Brouwer's Laplacian conjecture: claimed proof 2026 (Kothari–Tudose, arXiv:2606.12197), under review. | Status "claimed / under review"; exhaustive small-graph checks stay support-only. | `bash brouwer.sh` |
| [calibration-sendov](calibration-sendov/) | Sendov's conjecture: resolved August 2026 — complete AI-assisted proof, **Lean-verified** (Tao's blog digestion, 2026-08-12). Was slated as an open example; the status check at creation time caught the resolution. | Status "solved", with the formal verification named as such; interval spot checks stay support-only. Treating it as open fails calibration. | `bash sendov.sh` |
| [calibration-strassen-formal](calibration-strassen-formal/) | Correctness of Strassen's 7-product scheme (Laderman's 23-product 3×3 as stretch) — a finite system of ring identities, each closed by `ring` in Coq/Lean 4. Exercises the full `proof_submit` write → compile → error-feedback → resubmit loop. Backend: host `coqc`, or `lake` + `LEAN_PROJECT` (Mathlib), or a **containerized-Coq fallback** (verified: `docker run -v /tmp:/tmp coqorg/coq:8.20 coqc`) — no host prover needed. | ≥1 ACCEPTED Coq/Lean `proof_submit` (`PROOF-*` with `validates` edge); rejected compiles preserved as first-class attempts; numeric random-matrix checks stay support-only. | `bash strassen_formal.sh` |

Each directory has its own README with the full problem statement, a step-by-step
description of the workflow, and prerequisites.

---

## What these show

1. **Open problem → dossier** — `opentorus problem new --from-markdown notes.md`
   (or inline) turns a paper's stated problem into a typed, auditable dossier.
2. **Literature-backed proof attempt** — `opentorus prove PROBLEM-XXXX
   [--min-papers N] [--disprove]` runs a budgeted literature → draft → gap-fill
   loop; reports cite only local `PAPER-*` artifacts.
3. **Reproducible numerics** — the Simons example runs its `scripts/*.py` inside a
   pinned `python-sci` container (`opentorus env prepare`), recording `EXP-*`
   manifests.
4. **Honest reporting** — `opentorus problem report --lint` and `problem export
   --pdf` produce a report whose honesty linter flags overclaiming, and which
   never upgrades evidence into proof.

---

## Prerequisites

- **Docker** for the `python-sci` container (the numerical example).
- **A tool-calling model.** The scripts default to `gemma4:31b` on a local Ollama
  server (port 11434); override with `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`, or
  set `model.provider` / `model.name` / `model.base_url` to your own provider with
  `opentorus config set …`. The default `mock` provider is an offline smoke test
  only. Which model to pick is measured, not guessed — see below.

---

## Which model for which job

The scripts default to `gemma4:31b` because it did best in our own informal runs
of the calibration examples on local hardware. This is **not** a benchmark: a
handful of runs per model on a few examples, no statistical claim, and results
will differ on your hardware, your Ollama build, and your problems. Treat the
table as a starting point and re-check it yourself.

| Job | Model | What we saw |
|-----|-------|-------------|
| **Default** | **`gemma4:31b`** | Finished every task we gave it, labelled the 2026 Casas-Alvero and Crouzeix proof claims as *claimed, not peer-reviewed*, and had its verifier submissions accepted throughout. |
| Fast formal verification only | `qwen3.8:latest` | Much faster on the pure formalization example, but did not finish the open-ended ones inside our time budget, so it left no report to review. |
| Also workable | `nemotron-3-super`, `qwen3.6:27b`, `mistral-medium-3.5` | Reached full coverage on the formalization example; each was weaker than `gemma4:31b` on at least one open-ended example. |
| Did not get far for us | `gpt-oss:120b`, `deepseek-r1:70b`, `glm-4.7-flash`, `qwen3-vl:32b`, `qwen3-coder`, `muse-glimmer:30b` | Never reached the formal path, or produced no deliverable, in the runs we did. |

Three observations worth carrying over to your own model choices:

1. **Parameter count predicted little.** In our runs, 27–31 B models did better
   than everything above 100 B, and both sibling pairs inverted (`gemma4:31b` did
   better than `gemma4:26b`, but `qwen3.6:27b` better than `qwen3.6:35b`). What
   seemed to separate them was willingness to call a tool instead of writing more
   prose, and discipline in keeping to a format.
2. **Formal skill ≠ research skill.** A model that does well on the formalization
   example (fixed target, one tool, four identities) can still fail an open-ended
   dossier where it must decide *what* to do, run experiments, and finish in time.
   Try both before settling on a model.
3. **A single run tells you very little.** The same model produced 3 verifier
   submissions in one run and 0 in the next on an identical task. Repeat a few
   times before drawing conclusions.

---

## Set expectations

| Expectation | Reality |
|-------------|---------|
| "Solve every problem in a survey autonomously" | Scope one problem per `prove` run; surveys are for reading and prioritizing. |
| `opentorus research "…"` = general autonomous prover | Fixed loop: local papers + counterexample-search experiments + journal. |
| `opentorus problem report` writes the analysis | It assembles from existing dossier artifacts; run the agent first. |
| Evidence ⇒ proven | The status ladder stops at human review; a verified claim needs a verification artifact. |

For interactive steering (closest to a chat session): `opentorus chat`.
