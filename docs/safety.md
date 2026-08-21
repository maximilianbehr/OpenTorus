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

## Adversarial review

An independent critic (`opentorus review run`) challenges claims and reports,
verifies that cited ids exist, flags overclaiming, and can record `block`
findings. Open blocking findings gate publication (enforced in review mode)
until they are resolved.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
