# Changelog

All notable changes to OpenTorus are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Ten new examples drawn from the Randomstrasse101 open-problems blog** (ETH Zürich;
  38 numbered problems in 17 posts, all extracted and status-checked, ten selected for
  small-machine explorability and certifiability; every audit counter-checked by an
  independent session, with the usual harvest — an implication direction reversed, a
  covering radius wrong for the two smallest cases, a lower bound attributed to the
  wrong classical paper, and a second July-2026 preprint the first audit had not seen).
  Six campaigns: the Kuramoto 3/4 density threshold (RS101 #5 — twisted-state Hessians
  make dense non-synchronizing graphs exactly certifiable, so a certified graph above
  the known 0.6838 bound would be genuine progress), sign-matrix discrepancy (#11–12;
  exact maxima 2,1,2,3,4 for n = 2..6 computed and independently re-run at creation),
  the Paley clique conjecture (#25 with the localization relaxations #26–28 as tools —
  the 1-localization LP with exact rational duals yields certified per-prime clique
  bounds), Balan–Wang phase-retrieval stability (#20; the Gaussian case settled at
  exponential scale in July 2026, forcing β ≥ 1/4), KLS (#30 — slicing and thin shell
  are now theorems, the (log n)^{-1/4} improvement is claimed by two concurrent
  GPT-5.6-Pro-assisted July-2026 preprints and already cited as known by Milman),
  and the Lovász number of random circulant graphs (#18; ϑ is an LP with exact
  certificates). Four calibrations, each testing a different honesty label: ellipsoid
  fitting (#6 — a full proof claimed on 2026-08-10, one week before the audit),
  Group Spencer (#2 — two independent unrefereed June-2026 proofs; "two preprints
  agree" is not peer review), Sylvester Hadamard discrepancy (#13 — refuted for every
  odd k ≥ 9 via Boolean nonlinearity; the counter-audit re-derived the 512-entry
  certificate from the published truth tables), and phase-retrieval injectivity at
  4M−5 (#19 — theorem / false / claimed-by-an-AI-generated-note / open, four labels
  that must stay apart). Cross-references recorded: #1 and #16 already had examples
  (matrix-spencer, tensor-concentration); #4 and #9 are resolved (McRae 2025;
  Kothari–Xu 2025) and appear as settled neighbors.

### Changed
- `komlos-conjecture` had gone stale: the best upper bound is Bansal–Jiang's
  Õ(log^{1/4} n) (arXiv:2508.03961, Aug 2025), not Banaszczyk's O(√log n), and the
  lower bound K ≥ 1+√2 (Kunisky) was missing — driver, README and the examples table
  now carry them and register the papers. `matrix-spencer` records the June-2026
  structured special cases (Akbas–Sra's C*-algebra theorem; the group case) as
  claimed, with a pointer to the new calibration.

## [0.0.10] — 2026-08-17

Fourteen new problems for the example collection, and eight more inside an existing
one. The point of this release is not the count but the process that produced it:
every one of the ten new campaign dossiers carries a status audit taken fresh on the
day, and every audit was handed to a second, independent session with the instruction
to find what is wrong with it. That second pass earned its place again. It caught a
Williamson nonexistence result attributed to the wrong paper, a dual-conjecture
constant quoted without its factor 1/d, a degree-5 case described as "publication
status unclear" that has been in print since 2006, Schinzel's m/n threshold cited as
a theorem when it is a conjecture, and a claimed proof of Erdős–Straus from February
2026 that the first audit had not seen at all. None of these would have been a
computation error; every one would have been a wrong sentence in a report that a
model then cites as fact.

The audits also had a way of catching the world mid-motion. The Hadamard dossier was
audited five days after an unrefereed announcement of matrices for all twelve unknown
orders below 2000 — third-party integer-verified, no paper — and carries it as exactly
that. The hot spots dossier had to be scoped to the plane because the high-dimensional
convex case was refuted in a still-unpublished 2024 preprint. The Ryser–Brualdi–Stein
dossier is a mixed frontier by construction: one half proved for all large n in an
unpublished preprint, the other half open. Three of the four new calibrations exist to
test labels harder than "open" or "solved": a refutation whose counterexample lives
only in a paper's figures and must be reconstructed and certified; a published proof
that the community does not accept and a Lean effort that offers no verdict; a
conjecture that is true through dimension seven and false from eight.

### Added
- **Ten new campaign dossiers and four new calibration examples** under
  `examples/`, all built from `CAMPAIGN_TEMPLATE.md` with fresh status audits
  dated 2026-08-17, each audit counter-checked by a second independent
  session (non-negotiable #7; the counter-audits again earned their keep —
  among the findings: a misattributed Williamson nonexistence result, a
  dual-conjecture constant off by a factor 1/d, a "still unclear" d=5 proof
  that has in fact been published since 2006, a conjecture cited as a
  theorem, and a claimed proof of Erdős–Straus from February 2026 the first
  audit had missed entirely). Campaigns: the Hadamard conjecture (audited
  five days after the unrefereed August 2026 announcement of matrices for
  all twelve unknown orders below 2000 — the dossier carries it as claimed,
  machine-checkable, unrefereed), Erdős–Straus, Erdős' distinct subset sums
  (Erdős problem #1), the Erdős–Szekeres happy-ending conjecture, the
  1/3–2/3 conjecture (verified through n = 14 by a July 2026
  trillion-poset census), Erdős–Gyárfás power-of-2 cycles, Seymour's second
  neighborhood conjecture, Ryser–Brualdi–Stein (a mixed frontier: the n−1
  statement is proved for all large n in a still-unpublished preprint, the
  odd-order statement is open), the hot spots conjecture (planar convex case
  open; the high-dimensional convex case refuted in a still-unpublished 2024
  preprint), and Smale's mean value conjecture. Calibrations: Steinberg's
  conjecture (refuted 2016 — the `prove --disprove` run must reconstruct the
  gadget counterexample from the paper and machine-verify planarity,
  C4/C5-freeness, and 3-coloring UNSAT with a DRAT certificate; the
  reconstruction was smoke-tested during audit, including the one edge
  visible only in the paper's final figure), the Erdős discrepancy problem
  (solved — Tao 2015/16 must be reported as solved with Polymath5 credited
  for the reduction, C=1 certified exactly, and the C=3 exact maximum kept
  open), the abc conjecture (a published but contested claimed proof —
  the hardest status label in the collection: neither "proved" nor bare
  "open"; primary IUT sources are deliberately not on arXiv), and Keller's
  conjecture (resolved with a dimension split — true through n = 7, false
  from n = 8 — where blanket labels fail calibration and Mackey's 256-clique
  counterexample is reconstructed and pairwise-verified; the clique check
  was smoke-tested during audit, all 32,640 pairs). Two new
  container environments enter the examples: Debian **nauty**
  (geng/directg/gentourng/genposetg, symlinked from the distribution's
  nauty-prefixed binaries — smoke-tested) for exhaustive graph and poset
  generation, and CP-SAT + python-sat for exact-cover and
  proof-logging workloads.
- **The Simons-workshop example grew from five to thirteen dossiers.** A full
  second pass over arXiv:2602.05394 (41 numbered problems) extracted the eight
  further problems that are numerically explorable at small dimension: the
  Forsythe conjecture for restarted CG (2.20), updated CG residuals below
  machine precision (2.15, explicitly counterexample-shaped), bits of
  precision for n-step CG backward error (2.17), the distribution of Ritz
  values across the numerical range (3.6), MR3-family bidiagonal SVD failure
  modes (3.8), GECP's empirical rate on the fermionic kernel (4.2), QRCP row
  selection on orthonormal-column matrices (4.3), and volume sampling versus
  optimal column subset selection (4.7). Existing dossier ids stay stable
  (0001–0005 unchanged; the new problems are 0006–0013 — smoke-tested).
  Cross-references recorded: workshop problems 4.6 and 6.3 already have
  standalone examples (nystrom-submodularity, matrix-sign-approximation).

## [0.0.9] — 2026-08-17

Nineteen fixes, every one of them found by running the example collection against ten
model families the project had never been used with — and not one of them a computation
error or a crash. They are all the same defect wearing different clothes: the system
says something true that the model cannot act on, or a guard looks past a formatting
detail no test ever produced. That is why the suite stayed green through all of it.

The guards against circling were themselves the worst offenders. The one that catches
"same mistake, new arguments" keyed on raw error text, so a verifier stamping each
rejection with a fresh proof id and temp path split one recurring failure into 29
unique ones and the threshold of 4 was unreachable by construction. Its sibling ladder
only ever warned and never stopped, so a run rewrote one blocked command twenty times.
A cached re-read was logged as a success, so two runs re-read the same file 24 and 25
times invisibly. And a single observation was written 364 times — 365 of that run's 390
actions — because writing a duplicate note also succeeded. Each is now bounded, with
every threshold calibrated against the recorded runs rather than guessed.

Two defects made a capable model unusable outright: a system message the stable-prefix
ordering deliberately places mid-conversation, which strict local chat templates reject
with an HTTP 500 ninety seconds into a run, and a response deadline that bounded the
wait for the next chunk rather than the reply, letting a degenerate model hold a turn
for half an hour. Two more were failures of honesty rather than mechanics: a typographic
hyphen turned correctly cited lines into uncited ones at three separate sites, and the
literature gate's own placeholder citation was pasted back 364 times as a real
observation, naming a theorem that does not exist.

The rest are the ordinary work of making a refusal usable: naming what arrived, showing
the shape to send, re-reading a value the model encoded once too often, resolving a tool
name a corrupted output split with a space, and never sending a model to fetch a paper
that cannot be fetched.

### Fixed
- **A verifier stamping each rejection no longer blinds the unchanged-error guard.**
  The guard that catches "same mistake, new arguments" keyed on the raw error text,
  and a verifier rejection carries a fresh `PROOF-*` id, a fresh temp path, and a
  source position that shifts whenever the model edits anything above it. One Coq
  calibration run produced 31 rejections and 29 distinct keys, so the threshold of 4
  was unreachable by construction — twelve of those rejections were one and the same
  syntax error, each costing minutes in a container. Only the guard's key is
  normalized; the model still reads the verbatim message. On the recorded run: 29
  keys down to 12, firing on the fourth attempt. The consecutive-failure streak key
  is normalized for the same reason.
- **An endless re-read is no longer counted as progress.** A repeated
  `read_file`/`paper_read` of an already-read path is served from the read cache and
  logged `ok=True`, so a file compacted out of context stays recoverable — which also
  made it invisible: the chat-only streak resets, neither failure tracker sees it, and
  nothing counted it. Two runs re-read one and the same `statement.md` 24 and 25 times,
  a full model round-trip each, producing nothing; half of the recorded workspaces
  exceed three repeats. The first four re-serves stay, then the call fails and the
  identical-failure tracker takes over. The refusal deliberately carries no counter —
  a ticking number would make each failure look new and blind that very guard.
- **`model.timeout_seconds` now bounds the response, not just the wait for the next
  chunk.** It reaches `urlopen` as a socket timeout, and a model degenerating into an
  endless repetition keeps chunks arriving; with tools enabled `num_predict` is `-1`,
  so there was no token cap either. A 33B model spent half an hour inside a single
  turn emitting `Also maybe PAPER-1412 for 10.1007/…`. The stream reader now carries
  the same budget as a deadline and aborts with a clean, resumable `ProviderError`.
- **A typographic hyphen no longer turns a cited line into an uncited one.** Models
  type `PAPER‑0001` with U+2011 — nine of eleven citations in a recorded Casas-Alvero
  run did. Three separate ASCII-only patterns decide whether a line cites a paper, and
  each gates something real: the honesty linter exempting an attributed literature
  result from the overclaim rule, the literature gate refusing a `memory_add` without a
  citation, and the proof-sketch linter warning about a resolution claim naming no
  source. The identical sentence passed with `-` and was flagged with `‑`.
  `paper_citations` had normalized hyphens for exactly this reason; the other three
  sites were never brought along. One shared tolerant pattern now backs all of them.
- **A model is no longer sent back to fetch a paper that cannot be fetched.** A
  metadata-only paper is kept on purpose — withdrawn, source-only or 404'd — with the
  reason in `access_note`, but the citation check answered "call paper_fetch and ensure
  [parsed]" anyway. A Sendov run lost four `proof_write` attempts to a 404'd arXiv PDF
  while the workspace already held the explanation. The rejection now quotes the
  recorded reason, says re-fetching will not help, and names the routes that work.
- **A short artifact id resolves to the id that was minted.** Ids are minted as
  `PREFIX-%04d`, so `PAPER-002` can only mean `PAPER-0002` — but the lookup missed and
  answered "No PAPER-002 … call paper_list or paper_fetch first" while the paper sat in
  the workspace. Applied to every artifact-id lookup in the tool layer; anything that is
  not `PREFIX-<digits>` still misses, and still says so.
- **A system message that is not at the beginning never reaches Ollama.** The
  stable-prefix ordering deliberately puts the volatile workspace state in a `system`
  message just before the final turn, so the reusable prefix ends as late as possible.
  Strict local chat templates reject that outright — and here "system message must be
  at the beginning" means literally what it says, unlike the leading-run case
  `_merge_leading_system` already handles; two independent bugs behind one string.
  Observed as HTTP 500 on qwen3.8 and qwen3-coder about ninety seconds into a run,
  nothing produced. Folded in the Ollama conversion rather than the context builder, so
  no other provider and no golden transcript changes: the block attaches to the user
  turn it was meant to inform, or to the last tool result when the next turn is a
  tool_calls group that must not be split.
- **The unchanged-error ladder gained a ceiling.** It only ever warned. A prove run
  rewrote its `run_shell` command 20 times and got the identical "not available during
  prove" block every time; the nudge fired from the fourth attempt and the model kept
  going for another sixteen turns. The consecutive-failure ladder cannot stop this —
  every new argument set resets its streak. Calibrated across 19 recorded workspaces
  (median 1 argument set per error, only three exceed six, at 20, 11 and 9), the run
  now ends honestly at eight.
- **An argument the model JSON-encoded one time too many is re-read.** Teaching the
  shape in the rejection was not enough: llama3.1:70b sent `gaps` as a string sixteen
  times across two examples with the required JSON spelled out in every reply — and
  what it sent was the correct array, encoded once too often, plus `limit='10'` for an
  integer. Those are encodings of the intended value, not different values. Deliberately
  *not* coerced: a multi-line string for an array, because splitting it on newlines
  would guess how many items were meant and a gap count is load-bearing; likewise a
  non-numeric string, a boolean where a number belongs, and malformed JSON.
- **The streaming-deadline message counts reasoning as well as reply.** It reported only
  the content length, so a thinking model streaming everything through the reasoning
  channel was described as having produced "0 characters so far" — the opposite
  diagnosis for a run that had emitted six thousand characters of reasoning and simply
  never finished. Caught by the deadline itself firing on qwen3-vl:32b in a real run.
- **A tool name with a stray space resolves to the tool that was meant.** No registered
  tool has whitespace in its name — not the builtins, not the `mcp__server__tool` form —
  so `read_ file` can only mean `read_file`, and answering "unknown tool" to it is a
  true statement about a name the model never meant to write. Observed 39 times across
  four runs, one spending 25 of its 76 actions on it while every reply already listed
  the available tools: explaining could not help, because the model was not choosing the
  name, its output was corrupted. A name still unknown after the whitespace is removed
  still misses.
- **A note written twice is one note.** A run wrote one and the same observation 364
  times — 365 of its 390 actions — and every call succeeded, so nothing saw it: the
  chat-only streak reset on each, and neither failure tracker looks at successes.
  `add_memory` now returns the existing entry for identical text and the tool says so
  instead of reporting a write that did not happen.
- **The literature gate's example is no longer a usable observation.** The text that run
  repeated was the gate's own placeholder, "PAPER-0001 Theorem 2.1, p.5: asymptotic
  error bound …", pasted back verbatim — and PAPER-0001 contains no Theorem 2.1. An
  illustration a model can send straight back is an invitation to invent authority, so
  the example is written as a shape to fill in from the paper actually read.
- **A missing argument names the one that was sent instead.** Across the recorded runs
  this failure is a renaming, not an omission: `memory_add` wanted `text` and got `note`
  or `content`, `claim_new` wanted `statement` and got `claim`,
  `dossier_known_result_add` wanted `source_artifacts` and got `paper_id`. Nothing is
  renamed automatically — only the model knows whether its `note` was the entry text or
  a side remark, and guessing would put words into an artifact.
- **An unknown dossier id names the ones that exist.** A typo is the usual cause (runs
  asked for `PROPROBLEM-0001` and for a `PROBLEM-0003` that was never created) and a
  workspace almost always holds exactly one dossier.
- **Refusing to read a workspace file points at the right tool.** A recorded proof
  pointed at `paper_fetch`, sending the model to the literature when it asked for its
  own draft; a paper's reading note under `summaries/` got a generic hint that named no
  way to read a paper at all, while the same paper's bytes under `papers/` were
  recognised.
- **A rejected argument says what arrived and what shape to send.** "Argument 'gaps'
  must be a array." is ungrammatical, silent about what was sent, and shows nothing to
  correct against; a Sendov run passed its whole gap list as one newline-separated
  bullet string. The message now names the received type and, for the two shapes models
  get wrong most often, shows the JSON to send — built from the model's own first item.

## [0.0.8] — 2026-08-16

The release where the formal-verification path was used in anger for the first time,
and mostly did not survive it. `proof_submit` gives a model the verifier directly —
write formal source, read the checker's error, fix it, resubmit — and running the
calibration examples against a range of local models immediately exposed what no test
had: containerized Coq could not verify anything, rejections never taught the
certificate format, a list-shaped variable spec crashed the backend into a Python
traceback, four leading system messages broke whole model families on turn one, and a
model's own lemma numbering was read as a citation, making correct work impossible.

Two defects reached the invariant the project exists to defend. Evidence typed
`FORMAL_PROOF` counted as verification-grade with no artifact behind it at all; and an
SMT verdict printed next to a parse error was taken at face value, so a typo in a
constant name produced an accepted formal proof. Both are closed, and verification-grade
evidence must now cite an accepted `PROOF-*`.

The loop learned to notice when it is going in circles: guards for an acquisition
streak that never reads anything, for the same error arriving from ever-changing
arguments, and for a model call that simply never returns — each calibrated against
recorded runs rather than guessed. `opentorus eval digest` reports the same patterns
over a finished workspace. Reports and PDFs gained one design system, and the example
collection grew to twenty-odd open problems, calibration dossiers with known ground
truth, and campaign dossiers whose verdict is derived from artifacts instead of prose.

### Changed
- **One report design, two renderings.** The HTML report — what an export falls
  back to when there is no TeX toolchain or no model — was four CSS rules on
  system-ui, so the same dossier looked like a different document depending on
  which path produced it. Both now draw from
  `opentorus/research/dossier/theme.py`: the same palette, the same accent sans
  headings with a hairline rule, the same tinted output panels with an accent
  left rule, the same artifact ids, gap markers, status chips, booktabs-style
  tables and metadata strip under the title. The status→colour rule lives in
  `theme.STATUS_KIND` and is now the *only* copy, used by both the LaTeX
  `status_chip()` and the HTML `.chip-*` classes — so "colour never upgrades a
  claim" is one rule, not two that can drift. The LaTeX class repeats the hex
  values because it cannot import Python; a test pins the two copies together.
  The HTML keeps its stylesheet inlined (the report is a local file) and adds no
  new external fetch — MathJax remains the only one.
- **`preprint.cls` is gone; `opentorus.cls` replaces it.** The vendored
  third-party class (and the `opentorus.sty` layer written on top of it) are
  retired in favour of one self-contained class. Besides dropping the unused
  machinery — two-column mode, abstract/keywords/MSC/novelty front matter,
  cleveref equation formats, the BSD-2 license file — it drops `lineno`, the
  package whose patching of `verbatim` was the reason captured output could not
  wrap in the first place. Plain `\begin{verbatim}` now wraps too; `otoutput`
  stays the canonical name. Compiles are unchanged visually, and
  `_install_templates` deletes the retired `preprint.cls`/`opentorus.sty` pair
  from workspaces built by an older OpenTorus.
- **The exported report PDF has a house style.** The dossier PDF was the stock
  third-party preprint class with Computer Modern, `\hline` tables and raw
  `verbatim` dumps. The bundled `opentorus.cls` (re-installed on every compile,
  so it reaches dossiers built by an older OpenTorus) adds Libertinus
  text/math with `microtype`, accent-coloured headings with a hairline rule, a
  metadata strip under the title (dossier id, status, formalization, artifact
  counts), booktabs/tabularx tables, tinted output panels, status chips and
  callout boxes. Every optional package is probed with `\IfFileExists`,
  so a minimal TeX installation still compiles — it just gets a plainer document.
  Two of the conventions carry epistemic weight rather than being decorative:
  chip colour never upgrades a claim (green is reserved for
  `verified`/`formally_verified`/`supported`/`succeeded`; `unverified` and
  anything unrecognised stay neutral grey), and the "a sketch is not a verified
  proof" / "a counterexample candidate is not a refutation" caveats are now
  boxes a skimming reader cannot miss instead of sentences buried in prose. The
  compose prompt teaches the model the same macros, so the LLM-written report and
  the deterministic fallback look alike. Documented in `docs/cli-ux.md`.

### Fixed
- **Captured output ran off the right edge of the page.** Long stdout lines were
  typeset in a `verbatim` block that cannot break, so anything past the margin
  was simply lost from the PDF. Output now goes in an `otoutput` environment that
  wraps with a continuation marker. It has to be a *new* environment name:
  the then-vendored `preprint.cls` loaded `lineno`, which pinned the stock
  `verbatim` such that `fvextra`'s `breaklines` silently never fired (the class
  that replaced it does not load `lineno`), and wrapping it in a
  `\tcolorboxenvironment` defeats the breaking too (the body is captured as an
  argument and typeset at its natural width). The generator, the LaTeX sanitiser
  and the compose prompt all emit `otoutput`.
- **Markdown bold reached the page as literal `\{}textbf{...}`.** The proof-sketch
  fallback converter turned `**x**` into `\textbf{x}` and *then* LaTeX-escaped the
  result, so the command it had just written was escaped into text. Escaping now
  happens first. This also retires the old "the line contains `$`, so skip
  escaping entirely" rule: `$...$` spans are preserved either way, but a stray
  `_`/`&`/`%` in the surrounding prose can no longer abort the compile.
- **A `$$…$$` block corrupted every formula after it.** Display math spans lines,
  and the shared Markdown normaliser pairs `$` with a naive scan that reads the
  *second* dollar of an opening `$$` as an inline-math opener — from there the
  whole body pairs off by one, and `$1 + \sqrt{2}$` printed as
  `$1 + $\sqrt${2}$`. Display blocks are now lifted out before any per-line or
  Unicode pass touches the text, and emitted as `\[…\]` so the equation is
  centred on its own line instead of crammed into the paragraph. The Unicode
  guard tracks `\[…\]`/`\(…\)` as math too, so a symbol inside display math no
  longer becomes a nested `$…$`.
- **The problem statement was printed as its own source.** The deterministic
  report path escaped `statement.md` wholesale, so a statement written in
  Markdown with real LaTeX math rendered as `$W(A) = \{}mathbb{C}...$`. It now
  goes through the Markdown converter, which also gained ordered lists (numbered
  proof steps were running together into one paragraph) and keeps indented
  continuation lines inside their bullet.
- **`\item [REFEREE] …` was read as an optional argument** and typeset as a
  hanging description label. List items whose text starts with `[` are now
  guarded.
- **Claim-table cells collided.** The claim column was 51pt wide for an artifact
  id that needs 61pt, and a status chip is an unbreakable box up to 74pt, so
  `COUNTEREXAMPLE_CANDIDATE` overprinted the statement next to it. The table is
  now four columns with the type stacked under the id, sized against the widest
  real status and type values, with break opportunities after underscores and a
  `\strut` so a short cell aligns with the statement it belongs to.
- **The HTML report lost structure the Markdown had.** Its converter emitted one
  `<p>` per source line, so soft-wrapped prose read as a column of fragments;
  numbered proof steps became paragraphs instead of an `<ol>` (the same defect
  fixed on the LaTeX side); a `$$…$$` block split across paragraphs so MathJax
  never matched the delimiters and the reader saw raw `\lVert p(A)…` source; and
  `_emphasis_` printed its underscores. All four are fixed, with `_` emphasis
  guarded against intra-word matches so `HEURISTIC_ONLY` and `experiment_proof`
  stay literal. Pipe tables render as tables. `tests/test_html_export.py` is new —
  the HTML export had no tests at all.
- **An unchecked hole in EVAL-002.** `FORMAL_PROOF` / `VALIDATED_NUMERICAL`
  evidence counted as verification-grade as soon as its *type field* said so —
  the artifact was checked only for `EXPERIMENT`, i.e. for the one type that may
  never verify anything. `problem evidence --type FORMAL_PROOF` with no artifact
  at all promoted a claim to `formally_verified`. Verification-grade evidence
  must now cite an accepted `PROOF-*`; missing, rejected and inconclusive
  attempts are refused with a reason. Six test files rested on the hole (one with
  the summary "accepted Lean proof" and no Lean proof) and now produce a real
  verifier run through the new `accepted_proof` fixture. New:
  `problem evidence --artifact PROOF-0003` — the option was missing, so the
  legitimate route did not exist. The interval path
  (`record_validated_numerical`) records its own `PROOF-*`, so every promotion is
  traceable in `proofs.jsonl`.
- **A read timeout killed runs with a raw traceback.** `urlopen` raises a bare
  `TimeoutError` on a read timeout — an `OSError`, but not a `URLError`, so it
  escaped every handler that caught only `URLError`. Four example runs
  (bollobas-nikiforov, calibration-brouwer, kalai-3d, marcus-de-oliveira,
  2026-08-16 06:19) died in the tool-calling probe before doing anything, even
  though `require_tool_calling_provider` promises in its own docstring that a
  transient probe failure never blocks a run. Fixed at all five sites: the tool
  probe, both literature fetches (every `lit_search`/`paper_fetch` ran through
  the same hole), embeddings, and vision. An unreachable server is no longer
  probed a second time on top.
- **A proof could answer for a claim in a different store.** Proof attempts now
  record which claim store their `claim_id` belongs to: a dossier proof no longer
  answers a workspace lookup of the same id, and verification evidence rejects a
  proof recorded under a different dossier. The collision was not hypothetical —
  a real run held `CLAIM-0001` twice, once as "for every bipartite graph H and
  every graph G …" in the dossier and once as a statement about one 4-vertex
  graph in the workspace store, and the workspace promotion gate keyed on the
  bare id. Note the scope honestly: the id collision is real
  and recorded, but the promotion path it could open needs a workspace with
  several dossiers, one of them demanding formalization, and an accepted proof
  filed under another — a combination no recorded run reaches. This closes a
  gap reachable in principle; it does not repair an observed failure.
- **An undeclared constant could fabricate a formal proof.** An SMT verdict
  printed alongside `(error …)` lines is now inconclusive in both directions. z3
  and cvc5 drop an assertion they cannot parse and solve what remains, so the
  verdict describes a different problem than the one submitted. Verified against
  z3 5.0.0: four lines with a typo'd constant name previously produced
  `accepted=True` — and an accepted verification artifact is the one thing that
  may promote a claim to `formally_verified`. Surfaced by the first real SMT run
  in the project's history (a Barnette encoding), which reported `sat` after two
  "unknown constant" errors and was recorded as a rejection of mathematics the
  solver had never seen.
- **Verifiers reported non-results as rejection.** `smt.py` never inspected
  `timed_out` and never set `inconclusive`: a z3 timeout, an explicit `unknown`,
  and a solver error with no sat/unsat token all reached the model as `REJECTED`
  — against the documented promise to report such cases "never as a rejection".
  Likewise a signal-killed Lean/Coq process (SIGSEGV, OOM) and a failed container
  start were not distinguished from a real rejection, and interval arithmetic
  reported an enclosure that was merely too coarse as a refutation, though the
  method is one-sided. New helper `ran_at_all()` in `verifiers/base.py`; exit 1
  with error output remains a genuine rejection.
- **`exp replay` ignored the command and the container.** Replay hard-coded
  `python run.py` on the host and skipped `experiment.command`, `run_from` and
  the pinned environment — for every containerized experiment (so, every example)
  it ran with the wrong toolchain, and the divergence it reported was an artifact
  of the replay itself. It now goes through `_run_via_backend`, the same path as
  the original run, and additionally compares the git commit and image digest
  that were recorded all along but never checked.
- **A test poisoned the session.** `test_tool_support.py` set a module attribute
  raw instead of through `monkeypatch`, so every later test in the run saw a
  permanent "this model cannot call tools".
- **`paper_fetch` leaked exceptions to the model.** `SourceError` is a
  `RuntimeError`, not an `OpenTorusError`, so every HTTP failure escaped the
  tool's handler and reached the model as "Tool paper_fetch failed: HTTP 404 from
  …". Observed twice in live runs — one of them instructive: arXiv 1709.04009
  *exists* but is withdrawn and has no PDF at all, so the model had done nothing
  wrong. A 404 now explains both possibilities (no such identifier, or a
  withdrawn / source-only record), points at `lit_search` as the source of
  identifiers, and says to mark the step `[GAP-n]` instead.
- **A withdrawn paper discarded the whole record.** The resolver only decides that
  a PDF *should* exist; the fetch can still fail for a perfectly legitimate record,
  and `acquire_paper` let that failure abort the acquisition. arXiv keeps metadata
  and abstract for withdrawn and source-only papers but serves no PDF at all, so a
  citable record was thrown away and the model was handed an error for something it
  had not done wrong. Such a fetch now degrades to metadata-only — exactly how
  paywalled sources are already handled — with the reason recorded in the paper's
  access note.

Five defects in the formal-verification path, every one surfaced by running the
calibration examples against a range of local models — before that, no run had
ever called `proof_submit`, so the tests were green on stubs and well-formed input:

- **Containerized proof assistants could not verify anything.** `coqc` writes
  `.vo`/`.glob` next to the source and the container uid cannot write into a
  host-owned temp dir, so every submission failed "Can't find file". The verifier
  now makes its temp file readable for foreign uids, and the strassen example
  drives `coqtop -batch -load-vernac-source`, which checks without compiling.
  Verified end to end: a valid `ring` lemma is ACCEPTED, a false one REJECTED with
  the exact error line — the project's first real Coq verification.
- **Rejections never taught the certificate format.** Two capable models submitted
  malformed certificates and then switched backends instead of fixing the shape.
  Rejected and inconclusive `proof_submit` results now carry a minimal *valid*
  example for the JSON-certificate backends plus an explicit "do not switch
  backends because of a format error"; the tool description keeps a one-line
  summary so the per-request cost stays small.
- **The sympy backend crashed on a list-shaped `vars`**, handing the model
  `'list' object has no attribute 'items'` — 19 submissions across the benchmark
  died that way, exclusively among the models that engaged the formal path hardest.
  `vars`/`variables` are now accepted as object *or* list, unknown shapes degrade
  to plain symbols, and `proof_submit` wraps any backend exception into a
  malformed-input rejection, so no Python traceback ever reaches a model again.
- **Four leading system messages broke strict chat templates.** Whole model
  families failed on turn 1 with zero tool calls. The cause is the message *count*,
  not its position — Ollama's own error ("system message must be at the beginning")
  is misleading; verified against the server, one leading system message works and
  two do not. `to_ollama_messages` now merges the leading run into one, content
  preserved verbatim.
- **A model's own lemma numbering was read as a citation.** "- Lemma 6 (…):
  PAPER-0003 shows …" was attributed to PAPER-0003, which has no result 6 —
  unfixable from the model's side, and it cost one benchmark cell all 13 of its
  `proof_write` attempts and its entire deliverable. A result label that opens a
  line, bullet or heading is now treated as the author's own numbering; citations
  appear mid-sentence ("by Lemma 1 of PAPER-0003", "PAPER-0003 Theorem 2").

### Changed
- **Stable prompt prefix.** The workspace inventory sat at position 2 of every
  request and changes almost every step, so the reusable prefix ended after a few
  hundred tokens and the whole history behind it was re-evaluated on every call.
  Measured on a real run (matrix-spencer, gemma4:31b, server-reported numbers):
  1,263,204 prompt tokens against 51,534 completion tokens, with
  `prompt_eval_count` growing 8k → 30k in step with latency — 96 % of all
  processed tokens were prompt sent again. Volatile blocks now sit behind the
  history, directly before the last turn (not after it: the last turn is the
  answer template, and a tool_call/tool_result pair must not be split).
  `context.stable_prefix: false` restores the old order.
- **Failed attempts survive compaction.** The summarizer kept only tool *names*,
  so a dead end survived as the word `proof_write` in a comma-separated list —
  while the loop and the prove loop explicitly promise the user that the failed
  call and its error are preserved in the session log. Tool results now carry an
  `ok` flag, and the summary lists failed calls with their error text and a
  do-not-repeat note.
- **The referee flags a quantified claim whose verification artifact compares
  constants** (observed: `1/8 >= 1/16` as the only accepted proof in a dossier
  about all bipartite graphs). Advisory, not blocking: an accepted proof shows
  that something was checked, never that it was the claim citing it, and a
  heuristic about an artifact's meaning should raise the question rather than
  halt the run.
- **The search nudge now tracks the acquisition-to-processing ratio**, not just
  consecutive searches: a fetch between every pair of searches reset the streak
  counter while nothing was actually read (observed in a real run: 106 acquisition
  calls against 5 processing calls, and not one proof draft). Calibrated against
  twelve recorded runs rather than guessed — at ratio 4.0 with a minimum of 15
  acquisitions it fires on exactly that run and on none of the other eleven, whose
  end ratios sit between 0.2 and 1.6. Processing is the complement of acquisition,
  so a newly added tool cannot silently inflate the ratio; inventory polls count on
  neither side. The nudge rides on acquisition calls only, so a run that has moved
  on to processing is never nagged about its own results.
- **A third dead-end guard: the same error from N distinct argument sets.** The
  existing guards key on the whole `(tool, args, error)` triple, so a model that
  rewrites its arguments every time repeats none of them while making the
  identical mistake — circling then looks like progress. Observed on a recorded
  run as 36 `proof_write` failures across 26 argument sets, 11 of them returning
  one identical citation error. Calibrated against the recorded runs: the two
  pathological ones reach 11 and 9 distinct argument sets per error, every healthy
  one reaches 1. The hint is worded differently from the repeat hint, because here
  the model *is* changing something, just not the thing that matters.
- **Memory for non-consecutive dead ends.** The identical-failure guard held
  exactly one key, so a model alternating between two failing calls (A, B, A)
  reset the streak every time. Every distinct failure is now counted across the
  whole run and named when it reappears.
- **`agent.max_wall_seconds`** (off by default): a wall-clock budget per run,
  checked between steps. Every other guard assumes turns come back — a hung model
  call satisfies none of them.
- **Verification cache.** Byte-identical source is answered from the ledger
  instead of re-checked (minutes per submission on Lean/Coq), with no second
  artifact and an explicit note that resubmitting unchanged source cannot change
  the verdict. Inconclusive runs are deliberately not cached.

### Added
- **`opentorus eval digest [PATH…] [--json]`** — reads a finished workspace and
  reports the tool histogram, repeated failures with their error text, the
  longest search streak, verifier outcomes split into accepted / rejected /
  inconclusive, claim statuses, experiment outcomes, and the prompt share of
  tokens. Descriptive, not judgmental: the flags name patterns that have marked
  stuck runs before, and say nothing about the mathematics. On
  `examples/matrix-spencer` it reproduces the three findings that were hand-work
  before: a 5-call search streak, a proof written but never submitted, and a
  96 % prompt share.
- `proof_submit` agent tool: the model can now submit formal source (Lean 4, Coq,
  SMT-LIB, interval/sympy certificates) to the enabled verifier backends directly
  from the prove loop, closing the write → compile → error-feedback → resubmit
  loop that previously required a human running `opentorus proof submit`. The
  tool records the same `PROOF-*` artifact as the CLI (verbatim accept/reject
  output, `validates` edge on accept), preserves rejected attempts, refuses
  dangling claim ids, and reports unavailable backends as "check NOT run" —
  never as a rejection. Registered only when a verifier backend is enabled
  (interval + sympy are on by default); blocked during the literature phase.
  An accepted attempt still never promotes a claim by itself — status changes
  keep going through the gated update (EVAL invariants unchanged).
- `ProofAttempt` records now carry `inconclusive` and `outcome`, so a verifier
  timeout/crash is distinguishable from a mathematical rejection in the
  artifact, not just in the transient tool output.
- The prove prompt advertises the formal-check step (workflow step 7b) when — and
  only when — verifier backends are enabled, so default mock/golden transcripts
  are unchanged.
- Twelve new example workflows under `examples/`. Seven verified-open problems
  spanning numerical linear algebra, discrepancy theory, polyhedral
  combinatorics, spectral graph theory, and number theory: the
  complete-pivoting growth factor, Matrix Spencer, Marcus–de Oliveira, Komlós,
  Kalai's 3^d, Bollobás–Nikiforov, and Lehmer's problem — all with genuinely
  *general* (quantified) target statements, several chosen because candidate
  discoveries (counterexamples, certificates) are finite and machine-checkable
  via `proof_submit`. Two fixed-instance drafts (NIEP at n=5, the rank of the
  3×3 matrix multiplication tensor) were dropped before release under the
  general-conjecture scope policy: fixed instances are tools inside a dossier,
  not primary targets. Plus a new **calibration**
  category with known ground truth to regression-test the honesty pipeline:
  Crouzeix and Brouwer (2026 claimed proofs must be reported "under review"),
  Sendov (resolved August 2026 with a Lean-verified proof — originally slated
  as an open example, moved to calibration when the creation-time status check
  caught the resolution), Casas-Alvero (claimed proof + real small-degree
  verification), and Perfect–Mirsky (`prove --disprove` must reproduce and
  verify the known n=5 counterexample). Problem statuses were verified against
  the literature on 2026-08-14 at example-creation time.
- A fifteenth example, `calibration-strassen-formal`: the first to use the
  Lean 4 / Coq proof-assistant backends. Correctness of Strassen's 7-product
  scheme (and Laderman's 23-product 3×3 scheme as a stretch goal) is a finite
  system of ring identities, each mechanically closed by `ring` — so the
  calibration target is the `proof_submit` write → compile → error-feedback →
  resubmit loop itself, not the mathematics. The driver picks host `coqc`, a
  Mathlib-enabled Lean project via `LEAN_PROJECT`, or a containerized-Coq
  fallback (`docker run -v /tmp:/tmp coqorg/coq:8.20 coqc`, smoke-tested) so
  no host prover installation is required.
- The `polynomial-hirsch` example gained a containerized **polymake**
  environment (Debian package in `debian:trixie-slim`, smoke-tested:
  `cube(4)->GRAPH->DIAMETER` → 4) and an explicit experiment program: certified
  graph-diameter computations, reproduction of the Santos /
  Matschke–Santos–Weibel records, and a spindle search — a `d`-spindle of
  length `> d` is a finite, exactly checkable Hirsch-violating certificate,
  while the *polynomial* conjecture (an infinite-family statement) stays
  honestly out of reach of any single computation. Santos's arXiv:1006.2814 is
  pre-registered as the source paper.
- New example `difference-triangle-set`: construct a (7,5)-difference triangle
  set with scope ≤ 111 (scope 112 known) or certify nonexistence. The most
  certificate-friendly target in the collection — dual independent validators,
  exact `proof_submit` re-checks for constructions, DRAT/LRAT/SMT certificates
  for nonexistence, a five-phase workflow and a six-category claim policy baked
  into the statement; container ships CP-SAT (ortools), z3, and python-sat.

- **General-conjecture scope policy layer** (`dossier.scope` + `opentorus
  problem verdict`). Dossier target statements are classified as `general` /
  `fixed_instance` / `unclear` (unbounded quantifiers vs. single-parameter
  record asks; instances mentioned inside a general statement stay general —
  they are tools). A campaign-level terminal classification is *derived* from
  the recorded artifacts: `GENERAL_CONJECTURE_PROVED` requires the dossier's
  newly designatable primary claim (`primary_claim_id`, additive field;
  `problem verdict --set-primary`) to be `formally_verified`, and
  `GENERAL_CONJECTURE_REFUTED` requires a `COUNTEREXAMPLE_VERIFIED` claim
  targeting it — both additionally require a general target. Everything else
  maps conservatively downward (`VERIFIED_PARTIAL_THEOREM`,
  `VERIFIED_COUNTEREXAMPLE_TO_AUXILIARY_CLAIM`, `COMPUTATIONAL_EVIDENCE`,
  `NUMERICAL_EVIDENCE`, `FAILED_ATTEMPT`, `INCONCLUSIVE`,
  `STATUS_UNCERTAIN`); `VERIFIED_REDUCTION` is never auto-derived. The layer
  is read-only over claim statuses — the EVAL invariants are untouched, and
  tests pin that sketches, experiments, and supported claims can never produce
  the two resolving labels.

- **Campaign template and the first three campaign dossiers.**
  `examples/CAMPAIGN_TEMPLATE.md` codifies the general-conjecture workflow:
  fresh *dated* status audit at creation (never from memory — Brouwer and
  Sendov both changed status in 2026), partial results classified with sources
  instead of blanket-stamped "open", a **driver-designated primary claim**
  (`problem claim` + `problem verdict --set-primary`, so the resolving labels
  are wired deterministically, not left to model behavior), a dual research
  process (refutation and proof tracks that exchange information), and a
  closing `problem verdict`. First three dossiers built from it, audited
  2026-08-14: Graceful Tree (open; ≤ 35 vertices verified; the 2007 claimed
  proof recorded as unaccepted), Barnette (open; n ≤ 90 verified; Kardoš 2020
  recorded as a settled *neighboring* conjecture), and Caccetta–Häggkvist
  (widely open, even k = 3; triangle frontier [n/3, 0.3465n]). The remaining
  three complete the initial six, audited the same day: Frankl union-closed
  (open; Gilmer-line constant (3−√5)/2 with proven optimality for the
  approximate version — the gap to 1/2 is the campaign), Lonely Runner (open in
  general; ≤ 13 runners settled (k ≤ 12), 8–13 all 2025/26 computer-assisted
  preprints — the
  frontier method is itself computational, so the instance program engages the
  state of the art directly), and Sidorenko (open; broad settled classes, the
  approximate version holds, K₅,₅∖C₁₀ the simplest unknown case; refutation
  candidates complete to exact rational witnesses certifiable via
  `proof_submit`).

### Fixed
- A transient connection drop from the Ollama server
  (`http.client.RemoteDisconnected`, resets mid-stream, truncated stream
  chunks) escaped the provider's TimeoutError/HTTPError/URLError handlers and
  killed a literature-phase prove run (40 tool calls in) with a raw traceback.
  These now surface as a clean `ProviderError` that names the cause as a
  transient server/network hiccup and points at resuming the run — the run
  state was always preserved; the message now says so.

### Changed
- **Search-spam nudge in the agent loop.** Three real runs died in loops of
  consecutive `lit_search`/`web_search` calls that never fetched or read
  anything (11 searches in one run). Search tools stay exempt from the repeat
  guards (their results legitimately change), but from the fourth consecutive
  search on, each result now carries an explicit stop-searching instruction
  (fetch the best hit now, or proceed to the deliverable). Any substantive
  tool resets the streak; inventory polls (`paper_list`/`status`) are neutral.
  Pinned by tests in both directions.
- **Stage 2 of the formalization anchoring: a `formalization_required` referee
  finding.** When the dossier statement itself demands machine-checking
  (deterministic signal: it names `proof_submit`) and no verifier submission
  has been ACCEPTED, the hostile referee now blocks with a dedicated finding
  that reopens as a `[REFEREE]` gap — so the demand lives in the proof artifact,
  survives context compaction, and reappears in every gap listing. Escalation
  is evidence-driven: five real runs across two dossier families showed prompt
  text, workflow steps, and soft recovery nudges never produced a submission.
  The finding forces the *attempt*, never the outcome — an accepted submission
  clears it, a run that cannot comply is ended honestly by the no-progress
  windows, ordinary dossiers (statement never names `proof_submit`) are
  untouched, and the verdict stays with the artifacts. Pinned by tests in both
  directions plus a no-demand-no-finding guard.
- **Opt-in campaign gate** (`agent.prove_require_instance_work`, default off;
  set by the campaign drivers): the clean completion of a prove run is held
  until at least one experiment or one `proof_submit` is recorded. Decided on
  smoke-run evidence: both campaign smoke runs (lonely-runner fresh,
  Caccetta–Häggkvist fresh + resume with a patched START-HERE statement) ended
  with zero instance work — models follow what a gate enforces, not what
  statement prose requests (the literature phase works precisely because it is
  tool-gated). The gate delivers an explicit instruction at the recovery
  surface and forces the *attempt*, never the outcome: a model that still
  starts nothing is stopped honestly by a bounded no-progress window, failed
  runs stay preserved, and the derived campaign verdict remains whatever the
  artifacts support. Skipped in disprove mode; pinned by two integration tests
  (gate holds + honest stop; gate cleared by a recorded verifier attempt).
- The gap-fill recovery hint now re-anchors the formal-verification step: when
  verifier backends are enabled and no `proof_submit` has been accepted yet, it
  tells the model to machine-check any gap that reduces to a finite check via
  `proof_submit` instead of `exp_run` — and the nudge disappears once an
  accepted submission exists. Motivated by the first calibration runs, where
  `muse-glimmer:30b` ran per-degree verifications as evidence-grade experiments
  and never called `proof_submit` despite workflow step 7b; whether a stronger
  anchor (a referee gap) is needed awaits the strassen-formal litmus run.
- The formalization nudge now also reaches **smooth runs** (Stufe 1b). The
  strassen-formal litmus showed the gap-time nudge above never fires when every
  gap closes cleanly — the run never enters recovery. Completion is now held
  open for one bounded window (< 2 model steps) when all gaps are closed,
  formal backends are enabled, and no verifier submission was accepted: the
  completion-surface hint tells the model to machine-check the argument's
  finite core via `proof_submit` NOW, or record in `memory_add(kind=decisions)`
  why nothing is formalizable. Soft by design — after the window the run
  completes regardless (a hard formalization gate is the scope-policy layer's
  decision, not the loop's); skipped in disprove mode; an accepted submission
  clears it. Pinned by tests: the nudge reaches the model exactly once and an
  ignoring model still finishes without extra tool work.
- The eight original example workflows now default to `muse-glimmer:30b`
  (driver-script `OPENTORUS_MODEL` fallback, workspace `config.yaml`, READMEs),
  matching the model the new calibration examples were written against.
  Historical `usage/ledger.jsonl` records keep the model actually used at run
  time (`gpt-oss:120b`).

### Fixed
- **`opentorus config set` no longer reports success without persisting.** The
  surgical config writer only synced values into lines already present in the
  file, so any field added to the Config model after a workspace's
  `config.yaml` was written (five had accumulated, including the campaign gate
  and the interval/sympy verifier toggles) was silently dropped on write while
  the CLI printed a green "Set" — a field-test run executed without the gate
  its driver believed it had enabled. Fixed in three layers: the default
  template now carries every scalar Config field (pinned by a completeness
  test that fails on any future field without a template line), `write_config`
  appends fields missing from older workspace files into their existing
  section instead of dropping them, and the CLI re-reads the file after
  writing and fails loudly on any mismatch.
- Campaign status audits corrected after an independent peer cross-check
  (audit-amended 2026-08-15 in the dossiers): Lonely Runner is settled up to
  **13** runners, not 12 (arXiv:2604.23906 added; chronology and
  computer-assisted qualifiers fixed); Frankl's Gilmer-line citations
  re-attributed (arXiv:2211.11731 = Alweiss–Huang–Sellke, Sawin =
  arXiv:2211.11504, refinement = Cambie); Sidorenko's blow-up result stated
  precisely (some blow-up per graph, not all blow-ups), a tangential source
  dropped from the preregistered papers, and K₅,₅∖C₁₀ identified as the
  10-vertex Möbius ladder (not the Möbius–Kantor graph).
- The dossier honesty linter (shared by the hostile referee) no longer flags
  four classes of *honest* phrasing, all surfaced by the first real calibration
  runs: (1) negated experiment claims ("experiments support X **but do not
  prove** it" — the exact wording the linter itself asks for) and negated
  proof-verb phrases ("fails to prove the conjecture"); (2) "trivial" as a
  classifier noun phrase ("the trivial family $(X-\alpha)^d$") as opposed to
  dismissive uses ("the proof is trivial"), which stay flagged; (3) passive
  result-assertions attributed to a local source on the same line ("is proved
  for $d=p^k$; PAPER-0004 Theorem 3") — first-person and "provably" claims are
  still flagged, citation or not; (4) the linter re-flagging the quoted phrase
  inside a referee finding's own text ("[REFEREE] … 'is proved' …") — on such
  lines only text outside the quotes is linted, so smuggled overclaims still
  trip; (5) fenced code blocks (``` / ~~~), so a Coq template's `Qed.` in the
  statement echo is verbatim material, not a proof claim — inline `code` spans
  stay linted so prose cannot hide behind backticks (found by the
  strassen-formal calibration run); (6) attributed proof-verb phrases
  ("Rosenfeld proves the conjecture for k=7 … PAPER-0002") — the same
  same-line-citation licensing as (3), extended to the proof-claim pattern and
  to `lint_proof_sketch`'s resolves-an-open-conjecture warning ("The conjecture
  holds for k=8 … PAPER-0004" is a cited partial result); self-claims
  ("we prove", "QED", "hence proven") stay flagged, citation or not (found by
  the lonely-runner campaign smoke run). Each class is pinned by tests in both
  directions (the false positive gone, the true positive kept).

- **`apply_patch` no longer returns an empty success for a no-op patch.**
  Forensics of a real run showed `old == new` producing `ok("")` — a blank tool
  message with zero signal, which the model answered by re-issuing the same
  call verbatim, invisible to every loop guard *because the result was a
  success*. A no-op patch is now a failure with an actionable message, and a
  successful patch never returns empty content.
- **Every `_run_tool` rejection path now reaches the audit trail and the
  identical-failure tracker.** Unknown-tool, tool-gate, repeat-block,
  missing-file-repeat, permission/not-confirmed, and the literature-gate
  `proof_write` block all feed `_note_tool_failure` (six identical rejections
  end the run), and the previously unlogged repeat-block / read-cache paths now
  write `actions.jsonl` entries — an agent action with no audit record was a
  standing exception to the provenance promise.

Three fixes from a diagnosed prove-loop cycle (60 byte-identical `proof_write`
rejections over 41 minutes under `max_steps=inf`, ended only by Ctrl-C):

- **Citation attribution no longer bleeds across papers.** The `PAPER-*` id in a
  citation match was dropped (regex without a capture group), so every cited
  theorem number was checked against *every* cited paper — rejecting the whole
  `proof_write` for a citation the model never wrote, an unfixable error.
  Attribution is now nearest-mention within the sentence: "PAPER-0004 provides
  … Theorem 2.4" attributes 2.4 to PAPER-0004 only, and a number the *named*
  paper genuinely lacks still blocks.
- **A failing tool call no longer counts as progress.** The agent loop tracks
  identical `(tool, args, error)` failures: from the third one the error is
  annotated with an explicit do-not-repeat instruction, and after six the run
  stops honestly instead of cycling — regardless of which check produces the
  rejection. Varying calls, different errors, and eventual successes reset the
  streak; network tools with changeable results are exempt.
- **The prove draft phase now has its own no-progress window.** The gap-fill
  no-progress backstop was armed only after the first primary proof existed, so
  a draft whose deliverable failed every time was invisible to every guard once
  the step caps were inf. The draft phase now ends after
  `prove_gap_fill_no_progress_steps` steps without a new proof attempt or new
  evidence (via the new `AgentLoop(stall_check=…)` seam), with failed attempts
  preserved.

## [0.0.7] — 2026-07-04

This release makes the recorded artifacts match what actually happened, end to end.
Gap-laundering is challenged at the artifact boundary (deleting `[GAP-n]` markers is
not closing gaps), agent-run experiments become visible to reports, the status gate,
PDF export, citations, and the evidence gate, PDF export failures state their real
cause instead of blaming a missing TeX install, and experiment manifests stop
misattributing containerized runs to the host interpreter — verified by re-running
every recorded example experiment with byte-identical outputs. Windows becomes a
working platform (CreateProcess execution, POSIX-form manifests, cross-platform CI
on macOS/Windows and Python 3.11–3.14), and the project is citable via CITATION.cff
with a working security-reporting channel.

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
- Experiment provenance corrections, found auditing real containerized runs:
  the manifest's `environment:` block silently recorded the HOST interpreter
  (e.g. `python_version: 3.14.2`) for runs that executed inside a
  `python:3.11-slim` container — it now carries `captured_from: host` so the
  runtime is identified by the image fields, not misread from the host capture;
  locally-built images (`…:local`) recorded `image_digest: null` because the
  "digest" was only parsed from the ref, never resolved — the runtime image ID
  is now resolved via `docker/podman image inspect` (best-effort) into a new
  `image_id` manifest field, so digest-less local builds are still pinned to
  exact content; and the workspace experiment record now persists a one-line
  factual `result_summary` ("exit 0; stdout: …") on every run, so reports and
  `problem show` no longer re-derive it from the results directory. Also, curly
  apostrophes/quotes/ellipses now map to LaTeX-safe ASCII in PDF export instead
  of being dropped by the NFKD fallback ("Stewart's bound" no longer typesets
  as "Stewarts bound").
- Agent-run experiments were invisible to every dossier consumer: the report
  rendered "## Experiments … (none)" over 7 completed docker runs, the status
  gate could never derive `EXPERIMENTAL_ONLY` from `exp_new`/`exp_run` work, the
  PDF export skipped their stdout, and citing one as evidence was rejected as a
  fabricated EXP-* id. Root cause: those tools record the WORKSPACE experiment
  store (`.opentorus/experiments/EXP-*`) while report/status-gate/PDF/citation
  checks read only the dossier store (`problems/<pid>/experiments/`). A merged
  view (`list_problem_experiments` / `get_problem_experiment`) adapts attributed
  workspace runs (same attribution rule as `problem show`: tagged with the
  problem, plus untagged in single-dossier workspaces) and now backs all four
  consumers plus `proof_evidence_count`.
- `problem export --pdf` blamed a missing TeX install for EVERY HTML fallback:
  the CLI printed "No LaTeX engine found on PATH — install TeX Live" even when
  engines were installed and the real cause was a LaTeX compile failure or the
  export honesty gate refusing to typeset an overclaiming document (observed
  live: a refusal over 4 'provably' overclaims surfaced as "install TeX").
  `ProblemExportResult` now carries `html_reason`; the CLI prints the actual
  compile error or refusal text and points at the kept `.tex` source, reserving
  the install hint for a genuinely missing toolchain.
- Structured `lemmas`/`definitions` entries passed as JSON objects leaked Python
  dict reprs into proof bodies ("{'citation': ['PAPER-0005 Theorem 2.1'],
  'statement': …}"), which then flowed verbatim into report.md, the HTML export,
  and the PDF. `proof_write` now renders such items as markdown — statement text
  plus a visible "*(cited: …)*" line — so the citation stays scannable by the
  grounding check and reports read as prose.
- Experiments recorded by the agent's `exp_new`/`exp_run` tools (workspace-level
  `.opentorus/experiments/EXP-*`) were invisible to `proof_evidence_count`, which
  only read the dossier-level store — so real experiment work never counted as new
  evidence: the gap-closure challenge fired even after the model ran experiments
  (observed live: a prove run with 7 real EXP-* was challenged twice and had to fall
  back to one-gap-per-write), and experiment activity never reset the prove loop's
  no-progress window. Both stores are counted now; `exp_new`'s dedupe-by-command
  keeps re-runs of the same experiment from inflating the count.
- Windows support, caught by the new CI matrix on its first run: guarded shell
  execution tokenized every command with POSIX `shlex` rules, which eat the
  backslashes in `C:\...\python.exe` — so on Windows every local command,
  experiment, replay, and quality gate failed with exit 127 (`WinError 2`).
  Windows now hands the command string to `CreateProcess` verbatim (still no
  shell); POSIX hosts are unchanged. Container mount sources (Docker/Podman and
  Apptainer binds) and the recorded `containerfile` workspace path are now
  written in POSIX form on every host, so manifests prepared on Windows replay
  elsewhere. Experiment `run.sh` scripts are always written with LF line
  endings — the Windows text-mode default produced CRLF, which bash rejects
  (`set -euo pipefail\r`) — and a host without bash now records an honest
  failed run with a clear message instead of crashing.
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
