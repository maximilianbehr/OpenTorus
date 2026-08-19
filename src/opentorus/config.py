"""Configuration schema and YAML loader for OpenTorus.

The configuration lives in ``.opentorus/config.yaml`` and is parsed into a typed
:class:`Config` model. Unknown keys are preserved leniently so that newer config
files remain readable by older code paths during development.
"""

from __future__ import annotations

import logging
import math
import re
from importlib.resources import files
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from opentorus.errors import ConfigError

_logger = logging.getLogger("opentorus")

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
    # Sampling shape. Unset means "whatever the model's own Modelfile says", which is
    # not nothing: gemma4 ships top_k 64 / top_p 0.95, mistral-medium ships neither and
    # falls back to Ollama's 40 / 0.9, and qwen3.6 carries presence_penalty 1.5. Any
    # comparison across models that leaves these unset is comparing sampling as much as
    # models. The agent loop is dominated by exact-syntax output — tool names, JSON
    # certificates, PAPER-0002 — where a wide tail is what produces "read_ file" and
    # "python- sci", so tightening these is the point. Temperature is *not* driven to 0:
    # a run that cannot vary cannot escape a failing call either, and the identical-
    # failure guards exist because that happens.
    top_p: float | None = None
    top_k: int | None = None
    # Fixes the sampler so a run can be replayed. Left unset by default (a fixed seed
    # would make every dossier in a sweep explore the same way); set it for before/after
    # comparisons, where an unseeded model simply picks a different route and the
    # regression proves nothing — which happened twice in one day.
    seed: int | None = None
    # Max tokens to generate; -1 means no limit. When unset and tools are used,
    # OpenTorus defaults to -1 for Ollama to reduce truncated tool-call JSON.
    num_predict: int | None = None
    # Hard cap on output tokens for providers that require one (e.g. Anthropic).
    # Unset falls back to a provider default; raise it for long proofs.
    max_tokens: int | None = None
    # Ollama-only: how long the server keeps the model loaded after a request ("30m",
    # "2h", "-1" = until the server stops). Unset = the server's default (5 minutes).
    # A campaign worker often pauses for longer than that between calls (an experiment
    # runs, a paper is parsed) and the next call then pays a cold reload — 25 minutes
    # for a 31B model on a cluster's network filesystem, observed as a stall.
    keep_alive: str | None = None
    # Before an agent run, verify the model can call tools (a one-shot capability probe;
    # also reads Ollama /api/show). OpenTorus is useless without tool calling, so a model
    # that cannot is refused with a clear message. Set false to skip the check.
    verify_tool_calling: bool = True


class ModelProfile(ModelConfig):
    """A named model profile for per-task routing (``models.profiles``).

    Every ``model:`` key is accepted, plus a declared capability list (used when the
    provider kind alone cannot tell — e.g. tool calling on an Ollama model) and an
    explicit ``local_only`` override of the local-vs-cloud classification.
    """

    capabilities: list[str] = Field(default_factory=list)
    local_only: bool | None = None


class ModelsConfig(BaseModel):
    """Named model profiles. The ``model:`` block is always the implicit profile
    ``default``; ``default_profile`` may name a profile to use instead."""

    default_profile: str | None = None
    profiles: dict[str, ModelProfile] = Field(default_factory=dict)


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
    # Stop gap-filling after this many consecutive steps that do NOT reduce the proof's
    # gap count — even when the caps above are inf. Bounds an otherwise endless grind when
    # a model cannot close gaps; a model that IS shrinking the gap list resets the window
    # and keeps going. Positive integer, or inf / unlimited / -1 to disable.
    prove_gap_fill_no_progress_steps: float = 16
    # Campaign gate (opt-in, set by campaign example drivers): hold the clean completion
    # of a prove run until at least one experiment or one proof_submit is recorded. The
    # gate forces the ATTEMPT, never the outcome — the no-progress windows still end a
    # run that cannot comply, with an honest stop message, and the campaign verdict stays
    # with the artifacts. Ignored in --disprove mode. Both smoke runs of the initial
    # campaign showed that statement prose alone never starts the instance program.
    prove_require_instance_work: bool = False
    # Wall-clock budget for a single agent run, in seconds (None = no limit).
    # The other guards all assume turns return: a hung model call trips none of them,
    # and with max_steps: inf that is unbounded. This is the one bound that holds no
    # matter what the model does. Checked between steps, so it never interrupts a call
    # in flight — the provider timeout owns that.
    max_wall_seconds: float | None = None
    # When the model declares the sketch gap-free, give the hostile referee the final say:
    # if it blocks (unsupported result-claims, contradictions) the loop reopens the proof's
    # gap list with the referee's findings and keeps working instead of accepting an
    # overclaiming "done". Closes the escape where a model empties `gaps` by relabelling
    # unresolved steps as prose "Open Problems". Only active while prove_until_gaps_closed.
    prove_referee_reopens_gaps: bool = True

    @field_validator(
        "max_steps", "prove_gap_fill_max_steps", "prove_gap_fill_no_progress_steps", mode="before"
    )
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
    # Put the volatile blocks (workspace inventory, retrieval hits, recovery hint) at
    # the END of the request instead of near the front, so the stable head + history
    # form a prefix a local server can reuse from its KV cache across steps. Measured
    # before this change on a real run: prompt_eval_count climbed 8k -> 30k in step
    # with latency, i.e. the full prompt was re-evaluated every single call, and 96%
    # of all tokens processed were re-sent prompt. Set false for the old ordering.
    stable_prefix: bool = True
    # Recent session turns replayed verbatim into each request's context. Larger keeps
    # the model aware of earlier papers/claims/proof steps (less amnesia); it is bounded
    # by token_budget, which triggers compaction when the assembled context grows too big.
    history_turns: int = 50
    # History token budget before compaction. Must comfortably hold the system head
    # (statement + artifact inventory) plus a few paper reading notes (~900 tokens each)
    # and the current proof; a value too small (e.g. 6000) forces a compaction nearly
    # every turn during proof work, which adds summarization calls and induces amnesia.
    # Well within modern model context windows; lower it for small local models.
    token_budget: int = 24000
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
    # Symbolic identity/inequality checking via sympy (a core dependency); enabled by
    # default. Discharges a plain symbolic certificate, returning accepted only on a
    # symbolic proof and inconclusive otherwise — never faking rigor.
    sympy: bool = True
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

    ``task_routes`` maps a *task class* (``proof_development``, ``narration``, …,
    ``default``) to an ordered list of profile names from ``models.profiles``: the
    first eligible profile answers, the rest are fallbacks. ``task_models`` is the
    older form (task class → bare model name, run on the default profile's provider)
    and is still honoured. Empty mappings fall back to the default profile. The
    chosen profile and the model that actually answered are recorded per turn.
    """

    enabled: bool = False
    task_models: dict[str, str] = Field(default_factory=dict)
    task_routes: dict[str, list[str]] = Field(default_factory=dict)


class GovernanceConfig(BaseModel):
    """Cost, secrets, and model-use governance (Phase 24, M75).

    ``dlp`` adds a final pre-egress secret/PII scan that fails closed: a detected
    secret blocks the send. Budgets and routing build on the usage ledger (M31)
    and research-loop budgets (M53) without loosening any safety guarantee.
    """

    dlp: bool = True
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)


CampaignMode = Literal["prove-or-refute", "exploration", "survey"]


class SchedulerWeights(BaseModel):
    """Multipliers for the campaign scheduler's documented scoring factors."""

    novelty: float = 1.0
    root_impact: float = 1.0
    verifier_readiness: float = 1.0
    dependency: float = 1.0
    cost: float = 1.0
    redundancy: float = 1.0
    failure: float = 1.0


class CampaignConfig(BaseModel):
    """Defaults for ``opentorus campaign`` (the portfolio-based campaign engine).

    Every 0-valued budget means "not configured / unlimited". CLI flags override
    these per run; the engine snapshots the effective values into ``campaign.yaml``.
    """

    default_mode: CampaignMode = "exploration"
    # Proposals kept after de-duplication (``--branches`` overrides).
    initial_branches: int = 4
    # Branches scheduled concurrently; the rest queue as ``proposed``.
    max_active_branches: int = 3
    # v1 executes sequentially; a larger value is capped to 1 with a diagnostic.
    max_parallel_workers: int = 1
    # Total model turns across all workers; 0 = not configured / unlimited.
    max_steps: int = 50
    max_wall_seconds: int = 0
    token_budget: int = 0
    cost_budget: float = 0.0
    # Model turns per branch before it is exhausted.
    branch_step_budget: int = 10
    # Cap on the ``timeout`` a campaign worker may pass to exp_run (seconds; 0 = no cap).
    # A model asked for 1800 s searches and one work item then blocked a branch for half
    # an hour on a single experiment; the cap rewrites the argument and is reported.
    max_experiment_seconds: int = 600
    require_literature_mapping: bool = True
    require_root_relation: bool = True
    # Rewrite snapshot.json after every event (else at phase boundaries).
    persist_every_event: bool = True
    # Opt-in: ``opentorus research`` also records an exploration campaign.
    record_research: bool = False
    scheduler_weights: SchedulerWeights = Field(default_factory=SchedulerWeights)


class Config(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
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
    campaign: CampaignConfig = Field(default_factory=CampaignConfig)

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


def _scalar_leaves(data: dict, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            paths.extend(_scalar_leaves(value, prefix + (key,)))
        elif not isinstance(value, list):
            paths.append(prefix + (key,))
    return paths


def render_commented_config(base_text: str, data: dict) -> str:
    """Sync scalar leaf values from ``data`` into ``base_text``, preserving every
    comment, blank line, container (list/dict), and unknown key.

    ``opentorus config set`` only ever changes scalar leaves, so re-emitting just
    those keeps the inline field documentation (and any user-added comments or MCP
    blocks) intact across edits, instead of dumping bare comment-less YAML.

    Scalar leaves present in ``data`` but absent from ``base_text`` are **appended**
    instead of being dropped: a config file written before a field existed must not
    silently lose that field on the next ``config set`` — a real run spent its whole
    budget with a gate the driver believed it had enabled. A leaf whose parent
    section exists is appended at the end of that section. A leaf whose parent
    mapping is missing altogether (an old file predating ``campaign:`` or
    ``models:``, or a ``scheduler_weights:`` sub-mapping) is emitted together with
    the missing intermediate keys, at the end of its nearest existing ancestor
    section — a whole missing top-level section is appended at EOF as a block.
    Container values (dicts/lists) that live *under* such a missing mapping are
    emitted too (via indented ``yaml.safe_dump``): the file has no line for them
    that could be preserved.

    An **empty** one-line container (``profiles: {}``, ``mcp: []``) whose value in
    ``data`` is non-empty is replaced by a proper block (the header line at the same
    indent, the value below it via indented ``yaml.safe_dump``): the file has nothing
    inside it worth preserving, and leaving the line alone would silently drop what
    the caller set (``models.profiles``, ``routing.task_routes``). A *non-empty*
    one-line container (``{a: 1}``, ``[x]``) is a hand-edit surface and is left
    untouched; :func:`write_config` reports what that dropped.
    """
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # (indent, key) of open mapping parents
    seen: set[tuple[str, ...]] = set()  # scalar leaf paths present in base_text
    # Per mapping path: index (into out) of its last key line, and its child indent.
    section_last: dict[tuple[str, ...], int] = {(): -1}
    section_indent: dict[tuple[str, ...], int] = {(): 0}
    # Indent of a mapping's own header line (fallback child indent = header + 2).
    header_indent: dict[tuple[str, ...], int] = {}
    # Paths whose value is a container written on one line (``{}``, ``[]``, flow
    # style): left untouched, and nothing is ever appended *inside* them.
    container_paths: set[tuple[str, ...]] = set()
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
        for depth in range(len(path)):
            section_last[tuple(path[:depth])] = len(out)
        section_indent.setdefault(tuple(path[:-1]), indent)
        # A key with no value (or only a comment) opens a nested mapping. Register the
        # header itself as the section's last line so a section that has a header but
        # no keys yet still counts as existing (leaves go right under the header).
        if value_part is None or value_part.startswith("#"):
            stack.append((indent, key))
            header_indent[tuple(path)] = indent
            section_last[tuple(path)] = len(out)
            out.append(line)
            continue
        if value_part.rstrip() in ("[]", "{}"):
            container_paths.add(tuple(path))
            found, val = _lookup(data, path)
            empty_kind = dict if value_part.rstrip() == "{}" else list
            if found and isinstance(val, empty_kind) and val:
                # The empty container has children now: render it as a block in place.
                dumped = yaml.safe_dump(
                    {key: val}, sort_keys=False, allow_unicode=True, default_flow_style=False
                )
                pad = match.group(1)
                out.extend(
                    pad + text if text else text for text in dumped.rstrip("\n").splitlines()
                )
                continue
            out.append(line)
            continue
        seen.add(tuple(path))
        found, val = _lookup(data, path)
        if not found or isinstance(val, (dict, list)):
            if found:
                container_paths.add(tuple(path))
            out.append(line)  # unknown key or a container value → leave untouched
            continue
        out.append(f"{match.group(1)}{key}: {_format_scalar(val)}")

    def child_indent(section: tuple[str, ...]) -> int:
        if section in section_indent:
            return section_indent[section]
        return header_indent.get(section, -2) + 2

    def exists(section: tuple[str, ...]) -> bool:
        return section in section_last and section_last[section] >= 0

    # Missing leaves whose parent section exists are appended as single lines; the
    # others are grouped by the topmost missing mapping on their path and emitted as
    # one YAML block under the nearest existing ancestor. Nothing is appended inside
    # a one-line container (``profiles: {}``): that line stays as it is.
    inserts: dict[int, list[str]] = {}  # insertion index -> lines, in data order
    tail_blocks: list[list[str]] = []
    block_roots: dict[tuple[str, ...], tuple[str, ...]] = {}  # missing root -> anchor
    for leaf in _scalar_leaves(data):
        if leaf in seen or any(leaf[:k] in container_paths for k in range(1, len(leaf))):
            continue
        parent = leaf[:-1]
        if exists(parent):
            _, val = _lookup(data, list(leaf))
            line = f"{' ' * child_indent(parent)}{leaf[-1]}: {_format_scalar(val)}"
            inserts.setdefault(section_last[parent] + 1, []).append(line)
            continue
        depth = len(parent)
        while depth > 0 and not exists(parent[:depth]):
            depth -= 1
        block_roots.setdefault(leaf[: depth + 1], parent[:depth])
    for root, anchor in block_roots.items():
        _, subtree = _lookup(data, list(root))
        dumped = yaml.safe_dump(
            {root[-1]: subtree}, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
        pad = " " * child_indent(anchor)
        lines = [pad + text if text else text for text in dumped.rstrip("\n").splitlines()]
        if anchor == ():
            tail_blocks.append(lines)
        else:
            inserts.setdefault(section_last[anchor] + 1, []).extend(lines)
    # Deepest insertion points first, so earlier indices stay valid.
    for index in sorted(inserts, reverse=True):
        out[index:index] = inserts[index]
    for lines in tail_blocks:
        if out and out[-1].strip():
            out.append("")
        out.extend(lines)
    trailing = "\n" if base_text.endswith("\n") or (tail_blocks and out) else ""
    return "\n".join(out) + trailing


def dropped_leaves(rendered: str, data: dict) -> list[str]:
    """Dotted paths of scalar leaves in ``data`` that ``rendered`` does not carry.

    ``render_commented_config`` leaves a non-empty one-line container alone, so a
    value set under it never reaches the file. Re-parsing the rendered text and
    comparing scalar leaves is the honest check: it names exactly what was lost
    instead of assuming the render was complete.
    """
    try:
        parsed = yaml.safe_load(rendered) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(parsed, dict):
        return []
    # Compare what a *load* of the file yields, so a key the file merely omits (and
    # that loads back as its default) is not reported as lost.
    try:
        parsed = Config.model_validate(parsed).model_dump(mode="json")
    except Exception:  # noqa: BLE001 — an unloadable render still reports raw leaves
        pass
    dropped: list[str] = []
    for leaf in _scalar_leaves(data):
        _, wanted = _lookup(data, list(leaf))
        found, actual = _lookup(parsed, list(leaf))
        if not found or actual != wanted:
            dropped.append(".".join(leaf))
    return dropped


def write_config(path: Path, config: Config) -> None:
    """Persist a :class:`Config`, preserving the inline field documentation.

    Scalar values are written into the existing commented ``config.yaml`` (or the
    annotated default template on first write), so the per-field comments survive
    ``opentorus config set``. A value that could not be written because it lives
    under a hand-edited one-line container is reported by name (never silently
    lost).
    """
    base_text = path.read_text(encoding="utf-8") if path.exists() else default_config_yaml()
    data = config.model_dump(mode="json")
    rendered = render_commented_config(base_text, data)
    path.write_text(rendered, "utf-8")
    lost = dropped_leaves(rendered, data)
    if lost:
        _logger.warning(
            "config: %d value(s) were not written to %s because they live under a one-line "
            "container that was left as written (%s); edit that line by hand.",
            len(lost),
            path,
            ", ".join(lost),
        )


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
