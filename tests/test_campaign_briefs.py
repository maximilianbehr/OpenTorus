"""What the next work item is told: abandon reasons, review findings, prompt rules.

A brief is the only channel from one attempt to the next. These tests pin that a
worker that gives up says why (and the reason reaches the next brief without
destabilising the retry gate), that referee/critic rejections reach the branch's next
brief quoted as data and suspend a branch after two in a row, and that the campaign
worker prompts carry the working rules.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.clock import StepClock
from opentorus.campaign.failures import (
    NO_COUNTERARGUMENT,
    build_failure_signature,
    describe_failure,
    signature_key,
)
from opentorus.campaign.models import (
    FailureSignature,
    NormalizedProblem,
    WorkBudget,
    WorkerContext,
    WorkerRole,
)
from opentorus.campaign.workers.base import (
    ABANDON_RULE,
    MAX_ABANDON_REASON_CHARS,
    ROLE_ALLOWED_TOOLS,
    WorkerRuntime,
    abandon_reason_from,
)
from opentorus.config import default_config
from opentorus.providers.pool import ProviderPool
from support.campaign import make_workspace
from support.providers import ScriptedProvider, message


def _ctx(pid: str, role: WorkerRole, **overrides: object) -> WorkerContext:
    from opentorus.campaign.scheduler import ROLE_TASK_CLASS

    base: dict[str, object] = {
        "campaign_id": "CAMPAIGN-0001",
        "branch_id": "BRANCH-0001",
        "work_item_id": "WI-0001",
        "role": role,
        "task_class": ROLE_TASK_CLASS[role].value,
        "mode": "exploration",
        "root_problem": NormalizedProblem(
            problem_id=pid, statement="For every n >= 1, the property P(n) holds."
        ),
        "budget": WorkBudget(max_steps=3),
        "session_id": "CAMPAIGN-0001:BRANCH-0001:WI-0001",
        "allowed_tools": ROLE_ALLOWED_TOOLS[role],
    }
    base.update(overrides)
    return WorkerContext(**base)  # type: ignore[arg-type]


def _runtime(root: Path, ot: Path, provider: ScriptedProvider) -> WorkerRuntime:
    config = default_config()
    return WorkerRuntime(
        root=root,
        ot_dir=ot,
        config=config,
        pool=ProviderPool(config, ot_dir=ot, factory=lambda _cfg: provider),
        clock=StepClock(),
    )


# --------------------------------------------------------------------------------------
# item 10: abandon with a reason
# --------------------------------------------------------------------------------------


def test_abandon_reason_is_parsed_only_from_an_explicit_give_up_line() -> None:
    text = "I tried induction.\nGIVE UP: tried induction on n -- the step needs P(n+1) > P(n)"
    assert abandon_reason_from(text) == "tried induction on n -- the step needs P(n+1) > P(n)"
    assert abandon_reason_from("**Giving up:** no bound   on   the error") == (
        "no bound on the error"
    )
    # the last marker wins; a loop's own stop message is never a reason
    assert abandon_reason_from("give up: a\nmore\nGive-up — b") == "b"
    assert abandon_reason_from("Reached the maximum number of steps without a final answer.") == ""
    assert abandon_reason_from("") == "" and abandon_reason_from(None) == ""
    long = abandon_reason_from("GIVE UP: " + "x" * 5000)
    assert len(long) == MAX_ABANDON_REASON_CHARS and long.endswith("...")


def test_abandon_reason_is_stored_but_never_keyed() -> None:
    common: dict[str, object] = {
        "role": WorkerRole.numerical_experimenter,
        "strategy_class": "numerical_experiment",
        "tool_or_solver": "numerical",
        "error_category": "model_no_progress",
        "counterargument": "no experiment with parseable output",
    }
    plain = build_failure_signature(**common)  # type: ignore[arg-type]
    told = build_failure_signature(**common, abandon_reason="tried n<50; overflow")  # type: ignore[arg-type]
    assert told.abandon_reason == "tried n<50; overflow"
    # prose differs run to run; keying on it would make every failure look new
    assert plain.key == told.key == signature_key(told)


def test_describe_failure_never_prints_an_empty_counterargument() -> None:
    sig = FailureSignature(signature_id="FSIG-0001", key="k", strategy_class="s")
    assert describe_failure(sig) == NO_COUNTERARGUMENT
    sig.abandon_reason = "the bound diverges for n > 7"
    assert describe_failure(sig) == (
        "worker's stated reason for giving up (unverified): the bound diverges for n > 7"
    )
    sig.counterargument = "no witness in range"
    text = describe_failure(sig)
    assert text.startswith("no witness in range; ") and "diverges for n > 7" in text


def test_numerical_worker_records_the_stated_reason_on_its_signature(tmp_path: Path) -> None:
    from opentorus.campaign.workers.numerical import NumericalWorker

    root, ot, pid = make_workspace(tmp_path)
    give_up = "GIVE UP: tried a sieve up to 10^6 -- memory exhausted before any bound"
    provider = ScriptedProvider([message(give_up)], name="scripted")
    ctx = _ctx(pid, WorkerRole.numerical_experimenter, strategy_key="numerical_experiment")
    result = NumericalWorker().run(ctx, _runtime(root, ot, provider))
    assert result.status == "failed"
    assert result.abandon_reason == "tried a sieve up to 10^6 -- memory exhausted before any bound"
    assert result.failure_signature is not None
    assert result.failure_signature.abandon_reason == result.abandon_reason
    # the prompt carried the rule
    prompt = provider.calls[0][0][-1].content
    assert ABANDON_RULE in prompt


def test_reason_reaches_the_reduced_signature_and_the_next_prover_brief() -> None:
    from opentorus.campaign import events as ev
    from opentorus.campaign import reducer
    from opentorus.campaign.workers.prover import branch_instructions

    sig = build_failure_signature(
        role=WorkerRole.prover,
        strategy_class="proof_sketch",
        tool_or_solver="proof_write",
        error_category="model_no_progress",
        counterargument="",
        branch_id="BRANCH-0001",
    ).model_copy(update={"signature_id": "FSIG-0001"})
    snap = _seeded_snapshot()
    first = _event(2, ev.EventType.failure_signature_recorded, sig)
    snap = reducer.apply(snap, first)
    later = sig.model_copy(update={"abandon_reason": "Cauchy-Schwarz loses a factor n"})
    snap = reducer.apply(snap, _event(3, ev.EventType.failure_signature_recorded, later))
    stored = snap.failure_signatures["FSIG-0001"]
    assert stored.occurrences == 2
    assert stored.abandon_reason == "Cauchy-Schwarz loses a factor n"
    assert stored.key == sig.key
    ctx = _ctx(
        "PROBLEM-0001",
        WorkerRole.prover,
        failure_signatures=(stored,),
        strategy_key="proof_sketch",
    )
    brief = branch_instructions(ctx)
    assert "Cauchy-Schwarz loses a factor n" in brief
    assert "(no counterargument)" not in brief
    assert ABANDON_RULE in brief


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _seeded_snapshot():  # noqa: ANN202
    from opentorus.campaign import events as ev
    from opentorus.campaign import reducer
    from opentorus.campaign.models import CampaignRecord

    record = CampaignRecord(
        id="CAMPAIGN-0001",
        problem_id="PROBLEM-0001",
        mode="exploration",
        created_at=StepClock().now(),
    )
    return reducer.empty_snapshot(_event(1, ev.EventType.campaign_created, record))


def _event(seq: int, event_type: str, payload: object):  # noqa: ANN202
    from opentorus.campaign import events as ev

    return ev.build_event(
        campaign_id="CAMPAIGN-0001",
        seq=seq,
        timestamp=StepClock().now(),
        event_type=event_type,
        payload=payload,  # type: ignore[arg-type]
    )
