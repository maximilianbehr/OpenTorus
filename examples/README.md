# OpenTorus examples

Real, runnable end-to-end workflows on actual open problems. Each example is a
driver script that sets up a fresh `.opentorus/` workspace, configures a model,
registers the source paper(s), creates the problem dossier(s), runs the agent,
and builds an honesty-linted report.

> OpenTorus is a research-engineering shell around a capable LLM: tools, papers,
> experiments, claims, and an audit trail under `.opentorus/`. The model does the
> reasoning; OpenTorus makes the work inspectable, reproducible, and honest.

> **Each driver resets the local workspace** (`rm -rf .opentorus`) and targets a
> local Ollama model on `http://localhost:11435`. Run it in a scratch directory
> and edit the `opentorus config set model.*` lines for your own provider.

---

## The examples

| Directory | Problem | Numerics | Run |
|-----------|---------|----------|-----|
| [simons-eigenvalue-problems](simons-eigenvalue-problems/) | Five small eigenvalue / linear-systems open problems from a Simons workshop (arXiv:2602.05394): Ritz-value conditioning, CG vs randomized coordinate descent, eigenvalue clustering vs GMRES, invariant-subspace Ritz approximation, deterministic diagonal gaps. | yes (containerized `scripts/`) | `./simons_open_problems.sh [PROBLEM-ID]` |
| [matrix-functions](matrix-functions/) | Five open problems on limited-memory polynomial methods for `f(A)b` (Güttel, Kressner, Lund; arXiv:2002.01682): optimal restart length, a posteriori error estimation, stable first column of `f(H_m)`, two-pass Lanczos orthogonality loss, spectrum-adaptive polynomial methods. | yes (agent-written, containerized) | `./matrix_functions_open_problems.sh [PROBLEM-ID]` |
| [polynomial-hirsch](polynomial-hirsch/) | Polynomial Hirsch Conjecture: does a polynomial `p(n,d)` bound the graph diameter of every `d`-dimensional polytope with `n` facets? A literature + citation-honest dossier. | no | `bash poly_hirsch_sota.sh` |
| [backward-error-convergence](backward-error-convergence/) | Is randomness necessary for condition-number-independent backward-error convergence in general linear-system solvers? (arXiv:2604.16075) | no | `bash minberr_backward_error.sh` |
| [nystrom-submodularity](nystrom-submodularity/) | Is the nuclear-norm Nyström approximation error submodular for SDD/SDDM positive-definite matrices? | no | `bash nystroem_submodularity.sh` |
| [matrix-sign-approximation](matrix-sign-approximation/) | Asymptotic minimax error of the best degree-`2^m`-computable polynomial approximating the matrix sign function on `[-1,-δ] ∪ [δ,1]` (arXiv:2504.01500). | no | `bash sign.sh` |
| [random-nla](random-nla/) | Adaptive sketch size for randomized low-rank approximation: an a posteriori error estimate driving an adaptive `ℓ = k + p` in the randomized SVD / range finder, and the oversampling each spectral-decay profile needs (Martinsson & Tropp survey, arXiv:2002.01387). | yes (agent-written, containerized) | `bash adaptive_sketch_size.sh` |

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
- **A tool-calling model.** The scripts use a local Ollama model on port 11435;
  set `model.provider` / `model.name` / `model.base_url` to your own provider with
  `opentorus config set …`. The default `mock` provider is an offline smoke test
  only.

---

## Set expectations

| Expectation | Reality |
|-------------|---------|
| "Solve every problem in a survey autonomously" | Scope one problem per `prove` run; surveys are for reading and prioritizing. |
| `opentorus research "…"` = general autonomous prover | Fixed loop: local papers + counterexample-search experiments + journal. |
| `opentorus problem report` writes the analysis | It assembles from existing dossier artifacts; run the agent first. |
| Evidence ⇒ proven | The status ladder stops at human review; a verified claim needs a verification artifact. |

For interactive steering (closest to a chat session): `opentorus chat`.
