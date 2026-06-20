"""Plan execution: drive the task pool one task at a time.

The executor picks the next pending task, runs a bounded agent loop on its goal,
marks it ``done`` or ``failed``, and records a checkpoint between tasks so each
step is recoverable. It is resumable: re-running continues from the first
unfinished task. A global task cap and a per-task step cap prevent runaway loops.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from opentorus.agent.loop import AgentLoop, ConfirmCallback
from opentorus.agent.run_state import RunState, load_run_state, save_run_state
from opentorus.agent.run_summary import RunSummary, build_run_summary
from opentorus.agent.task_validation import snapshot_artifacts, validate_task_contract
from opentorus.config import Config
from opentorus.errors import OpenTorusError, ProviderError
from opentorus.providers.base import BaseProvider
from opentorus.research.checkpoints import create_checkpoint
from opentorus.research.tasks import (
    batch_task_summary,
    list_tasks,
    next_pending_task,
    plan_tasks,
    reset_runnable_tasks,
    set_task_status,
)
from opentorus.tools.registry import ToolRegistry

DEFAULT_MAX_TASKS = 12

# Abort a plan after this many consecutive tasks in which the model never issued a
# tool call on its own (a strong signal the model can't do autonomous tool work).
_MAX_NO_TOOL_TASKS = 2


def _task_status_reporter(
    task_id: str, report: Callable[[str], None]
) -> Callable[[str, str | None], None]:
    """Map a task's agent-loop status events to indented progress lines."""

    def on_status(phase: str, detail: str | None) -> None:
        if phase == "tool":
            report(f"  {task_id}: running {detail or 'tool'}…")
        else:
            report(f"  {task_id}: thinking…")

    return on_status


class TaskExecution(BaseModel):
    task_id: str
    goal: str
    status: str
    answer: str
    verification: str = "not_needed"
    contract: str = ""


class PlanExecutionResult(BaseModel):
    tasks: list[TaskExecution] = []
    summary: RunSummary | None = None
    idle_reason: str = ""


def execute_plan(
    root: Path,
    ot_dir: Path,
    provider: BaseProvider,
    registry: ToolRegistry,
    config: Config,
    *,
    goal: str | None = None,
    confirm: ConfirmCallback | None = None,
    max_tasks: int = DEFAULT_MAX_TASKS,
    max_steps_per_task: int | None = None,
    verify: bool = True,
    fresh: bool = False,
    use_llm_planner: bool = True,
    progress: Callable[[str], None] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_status: Callable[[str, str | None], None] | None = None,
    on_llm_request: Callable[[list, list[dict] | None], None] | None = None,
    on_llm_response: Callable[[object], None] | None = None,
    stream_llm: bool = False,
    session_id: str | None = None,
    retry_failed: bool = False,
    only_task_id: str | None = None,
    on_thinking: Callable[[str], None] | None = None,
) -> PlanExecutionResult:
    """Plan ``goal`` (if given) then execute pending tasks one at a time."""

    def _report(line: str) -> None:
        if progress:
            progress(line)

    run_before = snapshot_artifacts(root, ot_dir)
    batch_ids: set[str] | None = None
    if goal is not None:
        if fresh:
            from opentorus.research.tasks import clear_task_pool

            clear_task_pool(ot_dir)
        _report("Planning the goal into tasks…")
        planned = plan_tasks(ot_dir, goal, provider, use_llm=use_llm_planner)
        batch_ids = {t.id for t in planned}
        _report(f"Planned {len(planned)} task(s) for this run.")
        save_run_state(
            ot_dir,
            RunState(
                goal=goal,
                session_id=session_id or "",
                mode="plan",
                batch_task_ids=sorted(batch_ids),
            ),
        )
    elif not list_tasks(ot_dir):
        raise OpenTorusError("No tasks to execute. Provide a goal to plan first.")
    else:
        state = load_run_state(ot_dir)
        if state and state.batch_task_ids:
            batch_ids = set(state.batch_task_ids)
        if retry_failed:
            reset_scope = {only_task_id} if only_task_id else batch_ids
            reset = reset_runnable_tasks(ot_dir, only_ids=reset_scope)
            if reset and progress:
                _report(f"Retrying {len(reset)} failed or stuck task(s): {', '.join(reset)}")

    steps_per_task = (
        max_steps_per_task if max_steps_per_task is not None else config.agent.max_steps
    )

    results: list[TaskExecution] = []
    total_tool_calls = 0
    consecutive_no_model_tools = 0
    aborted_reason = ""

    def _merged_status(task_id: str, phase: str, detail: str | None) -> None:
        reporter = _task_status_reporter(task_id, _report)
        reporter(phase, detail)
        if on_status is not None:
            on_status(phase, detail)

    for _ in range(max_tasks):
        task = next_pending_task(ot_dir, only_ids=batch_ids, only_task_id=only_task_id)
        if task is None:
            break

        before_task = snapshot_artifacts(root, ot_dir)
        set_task_status(ot_dir, task.id, "in_progress")
        _report(f"{task.id} ({task.category}): {task.goal}")

        if task.category == "experiment":
            from opentorus.agent.task_bootstrap import _completed_experiment_for_scripts

            completed_id = _completed_experiment_for_scripts(root, ot_dir)
            if completed_id:
                set_task_status(ot_dir, task.id, "done")
                answer = (
                    f"Skipped: {completed_id} already completed for the workspace "
                    "verification script. Cite it in claims; do not exp_new or exp_run again."
                )
                _report(f"  {task.id} → done (existing {completed_id})")
                results.append(
                    TaskExecution(
                        task_id=task.id,
                        goal=task.goal,
                        status="done",
                        answer=answer,
                        contract="Deliverable contract satisfied.",
                    )
                )
                continue

        loop = AgentLoop(
            root,
            ot_dir,
            provider,
            registry,
            config,
            max_steps=steps_per_task,
            session_id=session_id,
            confirm=confirm,
            on_text=on_text,
            on_status=lambda phase, detail, tid=task.id: _merged_status(  # type: ignore[misc]
                tid, phase, detail
            ),
            on_llm_request=on_llm_request,
            on_llm_response=on_llm_response,
            stream_llm=stream_llm,
            on_thinking=on_thinking,
        )
        if session_id is None and loop.session_id:
            session_id = loop.session_id
        loop._task_id = task.id
        verification = "not_needed"
        contract_detail = ""
        model_called_tools = True
        try:
            answer = loop.run(task.goal)
            status = "done"
            total_tool_calls += loop.tool_calls_this_run
            model_called_tools = loop.model_tool_calls > 0

            after_task = snapshot_artifacts(root, ot_dir)
            after_task.tool_names = list(loop.tools_used_this_run)
            check = validate_task_contract(
                task,
                before_task,
                after_task,
                tool_calls=loop.tool_calls_this_run,
                edited=loop.edited,
            )
            contract_detail = check.detail
            if not check.ok:
                status = "failed"
                answer = f"Result contract not met: {check.detail}\n\n{answer}"
                if loop.hit_max_steps:
                    answer += (
                        f"\n\nThe agent ran out of steps (agent.max_steps="
                        f"{steps_per_task}) before producing the deliverable. Reasoning models "
                        "spend turns thinking and gathering context; raise agent.max_steps "
                        "(e.g. `opentorus config set agent.max_steps 40`, or "
                        "`opentorus config set agent.max_steps inf` for no cap) and retry."
                    )

            if verify:
                from opentorus.agent.verify import verify_and_repair

                _report(f"  {task.id}: verifying result…")
                outcome = verify_and_repair(loop, root, ot_dir, config)
                verification = outcome.status
                if outcome.status == "failed":
                    status = "failed"
                    answer = f"{answer}\n{outcome.detail}"
        except (ProviderError, OpenTorusError) as exc:
            answer = f"Task failed: {exc}"
            status = "failed"

        set_task_status(ot_dir, task.id, status)  # type: ignore[arg-type]
        _report(f"  {task.id} → {status}")
        create_checkpoint(root, ot_dir, f"after {task.id}")
        results.append(
            TaskExecution(
                task_id=task.id,
                goal=task.goal,
                status=status,
                answer=answer,
                verification=verification,
                contract=contract_detail,
            )
        )

        # Circuit breaker: if the model itself never calls a tool across several
        # consecutive tasks, it cannot do autonomous work here. Abort the run with
        # an actionable message instead of burning the whole task pool (and tokens).
        if status == "failed" and not model_called_tools:
            consecutive_no_model_tools += 1
        else:
            consecutive_no_model_tools = 0
        if consecutive_no_model_tools >= _MAX_NO_TOOL_TASKS:
            aborted_reason = (
                f"Aborted after {consecutive_no_model_tools} consecutive tasks where the model "
                f"({config.model.provider}/{config.model.name}) returned text without calling any "
                "tool. This model is not reliably tool-calling in this workspace. Try a "
                "tool-capable model (e.g. `opentorus config set model.name qwen2.5:14b` or "
                "llama3.1:8b), lower agent.max_steps, or run a single explicit `opentorus run "
                '"…"` task.'
            )
            _report(aborted_reason)
            break

    done = sum(1 for r in results if r.status == "done")
    failed = sum(1 for r in results if r.status == "failed")
    summary = build_run_summary(
        root,
        ot_dir,
        before=run_before,
        tool_calls=total_tool_calls,
        tasks_done=done,
        tasks_failed=failed,
    )
    if session_id:
        state = load_run_state(ot_dir)
        save_run_state(
            ot_dir,
            RunState(
                goal=state.goal if state else (goal or ""),
                session_id=session_id,
                mode="plan",
                batch_task_ids=state.batch_task_ids if state else sorted(batch_ids or []),
            ),
        )
    idle_reason = aborted_reason
    if not idle_reason and not results:
        counts = batch_task_summary(ot_dir, only_ids=batch_ids)
        pending = counts.get("proposed", 0) + counts.get("in_progress", 0)
        failed = counts.get("failed", 0)
        done = counts.get("done", 0)
        if not list_tasks(ot_dir):
            idle_reason = "No tasks in the pool."
        elif pending == 0 and failed == 0 and done > 0:
            idle_reason = "All planned tasks in this batch are complete."
        elif pending == 0 and failed > 0:
            idle_reason = (
                f"{failed} task(s) failed and were not retried. "
                "Run `opentorus task retry` or `opentorus run --resume` to try again."
            )
        else:
            idle_reason = "No pending tasks matched the saved batch."
    return PlanExecutionResult(tasks=results, summary=summary, idle_reason=idle_reason)
