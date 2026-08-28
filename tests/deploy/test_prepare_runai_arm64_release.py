# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "prepare_runai_arm64_release.py"


@pytest.fixture
def source_helm_dir(tmp_path: Path) -> tuple[Path, dict]:
    source = tmp_path / "helm"
    parent = source / "deployment-k8s"
    child = source / "helm-charts-k8s" / "aiq"
    parent.mkdir(parents=True)
    child.mkdir(parents=True)

    (parent / "Chart.yaml").write_text(
        """apiVersion: v2
name: aiq2-web
version: 2.2.0
dependencies:
  - name: aiq
    version: 0.0.5
    repository: file://../helm-charts-k8s/aiq
""",
        encoding="utf-8",
    )
    (child / "Chart.yaml").write_text(
        "apiVersion: v2\nname: aiq\nversion: 0.0.5\n",
        encoding="utf-8",
    )
    original_values = {
        "aiq": {
            "sharedSecrets": {"enabled": True, "targetSecretName": ""},
            "apps": {
                "backend": {
                    "image": {
                        "repository": "nvcr.io/nvidia/blueprint/aiq-agent",
                        "tag": "2.2.0",
                        "pullPolicy": "IfNotPresent",
                    },
                    "ingress": {"enabled": False},
                },
                "frontend": {
                    "image": {
                        "repository": "nvcr.io/nvidia/blueprint/aiq-frontend",
                        "tag": "2.2.0",
                        "pullPolicy": "IfNotPresent",
                    },
                    "ingress": {"enabled": True},
                },
                "postgres": {"enabled": True},
            },
            "unchanged": {"sentinel": ["keep", "me"]},
        }
    }
    (parent / "values.yaml").write_text(yaml.safe_dump(original_values), encoding="utf-8")
    return source, original_values


def run_helper(source: Path, output: Path, *, tag: str = "runai-arm64-7-1") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-helm-dir",
            str(source),
            "--output-dir",
            str(output),
            "--backend-repository",
            "ghcr.io/brent-stone/aiq-agent",
            "--frontend-repository",
            "ghcr.io/brent-stone/aiq-frontend",
            "--tag",
            tag,
        ],
        capture_output=True,
        check=False,
        text=True,
    )


def test_stages_local_chart_dependency_and_changes_only_application_images(
    source_helm_dir: tuple[Path, dict], tmp_path: Path
):
    source, original_values = source_helm_dir
    output = tmp_path / "release"

    result = run_helper(source, output)

    assert result.returncode == 0, result.stderr
    assert (output / "deployment-k8s" / "Chart.yaml").is_file()
    assert (output / "helm-charts-k8s" / "aiq" / "Chart.yaml").is_file()

    actual = yaml.safe_load((output / "deployment-k8s" / "values.yaml").read_text(encoding="utf-8"))
    expected = copy.deepcopy(original_values)
    expected["aiq"]["apps"]["backend"]["image"].update(
        repository="ghcr.io/brent-stone/aiq-agent", tag="runai-arm64-7-1"
    )
    expected["aiq"]["apps"]["frontend"]["image"].update(
        repository="ghcr.io/brent-stone/aiq-frontend", tag="runai-arm64-7-1"
    )
    assert actual == expected


def test_generates_known_good_runai_overrides(source_helm_dir: tuple[Path, dict], tmp_path: Path):
    source, _ = source_helm_dir
    output = tmp_path / "release"

    result = run_helper(source, output)

    assert result.returncode == 0, result.stderr
    overrides = yaml.safe_load((output / "runai-ai-applications-values.yaml").read_text(encoding="utf-8"))
    aiq = overrides["aiq"]
    assert aiq["sharedSecrets"] == {
        "enabled": True,
        "autoMount": True,
        "targetSecretName": "genericsecret-aiq-credentials",
    }
    assert aiq["apps"]["backend"]["ingress"] == {"enabled": False}
    assert aiq["apps"]["backend"]["env"] == {
        "NAT_JOB_STORE_POOL_PRE_PING": "true",
        "NAT_JOB_STORE_POOL_RECYCLE": "1800",
        "NAT_JOB_STORE_SUBMIT_TIMEOUT": "60",
    }
    assert aiq["apps"]["frontend"]["ingress"] == {"enabled": False}
    assert aiq["apps"]["postgres"]["volumeMounts"] == [
        {"name": "postgres-data", "mountPath": "/var/lib/postgresql/data"}
    ]
    assert "imagePullSecrets" not in aiq


@pytest.mark.parametrize("tag", ["latest", "", "   "])
def test_rejects_mutable_or_empty_tag(source_helm_dir: tuple[Path, dict], tmp_path: Path, tag: str):
    source, _ = source_helm_dir

    result = run_helper(source, tmp_path / "release", tag=tag)

    assert result.returncode != 0
    assert "tag" in result.stderr.lower()
