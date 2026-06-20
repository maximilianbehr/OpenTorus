# Design note: the problem model (options C and D)

Status: **proposal — not yet implemented.** Both options change either the on-disk
format (C) or the epistemic core enforced by `tests/test_dossier.py` EVAL-001..008
(D), so they should be executed deliberately, behind a phased migration with the
tests green at every step. Options **A** (active-problem pointer) and **B**
(deterministic structured extraction) are already implemented and make the current
multi-problem model ergonomic; C and D are the deeper, optional follow-ups.

## Context

Two structural tensions exist today:

1. **Philosophy vs. mechanics.** The README frames the flagship as "one open
   problem, one dossier," yet a workspace is a *container* of many
   `PROBLEM-XXXX` dossiers. A (active-problem pointer) removed most of the daily
   friction without resolving the underlying model.
2. **Two parallel claim/evidence stacks.**
   - **Global research stack:** `research/claims.py`, `research/evidence.py`,
     `research/experiments.py` — workspace-scoped, evidence has a `strength`
     field; used by `math_experiments`, literature, the general loop.
   - **Dossier stack:** `research/dossier/{claims,models,validation,store}.py` —
     per-problem, carries the EVAL invariants and the typed claim/status ladder.
   The overlap ("which claims system do I use?") is a real source of confusion and
   duplicated logic (e.g. two validated-numerics paths).

## Option C — one workspace = one problem

Make the workspace itself the dossier; drop `PROBLEM-XXXX` namespacing. Multiple
problems become multiple workspaces (directories), matching the README philosophy.

**Pros**: one mental model; no id juggling at all; commands lose the `PROBLEM_ID`
argument entirely; the report *is* the workspace report.

**Cons / risks**: on-disk format migration; loses cheap cross-problem grouping in a
survey-extraction flow; breaks every `problem <verb> PROBLEM-XXXX` invocation and
any saved scripts; forces a decision on where the (currently per-problem)
claims/evidence live relative to the (currently global) papers/index/datasets.

**Phased, non-breaking migration**
1. Introduce a `workspace.problem_mode` config: `multi` (today) | `single`.
2. In `single` mode, `init` creates one implicit dossier (`PROBLEM-0001`) and all
   `problem` subcommands + `prove` default to it (A already supplies the resolver).
   No namespacing is removed yet — this is purely a UX/lens change.
3. Add `opentorus problem split <id> <dir>` / `merge` to move a dossier between
   workspaces, so `multi` users can graduate to `single`.
4. Only once `single` is the default and validated do we consider collapsing the
   directory layout. Provide an automatic migrator + a format-version marker in
   `.opentorus/`.

**Recommendation**: ship steps 1–2 (a `single` lens over today's storage) first.
It delivers C's ergonomics with near-zero risk and no format change; defer the
directory collapse until there is real demand.

## Option D — unify the two claim/evidence stacks

Collapse the global and dossier stacks into one typed model.

**Constraint that dominates the design**: the dossier stack encodes the
non-negotiable invariants (EVAL-001..008). Any unification must *adopt the
stricter* dossier semantics — never relax them to fit the global stack. The global
stack's `strength` field must map onto the dossier's evidence types/directions
without ever letting `strength="strong"` imply verification.

**Phased plan**
1. **Audit & map** (no behavior change): enumerate every call site of
   `research.claims`/`research.evidence` vs `research.dossier.claims`; produce a
   field-by-field mapping (`strength` → evidence type + limitations; global
   `Claim` → `ClaimRecord`).
2. **Adapter layer**: route the global stack through dossier validation so both
   share one enforcement path; keep the public APIs. Add tests proving the global
   path now also refuses to "verify by evidence."
3. **Deprecate** the thinner stack with shims; migrate call sites incrementally.
4. **Remove** the duplicate once all call sites and goldens are migrated.

**Recommendation**: do step 1 (audit/map) and step 2 (shared validation adapter)
as a first, reversible increment — it removes the *invariant* duplication (the
risky part) without a big-bang data migration. Steps 3–4 follow only with the full
suite green.

**Status (decided this session): landed at the single-sourced invariant.**
- D-step-1 (characterization tests pinning the global stack's epistemic guards): done.
- D-step-2 (single source of truth): done — `opentorus/research/epistemics.py` now
  owns `VERIFICATION_EVIDENCE`, `VERIFIED_STATUSES`, `PROOF_REQUIRED_STATUSES`, and
  the shared `assert_proof_required(...)` enforcement, imported by both stacks.
- D-step-2b (physical model/storage merge): **deferred by decision.** The two
  scopes (workspace-global `memory/claims.jsonl` vs per-problem
  `problems/PROBLEM-XXXX/claims.jsonl`) are kept; ~14 source + 24 test files and an
  on-disk migration make the full merge a separate, decision-gated project. The
  dangerous part — the invariant drifting between stacks — is already eliminated.

## Why not implement C/D in one pass now

- C's directory collapse and D's data migration are **irreversible-leaning** and
  touch the on-disk format and the epistemic core respectively.
- A botched partial migration is worse than none; both deserve their own reviewed
  change-set with EVAL-001..008 and the golden transcripts green at each step.
- A (pointer) + B (structured extraction) already remove the everyday pain, so the
  urgency that would justify a rushed refactor is gone.

**Proposed next increment if approved**: C-step-2 (`problem_mode: single` lens) and
D-step-2 (shared validation adapter) — both reversible, both test-gated.
