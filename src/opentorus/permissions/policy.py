"""Permission policy for commands and file access.

Three modes shape day-to-day behavior (``safe`` / ``ask`` / ``trusted``), but two
guarantees hold in *every* mode and are never bypassable:

* Dangerous commands (``rm -rf /``, ``curl ... | bash``, ``shutdown`` ...) are
  always blocked.
* Sensitive files (``.env``, private keys, credentials ...) are never read
  without explicit confirmation.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from opentorus.config import OperatingStyle, PermissionMode

RiskLevel = Literal["low", "medium", "high", "blocked"]


class PermissionDecision(BaseModel):
    allowed: bool
    reason: str
    requires_confirmation: bool
    risk_level: RiskLevel


# Always-blocked command patterns (matched case-insensitively, whitespace-robust).
_DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # ``sudo`` / ``su`` only as a command — at the start or after a shell
        # separator — so a filename/argument like ``cat su.txt`` is not blocked.
        r"(?:^|[\n;&|(]|\x60)\s*(?:sudo|su)\b",
        # rm -rf targeting a filesystem root, glob, home, or env-expanded path.
        # An optional quote is tolerated so ``rm -rf "/"`` cannot slip through.
        r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(--\s+)?[\"']?(/|\*|~|\.|\$)",
        r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+(--\s+)?[\"']?(/|\*|~|\.|\$)",
        r"\bmkfs\b",
        r"\bdd\s+if=",
        # Writing to a raw block device (disk wipe); the null/zero sinks are safe.
        r"\bdd\b[^|]*\bof=/dev/(?!null\b|zero\b)",
        # chmod 777 on an absolute path, recursive or not (e.g. ``chmod 777 /etc``).
        r"\bchmod\s+(-R\s+)?[0-7]*777[0-7]*\s+/",
        r"\bchown\s+-R\b.*\s+/",
        r"(curl|wget)\b.*\|\s*(sudo\s+)?(bash|sh|zsh)\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bpoweroff\b",
        r"\bmkfs\.",
        r"\bdiskutil\s+eraseDisk\b",
        r":\(\)\s*\{.*\};:",  # classic fork bomb
    )
)

# Host package-manager installs — always blocked. Experiments must use container
# environments (exp_new + exp_run with environment=python-sci, julia, …).
_PACKAGE_INSTALL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bpip3?\s+install\b",
        r"\bpython3?\s+(-m\s+)?pip\s+install\b",
        r"\bensurepip\b",
        r"\bconda\s+install\b",
        r"\b(micro)?mamba\s+install\b",
        r"\buv\s+(pip\s+)?install\b",
        r"\bpoetry\s+add\b",
        r"\bapt(-get)?\s+install\b",
        r"\byum\s+install\b",
        r"\bdnf\s+install\b",
        r"\bbrew\s+install\b",
    )
)

# Commands considered harmless inspection (allowed even in ``safe`` mode).
# ``env`` is intentionally excluded: with arguments it is a program launcher
# (``env python evil.py``), so it is not read-only inspection.
_HARMLESS_FIRST_TOKENS = frozenset(
    {"echo", "ls", "pwd", "cat", "head", "tail", "wc", "which", "true", "date", "uname"}
)
# Harmless commands that read file *contents* (as opposed to ``ls``/``pwd``).
# When one of these targets a sensitive path it must not be treated as harmless,
# or ``cat .env`` would bypass the sensitive-file guarantee that ``read_file``
# enforces.
_FILE_READERS = frozenset({"cat", "head", "tail", "wc"})
_HARMLESS_PREFIXES = (
    "git status",
    "git log",
    "git diff",
    "git branch",
    "python --version",
    "python3 --version",
    "pip --version",
)

# Sensitive file patterns (glob-style against the file name or path tail).
_SENSITIVE_GLOBS = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p8",
    "*.p12",
    "*.pfx",
    "*.ppk",
    "*.keystore",
    "*.kdbx",
    "id_rsa",
    "id_rsa.*",
    "id_dsa",
    "id_dsa.*",
    "id_ecdsa",
    "id_ecdsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "secret",
    ".secret",
    "secret.*",
    "secrets",
    "secrets.*",
    "credentials",
    "credentials.*",
    "kubeconfig",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    ".htpasswd",
    "htpasswd",
    "passwd",
    ".passwd",
    "password",
    "passwords",
    "password.txt",
    "passwords.txt",
    "*.pwd",
    "token",
    ".token",
    "*.token",
    "access_token",
    "access_token.*",
    # Institutional / session material (Milestone 44): never logged or sent to a
    # provider; the agent reuses an existing session but never authenticates.
    "cookies.txt",
    "*.cookies",
    "*.cookies.txt",
    "cookiejar",
    "ezproxy",
    "ezproxy.*",
    "*.springer-key",
    "*.ieee-key",
    "*_api_key",
    "*_api_key.*",
    "apikey",
    "apikey.*",
    "api_key",
    "api_key.*",
    # Proprietary-tool license material (Milestone 57): never bundled, logged, or
    # sent to a provider. Bring-your-own licenses stay on the user's machine.
    "*.lic",
    "license.dat",
    "*license.dat",
    "*.licenses",
    "network.lic",
    "mlm.dat",
    "*.mathpass",
    "mathpass",
)
_SENSITIVE_DIR_PARTS = (".ssh", ".aws", ".gnupg", ".gcloud", ".kube", ".docker")


# Destructive (but not categorically dangerous) commands. These are permitted in
# trusted mode but always require explicit confirmation, even under autonomous.
_DESTRUCTIVE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brm\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\b",
        r"\bgit\s+push\b.*--force",
        r"\bgit\s+push\s+-f\b",
        r"\bgit\s+checkout\s+--\b",
        r"\b(drop|truncate)\s+table\b",
        r"\bmv\b",
        r"\btruncate\b",
    )
)


def _dequote(command: str) -> str:
    """Strip shell quote characters so quote-split evasion (``r''m -rf /``,
    ``rm -rf "/"``) cannot hide a dangerous command from pattern matching."""
    return command.replace('"', "").replace("'", "")


def is_dangerous_command(command: str) -> bool:
    # Match against the raw command and a dequoted form: the shell collapses
    # quotes before execution, so the classifier must too.
    candidates = (command, _dequote(command))
    return any(
        pattern.search(candidate) for pattern in _DANGEROUS_PATTERNS for candidate in candidates
    )


def is_package_install_command(command: str) -> bool:
    """True when the command would install packages on the host."""
    return any(pattern.search(command) for pattern in _PACKAGE_INSTALL_PATTERNS)


_PACKAGE_INSTALL_REASON = (
    "Installing packages on the host is blocked (pip/conda/apt install, ensurepip, …). "
    "Run 'opentorus env prepare python-sci --file docker/Dockerfile', then "
    "exp_new(..., environment='python-sci') and exp_run(exp_id=...)."
)


def is_destructive_command(command: str) -> bool:
    return any(pattern.search(command) for pattern in _DESTRUCTIVE_PATTERNS)


def _is_harmless_command(command: str) -> bool:
    stripped = command.strip()
    if not stripped:
        return False
    first = stripped.split()[0]
    if first in _HARMLESS_FIRST_TOKENS:
        return True
    return any(stripped.startswith(prefix) for prefix in _HARMLESS_PREFIXES)


def command_reads_sensitive_path(command: str) -> bool:
    """True when ``command`` is a file reader (``cat``/``head``/...) whose target
    is a sensitive path, so it must be gated like a sensitive ``read_file``."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unparseable quoting: fall back to not classifying it here; the normal
        # mode/style gate still applies.
        return False
    if not tokens or tokens[0] not in _FILE_READERS:
        return False
    return any(not tok.startswith("-") and is_sensitive_path(tok) for tok in tokens[1:])


def is_sensitive_path(path: Path | str) -> bool:
    p = Path(path)
    name = p.name
    if any(fnmatch.fnmatch(name, glob) for glob in _SENSITIVE_GLOBS):
        return True
    return any(part in _SENSITIVE_DIR_PARTS for part in p.parts)


def evaluate_command(
    command: str,
    mode: PermissionMode,
    *,
    style: OperatingStyle = "normal",
    review: bool = False,
) -> PermissionDecision:
    """Decide whether a shell command may run under the given mode/style.

    Hard guarantees that hold regardless of style or review:
    * dangerous commands are always blocked;
    * review mode is strictly read-only (only harmless inspection runs).
    """
    if is_dangerous_command(command):
        return PermissionDecision(
            allowed=False,
            reason="Command matches a dangerous pattern and is always blocked.",
            requires_confirmation=False,
            risk_level="blocked",
        )

    if is_package_install_command(command):
        return PermissionDecision(
            allowed=False,
            reason=_PACKAGE_INSTALL_REASON,
            requires_confirmation=False,
            risk_level="blocked",
        )

    # A shell read of a sensitive file (``cat .env``) is never harmless; it
    # always requires explicit confirmation, mirroring ``evaluate_read`` so the
    # command path cannot bypass the sensitive-file guarantee.
    if command_reads_sensitive_path(command):
        return PermissionDecision(
            allowed=True,
            reason="Command reads a potentially sensitive file; explicit confirmation required.",
            requires_confirmation=True,
            risk_level="high",
        )

    harmless = _is_harmless_command(command)

    if review:
        if harmless:
            return PermissionDecision(
                allowed=True,
                reason="Review mode permits read-only inspection commands.",
                requires_confirmation=False,
                risk_level="low",
            )
        return PermissionDecision(
            allowed=False,
            reason="Review mode is read-only; modifying commands are not permitted.",
            requires_confirmation=False,
            risk_level="blocked",
        )

    if harmless:
        return PermissionDecision(
            allowed=True,
            reason="Harmless inspection command.",
            requires_confirmation=False,
            risk_level="low",
        )

    if mode == "safe":
        return PermissionDecision(
            allowed=False,
            reason="Safe mode is read-only; only harmless inspection commands run.",
            requires_confirmation=False,
            risk_level="high",
        )

    destructive = is_destructive_command(command)

    if mode == "trusted":
        # Autonomous only takes effect in trusted mode.
        if style == "autonomous":
            if destructive:
                return PermissionDecision(
                    allowed=True,
                    reason="Autonomous still confirms destructive operations.",
                    requires_confirmation=True,
                    risk_level="high",
                )
            return PermissionDecision(
                allowed=True,
                reason="Autonomous performs low-risk commands without asking.",
                requires_confirmation=False,
                risk_level="low",
            )
        if style == "cautious" or destructive:
            return PermissionDecision(
                allowed=True,
                reason="Confirmation required (cautious style or destructive command).",
                requires_confirmation=True,
                risk_level="high" if destructive else "medium",
            )
        return PermissionDecision(
            allowed=True,
            reason="Trusted mode permits normal development commands.",
            requires_confirmation=False,
            risk_level="low",
        )

    # ask (default): every style asks before running non-harmless commands.
    return PermissionDecision(
        allowed=True,
        reason="Command requires confirmation in ask mode.",
        requires_confirmation=True,
        risk_level="high" if destructive else "medium",
    )


def evaluate_read(path: Path | str, mode: PermissionMode) -> PermissionDecision:
    """Reads are safe by default; sensitive files always require confirmation."""
    if is_sensitive_path(path):
        return PermissionDecision(
            allowed=True,
            reason="Potentially sensitive file; explicit confirmation required.",
            requires_confirmation=True,
            risk_level="high",
        )
    return PermissionDecision(
        allowed=True,
        reason="Reading a non-sensitive file is allowed.",
        requires_confirmation=False,
        risk_level="low",
    )


def evaluate_write(
    path: Path | str,
    mode: PermissionMode,
    *,
    style: OperatingStyle = "normal",
    review: bool = False,
) -> PermissionDecision:
    """Writes are blocked in safe/review mode and confirmed in ask mode."""
    if review:
        return PermissionDecision(
            allowed=False,
            reason="Review mode is read-only; file writes are not permitted.",
            requires_confirmation=False,
            risk_level="blocked",
        )
    if mode == "safe":
        return PermissionDecision(
            allowed=False,
            reason="Safe mode is read-only; file writes are not permitted.",
            requires_confirmation=False,
            risk_level="high",
        )
    if mode == "trusted":
        if style == "cautious":
            return PermissionDecision(
                allowed=True,
                reason="Cautious style confirms writes and always shows patches.",
                requires_confirmation=True,
                risk_level="medium",
            )
        return PermissionDecision(
            allowed=True,
            reason="Trusted mode permits file writes.",
            requires_confirmation=False,
            risk_level="low",
        )
    return PermissionDecision(
        allowed=True,
        reason="File write requires confirmation in ask mode.",
        requires_confirmation=True,
        risk_level="medium",
    )


def evaluate_external_tool(
    tool_name: str,
    mode: PermissionMode,
    *,
    style: OperatingStyle = "normal",
    review: bool = False,
) -> PermissionDecision:
    """Gate an opaque external (e.g. MCP) tool.

    External tools can do anything, so they are treated conservatively: blocked
    in review and safe modes, confirmed in ask mode and for cautious style, and
    allowed without asking only under trusted+fast/autonomous.
    """
    if review:
        return PermissionDecision(
            allowed=False,
            reason=f"Review mode is read-only; external tool '{tool_name}' is not permitted.",
            requires_confirmation=False,
            risk_level="blocked",
        )
    if mode == "safe":
        return PermissionDecision(
            allowed=False,
            reason=f"Safe mode does not allow external tool '{tool_name}'.",
            requires_confirmation=False,
            risk_level="high",
        )
    if mode == "trusted" and style in {"fast", "autonomous"}:
        return PermissionDecision(
            allowed=True,
            reason=f"Trusted/{style} runs external tool '{tool_name}' without asking.",
            requires_confirmation=False,
            risk_level="medium",
        )
    return PermissionDecision(
        allowed=True,
        reason=f"External tool '{tool_name}' requires confirmation.",
        requires_confirmation=True,
        risk_level="medium",
    )


def evaluate_egress(
    host: str,
    mode: PermissionMode,
    *,
    style: OperatingStyle = "normal",
    review: bool = False,
) -> PermissionDecision:
    """Decide whether the agent may make a network request to ``host``.

    Network egress mirrors command policy: no egress in ``safe`` or ``review``;
    ``ask`` confirms each new host (the runtime guard remembers confirmed hosts);
    ``trusted`` allows egress, but cautious style still confirms. Paywall and
    rate-limit invariants are enforced separately by the runtime egress guard.
    """
    if review:
        return PermissionDecision(
            allowed=False,
            reason=f"Review mode is read-only; no network egress to '{host}'.",
            requires_confirmation=False,
            risk_level="blocked",
        )
    if mode == "safe":
        return PermissionDecision(
            allowed=False,
            reason=f"Safe mode forbids network egress (to '{host}').",
            requires_confirmation=False,
            risk_level="high",
        )
    if mode == "trusted" and style in {"fast", "autonomous"}:
        return PermissionDecision(
            allowed=True,
            reason=f"Trusted/{style} permits egress to '{host}' without asking.",
            requires_confirmation=False,
            risk_level="medium",
        )
    return PermissionDecision(
        allowed=True,
        reason=f"Network egress to '{host}' requires confirmation.",
        requires_confirmation=True,
        risk_level="medium",
    )


def evaluate_claim_verification(review: bool) -> PermissionDecision:
    """Marking a claim verified is never allowed in review mode."""
    if review:
        return PermissionDecision(
            allowed=False,
            reason="Review mode may critique claims but never mark them verified.",
            requires_confirmation=False,
            risk_level="blocked",
        )
    return PermissionDecision(
        allowed=True,
        reason="Marking a claim verified requires explicit confirmation.",
        requires_confirmation=True,
        risk_level="high",
    )
