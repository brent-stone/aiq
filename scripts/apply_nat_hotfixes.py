#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Backport selected merged NeMo Agent Toolkit fixes into the pinned NAT 1.8.0 runtime."""

import importlib.metadata
import re
import sysconfig
from pathlib import Path

EXPECTED_NAT_CORE_VERSION = "1.8.0"
JOB_STORE_RELATIVE_PATH = Path("nat/front_ends/fastapi/async_jobs/job_store.py")

TIMEOUT_BACKPORT = '''DEFAULT_SUBMIT_TIMEOUT_SECONDS = 30


def _submit_timeout_seconds() -> int:
    """Resolve the Dask Variable.set acknowledgement timeout, in seconds."""
    raw = os.environ.get("NAT_JOB_STORE_SUBMIT_TIMEOUT")
    if raw is None:
        return DEFAULT_SUBMIT_TIMEOUT_SECONDS
    try:
        seconds = int(raw)
    except ValueError as error:
        raise ValueError(
            f"NAT_JOB_STORE_SUBMIT_TIMEOUT must be an integer number of seconds, got {raw!r}"
        ) from error
    if seconds <= 0:
        raise ValueError(
            f"NAT_JOB_STORE_SUBMIT_TIMEOUT must be a positive integer number of seconds, got {raw!r}"
        )
    return seconds


'''

POOL_BACKPORT = '''_POOL_PRE_PING_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_POOL_PRE_PING_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _apply_pool_env_defaults(engine_kwargs: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Fill in JobStore connection-pool settings from the environment."""
    resolved = dict(engine_kwargs)

    if "pool_pre_ping" not in resolved:
        pre_ping = os.environ.get("NAT_JOB_STORE_POOL_PRE_PING")
        if pre_ping is not None:
            normalized = pre_ping.strip().lower()
            if normalized in _POOL_PRE_PING_TRUE_VALUES:
                resolved["pool_pre_ping"] = True
            elif normalized in _POOL_PRE_PING_FALSE_VALUES:
                resolved["pool_pre_ping"] = False
            else:
                raise ValueError(
                    "NAT_JOB_STORE_POOL_PRE_PING must be one of "
                    f"{sorted(_POOL_PRE_PING_TRUE_VALUES | _POOL_PRE_PING_FALSE_VALUES)}, got {pre_ping!r}"
                )

    if "pool_recycle" not in resolved:
        recycle = os.environ.get("NAT_JOB_STORE_POOL_RECYCLE")
        if recycle is not None:
            try:
                resolved["pool_recycle"] = int(recycle)
            except ValueError as error:
                raise ValueError(
                    f"NAT_JOB_STORE_POOL_RECYCLE must be an integer number of seconds, got {recycle!r}"
                ) from error

    return resolved


'''


def patch_job_store_source(source: str) -> str:
    """Apply merged NAT PRs #2150 and #2159 to the 1.8.0 job-store source."""
    already_patched = all(
        marker in source
        for marker in (
            "DEFAULT_SUBMIT_TIMEOUT_SECONDS = 30",
            "def _apply_pool_env_defaults(",
            'timeout=f"{_submit_timeout_seconds()} s"',
            "echo=echo, **engine_kwargs",
        )
    )
    if already_patched:
        return source

    required_markers = (
        "class JobStore",
        'future_var.set(future, timeout="5 s")',
        "def get_db_engine(",
        "return create_engine_fn(db_url, echo=echo)",
    )
    missing = [marker for marker in required_markers if marker not in source]
    if missing:
        raise ValueError(f"NAT 1.8.0 job_store.py does not match the expected source: missing {missing!r}")

    job_store_class = re.search(r"^class JobStore(?:\([^\n]*\))?:", source, flags=re.MULTILINE)
    if job_store_class is None:
        raise ValueError("could not identify the NAT 1.8.0 JobStore class")
    source = source[: job_store_class.start()] + TIMEOUT_BACKPORT + source[job_store_class.start() :]
    source = source.replace(
        'future_var.set(future, timeout="5 s")',
        'future_var.set(future, timeout=f"{_submit_timeout_seconds()} s")',
        1,
    )
    source = source.replace("def get_db_engine(", POOL_BACKPORT + "def get_db_engine(", 1)

    signature = re.search(r"^def get_db_engine\([^\n]+$", source, flags=re.MULTILINE)
    if signature is None:
        raise ValueError("could not identify the NAT 1.8.0 get_db_engine signature")
    signature_text = signature.group(0)
    closing_parenthesis = signature_text.rfind(")")
    patched_signature = (
        signature_text[:closing_parenthesis]
        + ", **engine_kwargs: typing.Any"
        + signature_text[closing_parenthesis:]
    )
    source = source[: signature.start()] + patched_signature + source[signature.end() :]
    source = source.replace(
        "return create_engine_fn(db_url, echo=echo)",
        "engine_kwargs = _apply_pool_env_defaults(engine_kwargs)\n\n"
        "    return create_engine_fn(db_url, echo=echo, **engine_kwargs)",
        1,
    )
    compile(source, "job_store.py", "exec")
    return source


def apply_hotfix(job_store_path: Path, installed_version: str) -> bool:
    """Patch one installed NAT job-store module and report whether it changed."""
    if installed_version != EXPECTED_NAT_CORE_VERSION:
        raise ValueError(
            f"expected nvidia-nat-core {EXPECTED_NAT_CORE_VERSION}, found {installed_version}; "
            "remove the backport when AI-Q upgrades to a NAT release containing PRs #2150 and #2159"
        )

    original = job_store_path.read_text(encoding="utf-8")
    patched = patch_job_store_source(original)
    if patched == original:
        return False
    job_store_path.write_text(patched, encoding="utf-8")
    return True


def main() -> None:
    installed_version = importlib.metadata.version("nvidia-nat-core")
    purelib = Path(sysconfig.get_paths()["purelib"])
    job_store_path = purelib / JOB_STORE_RELATIVE_PATH
    changed = apply_hotfix(job_store_path, installed_version)
    action = "applied" if changed else "already present"
    print(f"NAT 1.8 compatibility backports {action}: PRs #2150 and #2159")


if __name__ == "__main__":
    main()
