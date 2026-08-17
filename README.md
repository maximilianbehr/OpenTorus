# ◎ OpenTorus

[![tests](https://github.com/maximilianbehr/OpenTorus/actions/workflows/tests.yml/badge.svg)](https://github.com/maximilianbehr/OpenTorus/actions/workflows/tests.yml)
[![lint](https://github.com/maximilianbehr/OpenTorus/actions/workflows/lint.yml/badge.svg)](https://github.com/maximilianbehr/OpenTorus/actions/workflows/lint.yml)
[![release](https://img.shields.io/github/v/tag/maximilianbehr/OpenTorus?label=release&sort=semver)](https://github.com/maximilianbehr/OpenTorus/releases)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://github.com/maximilianbehr/OpenTorus/blob/main/pyproject.toml)
[![os](https://img.shields.io/badge/os-linux%20|%20macos%20|%20windows-lightgrey)](https://github.com/maximilianbehr/OpenTorus/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

> **An AI agent for open mathematical problems.** It surveys the literature, runs
> reproducible experiments, searches for counterexamples, and drafts proofs —
> recording every step as inspectable artifacts on your own machine, and never
> mistaking evidence for proof.

![OpenTorus demo: the honesty linter flags "experiments prove" because no verification artifact backs it](docs/media/demo.gif)

*No API key needed for this demo — it runs on the offline mock provider and is
reproducible from [docs/media/demo.tape](docs/media/demo.tape).*

**Early release — inspect it, run it, and report issues.**

---

OpenTorus points a capable LLM — OpenAI, Anthropic, or a **local** Ollama model —
at **one open mathematical problem** and works it as an agent: it reads papers,
forms typed conjectures, runs numerics in pinned containers, hunts for
counterexamples, and writes a natural-language proof with its open gaps marked.
The entire research state lives as a typed, auditable **dossier** under
`.opentorus/` in your project — plain JSONL/YAML/Markdown you can read, grep, and
version-control. Nothing leaves your machine unless you configure it to.

```bash
opentorus problem new "Is κ_V(Q*AQ) bounded polynomially in n for random Krylov Q?"
opentorus prove PROBLEM-0001        # the agent: literature → proof draft → gap-fill
opentorus problem report PROBLEM-0001 --lint   # honest, citation-checked report
```

## The one rule that makes an autonomous math agent trustworthy

> **Evidence is not proof.** A numerical experiment, a symbolic computation, or a
> proof sketch can *support* a claim — it can never *verify* it. A claim reaches
> `verified` only when it is linked to a real verification artifact (an accepted
> formal proof, or an explicit verification record).

This invariant is enforced in code, not left to the model's good intentions. An
OpenTorus run can work for hours and still tell you precisely what is a
conjecture, what is supporting evidence, what is an open gap, and what — if
anything — is actually proven. A generated report is run through an
artifact-aware **honesty linter** that flags overclaiming ("we prove", "it is
known that", "the experiment proves", "obvious") unless the backing artifact
exists.

OpenTorus does **not** claim to solve open problems for you. It makes a strong
model's work on them inspectable, reproducible, and honest.

---

## Why an agent, not a chat window?

ChatGPT, Claude, or Gemini are excellent for a quick question or a single draft.
OpenTorus is for when the output is not a paragraph in a chat window but
**research state you must trust, reproduce, and resume weeks later**. It uses the
same models — the difference is everything wrapped around them:

| | Chat in a browser | OpenTorus |
|---|-------------------|-----------|
| **Memory** | Scrollback; context drifts; hard to grep | Typed artifacts under `.opentorus/` (claims, papers, experiments, action log) |
| **Evidence vs proof** | "The experiment confirms…" sounds authoritative | Status ladder enforced in code; honesty linter flags overclaiming |
| **Reproducibility** | Code you copy-paste | `EXP-*` manifests (command, seed, git commit, deps); `exp replay` |
| **Failed attempts** | Lost in the thread | First-class obstruction ledger — dead ends recorded, not repeated |
| **Literature** | Citations may be invented | arXiv, OpenAlex, Crossref, … → local `PAPER-*` with provenance; reports cite real artifacts only |
| **Privacy** | Data on the provider's servers | State on disk; egress consent-gated per host; DLP scan before anything leaves |
| **Safety** | Opaque plugin execution | Gated patches/shell/checkpoints; dangerous commands and secret-file reads always blocked |

---

## What the agent can do

### Tackle one open problem end to end

- **`opentorus prove PROBLEM-XXXX`** runs a focused, budgeted agent session —
  literature survey → proof draft → gap-fill — and writes a natural-language
  `PROOF-*` sketch with explicit `[GAP-n]` markers for every unproven step. The
  session is framed neutrally — *prove or refute* — so a statement that turns out
  false ends in a refutation sketch, not a hand-waved proof; `--disprove` puts
  counterexample search first. It records evidence and open gaps; it never
  reports a QED it cannot back.
- **Eight attack strategies** — `literature_map`, `special_cases`,
  `counterexample_search`, `symbolic_simplification`, `numerical_experiment`,
  `formalization_attempt`, `proof_sketch`, `obstruction_search` — each scaffolds a
  structured approach with objective, method, expected outputs, and failure modes.
- **Typed claims & evidence** — every statement carries a type (`CONJECTURE`,
  `OBSERVATION`, `THEOREM`, `COUNTEREXAMPLE_CANDIDATE`/`…_VERIFIED`,
  `REFERENCE_FACT`, `FORMAL_PROOF_VERIFIED`/`…_FAILED`, …) and an explicit status.
- **Reproducible experiments** — `EXP-*` manifests capture the command, Python
  version, dependency hash, git commit, and seed, and run in pinned containers
  (Docker/Podman/Apptainer) or on remote/HPC (SSH/Slurm); `opentorus problem
  replay` re-runs the chain.
- **Failed attempts are first-class** — recorded with their reason and reusable as
  obstructions, so the agent does not hit the same wall twice.
- **Honest report + export** — `opentorus problem report --lint` and `problem
  export --pdf` produce a citation-checked report (Markdown / LaTeX / PDF) that
  never upgrades evidence into proof.

### Research toolkit it draws on

- **Literature** across one interface: arXiv, OpenAlex, Crossref, Semantic
  Scholar, DBLP, zbMATH Open, Europe PMC, bioRxiv/medRxiv, plus keyed sources
  (Springer, IEEE, NASA ADS). Legal full-text acquisition (Unpaywall → arXiv →
  declared OA), cached as provenance-rich `PAPER-*`; paywalls are never bypassed.
- **Reading & knowledge** — extract structure from PDFs, a hybrid (BM25 +
  embeddings) index, and a citation + evidence graph.
- **Rigor backends** — optional Lean 4 / Coq / SMT (Z3/cvc5) and a sound
  interval-arithmetic validated-numerics backend.
- **Datasets & code as evidence** — fetch datasets (Zenodo, Hugging Face, OSF)
  and clone repos at a pinned commit to run their tests as *observed* evidence.

### Also a careful coding agent

Patches are first-class `PATCH-*` artifacts you review, apply, and revert (never
auto-committed); `write_file`/`apply_patch`/`run_shell` pass a permission policy;
`opentorus check` runs your test/lint/typecheck gates and the agent self-repairs
within bounds and reports honestly when validation fails.

---

## Quickstart

Python **3.11+**. Not yet on PyPI — install from a clone (six lightweight
dependencies, no ML framework; installs in seconds):

```bash
git clone https://github.com/maximilianbehr/OpenTorus.git
cd OpenTorus
pip install -e .
opentorus init
```

(Contributors: `pip install -e ".[dev]"` adds pytest, ruff, and mypy — see
[CONTRIBUTING.md](CONTRIBUTING.md).)

Point it at a model (the default is an offline, deterministic `mock` for smoke
tests):

```bash
# A local Ollama model — no API key, nothing leaves your machine:
opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b
opentorus config set model.base_url http://localhost:11434

# …or a hosted provider (reads OPENAI_API_KEY / ANTHROPIC_API_KEY from the env):
opentorus config set model.provider openai
opentorus config set model.name gpt-4o-mini
```

Then put the agent on a problem:

```bash
opentorus problem new "For every object satisfying …, prove or refute …"
opentorus prove PROBLEM-0001                  # autonomous: literature → draft → gaps
opentorus problem report PROBLEM-0001 --lint  # build + honesty-lint the report
```

Open `.opentorus/problems/PROBLEM-0001/report.md` — a structured report that keeps
the conjecture a conjecture, the experiment evidence, and the sketch a sketch.

Prefer to drive it by hand? The full `problem` surface (`attack`, `claim`,
`evidence`, `attempt`, `experiment`, `proof`, `report`, `replay`) builds the same
dossier step by step. For interactive use: `opentorus chat` (type `/help`).

---

## Examples

Real, runnable workflows on actual open problems (each resets a scratch
`.opentorus/` and targets a local model — see [examples/README.md](examples/README.md)).
To browse a finished dossier **without installing anything**, read the
[sample dossier](examples/nystrom-submodularity/sample-output/) — claims,
reproducible experiments, recorded dead ends, and a referee verdict, built by
hand through the same CLI artifact surface the agent drives (provenance in its
README):

| Example | Problem |
|---------|---------|
| [simons-eigenvalue-problems](examples/simons-eigenvalue-problems/) | Five eigenvalue / linear-systems open problems from a Simons workshop (arXiv:2602.05394), with containerized numerics. |
| [matrix-functions](examples/matrix-functions/) | Five open problems on limited-memory polynomial methods for `f(A)b` (arXiv:2002.01682), with agent-written numerics. |
| [polynomial-hirsch](examples/polynomial-hirsch/) | Polynomial Hirsch Conjecture — a literature + citation-honest dossier. |
| [backward-error-convergence](examples/backward-error-convergence/) | Is randomness necessary for condition-number-independent backward-error convergence? (arXiv:2604.16075) |
| [nystrom-submodularity](examples/nystrom-submodularity/) | Submodularity of the nuclear Nyström error for SDD/SDDM matrices — ships a finished [sample dossier](examples/nystrom-submodularity/sample-output/) with an exact-arithmetic counterexample candidate. |
| [matrix-sign-approximation](examples/matrix-sign-approximation/) | Best degree-`2^m` polynomial approximating the matrix sign function (arXiv:2504.01500). |
| [random-nla](examples/random-nla/) | Adaptive sketch size for randomized low-rank approximation — an a posteriori error estimate driving the randomized SVD (arXiv:2002.01387), with agent-written numerics. |
| [tensor-concentration](examples/tensor-concentration/) | The type-2 constant of tensors (Conjecture 16, randomstrasse101): open for `p < 2r`, rank `r ≥ 3` (arXiv:2411.10633), with agent-written numerics. |

---

## Safety & privacy

```bash
opentorus --mode review                       # read-only: inspect & critique, no edits
opentorus config set permissions.mode ask     # safe | ask | trusted
opentorus config set agent.style autonomous   # cautious | normal | fast | autonomous
```

Hard guarantees hold in **every** mode and are never bypassable:

- **Dangerous commands** (`rm -rf /`, `curl | bash`, …) and **reads of sensitive
  files** (`.env`, private keys) are always blocked.
- **`--mode review` is strictly read-only**; even `autonomous` style still
  confirms destructive operations.
- **Local-first & private** — sensitive file contents are excluded from provider
  context by default; a pre-egress DLP scan blocks secrets/PII before anything
  leaves the machine; all network access is consent-gated per host, throttled, and
  budget-capped.

---

## Core principles

| Principle | What it means |
|-----------|---------------|
| **Evidence is not proof** | Claims carry explicit statuses; experiments are evidence, never automatic verification. |
| **Local-first** | State lives in `.opentorus/`; nothing leaves your machine unless you configure it. |
| **No "trust me"** | The agent never reports success without validation (tests, diffs, command output). |
| **Reproducible** | Experiments capture a manifest (command, env, git commit, seed); images are digest-pinned. |
| **Citation-honest** | No invented sources; paywalls and licenses respected; reports cite real artifacts only. |
| **Provider-independent** | The model provider never leaks into core logic; the default is an offline mock. |

---

## Where state is stored

Everything lives under `.opentorus/` in your project (inspectable, Git-friendly):

```
.opentorus/
  config.yaml            # configuration (every field documented inline)
  problems/              # the dossiers: statement, claims, evidence, experiments, proofs, report
  memory/  evidence.jsonl  graph.jsonl   # structured memory + typed artifact graph
  experiments/  papers/  proofs/  datasets/  repos/  figures/
  index/  journal/  research/  reviews/   # retrieval, journal, loop state, reviews
  actions.jsonl          # tool action log (with permission decisions)
  usage/ledger.jsonl     # token/cost ledger (exact provider counts when reported)
```

The cross-workspace knowledge base lives in `~/.opentorus/kb/`.

---

## Documentation

- [docs/architecture.md](docs/architecture.md) — how the pieces fit together.
- [docs/artifact-model.md](docs/artifact-model.md) — the typed artifacts and their relationships.
- [docs/cli-ux.md](docs/cli-ux.md) — the command surface and output conventions.
- [docs/safety.md](docs/safety.md) · [docs/privacy.md](docs/privacy.md) — the safety and privacy models.
- [docs/roadmap.md](docs/roadmap.md) — where it is going.
- [examples/README.md](examples/README.md) — runnable examples and command patterns.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). By
participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache License 2.0](LICENSE).
