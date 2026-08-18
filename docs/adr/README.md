# Architecture decision records

Short, numbered records of the design decisions that shape OpenTorus. Each record
states the context, the decision itself, and the consequences we accept. Records
are append-only: a superseded decision gets a new record that says what replaced
it, never a silent edit.

| # | Title | Status |
|---|-------|--------|
| [0001](0001-campaign-engine.md) | Campaign engine: control plane, routing, persistence, proof tree, theorem references | accepted |

Conventions: ASCII only (no Mermaid, no Unicode box drawing), one decision table
per record, and a "Consequences" section that names what gets harder as well as
what gets easier.
