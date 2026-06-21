# Roadmap

OpenTorus was developed incrementally across **Milestones 0–75**. The first
public release, **v0.0.3**, bundles that work into one coherent agent and starts
the versioned history fresh. The milestones group into three capability bands,
all present in v0.0.3:

- **Core (M0–M22)** — the inspectable, local-first foundation: workspace, memory,
  the permission policy, tools, claims/evidence/experiments, the agent loop,
  providers, and review mode.
- **Engineering loop (M23–M41)** — agentic write/patch tools, plan execution,
  retrieval and context selection, streaming, the cost ledger, the Rich TUI,
  evaluation/regression harnesses, and reproducibility replay.
- **Research agent (M42–M75)** — literature connectors and legal full-text
  acquisition, paper understanding and the hybrid index, knowledge synthesis,
  math/proof backends, the autonomous research and `prove` loops, pluggable and
  HPC execution, adversarial review, rigorous numerics, authoring/dissemination,
  datasets and code-as-evidence, the cross-workspace knowledge base, the
  read-only dashboard, and governance (DLP, budgets, model routing).

The flagship surface is the **credible math dossier** (`opentorus problem …` and
`opentorus prove`): one open problem, an auditable artifact graph, and an honest
report that never upgrades evidence into proof. The live design notes are in
[design-problem-model.md](design-problem-model.md).

Each milestone is a small, reviewable step: run the tests, show the diff,
summarize the changes, stop. Post-v0.0.3 work continues in that style.
