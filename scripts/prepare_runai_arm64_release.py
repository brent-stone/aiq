#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stage the AI-Q Helm chart with immutable RUN:AI ARM64 images."""

import argparse
import shutil
from pathlib import Path

import yaml

RUNAI_OVERRIDES = {
    "aiq": {
        "sharedSecrets": {
            "enabled": True,
            "autoMount": True,
            "targetSecretName": "genericsecret-aiq-credentials",
        },
        "apps": {
            "backend": {
                "env": {
                    "NAT_JOB_STORE_POOL_PRE_PING": "true",
                    "NAT_JOB_STORE_POOL_RECYCLE": "1800",
                    "NAT_JOB_STORE_SUBMIT_TIMEOUT": "60",
                },
                "ingress": {"enabled": False},
            },
            "frontend": {"ingress": {"enabled": False}},
            "postgres": {
                "persistence": [
                    {
                        "name": "aiq-postgres-data",
                        "accessModes": ["ReadWriteOnce"],
                        "size": "10Gi",
                    }
                ],
                "volumes": [
                    {
                        "name": "postgres-data",
                        "persistentVolumeClaim": {"claimName": "aiq-postgres-data"},
                    }
                ],
                "volumeMounts": [
                    {
                        "name": "postgres-data",
                        "mountPath": "/var/lib/postgresql/data",
                    }
                ],
            },
        },
    }
}


def non_empty(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def prepare_release(
    source_helm_dir: Path,
    output_dir: Path,
    backend_repository: str,
    frontend_repository: str,
    tag: str,
) -> None:
    backend_repository = non_empty(backend_repository, "backend repository")
    frontend_repository = non_empty(frontend_repository, "frontend repository")
    tag = non_empty(tag, "tag")
    if tag.lower() == "latest":
        raise ValueError("tag must be immutable and cannot be 'latest'")

    parent_source = source_helm_dir / "deployment-k8s"
    child_source = source_helm_dir / "helm-charts-k8s" / "aiq"
    if not parent_source.is_dir() or not child_source.is_dir():
        raise ValueError("source Helm directory must contain deployment-k8s and helm-charts-k8s/aiq")

    parent_output = output_dir / "deployment-k8s"
    child_output = output_dir / "helm-charts-k8s" / "aiq"
    shutil.copytree(parent_source, parent_output)
    shutil.copytree(child_source, child_output)

    values_path = parent_output / "values.yaml"
    values = yaml.safe_load(values_path.read_text(encoding="utf-8"))
    apps = values["aiq"]["apps"]
    apps["backend"]["image"].update(repository=backend_repository, tag=tag)
    apps["frontend"]["image"].update(repository=frontend_repository, tag=tag)
    values_path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")

    overrides_path = output_dir / "runai-ai-applications-values.yaml"
    overrides_path.write_text(yaml.safe_dump(RUNAI_OVERRIDES, sort_keys=False), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-helm-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--backend-repository", required=True)
    parser.add_argument("--frontend-repository", required=True)
    parser.add_argument("--tag", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        prepare_release(
            source_helm_dir=args.source_helm_dir,
            output_dir=args.output_dir,
            backend_repository=args.backend_repository,
            frontend_repository=args.frontend_repository,
            tag=args.tag,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
