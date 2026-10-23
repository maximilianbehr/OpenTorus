"""Remote and HPC execution backends (Milestone 65).

``RemoteBackend`` (plain SSH) and ``SlurmBackend`` (SSH + ``sbatch``) implement
the M55 :class:`ExecutionBackend` protocol: they stage the experiment directory
to a remote host, run/submit the command, and retrieve results into the local
``results/`` — returning the same :class:`ShellResult` shape as a local run, so
manifests and provenance are unchanged.

Argv and submission scripts are assembled by pure methods (testable without a
cluster). Execution goes through an injectable ``runner`` so a stubbed run
returns the standard result shape. Credentials (SSH keys) flow through the user's
SSH config and the sensitive-file policy (M20); they are never bundled.
"""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable
from pathlib import Path

from opentorus.execution.base import ExecutionRequest
from opentorus.execution.intents import IntentLog, args_digest, new_operation_id
from opentorus.tools.shell import ShellResult, run_argv

Runner = Callable[..., ShellResult]


class _SSHBase:
    """Shared SSH plumbing: target, availability, staging, and fetching."""

    name = "ssh"
    requires_image = False

    def __init__(
        self,
        *,
        host: str | None = None,
        user: str | None = None,
        remote_root: str = "~/opentorus-runs",
        ssh_command: str = "ssh",
        copy_command: str = "scp",
        runner: Runner | None = None,
    ) -> None:
        self.host = host
        self.user = user
        self.remote_root = remote_root
        self.ssh_command = ssh_command
        self.copy_command = copy_command
        self._runner: Runner = runner or run_argv

    def _ssh_binary(self) -> str:
        parts = shlex.split(self.ssh_command)
        return parts[0] if parts else ""

    def _copy_binary(self) -> str:
        parts = shlex.split(self.copy_command)
        return parts[0] if parts else ""

    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else (self.host or "")

    def is_available(self) -> bool:
        return bool(self.host) and shutil.which(self._ssh_binary()) is not None

    def version(self) -> str | None:
        if not self.is_available():
            return None
        result = self._runner([self._ssh_binary(), "-V"], timeout=20)
        text = (result.stderr or result.stdout).strip()
        return text.splitlines()[0] if text else None

    def remote_workdir(self, request: ExecutionRequest) -> str:
        return f"{self.remote_root}/{Path(request.workdir).name}"

    def stage_argv(self, request: ExecutionRequest) -> list[str]:
        """Copy the experiment directory up to the remote root (recursive)."""
        return [
            *shlex.split(self.copy_command),
            "-r",
            str(request.workdir),
            f"{self.target()}:{self.remote_root}/",
        ]

    def fetch_argv(self, request: ExecutionRequest) -> list[str]:
        """Copy the remote ``results/`` directory back into the local workdir."""
        remote = self.remote_workdir(request)
        return [
            *shlex.split(self.copy_command),
            "-r",
            f"{self.target()}:{remote}/results",
            str(request.workdir),
        ]

    def _unavailable(self, request: ExecutionRequest, reason: str) -> ShellResult:
        return ShellResult(command=request.command, stdout="", stderr=reason, exit_code=127)

    def _preflight(self, request: ExecutionRequest) -> ShellResult | None:
        if not self.host:
            return self._unavailable(
                request,
                f"No remote host configured for backend '{self.name}' "
                "(set config.execution.remote.host); run not executed.",
            )
        if shutil.which(self._ssh_binary()) is None:
            return self._unavailable(
                request,
                f"'{self._ssh_binary()}' is not installed; remote execution unavailable.",
            )
        return None


class RemoteBackend(_SSHBase):
    """Run a command on a remote host over SSH."""

    name = "ssh"

    def build_argv(self, request: ExecutionRequest) -> list[str]:
        remote = self.remote_workdir(request)
        inner = f"cd {shlex.quote(remote)} && {request.command}"
        return [*shlex.split(self.ssh_command), self.target(), inner]

    def run(self, request: ExecutionRequest) -> ShellResult:
        unavailable = self._preflight(request)
        if unavailable is not None:
            return unavailable
        staged = self._runner(self.stage_argv(request), timeout=request.limits.timeout)
        if staged.exit_code != 0:
            return staged
        result = self._runner(
            self.build_argv(request), timeout=request.limits.timeout, label=request.command
        )
        self._runner(self.fetch_argv(request), timeout=request.limits.timeout)
        return result


class SlurmBackend(_SSHBase):
    """Submit a command to a Slurm cluster via SSH + ``sbatch``."""

    name = "slurm"

    def __init__(
        self,
        *,
        partition: str | None = None,
        time_limit: str | None = None,
        account: str | None = None,
        extra_sbatch: list[str] | None = None,
        intent_log_path: Path | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.intent_log_path = intent_log_path
        self.partition = partition
        self.time_limit = time_limit
        self.account = account
        self.extra_sbatch = extra_sbatch or []

    _SCRIPT_NAME = "opentorus_job.sbatch"

    def build_sbatch_script(self, request: ExecutionRequest, *, job_name: str = "opentorus") -> str:
        remote = self.remote_workdir(request)
        lines = ["#!/bin/bash", f"#SBATCH --job-name={job_name}"]
        if self.partition:
            lines.append(f"#SBATCH --partition={self.partition}")
        if self.time_limit:
            lines.append(f"#SBATCH --time={self.time_limit}")
        if self.account:
            lines.append(f"#SBATCH --account={self.account}")
        for extra in self.extra_sbatch:
            lines.append(f"#SBATCH {extra}")
        lines += [
            "#SBATCH --output=results/slurm-%j.out",
            "#SBATCH --error=results/slurm-%j.err",
            "",
            f"cd {shlex.quote(remote)}",
            request.command,
        ]
        return "\n".join(lines) + "\n"

    def build_submit_argv(self, request: ExecutionRequest) -> list[str]:
        remote = self.remote_workdir(request)
        script = f"{remote}/{self._SCRIPT_NAME}"
        return [
            *shlex.split(self.ssh_command),
            self.target(),
            f"sbatch --parsable {shlex.quote(script)}",
        ]

    def build_argv(self, request: ExecutionRequest) -> list[str]:
        """Protocol entry point: the concrete argv is the sbatch submission."""
        return self.build_submit_argv(request)

    # -- intent-before-dispatch ---------------------------------------------------

    INTENTS_NAME = "slurm-intents.jsonl"

    def intent_log(self, request: ExecutionRequest) -> IntentLog:
        path = self.intent_log_path or Path(request.workdir) / self.INTENTS_NAME
        return IntentLog(path)

    def _remote(self, command: str) -> list[str]:
        return [*shlex.split(self.ssh_command), self.target(), command]

    def find_job(self, op_id: str, timeout: int = 60) -> tuple[str | None, bool]:
        """Look the job up by its name (the op id) instead of resubmitting.

        Returns ``(job_id, determined)``: ``determined`` is False when the cluster
        could not be asked (ssh down), so absence means nothing.
        """
        name = shlex.quote(op_id)
        queued = self._runner(
            self._remote(f"squeue --noheader --name {name} --format %i"), timeout=timeout
        )
        if queued.exit_code == 0 and queued.stdout.strip():
            return queued.stdout.split()[0], True
        accounted = self._runner(
            self._remote(f"sacct --noheader -X --name {name} --format JobID"), timeout=timeout
        )
        if accounted.exit_code == 0 and accounted.stdout.strip():
            return accounted.stdout.split()[0], True
        determined = queued.exit_code == 0 and accounted.exit_code == 0
        return None, determined

    @staticmethod
    def _unknown_transport(result: ShellResult) -> bool:
        # A timeout, or ssh's own failure code (255), after the command may have
        # reached the cluster: the submission may or may not have happened.
        return result.timed_out or result.exit_code == 255

    @staticmethod
    def _submitted(request: ExecutionRequest, job_id: str, note: str) -> ShellResult:
        return ShellResult(
            command=f"sbatch {request.command}", stdout=job_id + "\n", stderr=note, exit_code=0
        )

    @staticmethod
    def _unknown(request: ExecutionRequest, op_id: str, why: str) -> ShellResult:
        return ShellResult(
            command=f"sbatch {request.command}",
            stdout="",
            stderr=(
                f"Slurm submission outcome unknown ({why}). It may have been submitted as "
                f"job name '{op_id}'. Not resubmitted -- check with "
                f"`squeue --name {op_id}` / `sacct --name {op_id}` first."
            ),
            exit_code=124,
            timed_out=True,
        )

    def _recover(self, request: ExecutionRequest, digest: str) -> ShellResult | None:
        """Resolve an earlier, unresolved submission of the same request, if any."""
        log = self.intent_log(request)
        for rec in log.unresolved():
            if rec.get("kind") != "slurm_sbatch" or rec.get("args_digest") != digest:
                continue
            op_id = str(rec["op_id"])
            job_id, determined = self.find_job(op_id)
            if job_id is not None:
                log.outcome(op_id, "succeeded", job_id=job_id, via="squeue/sacct")
                note = f"Recovered earlier submission {op_id} as job {job_id}; not resubmitted."
                return self._submitted(request, job_id, note)
            if not determined:
                return self._unknown(request, op_id, "an earlier submission is unresolved")
            log.outcome(op_id, "failed", reason="not found by squeue/sacct")
        return None

    def run(self, request: ExecutionRequest) -> ShellResult:
        unavailable = self._preflight(request)
        if unavailable is not None:
            return unavailable
        digest = args_digest(
            {"host": self.target(), "workdir": self.remote_workdir(request), "cmd": request.command}
        )
        recovered = self._recover(request, digest)
        if recovered is not None:
            return recovered
        # The op id is the job name, so the cluster can be asked about this exact
        # submission later -- the only safe answer to "did it go through?".
        op_id = new_operation_id("slurm")
        script = Path(request.workdir) / self._SCRIPT_NAME
        script.write_text(self.build_sbatch_script(request, job_name=op_id), encoding="utf-8")
        staged = self._runner(self.stage_argv(request), timeout=request.limits.timeout)
        if staged.exit_code != 0:
            return staged
        log = self.intent_log(request)
        log.intent(op_id, "slurm_sbatch", target=self.target(), digest=digest)
        # The submission returns a job id (a recoverable state the research loop
        # can checkpoint around and resume — M15/M53); polling/fetch is the
        # caller's responsibility once the job completes.
        result = self._runner(
            self.build_submit_argv(request),
            timeout=request.limits.timeout,
            label=f"sbatch {request.command}",
        )
        if self._unknown_transport(result):
            job_id, determined = self.find_job(op_id)
            if job_id is not None:
                log.outcome(op_id, "succeeded", job_id=job_id, via="squeue/sacct")
                return self._submitted(
                    request, job_id, f"sbatch reply lost; found job {job_id} by name {op_id}."
                )
            log.outcome(op_id, "unknown", reason="no sbatch reply", determined=determined)
            return self._unknown(request, op_id, "no reply from sbatch")
        if result.exit_code == 0:
            log.outcome(op_id, "succeeded", job_id=result.stdout.strip().split(";")[0])
        else:
            log.outcome(op_id, "failed", exit_code=result.exit_code)
        return result
