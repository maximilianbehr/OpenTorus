# Contributing to OpenTorus

Thanks for your interest in OpenTorus! It is **pre-alpha** software, so the
internals move quickly. Contributions of all kinds — code, docs, tests, and
design proposals — are welcome.

## Development setup

OpenTorus uses a `src` layout. Work inside a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running tests, linting, and type-checking

```bash
pytest
ruff check .
mypy src
```

Please make sure tests pass and that the linter and type-checker are clean
before opening a pull request. You can also run the configured gates through the
CLI from inside a workspace:

```bash
opentorus check            # runs the configured test/lint/typecheck gates
```

## Epistemic rules (non-negotiable)

OpenTorus is an *epistemic ledger*. Its credibility depends on one invariant:

> **Evidence is not truth.**

Any contribution that touches claims, evidence, experiments, proofs, reports, or
the honesty linter must preserve these rules. They are enforced in
`opentorus.research.dossier.validation` and covered by `tests/test_dossier.py`
(EVAL-001..008) — do not weaken those tests to make a feature pass.

1. **Numerical experiments and proof sketches only ever *support* a claim.** They
   must never set a claim's status to `verified` or `formally_verified`.
2. **Only a verification artifact promotes a claim.** `formally_verified` requires
   an accepted formal proof; a `COUNTEREXAMPLE_VERIFIED` requires an explicit
   verification artifact (a verified proof attempt or `FORMAL_PROOF` evidence).
3. **No hallucinated authority.** A `THEOREM`, `REFERENCE_FACT`, known result, or
   bibliography entry must cite a *local* source artifact (`PAPER-*`, a theorem
   reference, or a verified local artifact). Missing metadata is marked missing,
   never invented.
4. **Reports never silently upgrade evidence into proof.** Generated text uses
   status-accurate language and is run through the artifact-aware honesty linter.
5. **Failed attempts are first-class.** They are preserved, not discarded, and
   not silently retried.

If you add a new claim type, status, evidence type, or report phrasing, add a
test that pins down its honest behavior.

## Pull requests

- Keep changes focused and small where possible.
- Follow the existing milestone scope; large new directions are best discussed
  first via a **design proposal** issue.
- Update docs and `CHANGELOG.md` when behavior changes.

## Code of conduct

By participating, you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).
