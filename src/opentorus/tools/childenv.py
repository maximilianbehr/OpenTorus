"""The environment a child process is allowed to see.

A subprocess inherits ``os.environ`` by default, and in OpenTorus that environment
holds the provider API keys the dotenv loader put there. A command the policy
allows (``cat /proc/self/environ``, ``env``, a script that prints ``os.environ``)
then hands those keys to the model -- the policy checks the *command string*, not
what the process can read once it runs.

Two levels, both of which always drop credentials:

* :func:`scrubbed_env` -- the parent environment minus every credential-looking
  name. Used for OpenTorus' own helper processes (git, container CLIs, verifiers,
  LaTeX) that may need ``DOCKER_HOST``, ``XDG_RUNTIME_DIR``, ``ELAN_HOME`` and the like.
* :func:`clean_env` -- an allowlist only (``PATH``, ``HOME``, locale, temp dirs,
  thread-count knobs, plus ``execution.env_allowlist``). Used for model-chosen
  commands (``run_shell``) and local experiment runs.

Credential names are stripped even when an allowlist pattern or an explicit
``env`` mapping names them: an allowlist decides what is *useful*, never what is
safe.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Mapping

# Environment variables whose *value* must never be forwarded. Names only -- the
# values are read from the environment at use time and never stored.
CREDENTIAL_ENV_NAMES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "MISTRAL_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
)

# Name components that mark a credential (``OPENTORUS_KEY``, ``AWS_ACCESS_KEY_ID``,
# ``DB_PASS``, ``NPM_TOKEN``). Matched per ``_``-separated component so ``MONKEY``
# or ``KEYBOARD_LAYOUT`` are not caught, plus substrings that are never innocent.
_CREDENTIAL_PARTS = frozenset(
    {
        "KEY",
        "KEYS",
        "APIKEY",
        "TOKEN",
        "TOKENS",
        "SECRET",
        "SECRETS",
        "PASSWORD",
        "PASSWD",
        "PASS",
        "PASSPHRASE",
        "PAT",
        "CREDENTIAL",
        "CREDENTIALS",
        "COOKIE",
    }
)
_CREDENTIAL_SUBSTRINGS = ("PASSWORD", "SECRET", "TOKEN", "APIKEY", "API_KEY", "PRIVATE_KEY")

# What a model-chosen command gets to see. Glob patterns, matched case-sensitively
# (environment names are case-sensitive on POSIX).
BASE_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LANGUAGE",
    "LC_*",
    "TERM",
    "TZ",
    "TMPDIR",
    "TMP",
    "TEMP",
    "PYTHONPATH",
    "PYTHONHASHSEED",
    "PYTHONUNBUFFERED",
    "PYTHONIOENCODING",
    "PYTHONDONTWRITEBYTECODE",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "LD_LIBRARY_PATH",
    "OMP_*",
    "MKL_*",
    "OPENBLAS_*",
    "NUMEXPR_*",
    "VECLIB_MAXIMUM_THREADS",
    "CUDA_VISIBLE_DEVICES",
    # Windows needs these for CreateProcess / the CRT to work at all.
    "SYSTEMROOT",
    "SystemRoot",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
)


def is_credential_name(name: str) -> bool:
    """True when an environment variable name looks like it carries a credential."""
    upper = name.upper()
    if upper in CREDENTIAL_ENV_NAMES:
        return True
    if any(sub in upper for sub in _CREDENTIAL_SUBSTRINGS):
        return True
    return any(part in _CREDENTIAL_PARTS for part in upper.split("_"))


def _strip(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if not is_credential_name(k)}


def scrubbed_env(
    extra: Mapping[str, str] | None = None, *, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The parent environment (plus ``extra``) with every credential name removed."""
    base = dict(os.environ if environ is None else environ)
    if extra:
        base.update(extra)
    return _strip(base)


def clean_env(
    extra: Mapping[str, str] | None = None,
    *,
    allowlist: Iterable[str] = (),
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """An allowlisted environment (plus ``extra``), credentials always removed."""
    source = os.environ if environ is None else environ
    patterns = (*BASE_ENV_ALLOWLIST, *allowlist)
    env = {k: v for k, v in source.items() if any(fnmatch.fnmatchcase(k, pat) for pat in patterns)}
    if extra:
        env.update(extra)
    return _strip(env)
