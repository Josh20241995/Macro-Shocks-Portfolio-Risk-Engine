#!/usr/bin/env bash
# scripts/deploy_production.sh
# Zero-downtime production deployment for the Macro Shock Risk Engine.
#
# Prerequisites:
#   - Docker Swarm or Kubernetes (adapt service update commands as needed)
#   - Image already built and tagged: msre-pipeline:VERSION
#   - Environment variables set in deployment secrets
#
# Usage:
#   bash scripts/deploy_production.sh --version 1.0.0
#   bash scripts/deploy_production.sh --version 1.0.0 --dry-run

set -euo pipefail

# ─── Defaults ────────────────────────────────────────────────
VERSION=""
DRY_RUN=false
ENV="production"
REGISTRY="${DOCKER_REGISTRY:-docker.io/yourorg}"
DEPLOY_TIMEOUT=120     # seconds to wait for service to stabilise
SMOKE_TEST_RETRIES=5

# ─── Colours ─────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'; BOLD='\033[1m'
info()  { echo -e "${GREEN}[INFO]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()   { error "$*"; exit 1; }

# ─── Parse arguments ─────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)  VERSION="$2";  shift 2 ;;
        --dry-run)  DRY_RUN=true;  shift   ;;
        --env)      ENV="$2";      shift 2 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ -z "$VERSION" ]] && die "--version is required (e.g. --version 1.0.0)"

IMAGE="${REGISTRY}/msre-pipeline:${VERSION}"
API_URL="${MSRE_API_URL:-http://msre-api.internal:8000}"

# ─── Dry-run wrapper ──────────────────────────────────────────
run() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "${YELLOW}[DRY-RUN]${RESET} $*"
    else
        "$@"
    fi
}

# ─── Main ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  MSRE Production Deployment${RESET}"
echo -e "${BOLD}  Version:  ${VERSION}${RESET}"
echo -e "${BOLD}  Image:    ${IMAGE}${RESET}"
echo -e "${BOLD}  Env:      ${ENV}${RESET}"
[[ "$DRY_RUN" == "true" ]] && echo -e "${YELLOW}  *** DRY RUN — NO CHANGES APPLIED ***${RESET}"
echo -e "${BOLD}════════════════════════════════════════════════${RESET}"
echo ""

# ── Step 1: Pre-flight checks ─────────────────────────────────
info "Step 1/8: Pre-flight checks"

# Verify image exists
docker image inspect "${IMAGE}" > /dev/null 2>&1 \
    || die "Image ${IMAGE} not found locally. Build or pull it first."
info "Image exists: ${IMAGE}"

# Run health check on current production (pre-deploy baseline)
info "Current production health:"
python3 scripts/health_check.py --env "${ENV}" || warn "Pre-deploy health check failed (continuing)"

# ── Step 2: Git tag ───────────────────────────────────────────
info "Step 2/8: Tagging release in git"
DEPLOY_TAG="deploy/${ENV}/${VERSION}/$(date -u +%Y%m%d-%H%M%S)"
run git tag "${DEPLOY_TAG}" -m "Deploy ${VERSION} to ${ENV}"
run git push origin "${DEPLOY_TAG}" 2>/dev/null || warn "Could not push tag (continuing)"

# ── Step 3: Database migrations ───────────────────────────────
info "Step 3/8: Applying database migrations"
run python3 scripts/migrate_db.py --env "${ENV}" --apply --version "${VERSION}" \
    || die "Database migration failed — aborting deployment"
info "Migrations applied successfully"

# ── Step 4: Deploy pipeline workers ───────────────────────────
info "Step 4/8: Deploying pipeline workers (zero-downtime rolling update)"
run docker service update \
    --image "${IMAGE}" \
    --update-parallelism 1 \
    --update-delay 10s \
    --update-failure-action rollback \
    --rollback-parallelism 1 \
    msre_pipeline \
    || die "Pipeline worker update failed"

# ── Step 5: Deploy API server ──────────────────────────────────
info "Step 5/8: Deploying API server"
run docker service update \
    --image "${IMAGE}" \
    --update-parallelism 1 \
    --update-delay 5s \
    --update-failure-action rollback \
    msre_api \
    || die "API server update failed"

# ── Step 6: Wait for service stabilisation ────────────────────
info "Step 6/8: Waiting for services to stabilise (${DEPLOY_TIMEOUT}s)"
if [[ "$DRY_RUN" == "false" ]]; then
    sleep 15
    ELAPSED=0
    until python3 scripts/health_check.py --env "${ENV}" --component api > /dev/null 2>&1; do
        ELAPSED=$((ELAPSED + 5))
        if [[ $ELAPSED -ge $DEPLOY_TIMEOUT ]]; then
            error "Services did not stabilise within ${DEPLOY_TIMEOUT}s"
            info "Triggering automatic rollback..."
            docker service rollback msre_api    || warn "API rollback failed"
            docker service rollback msre_pipeline || warn "Pipeline rollback failed"
            die "Deployment failed — rolled back to previous version"
        fi
        echo "  Waiting... (${ELAPSED}s elapsed)"
        sleep 5
    done
fi
info "Services healthy"

# ── Step 7: Smoke test ────────────────────────────────────────
info "Step 7/8: Running smoke test"
SMOKE_ATTEMPT=0
SMOKE_OK=false
while [[ $SMOKE_ATTEMPT -lt $SMOKE_TEST_RETRIES ]]; do
    SMOKE_ATTEMPT=$((SMOKE_ATTEMPT + 1))
    if run python3 scripts/smoke_test.py \
        --env "${ENV}" \
        --api-url "${API_URL}" \
        --scenario hawkish_surprise; then
        SMOKE_OK=true
        break
    fi
    warn "Smoke test attempt ${SMOKE_ATTEMPT}/${SMOKE_TEST_RETRIES} failed — retrying in 10s"
    sleep 10
done

if [[ "$SMOKE_OK" == "false" ]]; then
    error "Smoke test failed after ${SMOKE_TEST_RETRIES} attempts"
    info "Triggering rollback..."
    run docker service rollback msre_api
    run docker service rollback msre_pipeline
    die "Deployment smoke test failed — rolled back"
fi

# ── Step 8: Post-deploy tasks ─────────────────────────────────
info "Step 8/8: Post-deploy cleanup"
run python3 scripts/health_check.py --env "${ENV}" || warn "Post-deploy health check degraded"

# Notify
if [[ -n "${SLACK_WEBHOOK_URL:-}" && "$DRY_RUN" == "false" ]]; then
    curl -s -X POST "${SLACK_WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "{\"text\": \"✅ MSRE *${VERSION}* deployed to *${ENV}* successfully.\"}" \
        > /dev/null || warn "Slack notification failed"
fi

echo ""
echo -e "${BOLD}════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  DEPLOYMENT SUCCESSFUL: ${VERSION} → ${ENV}${RESET}"
echo -e "${BOLD}════════════════════════════════════════════════${RESET}"
echo ""
