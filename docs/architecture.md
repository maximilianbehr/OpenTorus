# Architecture

OpenTorus is a local-first, terminal-native agent. This document describes how
the pieces fit together and the boundaries that keep it inspectable.

## High-level shape

```
            ┌─────────────────────────────────────────────┐
   user ──▶ │  CLI / REPL / TUI  (opentorus.cli, .repl)    │
            └───────────────┬─────────────────────────────┘
                            │ commands & interactive turns
            ┌───────────────▼─────────────────────────────┐
            │  Agent loop & research loop                  │
            │  (opentorus.agent.*)                         │
            │   plan → call tool → record → feed back      │
            └───┬───────────────┬───────────────┬──────────┘
                │               │               │
       ┌────────▼─────┐ ┌───────▼──────┐ ┌──────▼─────────┐
       │ Providers    │ │ Tools +      │ │ Research stack │
       │ (mock/openai │ │ Permissions  │ │ (claims, exps, │
       │  /anthropic/ │ │ + Execution  │ │  papers, KB,   │
       │  ollama)     │ │ backends     │ │  verifiers …)  │
       └──────────────┘ └──────┬───────┘ └──────┬─────────┘
                               │                │
                        ┌──────▼────────────────▼──────┐
                        │  .opentorus/  (project memory)│
                        │  JSONL + YAML artifacts       │
                        └───────────────────────────────┘
```

## Layers and boundaries

- **CLI / REPL / TUI** (`opentorus.cli`, `opentorus.repl`, `opentorus.tui`):
  the only user-facing surface. The interactive dispatch core is kept testable
  and separate from rendering.
- **Agent loops** (`opentorus.agent`): the synchronous task loop
  (`agent.loop.AgentLoop`) and the long-horizon, budgeted `agent.research_loop`.
  Loops plan, request tool calls, record each step with its permission decision,
  and feed results back to the provider.
- **Providers** (`opentorus.providers`): a `BaseProvider` interface with
  `MockProvider` (offline, deterministic — the default) plus optional OpenAI,
  Anthropic, and Ollama backends. The provider never leaks into core logic; tool
  calling is normalized across providers.
- **Tools + permissions** (`opentorus.tools`, `opentorus.permissions`): an
  abstract `Tool` interface with `ToolCall`/`ToolResult` schemas and a registry.
  Every effecting action is gated by the permission policy (mode + operating
  style + review mode) with non-bypassable hard guarantees.
- **Execution backends** (`opentorus.execution`): a neutral `ExecutionBackend`
  protocol with local, Docker, Podman, Apptainer, SSH (remote), and Slurm (HPC)
  implementations, plus digest pinning, sandboxed mounts, and a result cache.
- **Research stack** (`opentorus.research`): claims, evidence, the artifact
  graph, experiments and manifests, literature sources, papers and the hybrid
  index, datasets, repos, verifiers (Lean/Coq/SMT), figures, authoring, packs,
  and the cross-workspace knowledge base.
- **Governance** (`opentorus.governance`, `opentorus.research.egress`,
  `opentorus.usage`): pre-egress DLP, per-provider/investigation budgets, model
  routing, and an estimated cost/usage ledger.

## Data flow through a loop

1. The user issues a command or interactive turn.
2. The loop assembles **context** (transparent, retrieval-driven, honoring the
   privacy filter) and asks the provider for the next step.
3. If the provider requests a tool, the **permission policy** decides
   allow / ask / block. Allowed tools execute (possibly inside an execution
   backend); the call, result, and decision are appended to the action log.
4. Effects produce or update **artifacts** under `.opentorus/`.
5. The result is fed back to the provider for the next step or a final answer.

## Design rules

- **Local-first**: all state is files under `.opentorus/`; no hidden cloud state.
- **Deterministic where possible**: ids, manifests, and the mock provider are
  reproducible, which makes golden-transcript regression testing possible.
- **Lazy imports**: heavy/optional dependencies (PDF, embeddings, providers) are
  imported only when used, so the base CLI stays fast and dependency-light.
- **Evidence vs. truth**: the research stack records evidence; status upgrades
  are human-gated and "formally verified" requires a machine-checked proof.

See [artifact-model.md](artifact-model.md) for the persisted schemas and
[safety.md](safety.md) for the permission and egress guarantees.
