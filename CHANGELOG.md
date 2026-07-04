# Changelog

All notable changes to OpenTorus are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `CITATION.cff`, so GitHub offers "Cite this repository" and the tool is citable
  in papers; `pyproject.toml` now names the actual author.
- CI now tests on macOS and Windows and on Python 3.13/3.14 (previously
  Ubuntu-only, 3.11/3.12), and the README carries status badges (tests, lint,
  release, Python, OS, license) instead of a hardcoded — and stale — version line.

### Changed
- `opentorus problem report --lint` now **builds** `report.md` from the dossier's
  artifacts before linting, matching its documented "build + honesty-lint"
  behavior. Previously it only linted whatever file existed — including the
  "report not built yet" placeholder, which passed with "No honesty warnings"
  without any report having been generated. The linter itself now also flags an
  unbuilt/empty report (new `not_built` issue kind) instead of blessing it.
- `opentorus doctor` runs the same tool-calling probe as `prove`, so a provider
  that cannot actually work (missing API key, unreachable server, missing model)
  turns the `model` check red with the "Likely cause / Next action" guidance
  instead of reporting a false green. The probe runs under a hard 20-second
  deadline on a daemon thread: provider SDKs default to multi-minute read
  timeouts, and an accept-then-stall endpoint must not hang the diagnostics
  command users run precisely when their setup is broken.
- `opentorus init`/`suggest` next-steps now recommend the README golden path
  (`problem new` → `prove` → `problem report --lint`) and the same example model
  as the quickstart (`gpt-oss:120b`), instead of `llama3` and a `run --plan`
  workflow the README never mentions.
- Example drivers default to Ollama's standard port 11434 (was the non-default
  11435) and honor `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL` overrides; all eight
  examples now default to `gpt-oss:120b`, and each example README matches what
  its script actually sets.
- The mock provider prints its "no LLM configured" disclaimer once per session
  instead of on every fall-through turn, and the streaming display printer now
  closes its pending line at each provider-turn boundary (via the existing
  `on_llm_response` hook), so consecutive streamed replies no longer render
  glued together ("…Validation not run.Here is what I found:…"). The streamed
  chunks themselves still reassemble to exactly the reply text, and verbose
  `--verbose/--debug` trace output is untouched — the trace session closes its
  own lines.

- `proof_write` now challenges gap-laundering: a rewrite of the dossier's primary
  answer that closes **two or more numbered `[GAP-n]` markers at once** is rejected
  unless new evidence (a parsed paper or a recorded experiment) arrived since the
  previous write. Observed failure: a model wrote an honest 3-gap sketch, then one
  rewrite later declared every gap "resolved" in prose — no new paper, no experiment,
  and a calculus error inside the "resolution" — which ended the prove run in ~4
  minutes. Closing a single gap by pure reasoning stays unrestricted, unmarked
  descriptive gap entries are not counted, and referee-reopened `[REFEREE]` gaps are
  exempt (they answer to the referee's recheck, so rewording flagged language is never
  blocked). Backed by a new `evidence_snapshot` field on proof attempts (parsed papers
  + experiments at last write; older records without it are never challenged), shared
  with the prove loop's no-progress signal so the tool and the loop agree on what
  counts as new work. Enforces epistemic invariant 5 at the artifact boundary:
  deleting gap markers is not closing gaps — failed attempts are first-class.

### Fixed
- Windows support, caught by the new CI matrix on its first run: guarded shell
  execution tokenized every command with POSIX `shlex` rules, which eat the
  backslashes in `C:\...\python.exe` — so on Windows every local command,
  experiment, replay, and quality gate failed with exit 127 (`WinError 2`).
  Windows now hands the command string to `CreateProcess` verbatim (still no
  shell); POSIX hosts are unchanged. Container mount sources and the recorded
  `containerfile` workspace path are now written in POSIX form on every host,
  so manifests prepared on Windows replay elsewhere.
- `SECURITY.md` pointed vulnerability reports at a nonexistent repository
  (`opentorus/opentorus`); it now targets this repo, and private vulnerability
  reporting is enabled. The Apache-2.0 LICENSE copyright placeholder is filled in.
- The `problem report --lint` warning printer passed the issue kind through rich
  markup, so the `[experiment_proof]`-style tag was swallowed as an unknown
  style and never displayed; the tag (and the phrase/suggestion) are now
  escaped and visible.
- Explicit `gaps` entries written bare ("GAP-1", no brackets) — the form models
  most often pass — did not dedupe against the body's `[GAP-1]` markers, doubling
  the recorded gap count (observed: 3 gaps recorded as 6). This inflated gap-fill
  budgeting and made the subsequent "closed all gaps" rewrite look even more
  productive than it was. `gap_marker_key` now keys any numbered marker — "GAP-1",
  "[GAP-1]", "[GAP-1: description]" — on its number, so all forms collapse to one
  gap; prose like "the spectral gap 2" is still never counted as a marker.

## [0.0.6] — 2026-06-27

This release makes `opentorus prove` finish *honestly*. The hostile referee now feeds back
into the loop and the proof gap counter can actually reach zero, so a sketch can no longer
"stop early" by relabelling unresolved steps as prose "Open Problems" or by a self-inflicted
gap miscount — yet a genuinely complete proof still settles. It also clears a batch of
literature-search, citation-grounding, report-export, and trace-rendering papercuts that were
burning prove-loop budget or surfacing false rejections.

### Changed
- The hostile referee now feeds back into `opentorus prove`: on every completion check the
  deterministic referee gets a say before the loop accepts "done". If it blocks (unsupported
  result-claims like "we prove"/"provably" with no backing THEOREM, or contradictions) the
  loop *reopens* the proof's gap list with the referee's findings (tagged `[REFEREE]`) and
  keeps working; when it passes, those gaps are stripped. The run settles only once the
  proof is gap-free *and* the referee passes. Running on every check — not just when the
  model's own gap count is zero — means a *miscounted* gap state cannot hide a referee
  block either. This closes an escape where a model emptied `gaps` by relabelling unresolved
  steps as prose "Open Problems" — observed as a prove run that "stopped very early" with
  `max_steps=inf` and `prove_until_gaps_closed=true`, leaving a referee-blocked
  HEURISTIC_ONLY report. The existing no-progress backstop still bounds a model that cannot
  satisfy the referee, and a referee failure can never break the run. Controlled by the new
  `agent.prove_referee_reopens_gaps` (default `true`); active only while
  `prove_until_gaps_closed`. The referee remains record-only — it never upgrades truth
  status, and the epistemic invariants are unchanged.
- Raised the default `context.history_turns` 10 → 50, so more recent session turns are
  replayed into each request (less amnesia about earlier papers/claims/proof steps). It
  remains bounded by `context.token_budget`, which triggers compaction.
- When a proof cites a theorem number that does not exist in a paper, the citation
  grounding rejection now points at the result the proof *meant*. It ranks the paper's
  real numbered results by keyword overlap with the prose around the citation and names
  the closest matches with a snippet of each statement (e.g. cites a fabricated
  "Theorem 1.2" but described Richardson's universal-convergence result → the rejection
  surfaces "Theorem 3.3 — '…universal convergence rate…'"). This breaks a livelock seen
  in `opentorus prove`: a model could retry the same nonexistent number dozens of times
  because a bare list of available numbers gave it no way to map its described result
  onto the right one, exhausting the gap-fill no-progress backstop with the gap still
  open. The check still blocks the invented number — no fabricated authority is admitted
  (epistemic invariant #3); it is only more actionable about the fix.

### Fixed
- The proof gap counter could never reach zero on a finished proof, stalling
  `opentorus prove`. Two miscounts: (1) a "Summary of gaps closed" section that references
  `[GAP-1]`, `[GAP-2]`, … to say they are *resolved* was re-counted as that many *open*
  gaps by the body-marker scan; (2) a literal `gaps: "None"` (the model's way of saying
  "no gaps left") was stored as a gap *named* "None". Together they pinned the count above
  zero, so the completion gate never saw `gaps == 0`: the model kept declaring "all gaps
  closed" while the loop kept insisting gaps remained, until a backstop ended the run with
  a contradictory, referee-blocked artifact. `explicit_gaps` now excludes markers the body
  describes as closed (under a gaps-closed heading, or immediately followed by a closure
  verb like "handled"/"resolved") and drops "no gaps" sentinels; `_normalize_gap_args`
  drops the same sentinels before they are stored. Genuinely open gaps — including one
  mentioned alongside a closure summary — are still counted. This also lets the
  referee-reopen gate (above) engage: once a clean proof reaches `gaps == 0`, the referee
  gets its say instead of the count being stuck.
- HTML report export now renders display equations that were written as indented LaTeX
  without `$$` delimiters. Proof bodies commonly write a display equation as a 4-space
  indented line of raw LaTeX (e.g. `k ≥ \frac{…}{…}`); the Markdown→HTML converter stripped
  the indent and emitted a plain paragraph, so MathJax never saw math delimiters and
  `\frac{…}` leaked to the page as literal text. Indented blocks containing a TeX macro
  are now wrapped in `\[…\]` so MathJax typesets them (indented blocks without a macro keep
  their prior paragraph rendering). Re-run `opentorus problem export` to regenerate an
  existing report's HTML. (Inline math written without `$…$` in prose, and lemmas stored
  as structured data, are separate authoring-side issues not addressed here.)
- Literature search no longer livelocks on unsupported query operators. Models write
  Google-style queries (`"phrase"`, `-exclude`, `author:`, `OR`), but the connectors do
  not honor them — and arXiv's `all:` field actively misreads a leading `-` as a token to
  *include*. So when a model tried to remove off-topic hits by appending
  `-microwave -qcd …`, the query *broadened* (to ~1.9M results) and surfaced exactly the
  physics papers it was excluding; the model kept adding exclusions and the same junk kept
  ranking higher, burning the whole literature-phase budget in `opentorus prove`. Queries
  are now normalized to clean positive keywords before any connector sees them (negations
  and quotes dropped, `field:` qualifiers reduced to their value) — translating to arXiv's
  `ANDNOT`/phrase syntax was tested and found unreliable, so we strip rather than translate.
  `lit_search` also now reports when a search surfaced **no new papers** (or repeats an
  earlier query this session), so the model stops re-issuing near-identical searches and
  moves on to fetching/reading. Repeat queries are still never blocked.
- The honesty linter no longer raises phantom warnings on its own output. Two
  self-inflicted false positives are fixed: (1) the proof-sketch bootstrap scaffold's
  gap placeholder said "do not claim the theorem **is proved** while gaps remain",
  which tripped the result-assertion check — reworded so OpenTorus-generated text never
  self-trips; (2) `lint_dossier_report` re-linted the report's own "Honesty Warnings"
  section, whose entries quote the flagged phrase (e.g. `'is proved'`) and re-triggered
  the linter, double-counting every warning — that section is now excluded from
  re-linting.
- Citation grounding no longer rejects results that exist deep in a paper. `read_paper`
  persists only a 280-char outline per section in `structure.json`, and the citation
  corpus was built from that outline — so a real result in a later section (e.g.
  `Lemma 3.1`) was invisible and wrongly reported as an invented citation. `read_paper`
  now also writes the full extracted text (`text.txt`) it already has, so the whole body
  is searchable; the compact `structure.json` is unchanged. Re-run `paper_read` /
  `paper_fetch` on existing dossiers to regenerate the full-text artifact.
- The CLI agent trace no longer crashes when a provider emits stray markup-like tokens.
  Model/tool text (e.g. a model writing a `[/THINK]` reasoning marker, or a tool argument
  containing brackets) was interpolated raw into rich's markup-enabled `console.print`,
  so a mismatched `[...]` raised `rich.errors.MarkupError` and aborted the whole run
  (seen during `opentorus prove` gap-fill). Such text is now escaped before printing in
  the non-streaming trace paths (context replay, tool-call args, reply preview), matching
  the `markup=False` guard already used on the streaming paths.
- Citation grounding now recognizes **all numbered environments** — theorem, lemma,
  proposition, corollary, **definition, remark, equation, example** — not just
  theorem-like ones. A proof citing e.g. `Definition 1.1` of a paper that has no
  `Theorem 1.1` is no longer wrongly rejected as a fabricated citation, and such numbers
  now appear in the "parsed text contains …" hint. Messages are reworded from
  "Theorem/Lemma N" to the generic "numbered result N".

## [0.0.5] — 2026-06-21

This release hardens `opentorus prove` and provider handling for real local/OpenAI-compatible
model use: it stops infinite gap-fill grinds, unblocks proof writing, refuses or warns when a
model cannot call tools, and reports local-endpoint cost honestly.

### Added
- **Tool-calling capability check** (`model.verify_tool_calling`, default true): before
  an agent run (`run`, `prove`, `research`) OpenTorus verifies the model can call tools,
  since every deliverable is a tool call. It refuses with a clear message when an Ollama
  model authoritatively lacks the `tools` capability (`/api/show`); for other providers
  a one-shot probe *confirms* tool support and otherwise emits a non-fatal warning
  (the probe never refuses a model on an unforced sample, so a tool-capable model is
  never wrongly blocked). If a run executes zero tool calls despite tools being
  available, it now stops with a message naming the likely tool-calling cause.
- **Gap-fill no-progress backstop** (`agent.prove_gap_fill_no_progress_steps`,
  default 16): `opentorus prove` now ends gap-filling after a window of steps that do
  not reduce the proof's gap count — even when `max_steps` and
  `prove_gap_fill_max_steps` are `inf`. A model that keeps shrinking the gap list
  resets the window and continues; a model that cannot close gaps stops instead of
  grinding indefinitely (observed: an ~80-minute unbounded run on a workspace with
  both caps set to `inf`).

### Changed
- A rejected proof citation now lists the theorem/lemma numbers the parsed paper
  actually contains, so the model can cite a real result (or mark a `[GAP-n]`) instead
  of guessing numbers and having the whole `proof_write` rejected. The prove prompt
  also instructs the model not to invent theorem numbers.
- The gap-fill no-progress window now also resets when the model gathers **new evidence**
  (a completed experiment or newly parsed paper), not only when the gap count drops — so
  a model actively running experiments toward a gap is no longer cut off mid-work, while
  bare re-reads / re-writes of the same sketch still stop it.

### Fixed
- `read_file` / `list_files` / `glob_files` recover a bare dossier-artifact path
  (e.g. `proof_attempts/PROOF-0001.md`) against the active dossier, so the agent can
  read back a proof it just wrote without the full `.opentorus/problems/PROBLEM-XXXX/`
  prefix.
- **Local OpenAI-compatible endpoints are no longer billed as "price unknown".** Cost
  reporting now treats a provider whose `base_url` is a loopback/private host
  (`localhost`, `127.0.0.1`, `192.168.*`, `10.*`, `172.16–31.*`, `*.local`) as local
  inference: the per-step line reads `$0 (local)` instead of `$? (price unknown)` for a
  model name not in the price table, and pre-egress DLP is skipped for it. Genuinely
  remote endpoints with an unknown model name still read `$? (price unknown)`.
- **Ollama gpt-oss harmony tool-name leak fixed at the source.** When Ollama's harmony
  parser leaks channel framing into `function.name`
  (e.g. `assistant<|channel|>commentary`), the Ollama provider now sanitizes it: a real
  tool name is recovered from the `to=functions.NAME` recipient (anchored on `to=`, so a
  function merely mentioned in a preamble is not dispatched), and a bare channel/role
  marker is dropped (the turn degrades to a message) rather than persisted as a bogus
  tool call that later breaks strict providers. Names that are not harmony framing —
  including namespaced/dotted MCP tools like `mcp__server__get.forecast` — pass through
  unchanged and are never dropped or rewritten. The streaming path now accumulates
  tool-call deltas instead of overwriting, so a valid call is not lost when a later
  delta carries only framing.

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
