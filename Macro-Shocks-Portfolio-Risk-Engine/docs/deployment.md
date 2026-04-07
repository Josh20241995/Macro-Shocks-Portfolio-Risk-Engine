# Deployment Guide

## Macro Shock Risk Engine — Production Deployment

---

## Environment Hierarchy

```
research   ← Local development. No live feeds. No OMS. Synthetic data.
staging    ← Full live feed connections. No OMS write access. Alert routing disabled.
production ← All systems live. OMS connected. Full alert routing. On-call active.
```

Never promote directly from `research` to `production`. All changes must pass `staging` validation.

---

## Pre-Deployment Checklist

### Code Quality Gates

- [ ] All unit tests pass (`pytest python/tests/unit/ -v --cov=macro_shock`)
- [ ] Coverage ≥ 80% overall, ≥ 90% for `risk_scoring/`
- [ ] All integration tests pass (`pytest python/tests/integration/ -v -m integration`)
- [ ] C++ tests pass (`cd cpp/build && ctest --output-on-failure`)
- [ ] C# tests pass (`cd csharp && dotnet test`)
- [ ] No `mypy` type errors in `python/src/`
- [ ] `ruff` linting clean
- [ ] `black` formatting clean
- [ ] No hardcoded credentials (grep check in CI)
- [ ] All new model changes reviewed by at least two quant engineers

### Model Validation Gates (Production Only)

- [ ] Backtest walk-forward validation run on full historical corpus
- [ ] Out-of-sample score accuracy ≥ 0.30 correlation with realized severity
- [ ] Precision@CRITICAL ≥ 0.60 (< 40% false alarms when score ≥ 75)
- [ ] Recall@CRITICAL ≥ 0.75 (catch ≥ 75% of true CRITICAL events)
- [ ] Weekend gap estimate error ≤ 3% mean absolute error
- [ ] Champion/challenger comparison documented for any model change
- [ ] Risk officer sign-off on model change

### Infrastructure Gates

- [ ] All data feed connections tested in staging (15-minute smoke test)
- [ ] TimescaleDB migration applied and verified
- [ ] Redis cache populated with at least one valid risk score
- [ ] OMS endpoint health check passes
- [ ] Alert routing tested: Slack ✓, PagerDuty ✓, OMS ✓
- [ ] Dashboard API health endpoint returns 200
- [ ] C# dashboard connected to staging API and displaying data
- [ ] Heartbeat monitor configured and tested
- [ ] Log rotation policy confirmed
- [ ] Backup/restore procedure tested in the last 30 days

### Operational Gates

- [ ] On-call rotation set and tested
- [ ] Runbook reviewed and up to date (`docs/runbook.md`)
- [ ] Escalation path documented
- [ ] Kill switch procedure reviewed with PM team
- [ ] PM and risk officer briefed on deployment and new model version
- [ ] Rollback procedure confirmed (< 5 minutes to previous version)

---

## Deployment Steps

### Step 1: Tag the Release

```bash
git tag v1.0.0-production -m "Production deployment $(date -u +%Y-%m-%d)"
git push origin v1.0.0-production
```

### Step 2: Build Docker Images

```bash
# Python pipeline image
docker build -t msre-pipeline:v1.0.0 -f docker/Dockerfile.pipeline .

# C++ shared library (built into pipeline image)
# C# dashboard
docker build -t msre-dashboard:v1.0.0 -f docker/Dockerfile.dashboard .
```

### Step 3: Deploy Database Migrations

```bash
python scripts/migrate_db.py --env production --apply
# Verify:
python scripts/migrate_db.py --env production --verify
```

### Step 4: Deploy Pipeline Workers

```bash
# Zero-downtime deployment: bring up new, then tear down old
docker service update --image msre-pipeline:v1.0.0 msre_pipeline
# Verify worker is running and heartbeat is active:
python scripts/health_check.py --env production
```

### Step 5: Deploy API Server

```bash
docker service update --image msre-pipeline:v1.0.0 msre_api
# Verify API:
curl https://msre-api.internal/health
```

### Step 6: Deploy Dashboard

```bash
# Push new build to dashboard distribution share
./scripts/deploy_dashboard.sh --version v1.0.0
# Notify analysts to restart the dashboard application
```

### Step 7: Smoke Test in Production

```bash
# Inject a synthetic test event (does NOT produce OMS orders)
python scripts/smoke_test.py --env production --event synthetic_fed_press_conf
# Verify:
# - Risk score computed and stored
# - Alert emitted to Slack test channel
# - Dashboard shows updated score
# - Audit log entry written
```

### Step 8: Enable Live Monitoring

```bash
# Confirm live event monitoring is active
python -m macro_shock.orchestration.pipeline --config configs/production.yaml --mode monitor
```

---

## Rollback Procedure

If any production issue is detected:

```bash
# Immediate: revert to previous image
docker service update --image msre-pipeline:v0.9.x msre_pipeline
docker service update --image msre-pipeline:v0.9.x msre_api

# Verify rollback:
python scripts/health_check.py --env production

# Notify PM team and risk officer immediately
# File incident report within 2 hours
# Post-mortem within 24 hours
```

---

## Environment Variables (Production)

```bash
# Data feeds
BLOOMBERG_API_KEY=<from Vault>
FRED_API_KEY=<from Vault>
REFINITIV_API_KEY=<from Vault>

# Alert routing
SLACK_WEBHOOK_URL=<from Vault>
PAGERDUTY_KEY=<from Vault>
OMS_ALERT_URL=<from Vault>
OMS_ENDPOINT_URL=<from Vault>

# Database
TIMESCALEDB_URL=<from Vault>
POSTGRES_URL=<from Vault>
REDIS_URL=<from Vault>
ELASTICSEARCH_URL=<from Vault>

# System
MSRE_ENVIRONMENT=production
MSRE_LOG_LEVEL=WARNING
MSRE_AUDIT_LOG_DIR=/var/log/msre/audit
```

---

## Monitoring in Production

### Key Metrics to Watch

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Pipeline heartbeat | > 5 min silence | Page on-call |
| Score computation latency | > 2s p99 | Investigate lag |
| Data feed staleness | > configured limit | Alert, use cached |
| Failed stages per run | > 2 | Review pipeline health |
| OMS order queue depth | > 10 pending | PM attention |
| Unacknowledged CRITICAL alerts | > 0 for > 15min | Page PM |

### Log Queries (Elasticsearch)

```json
// Find all CRITICAL alerts in last 24h
{ "query": { "bool": { "must": [
    { "term": { "audit_type": "alert_emitted" } },
    { "term": { "level": "CRITICAL" } },
    { "range": { "timestamp": { "gte": "now-24h" } } }
]}}}

// Find all events with weekend_gap=true
{ "query": { "bool": { "must": [
    { "term": { "audit_type": "event_detected" } },
    { "term": { "full_weekend_gap": true } }
]}}}
```

---

## Model Governance and Recalibration

### Recalibration Schedule

| Component | Frequency | Trigger |
|-----------|-----------|---------|
| Lexicon weights | Semi-annually | FOMC communication style change |
| Vulnerability calibration percentiles | Quarterly | Significant market regime shift |
| Scenario base probabilities | Quarterly | Backtest accuracy degradation |
| Regime multipliers | Semi-annually | Crisis/expansion classification drift |
| Transformer anchor sentences | Annually | Communication paradigm shift |

### Recalibration Process

1. Run full backtest on latest 12-month corpus
2. Compare score accuracy, precision@CRITICAL, recall@CRITICAL to prior version
3. If any metric degrades > 10%: mandatory recalibration before next production deploy
4. Champion/challenger: run old and new models in parallel on staging for 2 weeks
5. Risk officer approval required for any parameter change
6. All calibration changes versioned in MLflow with full reproducibility

### Overfitting Safeguards

- All calibration uses strict walk-forward (no future data in training)
- Test set is always the most recent N events (temporal split, not random)
- Minimum 20 events required per regime for any regime-specific calibration
- Parameter changes require out-of-sample validation improvement before merging
- No model changes during active major market events
