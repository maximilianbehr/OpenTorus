# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OpenTorus is a local-first, terminal-native research agent for open mathematical
problems. It wraps existing LLMs (mock/openai/anthropic/ollama) and adds a typed
local artifact graph, a permission policy, and execution backends. All state
lives as JSONL/YAML/Markdown under `.opentorus/` in the user's project; nothing
leaves the machine unless explicitly configured. The package uses a `src` layout
and requires Python 3.11+.

## Commands

```bash
pip install -e ".[dev]"        # editable install with pytest + ruff + mypy
pytest                         # full test suite (config: -q, testpaths=tests)
pytest tests/test_dossier.py   # one file
pytest tests/test_dossier.py::test_name   # one test
ruff check .                   # lint (rules: E,F,I,UP,B; line-length 100)
ruff format --check .          # formatting (ruff is version-pinned for reproducibility)
mypy src                       # type-check (files = src/opentorus)
```

`opentorus check` runs the configured test/lint/typecheck gates from *inside* a
workspace; the bare `pytest`/`ruff`/`mypy` commands above are for developing
OpenTorus itself.

The CLI entry point is `opentorus = opentorus.cli:app`. Global flags `--verbose`
and `--debug` exist on every command.

## Architecture

Flow: **CLI/REPL/TUI → agent loop → (provider | tools+permissions | research stack) → `.opentorus/` artifacts.**

- **`opentorus.cli`** (Typer app, ~3.8k lines) — the user-facing command surface.
  `opentorus.repl` and `opentorus.tui` are the interactive surfaces. Rendering is
  kept separate from the testable dispatch core.
- **`opentorus.agent`** — the loops. `loop.AgentLoop` is the synchronous task
  loop (plan → request tool call → permission-check → execute → log → feed back,
  with a step cap). `research_loop` is the long-horizon, budgeted
  counterexample/evidence loop. `prove_loop` drives proof writing. Supporting
  modules: `context` (assembles provider context honoring the privacy filter),
  `planner`, `compaction`, `inventory`, `prompts`, `review`, `verify`.
- **`opentorus.providers`** — `BaseProvider` interface, `MockProvider` (offline,
  deterministic — the **default**, and what makes golden tests possible) plus
  openai/anthropic/ollama. Tool calling is normalized across providers; the
  provider must never leak into core logic.
- **`opentorus.tools`** — abstract `Tool` (name, description, `input_schema`,
  `risk_level`, `permission`) with `ToolCall`/`ToolResult` pydantic schemas and a
  `ToolRegistry`. Each tool declares a `PermissionKind`: `read` (no gate),
  `write` (gated by `evaluate_write` on the `path` arg), `command` (gated by
  `evaluate_command` on the `command` arg), or `external` (MCP, gated by
  `evaluate_external_tool`).
- **`opentorus.permissions.policy`** — the gate every effecting action passes
  through: mode (safe/ask/trusted) × operating style (cautious/normal/fast/
  autonomous) × review mode. Hard guarantees are non-bypassable: dangerous
  commands (`rm -rf`, `curl | bash`) and sensitive-file reads (`.env`, keys) are
  *always* blocked; `--mode review` is strictly read-only.
- **`opentorus.execution`** — `ExecutionBackend` protocol with local/Docker/
  Podman/Apptainer/SSH/Slurm implementations, digest pinning, sandboxed mounts,
  result cache.
- **`opentorus.research`** — the artifact stack: `claims`, `evidence`, `graph`,
  `experiments`, literature `sources/` (arxiv, openalex, crossref, …), `papers`
  + hybrid `index` (BM25 + embeddings), `datasets`, `repos`, `verifiers/`
  (Lean/Coq/SMT), `figures`, `authoring`, `pack`, `kb` (cross-workspace
  knowledge base in `~/.opentorus/kb/`), `egress` (DLP/throttle/consent).
  - **`opentorus.research.dossier`** — the flagship "one open problem" workflow:
    `models`, `store`, `claims`, `experiments`, `strategies`, `report`,
    `nl_proof`, `pdf_export`, and `validation` (where the epistemic invariants
    are enforced).
- **`opentorus.governance` / `usage`** — pre-egress DLP, budgets, model routing,
  estimated cost ledger.

## Non-negotiable epistemic invariants

These are enforced in `opentorus.research.dossier.validation` and pinned by
`tests/test_dossier.py` (EVAL-001..008). **Do not weaken those tests to make a
feature pass.** Any change touching claims/evidence/experiments/proofs/reports/
the honesty linter must preserve them:

1. Numerical experiments and proof sketches only ever *support* a claim — they
   never set status to `verified` / `formally_verified`.
2. Only a verification artifact promotes a claim (`formally_verified` needs an
   accepted formal proof; `COUNTEREXAMPLE_VERIFIED` needs an explicit
   verification record).
3. No hallucinated authority: a `THEOREM` / `REFERENCE_FACT` / bibliography entry
   must cite a *local* source artifact. Missing metadata is marked missing, never
   invented.
4. Reports never silently upgrade evidence into proof; generated text runs
   through the artifact-aware honesty linter (flags "we prove", "it is known
   that", "the experiment proves", "obvious").
5. Failed attempts are first-class — preserved, not discarded or silently retried.

When adding a claim type, status, evidence type, or report phrasing, add a test
that pins down its honest behavior.

## Conventions

- **Golden-transcript regression**: `tests/test_golden.py` + `opentorus.evals.golden`
  verify deterministic mock-provider transcripts against `tests/golden/*.txt`.
  Behavior changes to the mock loop will fail these; regenerate via
  `record_goldens` (used in the test fixtures) when the change is intentional.
- **Lazy imports**: heavy/optional deps (PDF, embeddings, providers, verifiers)
  are imported only when used so the base CLI stays fast — keep new optional deps
  behind lazy imports.
- **Determinism**: ids, manifests, and the mock provider are reproducible by
  design; preserve this (it underpins golden testing). Note the harness forbids
  `Date.now`/`Math.random`-style nondeterminism in reproducible paths.
- Update `CHANGELOG.md` and docs when behavior changes.

## Docs worth reading first

`docs/architecture.md`, `docs/artifact-model.md` (persisted schemas),
`docs/cli-ux.md` (command surface + output conventions), `docs/safety.md`,
`docs/privacy.md`, `CONTRIBUTING.md` (epistemic rules), `examples/README.md`.
