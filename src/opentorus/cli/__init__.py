"""OpenTorus command-line interface.

Split from a former monolithic ``cli.py`` into per-command-group modules. Importing
this package executes each submodule, registering its sub-app and commands on the
shared root :data:`app`.
"""

# Submodule imports run for their registration side effects (sub-apps + commands).
from opentorus.cli import (  # noqa: F401
    checkpoint,
    claim,
    completion,
    config,
    data,
    env,
    eval_,
    evidence,
    exp,
    gov,
    graph,
    index,
    journal,
    kb,
    lit,
    memory,
    pack,
    paper,
    patch,
    problem,
    proof,
    replay,
    repo,
    review,
    root,
    task,
)
from opentorus.cli._base import BANNER, SLOGAN, app

__all__ = ["app", "BANNER", "SLOGAN"]
