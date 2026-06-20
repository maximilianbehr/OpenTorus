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
- **Egress fails closed** — the pre-egress DLP scan blocks payloads containing
  secrets/PII before they leave the machine.

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
