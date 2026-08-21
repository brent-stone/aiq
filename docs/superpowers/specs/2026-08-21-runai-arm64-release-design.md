# RUN:AI ARM64 AI-Q 2.2 Publication Design

Date: 2026-08-21

## Objective

Publish native `linux/arm64` AI-Q 2.2 backend and frontend images plus a patched Helm parent chart that can be installed through the NPS RUN:AI AI Applications interface on DGX GB300 Grace/Blackwell compute nodes.

## Scope

The release is ARM64-only and deployment-focused. It reuses the existing AI-Q Dockerfiles and the chart at commit `f7c3b27414bd55b04e3ced2e1f0bee5b9e723d3f`, which already propagates `sharedSecrets.targetSecretName` and packages the full parent chart. It does not add application features, broad test coverage, or an AMD64 build.

## Artifacts

A manually dispatched GitHub Actions workflow publishes:

- `ghcr.io/brent-stone/aiq-agent:<release-tag>`
- `ghcr.io/brent-stone/aiq-frontend:<release-tag>`
- `aiq2-web-2.2.0-<release-tag>.tgz`
- RUN:AI values YAML
- SHA-256 checksums and release notes containing image digests and platforms

The initial tag format is `runai-arm64-<run-number>-<run-attempt>`.

## Build and publication flow

1. A prepare job derives the immutable release tag and chart filename.
2. Backend and frontend matrix jobs run on `ubuntu-24.04-arm`, use Buildx with `platforms: linux/arm64`, and push to GHCR.
3. Each job verifies its image on the native ARM runner:
   - backend: `/app/.venv/bin/python` runs, reports `aarch64`, and imports the API package;
   - frontend: `node` runs and reports `arm64`.
4. The packaging job verifies both remote manifests report `linux/arm64`.
5. The packaging job updates only the packaged parent chart defaults to reference the immutable GHCR repositories and tag.
6. Helm lint and template checks run with the RUN:AI values.
7. A GitHub release is created only after every prior job succeeds.

## Helm deployment contract

The packaged chart must render exactly these deployments:

- `aiq-postgres`
- `aiq-backend`
- `aiq-frontend`

It must also preserve:

- all AI-Q credential references targeting `genericsecret-aiq-credentials`;
- PostgreSQL PVC mount at `/var/lib/postgresql/data`;
- the backend database-init container and ConfigMap;
- disabled frontend Ingress for RUN:AI;
- no global list-valued `aiq.imagePullSecrets` override;
- immutable ARM64 backend and frontend tags.

PostgreSQL continues using its upstream Bitnami image because it has already started successfully on the cluster.

## Failure handling

No chart or GitHub release is published if either image build, native entrypoint check, manifest platform audit, Helm lint, or render assertion fails. Images use immutable run-specific tags; the workflow does not publish or overwrite `latest`.

## Acceptance criteria

Publication is complete when GitHub exposes both ARM64 image tags and a downloadable chart/values pair, with recorded digests and checksums, and local inspection confirms that the chart references those exact tags. Deployment completion remains separate and requires RUN:AI evidence that PostgreSQL, backend, and frontend are Ready and the backend health endpoint responds.
