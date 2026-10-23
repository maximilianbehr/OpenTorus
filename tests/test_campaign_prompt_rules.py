"""The working rules every model-driven campaign worker prompt carries (campaign only)."""

from __future__ import annotations

from opentorus.campaign.models import (
    CampaignMode,
    NormalizedProblem,
    WorkBudget,
    WorkerContext,
    WorkerRole,
)
from opentorus.campaign.portfolio import PortfolioContext
from opentorus.campaign.scheduler import ROLE_TASK_CLASS
from opentorus.campaign.workers import falsifier, numerical, symbolic
from opentorus.campaign.workers.base import (
    ABANDON_RULE,
    CHECK_BEFORE_SUBMIT_RULE,
    NO_ENDLESS_RESTART_RULE,
    REWORDING_RULE,
    ROLE_ALLOWED_TOOLS,
    TOOL_REPLY_RULE,
)
from opentorus.campaign.workers.prover import branch_instructions
from opentorus.campaign.workers.strategist import strategist_prompt

PID = "PROBLEM-0001"


def _ctx(role: WorkerRole) -> WorkerContext:
    return WorkerContext(
        campaign_id="CAMPAIGN-0001",
        branch_id="BRANCH-0001",
        work_item_id="WI-0001",
        role=role,
        task_class=ROLE_TASK_CLASS[role].value,
        mode=CampaignMode.exploration,
        root_problem=NormalizedProblem(problem_id=PID, statement="For every n, P(n)."),
        budget=WorkBudget(max_steps=3),
        allowed_tools=ROLE_ALLOWED_TOOLS[role],
    )


def test_rule_texts_are_pinned() -> None:
    assert TOOL_REPLY_RULE == (
        "A reply without a tool call ends your run; keep working through your tools."
    )
    assert CHECK_BEFORE_SUBMIT_RULE == "Do not submit what you have not checked yourself."
    assert NO_ENDLESS_RESTART_RULE == (
        "Do not restart an unsuccessful branch indefinitely; use what was learned."
    )
    assert REWORDING_RULE.startswith("Rewording is not different")
    assert "abandoned" in REWORDING_RULE and "as taken as one being worked" in REWORDING_RULE


def test_every_model_driven_worker_prompt_carries_the_rules() -> None:
    prompts = {
        "prover": branch_instructions(_ctx(WorkerRole.prover)),
        "falsifier": falsifier._prompt(_ctx(WorkerRole.falsifier)),
        "numerical": numerical._prompt(_ctx(WorkerRole.numerical_experimenter), "numerical"),
        "symbolic": symbolic._prompt(_ctx(WorkerRole.symbolic_experimenter)),
    }
    rules = (TOOL_REPLY_RULE, CHECK_BEFORE_SUBMIT_RULE, NO_ENDLESS_RESTART_RULE, ABANDON_RULE)
    for name, prompt in prompts.items():
        for rule in rules:
            assert rule in prompt, (name, rule)


def test_strategist_prompt_says_rewording_is_not_different() -> None:
    prompt = strategist_prompt(
        PortfolioContext(
            campaign_id="CAMPAIGN-0001",
            mode=CampaignMode.exploration,
            problem=NormalizedProblem(problem_id=PID, statement="s"),
        )
    )
    assert REWORDING_RULE in prompt
