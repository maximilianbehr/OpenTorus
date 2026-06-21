# Changelog

All notable changes to OpenTorus are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.3] — 2026-06-21

This release turns the integrity scaffolding into enforced behavior: the documented
epistemic and governance guarantees are now backed by code rather than convention.

### Added
- **Claim ledger** extensions: claim types `HEURISTIC`, `EXPERIMENTAL_OBSERVATION`,
  `OPEN_GAP` and the `needs_review` status; a logged-only `downgrade_claim_type`.
- **Hostile referee** (`opentorus problem referee`): deterministic post-proof stage
  that classifies theorem-like claims (proved/cited/heuristic/unsupported/refuted),
  recommends `THEOREM → CONJECTURE` downgrades, flags contradictions and overclaims,
  and persists a JSON + Markdown report. Reusable prompt at `prompts/referee.md`.
- **Algebra checker** (`opentorus check-algebra`): sympy-backed check of a claimed
  optimizer against `dW/dm = 0`, monotonicity, and the second-order condition; a
  rejection persists an `ALG-*` artifact and drives the status gate to `INVALID`.
- **Report status gate**: derives `SOLVED` / `PARTIALLY_SOLVED` / `HEURISTIC_ONLY`
  / `EXPERIMENTAL_ONLY` / `UNSOLVED` / `INVALID` and a structured report header.
- **SymPy verification backend** for symbolic identities/inequalities
  (`config.tools.verifiers.sympy`, on by default).
- **Checkpoint restore** (`opentorus checkpoint restore`): check out a git
  checkpoint or diff a manifest checkpoint.
- **Cost transparency**: a paid cloud model with no known price renders
  `$? (price unknown)` rather than `$0 (local)`.
- `doctor` now reports verifier and execution backend availability.
- Reviewer pack writes a hash-bearing `pack/papers-manifest.json`.

### Changed
- `sympy` is now a core dependency (the optional `algebra` extra was removed).
- Honesty linters and the DLP secret scanner normalize text (zero-width removal,
  homoglyph folding) so trivial Unicode evasion no longer bypasses them; the dossier
  linter now also lints heading text. Per-claim honesty licensing prevents one
  verified claim from licensing overclaims about another.
- Honesty is enforced on outputs: the autonomous `prove` loop exits non-zero on
  unresolved honesty warnings, and PDF export refuses to typeset an overclaiming or
  `INVALID`-status report (`--force` overrides; the honest HTML report is written).
- Pre-egress DLP screens provider sends; budget caps are enforced on the main agent
  loop; the egress daily-budget ledger reconciles with disk to avoid undercounting.
- Provider responses carry a `truncated` flag (Anthropic `max_tokens` / OpenAI
  `length`); the Anthropic client receives the configured timeout.
- Experiment cache key folds attached-dataset digests, preventing a stale cache hit
  when only the data changes.
- Verification backends distinguish a timeout (`inconclusive`) from a genuine
  rejection; an SMT `sat` model is recorded as weak, unvalidated evidence.
- Whole-file artifact writes (claims/evidence/YAML, egress ledger) are atomic
  (temp file + fsync + rename), so a crash mid-write cannot truncate a ledger.
- `prove_harvest` no longer fabricates a domain-specific refutation for an unrelated
  problem; off-domain runs get a hedged, domain-agnostic candidate.

## [0.0.2]

- Require a model for PDF math; drop the deterministic-math PDF path (HTML/MathJax
  fallback). Robust LaTeX handling of bare Unicode and stray `\tag`.
- `matrix-functions` example (limited-memory polynomial methods for `f(A)b`).
- Workspace-global research store tagged with `problem_id` for correct attribution.

## [0.0.1]

- Initial public release: typed dossier, prove/research loops, literature stack,
  execution backends, permission policy, and the epistemic invariants (EVAL-001..008).
