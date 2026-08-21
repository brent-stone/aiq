# RUN:AI ARM64 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish native Linux ARM64 AI-Q 2.2 backend and frontend images plus a patched, directly installable Helm chart for the NVIDIA DGX GB300 RUN:AI cluster.

**Architecture:** A manually dispatched GitHub Actions workflow runs image work on GitHub's native `ubuntu-24.04-arm` runner. It builds the existing Dockerfiles for `linux/arm64`, pushes immutable run-scoped tags to GHCR, performs architecture smoke tests, stages the parent and child Helm charts, changes only the two application image defaults, verifies the rendered RUN:AI contract, and publishes release assets.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, Python 3/PyYAML, Helm 3, pytest

**Spec:** `docs/superpowers/specs/2026-08-21-runai-arm64-release-design.md`

## Global Constraints

- Work only on `codex/runai-arm64-release`; do not change the NVIDIA contribution branch.
- Build only `linux/arm64` and reuse `deploy/Dockerfile` and `frontends/ui/deploy/Dockerfile`.
- Publish `ghcr.io/brent-stone/aiq-agent:<release-tag>` and `ghcr.io/brent-stone/aiq-frontend:<release-tag>`.
- Define `<release-tag>` once as `runai-arm64-<github.run_number>-<github.run_attempt>`; never publish `latest`.
- Preserve `sharedSecrets.targetSecretName` propagation and PostgreSQL mount `/var/lib/postgresql/data`.
- Keep global `aiq.imagePullSecrets` unset; GHCR images are expected to be public.
- Sign off every commit with `Signed-off-by: Brent Stone <brent.stone@nps.edu>`.
- Create no GitHub release unless image builds, runtime architecture checks, manifest checks, Helm lint, Helm render, and contract assertions all pass.

---

## Task 1: Add a deterministic ARM64 chart-preparation helper

**Files:**
- Create: `scripts/prepare_runai_arm64_release.py`
- Test: `tests/deploy/test_prepare_runai_arm64_release.py`
- Read only: `deploy/helm/deployment-k8s/`
- Read only: `deploy/helm/helm-charts-k8s/aiq/`

- [ ] **Step 1: Write failing tests for the helper**

Use temporary fixture directories and assert that the helper:

1. Copies both `deployment-k8s` and `helm-charts-k8s/aiq` while preserving the parent's `file://../helm-charts-k8s/aiq` dependency.
2. Changes only the backend/frontend image repository and tag fields in staged `values.yaml`.
3. Generates `runai-ai-applications-values.yaml` with `genericsecret-aiq-credentials`, `/var/lib/postgresql/data`, ingress disabled, and no global `aiq.imagePullSecrets` list.
4. Rejects empty image fields and the mutable tag `latest`.

- [ ] **Step 2: Confirm the focused test fails**

```bash
python -m pytest -q tests/deploy/test_prepare_runai_arm64_release.py
```

Expected: FAIL because `scripts.prepare_runai_arm64_release` does not exist.

- [ ] **Step 3: Implement the smallest helper**

Implement a CLI accepting:

```text
--source-helm-dir deploy/helm
--output-dir <staging-directory>
--backend-repository ghcr.io/brent-stone/aiq-agent
--frontend-repository ghcr.io/brent-stone/aiq-frontend
--tag runai-arm64-<run-number>-<run-attempt>
```

Use `pathlib`, `shutil`, and `yaml.safe_load/safe_dump`. Copy the parent and child sources, update the four image fields in the staged parent chart, and generate the minimal RUN:AI override. Do not mutate source chart files.

- [ ] **Step 4: Confirm the focused test passes**

```bash
python -m pytest -q tests/deploy/test_prepare_runai_arm64_release.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/prepare_runai_arm64_release.py tests/deploy/test_prepare_runai_arm64_release.py
git commit -s -m "build: prepare RUN:AI ARM64 chart release"
```

---

## Task 2: Add the native ARM64 publication workflow

**Files:**
- Create: `.github/workflows/publish-runai-arm64.yml`
- Create: `tests/deploy/test_publish_runai_arm64_workflow.py`
- Use unchanged: `deploy/Dockerfile`
- Use unchanged: `frontends/ui/deploy/Dockerfile`

- [ ] **Step 1: Write failing workflow-contract tests**

Parse the workflow YAML and assert:

- The trigger is manual `workflow_dispatch`.
- Permissions contain `contents: write` and `packages: write`.
- Image build and runtime smoke jobs use `ubuntu-24.04-arm`.
- Backend uses context `.`, file `deploy/Dockerfile`, target `release`, and `platforms: linux/arm64`.
- Frontend uses context `frontends/ui`, file `frontends/ui/deploy/Dockerfile`, and `platforms: linux/arm64`.
- Both images use `ghcr.io/brent-stone`, share the immutable run tag, and never publish `latest`.
- Chart publication depends on image verification; release creation depends on chart verification.

- [ ] **Step 2: Confirm the workflow test fails**

```bash
python -m pytest -q tests/deploy/test_publish_runai_arm64_workflow.py
```

Expected: FAIL because the workflow does not exist.

- [ ] **Step 3: Implement metadata and ARM64 build jobs**

Create `.github/workflows/publish-runai-arm64.yml` with:

1. A `prepare` job emitting `release_tag=runai-arm64-${{ github.run_number }}-${{ github.run_attempt }}` and both fully qualified image references.
2. A two-entry matrix on `ubuntu-24.04-arm`.
3. `docker/login-action@v3` using `github.actor` and `secrets.GITHUB_TOKEN`.
4. `docker/setup-buildx-action@v3`.
5. `docker/build-push-action@v6` with `push: true`, `platforms: linux/arm64`, GitHub Actions cache, and immutable tags only.

Matrix values:

```yaml
- context: .
  file: deploy/Dockerfile
  target: release
  image: ghcr.io/brent-stone/aiq-agent
- context: frontends/ui
  file: frontends/ui/deploy/Dockerfile
  image: ghcr.io/brent-stone/aiq-frontend
```

- [ ] **Step 4: Add authoritative image verification**

After both pushes, run on `ubuntu-24.04-arm`:

```bash
docker buildx imagetools inspect "$BACKEND_IMAGE" | grep -F "linux/arm64"
docker buildx imagetools inspect "$FRONTEND_IMAGE" | grep -F "linux/arm64"

docker run --rm --entrypoint /app/.venv/bin/python "$BACKEND_IMAGE" \
  -c "import platform; import aiq_api; assert platform.machine() in ('aarch64', 'arm64'); print(platform.machine())"

docker run --rm --entrypoint node "$FRONTEND_IMAGE" \
  -e "if (process.arch !== 'arm64') process.exit(1); console.log(process.arch)"
```

Any failed pull, import, platform assertion, or exit code stops publication.

- [ ] **Step 5: Add chart packaging and rendered-contract verification**

On `ubuntu-latest`, after image verification:

1. Install Helm 3 and PyYAML.
2. Run `scripts/prepare_runai_arm64_release.py` into `$RUNNER_TEMP/aiq-arm64-release`.
3. Run `helm dependency build` on the staged `deployment-k8s` chart.
4. Run `helm lint` and `helm template` with generated RUN:AI values.
5. Assert the render contains both immutable images, Deployments `aiq-backend`, `aiq-frontend`, `aiq-postgres`, secret `genericsecret-aiq-credentials`, init container `db-init`, and mount `/var/lib/postgresql/data`.
6. Package the staged parent with `helm package`.
7. Generate `SHA256SUMS` for chart and values.
8. Upload chart, values, rendered manifest, and checksums as a workflow artifact.

- [ ] **Step 6: Add gated GitHub release creation**

Create release/tag `runai-arm64-<run-number>-<run-attempt>` at `${{ github.sha }}` only after the chart job passes. Attach:

- `aiq2-web-2.2.0.tgz`
- `runai-ai-applications-values.yaml`
- `rendered.yaml`
- `SHA256SUMS`

Release notes must list both immutable GHCR image references and state `linux/arm64`.

- [ ] **Step 7: Run focused tests and validate YAML**

```bash
python -m pytest -q \
  tests/deploy/test_prepare_runai_arm64_release.py \
  tests/deploy/test_publish_runai_arm64_workflow.py
python - <<'PY'
from pathlib import Path
import yaml
path = Path('.github/workflows/publish-runai-arm64.yml')
assert isinstance(yaml.safe_load(path.read_text()), dict)
print(path)
PY
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add .github/workflows/publish-runai-arm64.yml tests/deploy/test_publish_runai_arm64_workflow.py
git commit -s -m "ci: publish native ARM64 RUN:AI artifacts"
```

---

## Task 3: Perform lean pre-publication verification

**Files:**
- Verify: `scripts/prepare_runai_arm64_release.py`
- Verify: `.github/workflows/publish-runai-arm64.yml`
- Verify: both Helm chart source directories

- [ ] **Step 1: Run both focused tests from a clean checkout**

```bash
python -m pytest -q \
  tests/deploy/test_prepare_runai_arm64_release.py \
  tests/deploy/test_publish_runai_arm64_workflow.py
```

- [ ] **Step 2: Exercise chart generation with an immutable test tag**

```bash
release_dir="$(mktemp -d)"
python scripts/prepare_runai_arm64_release.py \
  --source-helm-dir deploy/helm \
  --output-dir "$release_dir" \
  --backend-repository ghcr.io/brent-stone/aiq-agent \
  --frontend-repository ghcr.io/brent-stone/aiq-frontend \
  --tag runai-arm64-test-1
helm dependency build "$release_dir/deployment-k8s"
helm lint "$release_dir/deployment-k8s" \
  -f "$release_dir/runai-ai-applications-values.yaml"
helm template aiq "$release_dir/deployment-k8s" \
  -f "$release_dir/runai-ai-applications-values.yaml"
```

Expected: dependency build, lint, and render all succeed.

- [ ] **Step 3: Inspect final history and diff**

```bash
git status --short
git log --format=fuller -5
git diff --check origin/codex/runai-arm64-release...HEAD
```

Expected: clean worktree, no whitespace errors, and all new commits have the DCO sign-off.

---

## Task 4: Publish and verify the release

**Files:**
- Workflow: `.github/workflows/publish-runai-arm64.yml`
- Release assets: generated by GitHub Actions

- [ ] **Step 1: Push implementation commits**

```bash
git push origin codex/runai-arm64-release
```

- [ ] **Step 2: Dispatch and watch publication**

```bash
gh workflow run publish-runai-arm64.yml \
  --repo brent-stone/aiq \
  --ref codex/runai-arm64-release
gh run watch --repo brent-stone/aiq <run-id> --exit-status
```

Expected: image, smoke-test, chart, and release jobs pass.

- [ ] **Step 3: Verify remote image platforms**

```bash
docker buildx imagetools inspect ghcr.io/brent-stone/aiq-agent:<release-tag>
docker buildx imagetools inspect ghcr.io/brent-stone/aiq-frontend:<release-tag>
```

Expected: `linux/arm64` is present and no chart value references NVIDIA's AMD64-only application images.

- [ ] **Step 4: Verify release assets and checksums**

```bash
gh release view <release-tag> --repo brent-stone/aiq
gh release download <release-tag> --repo brent-stone/aiq
sha256sum --check SHA256SUMS
```

Expected: the chart and values exist and checksums pass.

- [ ] **Step 5: Hand off exact RUN:AI inputs**

Provide the immutable release URL, direct chart asset URL, exact values contents, and both immutable GHCR image references. Do not claim cluster deployment success until the user's manual RUN:AI redeployment reaches Ready and health checks pass.
