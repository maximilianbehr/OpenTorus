# Privacy

OpenTorus is **local-first**. Your project memory lives in `.opentorus/` on your
machine, and nothing about your project leaves your machine unless you explicitly
configure an external model or network source.

## What is stored, and where

- **Per-project**: everything under `.opentorus/` in your repository —
  configuration, session transcripts, the action log, memory, claims, evidence,
  the artifact graph, experiments, papers, datasets, repos, reports, the index,
  the campaign event logs under each dossier, the theorem-reference ledgers, the
  estimated usage/cost ledger, the **routing ledger** (`usage/routing.jsonl`:
  which model profile was leased for which task class, and why) and the doctor's
  capability probe cache. It is plain JSONL/YAML you can read, diff, and delete.
  Both ledgers are local-only records; nothing reads them off the machine, and
  credentials appear in them by environment-variable *name* only.
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
- A pre-egress **DLP scan** inspects outbound payloads before anything leaves the
  machine. A **secret** (API key, private key, bearer token) **fails closed**: the
  send is blocked and reported. **PII** (email addresses) is **redacted** by default
  and the turn proceeds — `governance.dlp_pii` selects `redact` (default), `block`
  (the old fail-closed behaviour) or `off`. Redaction is the default because every
  academic PDF carries author emails: blocking on them closed the paper-reading
  workflow for every cloud provider, and the only way out was disabling DLP entirely,
  which gave up secret protection as well. The redaction rewrites the outbound payload
  in full — message text *and* tool-call arguments — so the address never reaches the
  wire, and the send is blocked outright if any PII survives the rewrite. PII redaction
  is not a disk control: a message is appended to `session.jsonl` before the turn
  carrying it is screened, so the workspace log still holds the original text (emails
  included). **Secrets** are different: `session.jsonl` and `actions.jsonl` are
  secret-scanned before every write and a detected secret is replaced by a masked
  preview, so an API key a tool printed never lands on disk.
- Child processes (shell commands, background jobs, local experiments, MCP servers)
  never receive this process's credentials: their environment is an allowlist with
  every credential-named variable removed (see [safety.md](safety.md)).
- With model routing, the DLP scan (and the cost estimate) follow the provider
  that is **leased** for the task, not the workspace default: a cloud profile
  routed for one task class under a local default is screened and priced as a
  cloud call. A campaign worker's turns go to whichever profile its task class
  routes to; the routing ledger records each choice. Read-only views (`campaign
  status`, `tree`, the optional dashboard) contact no provider at all.

## Network egress (literature & data)

All scholarly/network access is governed by an egress guard:

- **Throttled** with rate limits and a daily budget.
- **Consent-gated per host** — you approve which hosts may be contacted.
- **Credential-redacted** in logs; API keys and sessions are treated as
  sensitive files.
- **No bulk harvesting and no paywall bypass.** Full text is only acquired via
  the legal resolver chain (Crossref → Unpaywall → arXiv → institutional access).
- **Never inward.** A fetched page cannot redirect a request to this machine or the
  local network (loopback/private/link-local addresses are refused on every hop),
  so a local vLLM/Ollama server or a cloud metadata endpoint is unreachable from
  `fetch_url` and the literature connectors. `fetch_url` and MCP-over-HTTP requests
  pass the same guard as literature access.
- **Refusals are respected.** Captchas, challenge pages and rate limits are
  reported as access denied, not worked around.

## Sharing safely

`opentorus export` and `opentorus pack export` produce privacy/license-clean
bundles for review. Every text file in them is secret-scanned: secrets are
redacted and listed (location and kind, never the value) in the manifest, or the
export is refused with `opentorus pack export --refuse-secrets`. Before
committing shared material (e.g. `examples/`), run `opentorus gov scan <dir>`.
The scan matches key formats, private-key blocks, JWTs, Authorization headers,
`user:pass@` URLs and credential-named `KEY=VALUE` assignments, and ignores
placeholders such as `xxx`, `<your-key>`, `${VAR}` or `changeme`. It cannot know
every secret format, so stay mindful of what you share. See
[safety.md](safety.md) for the enforcement details.
