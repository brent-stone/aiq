# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import ast
from pathlib import Path

import pytest

from scripts.apply_nat_hotfixes import apply_hotfix
from scripts.apply_nat_hotfixes import patch_job_store_source

NAT_1_8_JOB_STORE = '''import os
import typing


class JobInfo:
    def __repr__(self):
        return "JobInfo"


class JobStore(DaskClientMixin):
    async def submit_job(self):
        future_var.set(future, timeout="5 s")


def get_db_engine(db_url=None, echo=False, use_async=True):
    if use_async:
        create_engine_fn = async_engine_factory
    else:
        create_engine_fn = sync_engine_factory

    return create_engine_fn(db_url, echo=echo)
'''


def _load_helpers(source: str) -> dict[str, object]:
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign))
        or isinstance(node, ast.FunctionDef)
        and node.name in {"_submit_timeout_seconds", "_apply_pool_env_defaults"}
    ]
    namespace: dict[str, object] = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<hotfix>", "exec"), namespace)
    return namespace


def test_backports_nat_job_store_timeout_and_pool_configuration(monkeypatch: pytest.MonkeyPatch):
    patched = patch_job_store_source(NAT_1_8_JOB_STORE)
    compile(patched, "<patched-job-store>", "exec")
    helpers = _load_helpers(patched)

    timeout = helpers["_submit_timeout_seconds"]
    pool_defaults = helpers["_apply_pool_env_defaults"]

    monkeypatch.delenv("NAT_JOB_STORE_SUBMIT_TIMEOUT", raising=False)
    assert timeout() == 30
    monkeypatch.setenv("NAT_JOB_STORE_SUBMIT_TIMEOUT", "60")
    assert timeout() == 60

    monkeypatch.setenv("NAT_JOB_STORE_POOL_PRE_PING", "true")
    monkeypatch.setenv("NAT_JOB_STORE_POOL_RECYCLE", "1800")
    assert pool_defaults({}) == {"pool_pre_ping": True, "pool_recycle": 1800}

    assert 'future_var.set(future, timeout=f"{_submit_timeout_seconds()} s")' in patched
    assert "return create_engine_fn(db_url, echo=echo, **engine_kwargs)" in patched


@pytest.mark.parametrize("value", ["0", "-1", "abc", "5 s"])
def test_submit_timeout_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, value: str):
    timeout = _load_helpers(patch_job_store_source(NAT_1_8_JOB_STORE))["_submit_timeout_seconds"]
    monkeypatch.setenv("NAT_JOB_STORE_SUBMIT_TIMEOUT", value)

    with pytest.raises(ValueError, match="NAT_JOB_STORE_SUBMIT_TIMEOUT"):
        timeout()


def test_hotfix_refuses_unexpected_nat_version(tmp_path: Path):
    job_store = tmp_path / "job_store.py"
    job_store.write_text(NAT_1_8_JOB_STORE, encoding="utf-8")

    with pytest.raises(ValueError, match="expected nvidia-nat-core 1.8.0"):
        apply_hotfix(job_store, installed_version="1.9.0")

    assert job_store.read_text(encoding="utf-8") == NAT_1_8_JOB_STORE


def test_hotfix_is_idempotent_for_nat_1_8(tmp_path: Path):
    job_store = tmp_path / "job_store.py"
    job_store.write_text(NAT_1_8_JOB_STORE, encoding="utf-8")

    assert apply_hotfix(job_store, installed_version="1.8.0") is True
    first = job_store.read_text(encoding="utf-8")
    assert apply_hotfix(job_store, installed_version="1.8.0") is False
    assert job_store.read_text(encoding="utf-8") == first
