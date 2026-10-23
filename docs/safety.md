# Safety

OpenTorus is built so that every potentially impactful action is **explicit,
reviewable, and reversible**. Some guarantees are *hard* — they hold in every
mode and style and cannot be configured away.

## Hard guarantees (never bypassable)

- **Dangerous commands are blocked** — e.g. `rm -rf`, `curl | bash`, fork bombs,
  and similar destructive patterns are refused regardless of permission mode.
- **Sensitive files are protected** — reads of `.env`, private keys,
  credentials, and similar are blocked or gated, and their contents are excluded
  from provider context by default.
- **Review mode is read-only** — `opentorus --mode review` (or `/mode review`)
  permits inspection and critique only; no writes, commands, or restricted claim
  upgrades.
- **No silent self-promotion** — a machine can never advance a claim into a
  restricted status (`partially_validated`, `human_reviewed`, `verified`)
  without explicit human confirmation; `verified` requires a real proof.
- **No auto-commit** — agent edits are recorded as `PATCH-*` artifacts; commits
  are always a human action.
- **Egress fails closed on secrets** — the pre-egress DLP scan blocks any payload
  containing a secret before it leaves the machine. PII is redacted rather than
  blocked by default (`governance.dlp_pii`); see [privacy.md](privacy.md).

## Configurable controls

These tune *how much friction* the gates add, but never weaken the hard
guarantees above.

### Permission mode (`permissions.mode`)

| Mode | Behavior |
|------|----------|
| `safe` | Only read-only tools run automatically; writes/commands are blocked. |
| `ask` | Writes and commands prompt for confirmation (allow-once / session-allow). |
| `trusted` | Writes/commands run without prompting — but dangerous ones are still blocked. |

### Operating style (`agent.style`)

`cautious` | `normal` | `fast` | `autonomous` — controls how aggressively the
agent acts and how often it checks in. Even `autonomous` still confirms
destructive operations.

### Agent mode

`normal` (can act, subject to the policy) vs. `review` (strictly read-only).

### Campaign and routing controls

A campaign (`opentorus campaign`) runs its workers through the same permission
policy, tool gates and DLP as any agent session -- each worker role additionally
gets only its own tool allow-list, its own session id, a step / token / cost /
wall-clock budget (`0` = unlimited; a campaign with no positive limit on any axis
is refused) and no transcript from any other branch. Nothing a campaign records
-- a closed obligation, a finished branch, a completed campaign -- can promote a
claim; obligation closure requires an accepted artifact and completion never
touches a status (a campaign can finish without solving the problem). Model
routing (`models.profiles`, `governance.routing.task_routes`) decides which
provider answers a task; the DLP scan, cost estimate and tool-calling check are
applied to the **leased** provider, and every routing decision -- including a
refusal -- is written to the local `usage/routing.jsonl`, so a fallback is never
silent. The optional dashboard is read-only. See
[campaign-engine.md](campaign-engine.md) and [model-routing.md](model-routing.md).

## Reversibility & auditability

- **Checkpoints** (`opentorus checkpoint create`) record recoverable state (a git
  ref or a file manifest) before risky edits.
- **Patches** are first-class artifacts you can `show`, `apply`, and `revert`.
- **The action log** (`opentorus actions`) records every tool call with its
  permission decision and outcome.
- **Session replay** (`opentorus replay`) summarizes a session for after-the-fact
  review.

## Sandboxing & execution

Tool and experiment code can run in a container (Docker/Podman/Apptainer), which
is treated as the sandbox boundary, with least-privilege mounts. Images are
**digest-pinned** (`@sha256:`) for reproducibility; `opentorus env verify` fails
if any environment is unpinned. Remote/HPC execution (SSH/Slurm) stages and runs
explicitly and reports honestly when a host or runtime is missing.

### Child processes

- **No credentials in a child's environment.** `run_shell`, background jobs and
  local experiment runs get only an allowlist (`PATH`, `HOME`, locale, temp dirs,
  thread-count knobs, plus `execution.env_allowlist`). OpenTorus' own helper
  processes (git, container CLIs, verifiers) inherit the parent environment minus
  every credential-looking name (`*_KEY`, `*_TOKEN`, `*SECRET*`, `*PASSWORD*`, the
  provider keys, ...). Credential names are stripped even when an allowlist names
  them, so `cat /proc/self/environ` shows no API key.
- **Nothing outlives its command.** Every child leads its own process group; a
  timeout, a cancel, or the command's own exit ends the whole group (SIGTERM,
  then SIGKILL), grandchildren included.
- **Background work stays visible.** `run_shell(background=true)` starts a job
  that `shell_jobs` can list, read and stop; jobs are killed at their deadline
  and at session end, and the loop is told when one finishes. The model picks a
  foreground timeout up to `tools.shell.max_timeout`.
- **Local confinement** (`execution.local_confinement`): with `auto` (default) a
  host run that asks for no network runs inside `bwrap --unshare-net
  --die-with-parent --dev-bind / / --tmpfs /run` when bubblewrap works, and
  unconfined (logged) otherwise; `require` refuses a run that cannot be confined;
  `off` never wraps. `memory` maps to `RLIMIT_AS`, `cpus` to CPU affinity plus an
  `RLIMIT_CPU` of timeout x cpus.
- **Containers.** Apptainer runs with `--containall --cleanenv` (no host
  environment, no host `$HOME`/`~/.ssh`). The run's working directory is bound
  read-write at `/work` (it is the run's own directory); when that directory is a
  workspace root its `.opentorus/` store is bound again read-only on top. Callers
  that want the whole workspace read-only use `sandboxed_mounts`.
- **Writes are TOCTOU-safe.** `write_file`/`apply_patch` open the final path
  component with `O_NOFOLLOW` and check the descriptor's real path (inside the
  workspace, not sensitive, not internal state) before writing a byte.
- **Git inspection runs no repository code** (`core.fsmonitor`, external diff,
  textconv and hooks disabled). `git_diff` shows staged, unstaged and untracked
  files and pages long output.

### Network and external tools

- **No internal addresses.** Every HTTP(S) fetch (literature, datasets, PDFs,
  `fetch_url`) resolves the host of every hop -- the request and each redirect --
  and refuses loopback, private, link-local, CGNAT, multicast and IPv4-mapped
  addresses, connecting to the address it checked. Hosts in
  `tools.web.allow_private_hosts` are exempt. No ambient proxies; bodies are
  streamed up to a byte cap (`tools.web.max_bytes`).
- **A site's refusal is a refusal.** A captcha/challenge page, a redirect to a
  human gate, or a 429 becomes an "access denied; do not work around it" error
  (a short `Retry-After` is waited out once).
- **`fetch_url` goes through the egress guard** (host consent, rate limit, daily
  budget) on every hop, and the approval prompt shows the URL.
- **MCP servers** get a clean environment plus only their configured `env`, run
  one process per session (killed on exit), are bounded in time and to 1 MiB per
  message, and can be restricted to a `tools` allowlist (startup fails if a listed
  tool is missing). The `http` transport (MCP Streamable HTTP) is HTTPS-only,
  follows no redirects, and every request passes the egress guard and DLP.

### Approvals, effects and unknown outcomes

- **Approvals are keyed on the tool and its relevant arguments** (path, command,
  fetch host, MCP server): approving `write_file x.py` never covers `apply_patch
  x.py`, and `[s] this session` for one external tool never covers another. Each
  decision records the policy version (`POLICY_VERSION`) in the action log.
- **Effect classes.** Every tool is `observation`, `reversible`,
  `compensatable` or `irreversible`. Irreversible calls (shell commands, code
  runs, MCP tools without a read-only hint) are approved one call at a time.
- **Unknown outcomes are never retried.** A Slurm submission or MCP call whose
  answer was lost writes an fsync'd intent record before dispatch and its outcome
  after; a lost answer is "outcome unknown", the identical call is refused for the
  session, and Slurm recovers the job by name (`squeue --name <op id>`) instead of
  submitting twice.
- **Background campaigns** (no terminal) queue approval requests under
  `.opentorus/approvals/pending/`; `opentorus approvals list|approve|deny <id>`
  decides them. An approval is single use and binds to the tool, a digest of the
  exact arguments and the policy version. The run waits up to
  `permissions.approval_wait_seconds` (default 0: record the denial and move on).

### Secrets in logs and exports

Session and action logs are secret-scanned before they are written (masked
preview, never the value); session bundles and research packs are redacted and
list their findings in the manifest (`--refuse-secrets` / `on_secret="refuse"`
fails instead). `opentorus governance scan <dir>` (alias `gov scan`) checks a
directory such as `examples/` before a commit and exits 1 on any finding.

## Adversarial review

An independent critic (`opentorus review run`) challenges claims and reports,
verifies that cited ids exist, flags overclaiming, and can record `block`
findings. Open blocking findings gate publication (enforced in review mode)
until they are resolved.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
