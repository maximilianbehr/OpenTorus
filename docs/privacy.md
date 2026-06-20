# Privacy

OpenTorus is **local-first**. Your project memory lives in `.opentorus/` on your
machine, and nothing about your project leaves your machine unless you explicitly
configure an external model or network source.

## What is stored, and where

- **Per-project**: everything under `.opentorus/` in your repository —
  configuration, session transcripts, the action log, memory, claims, evidence,
  the artifact graph, experiments, papers, datasets, repos, reports, the index,
  and the estimated usage/cost ledger. It is plain JSONL/YAML you can read,
  diff, and delete.
- **Cross-workspace** (opt-in): the knowledge base in `~/.opentorus/kb/`
  (overridable via `OPENTORUS_KB_DIR`). Only artifacts you explicitly *promote*
  land here, with their provenance retained.

To remove project memory, delete the `.opentorus/` directory. To remove KB
entries, manage `~/.opentorus/kb/`.

## The default is offline

The default model provider is `mock` — deterministic and entirely offline. No
API key and no network access are required to use OpenTorus. You opt in to an
external model (OpenAI/Anthropic/Ollama) and to literature/data network sources.

## What is sent to a provider

When you configure an external model, only the **assembled context** for a turn
is sent — and the privacy filter applies:

- Sensitive file contents (`.env`, private keys, credentials, …) are **excluded
  from provider context by default** (`privacy.allow_sensitive_context: false`).
- `/context` in the interactive session shows the provider-context privacy
  notice so you can see what the policy covers.
- A pre-egress **DLP scan** inspects outbound payloads and **fails closed** when
  it detects secrets or PII (`DlpBlocked`), before anything leaves the machine.

## Network egress (literature & data)

All scholarly/network access is governed by an egress guard:

- **Throttled** with rate limits and a daily budget.
- **Consent-gated per host** — you approve which hosts may be contacted.
- **Credential-redacted** in logs; API keys and sessions are treated as
  sensitive files.
- **No bulk harvesting and no paywall bypass.** Full text is only acquired via
  the legal resolver chain (Crossref → Unpaywall → arXiv → institutional access).

## Sharing safely

`opentorus export` and `opentorus pack export` produce privacy/license-clean
bundles for review. Even so, be mindful not to include secrets or sensitive data
in artifacts you share. See [safety.md](safety.md) for the enforcement details.
