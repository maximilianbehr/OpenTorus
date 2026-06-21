"""Configuration schema and YAML loader for OpenTorus.

The configuration lives in ``.opentorus/config.yaml`` and is parsed into a typed
:class:`Config` model. Unknown keys are preserved leniently so that newer config
files remain readable by older code paths during development.
"""

from __future__ import annotations

import math
import re
from importlib.resources import files
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from opentorus.errors import ConfigError

CONFIG_FILENAME = "config.yaml"

ProjectMode = Literal["code", "research", "writing", "data", "mixed"]
OperatingStyle = Literal["cautious", "normal", "fast", "autonomous"]
PermissionMode = Literal["safe", "ask", "trusted"]
AgentMode = Literal["normal", "review"]
EmbeddingsBackend = Literal["auto", "local", "openai", "ollama", "off"]

_UNLIMITED_STEP_TOKENS = frozenset({"inf", "infinity", "unlimited", "unbounded", "none", "null"})


def parse_max_steps(value: object) -> float:
    """Parse agent.max_steps: positive integer or ``float('inf')`` for no cap."""
    if value is None:
        return math.inf
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _UNLIMITED_STEP_TOKENS:
            return math.inf
    if isinstance(value, bool):
        raise ValueError("max_steps must be a positive integer or inf")
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isinf(number) and number > 0:
            return math.inf
        if number == -1:
            return math.inf
        if number >= 1 and math.isfinite(number):
            return number
    raise ValueError("max_steps must be a positive integer or inf")


def is_unlimited_steps(max_steps: float) -> bool:
    return math.isinf(max_steps) and max_steps > 0


class ModelConfig(BaseModel):
    provider: str = "mock"
    name: str = "mock-default"
    temperature: float = 0.2
    base_url: str | None = None
    # Provider HTTP timeout (seconds). Local models (Ollama) often need several
    # minutes on large contexts; cloud APIs are usually faster.
    timeout_seconds: int = 300
    # Ollama-only generation options (ignored by other providers).
    num_ctx: int | None = None
    # Max tokens to generate; -1 means no limit. When unset and tools are used,
    # OpenTorus defaults to -1 for Ollama to reduce truncated tool-call JSON.
    num_predict: int | None = None
    # Hard cap on output tokens for providers that require one (e.g. Anthropic).
    # Unset falls back to a provider default; raise it for long proofs.
    max_tokens: int | None = None


class ProjectConfig(BaseModel):
    mode: ProjectMode = "mixed"


class AgentConfig(BaseModel):
    style: OperatingStyle = "normal"
    mode: AgentMode = "normal"
    max_steps: float = 12
    # Minimum [parsed] papers required before proof_write in ``opentorus prove`` (0 = optional).
    prove_min_papers: int = Field(default=0, ge=0)
    # After the first primary proof_write, keep the prove loop running while gaps remain.
    prove_until_gaps_closed: bool = True
    # Extra model steps allowed for gap-filling after the first sketch (when max_steps is inf).
    # Positive integer, or inf / unlimited / -1 for no separate gap-fill cap.
    prove_gap_fill_max_steps: float = 48

    @field_validator("max_steps", "prove_gap_fill_max_steps", mode="before")
    @classmethod
    def _validate_step_count(cls, value: object) -> float:
        return parse_max_steps(value)


class PermissionsConfig(BaseModel):
    mode: PermissionMode = "ask"


class PrivacyConfig(BaseModel):
    sensitive_file_guard: bool = True
    allow_sensitive_context: bool = False


class UIConfig(BaseModel):
    render_math: bool = True
    # Desktop notifications (native OS toast when available; bell fallback).
    notifications_enabled: bool = True
    notify_on_turn_complete: bool = True
    notify_on_permission: bool = True
    # When true, skip notifications for interactive TTY sessions (background/piped runs still
    # notify).
    notify_only_unfocused: bool = True
    # Minimum agent-turn duration before a completion notification is sent.
    notify_min_elapsed_seconds: float = 3.0


class QualityConfig(BaseModel):
    test_command: str | None = "pytest -q"
    lint_command: str | None = "ruff check ."
    typecheck_command: str | None = "mypy"


class EnvironmentConfig(BaseModel):
    capture_pip_freeze: bool = False
    capture_os_info: bool = True
    capture_git_state: bool = True


class ContextConfig(BaseModel):
    retrieval_enabled: bool = True
    top_k: int = 5
    history_turns: int = 10
    token_budget: int = 6000
    compaction_enabled: bool = True
    # Persistently rewrite session.jsonl when history exceeds this fraction of token_budget.
    compaction_threshold: float = Field(default=0.85, ge=0.1, le=1.0)
    # Summarize compacted turns with the chat provider when available (falls back to heuristics).
    compaction_llm: bool = True
    # Fraction of token_budget to keep as recent verbatim turns after a session compaction.
    compaction_keep_ratio: float = Field(default=0.5, ge=0.1, le=0.95)
    # Hybrid retrieval (Milestone 46): BM25 + embeddings from the chat provider
    # (OpenAI/Ollama) or optional local sentence-transformers.
    embeddings_enabled: bool = True
    embeddings_backend: EmbeddingsBackend = "auto"
    # Force embedding source when chat provider lacks an API (e.g. anthropic → ollama).
    embeddings_provider: Literal["openai", "ollama", "local"] | None = None
    # null = provider default (text-embedding-3-small / nomic-embed-text / all-MiniLM-L6-v2)
    embeddings_model: str | None = None


class McpServerConfig(BaseModel):
    """One external Model-Context-Protocol server (opt-in, disabled by default)."""

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    enabled: bool = False


class LiteratureConfig(BaseModel):
    """Literature source access (Phase 13).

    Free, keyless sources are on by default. Springer/IEEE require a user-supplied
    API key and stay off until both enabled and keyed. ``contact_email`` joins the
    OpenAlex/Crossref polite pool; ``proxy_base_url`` is an optional institutional
    proxy (e.g. EZproxy) for licensed full text.
    """

    enabled: bool = True
    openalex: bool = True
    arxiv: bool = True
    crossref: bool = True
    semantic_scholar: bool = True
    # Additional free, field-specific connectors (Phase 23 / M70).
    dblp: bool = True
    zbmath: bool = True
    # Biomedical preprint/literature servers — off by default since OpenTorus targets
    # open mathematical problems; querying them for math/CS topics only adds 503s and
    # timeouts. Enable explicitly for biomedical work:
    #   opentorus config set tools.literature.europepmc true
    europepmc: bool = False
    biorxiv: bool = False
    # Keyed sources stay off until both enabled and keyed.
    springer: bool = False
    ieee: bool = False
    ads: bool = False
    springer_api_key: str | None = None
    ieee_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    ads_api_key: str | None = None
    contact_email: str | None = None
    proxy_base_url: str | None = None
    rate_limit_per_minute: int = 20
    daily_request_budget: int = 500


class VerifiersConfig(BaseModel):
    """Formal verification backends (Phase 16, opt-in).

    Disabled by default; when enabled the agent shells out to the configured
    proof assistant. No backend ⇒ formal verification is simply unavailable.
    """

    lean: bool = False
    coq: bool = False
    smt: bool = False
    # Validated numerics (interval arithmetic) needs no external binary — only the
    # optional ``mpmath`` dependency — so it is enabled by default; it reports itself
    # unavailable when mpmath is absent rather than faking rigor.
    interval: bool = True
    lean_command: str = "lake env lean"
    coq_command: str = "coqc"
    smt_command: str = "z3"


class DatasetsConfig(BaseModel):
    """Dataset acquisition with hash + license provenance (Phase 23, M71).

    Downloads route through the egress guard and are license-respecting: a fetch
    is refused unless the resolved license is on ``allowed_licenses`` (substring,
    case-insensitive). Unknown/absent licenses are blocked unless
    ``allow_unknown_license`` is set explicitly.
    """

    enabled: bool = True
    zenodo: bool = True
    huggingface: bool = True
    osf: bool = True
    allowed_licenses: list[str] = Field(
        default_factory=lambda: [
            "cc0",
            "cc-by",
            "cc-by-sa",
            "public domain",
            "pddl",
            "odbl",
            "odc-by",
            "mit",
            "apache",
            "bsd",
        ]
    )
    allow_unknown_license: bool = False
    max_file_bytes: int = 500_000_000


class CodeEvidenceConfig(BaseModel):
    """External code as inspectable evidence (Phase 23, M72).

    Repositories are cloned at a pinned commit (egress-gated) and their tests are
    run inside a sandboxed execution environment. Repository credentials and any
    fetched secrets are sensitive (M20/M44) and never bundled.
    """

    enabled: bool = True
    clone_command: str = "git"
    max_repo_bytes: int = 500_000_000


class WebConfig(BaseModel):
    """General web access: fetch a URL and run a keyword web search (Phase 25).

    Distinct from ``literature`` (scholarly databases): this lets the agent read
    an arbitrary page the user points at and discover pages by keyword. Every
    call still passes through the egress policy (blocked in review mode, confirmed
    in ask mode), and fetched text is length-capped to ``max_chars``.
    """

    enabled: bool = True
    fetch: bool = True
    search: bool = True
    max_chars: int = 8000


class ToolsConfig(BaseModel):
    # External MCP servers are opt-in: empty by default, and each is disabled
    # until explicitly enabled. Their tools always pass through permission policy.
    mcp: list[McpServerConfig] = Field(default_factory=list)
    literature: LiteratureConfig = Field(default_factory=LiteratureConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    verifiers: VerifiersConfig = Field(default_factory=VerifiersConfig)
    datasets: DatasetsConfig = Field(default_factory=DatasetsConfig)
    code_evidence: CodeEvidenceConfig = Field(default_factory=CodeEvidenceConfig)


ExecutionBackendName = Literal["auto", "local", "docker", "podman", "apptainer", "ssh", "slurm"]


class RemoteExecConfig(BaseModel):
    """Connection settings for remote / HPC execution (Phase 21, opt-in).

    Empty by default: ``ssh``/``slurm`` backends are unusable until a ``host`` is
    set. Credentials (SSH keys) live in the user's ``~/.ssh`` and are sensitive
    (M20) — they are never stored here and never bundled.
    """

    host: str | None = None
    user: str | None = None
    remote_root: str = "~/opentorus-runs"
    ssh_command: str = "ssh"
    copy_command: str = "scp"
    # Slurm submission options:
    partition: str | None = None
    time_limit: str | None = None
    account: str | None = None
    extra_sbatch: list[str] = Field(default_factory=list)


class ExecutionConfig(BaseModel):
    """Where tool/experiment code runs (Phase 18 / Phase 21).

    ``backend`` selects the runtime; ``auto`` prefers the host for plain commands
    and the first available container runtime (in ``auto_preference`` order) when
    a pinned image is requested. ``ssh``/``slurm`` are explicit-only and read
    connection settings from ``remote``. Defaults are safe: no network,
    least-privilege.
    """

    backend: ExecutionBackendName = "auto"
    auto_preference: list[str] = Field(default_factory=lambda: ["docker", "podman", "apptainer"])
    network: bool = False
    memory_limit: str | None = None
    cpu_limit: str | None = None
    cache: bool = True  # content-addressed result cache (Phase 21, M66)
    remote: RemoteExecConfig = Field(default_factory=RemoteExecConfig)


class BudgetConfig(BaseModel):
    """Cost/token budgets for governance (Phase 24, M75).

    A breach raises an alert and stops cleanly; it never silently overspends.
    Per-provider caps are USD cost limits keyed by provider name.
    """

    cost_budget_usd: float | None = None
    token_budget: int | None = None
    per_provider_usd: dict[str, float] = Field(default_factory=dict)


class RoutingConfig(BaseModel):
    """Policy model routing (Phase 24, M75), opt-in.

    Maps a *task class* (planning, narration, proof, critique, default) to a model
    name so cheaper models handle planning/narration and stronger ones handle
    proofs/critique. Empty mappings fall back to ``model.name``. The chosen model
    and task class are recorded per turn for transparency.
    """

    enabled: bool = False
    task_models: dict[str, str] = Field(default_factory=dict)


class GovernanceConfig(BaseModel):
    """Cost, secrets, and model-use governance (Phase 24, M75).

    ``dlp`` adds a final pre-egress secret/PII scan that fails closed: a detected
    secret blocks the send. Budgets and routing build on the usage ledger (M31)
    and research-loop budgets (M53) without loosening any safety guarantee.
    """

    dlp: bool = True
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)


class Config(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)


def default_config() -> Config:
    """Return a :class:`Config` populated entirely with defaults."""
    return Config()


def load_config(path: Path) -> Config:
    """Load and validate a config file. Raises :class:`ConfigError` on failure."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not read config at '{path}': {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config at '{path}' must be a mapping, got {type(raw).__name__}.")
    try:
        return Config.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError -> friendly message
        raise ConfigError(f"Invalid config at '{path}': {exc}") from exc


def default_config_yaml() -> str:
    """Return the annotated default config template shipped with OpenTorus."""
    return files("opentorus").joinpath("default_config.yaml").read_text(encoding="utf-8")


def write_default_config(path: Path) -> None:
    """Write the commented default ``config.yaml`` (used by ``opentorus init``)."""
    path.write_text(default_config_yaml(), encoding="utf-8")


_CONFIG_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_]+):(?:[ \t]+(\S.*))?$")


def _format_scalar(value: object) -> str:
    """Render a Python scalar as a single-line YAML value (``null``, ``true``, …)."""
    return yaml.safe_dump(value, default_flow_style=True, allow_unicode=True).split("\n", 1)[0]


def _lookup(data: dict, path: list[str]) -> tuple[bool, object]:
    node: object = data
    for part in path:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False, None
    return True, node


def render_commented_config(base_text: str, data: dict) -> str:
    """Sync scalar leaf values from ``data`` into ``base_text``, preserving every
    comment, blank line, container (list/dict), and unknown key.

    ``opentorus config set`` only ever changes scalar leaves, so re-emitting just
    those keeps the inline field documentation (and any user-added comments or MCP
    blocks) intact across edits, instead of dumping bare comment-less YAML.
    """
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # (indent, key) of open mapping parents
    for line in base_text.splitlines():
        stripped = line.strip()
        match = _CONFIG_KEY_RE.match(line)
        if not stripped or stripped.startswith(("#", "- ")) or match is None:
            out.append(line)
            continue
        indent, key, value_part = len(match.group(1)), match.group(2), match.group(3)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = [k for _, k in stack] + [key]
        # A key with no value (or only a comment) opens a nested mapping.
        if value_part is None or value_part.startswith("#") or value_part.rstrip() in ("[]", "{}"):
            if value_part is None or value_part.startswith("#"):
                stack.append((indent, key))
            out.append(line)
            continue
        found, val = _lookup(data, path)
        if not found or isinstance(val, (dict, list)):
            out.append(line)  # unknown key or a container value → leave untouched
            continue
        out.append(f"{match.group(1)}{key}: {_format_scalar(val)}")
    trailing = "\n" if base_text.endswith("\n") else ""
    return "\n".join(out) + trailing


def write_config(path: Path, config: Config) -> None:
    """Persist a :class:`Config`, preserving the inline field documentation.

    Scalar values are written into the existing commented ``config.yaml`` (or the
    annotated default template on first write), so the per-field comments survive
    ``opentorus config set``.
    """
    base_text = path.read_text(encoding="utf-8") if path.exists() else default_config_yaml()
    path.write_text(render_commented_config(base_text, config.model_dump(mode="json")), "utf-8")


def _coerce(value: str) -> object:
    low = value.lower().strip()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none"}:
        return None
    if low in _UNLIMITED_STEP_TOKENS:
        return math.inf
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def set_dotted(config: Config, dotted_key: str, value: str) -> Config:
    """Return a new Config with ``dotted_key`` (e.g. ``model.provider``) updated.

    Raises :class:`ConfigError` for unknown sections/keys or invalid values.
    """
    data = config.model_dump(mode="json")
    parts = dotted_key.split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            raise ConfigError(f"Unknown config section '{part}' in '{dotted_key}'.")
        node = node[part]
    last = parts[-1]
    if last not in node:
        raise ConfigError(f"Unknown config key '{dotted_key}'.")
    node[last] = _coerce(value)
    try:
        return Config.model_validate(data)
    except Exception as exc:
        raise ConfigError(f"Invalid value for '{dotted_key}': {exc}") from exc
