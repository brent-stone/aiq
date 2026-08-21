# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import copy
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "publish-runai-arm64.yml"


class WorkflowLoader(yaml.SafeLoader):
    """Load GitHub workflow keys without YAML 1.1 coercing `on` to True."""


WorkflowLoader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for key, resolvers in list(WorkflowLoader.yaml_implicit_resolvers.items()):
    WorkflowLoader.yaml_implicit_resolvers[key] = [
        resolver for resolver in resolvers if resolver[0] != "tag:yaml.org,2002:bool"
    ]


def load_workflow() -> dict[str, Any]:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=WorkflowLoader)


def step_using(job: dict[str, Any], action: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step.get("uses") == action)


def combined_run(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_workflow_builds_both_images_natively_with_immutable_tags():
    workflow = load_workflow()

    assert "workflow_dispatch" in workflow["on"]
    assert workflow["on"]["push"]["branches"] == ["codex/runai-arm64-release"]
    assert workflow["permissions"] == {"contents": "write", "packages": "write"}

    build = workflow["jobs"]["build-images"]
    assert build["runs-on"] == "ubuntu-24.04-arm"
    assert build["needs"] == "prepare"
    assert build["strategy"]["matrix"]["include"] == [
        {
            "image": "aiq-agent",
            "context": ".",
            "dockerfile": "deploy/Dockerfile",
            "target": "release",
        },
        {
            "image": "aiq-frontend",
            "context": "frontends/ui",
            "dockerfile": "frontends/ui/deploy/Dockerfile",
            "target": "",
        },
    ]
    build_step = step_using(build, "docker/build-push-action@v6")
    assert build_step["with"]["platforms"] == "linux/arm64"
    assert build_step["with"]["push"] == "true"
    assert build_step["with"]["tags"] == (
        "${{ needs.prepare.outputs.registry }}/${{ matrix.image }}:${{ needs.prepare.outputs.release_tag }}"
    )
    assert build_step["with"]["provenance"] == "mode=max"
    assert build_step["with"]["sbom"] == "true"
    assert ":latest" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_smoke_tests_arm64_runtime_before_chart_packaging():
    workflow = load_workflow()
    jobs = workflow["jobs"]

    verify = jobs["verify-images"]
    assert verify["runs-on"] == "ubuntu-24.04-arm"
    assert set(verify["needs"]) == {"prepare", "build-images"}
    commands = combined_run(verify)
    assert "docker buildx imagetools inspect" in commands
    assert "--entrypoint /app/.venv/bin/python" in commands
    assert "import aiq_api" in commands
    assert "platform.machine()" in commands
    assert "--entrypoint node" in commands
    assert "process.arch !== 'arm64'" in commands

    package = jobs["package-chart"]
    assert set(package["needs"]) == {"prepare", "verify-images"}
    assert package["runs-on"] == "ubuntu-latest"
    package_commands = combined_run(package)
    assert "prepare_runai_arm64_release.py" in package_commands
    assert "helm dependency build" in package_commands
    assert "helm lint" in package_commands
    assert "helm template" in package_commands
    assert "genericsecret-aiq-credentials" in package_commands
    assert "/var/lib/postgresql/data" in package_commands
    assert "sha256sum" in package_commands


def test_release_is_gated_on_chart_verification_and_publishes_runai_assets():
    workflow = load_workflow()
    release = workflow["jobs"]["release"]

    assert set(release["needs"]) == {"prepare", "package-chart"}
    commands = combined_run(release)
    assert "gh release create" in commands
    assert "aiq2-web-2.2.0.tgz" in commands
    assert "runai-ai-applications-values.yaml" in commands
    assert "rendered.yaml" in commands
    assert "SHA256SUMS" in commands
    assert '--target "$GITHUB_SHA"' in commands
