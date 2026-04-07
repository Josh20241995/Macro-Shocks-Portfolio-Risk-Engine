# Operational Runbook

## Macro Shock Risk Engine — On-Call and Incident Response Guide

**Audience:** On-call engineers, risk officers, system administrators  
**Version:** 1.0  
**Classification:** Internal — do not share externally  

---

## Quick Reference

| Condition | First Action |
|-----------|-------------|
| API not responding | Check docker service, restart if down; page risk officer if >2min |
| Pipeline silent >5min | Check heartbeat monitor; inspect logs |
| CRITICAL alert firing | Notify PM/Risk Officer immediately; do NOT auto-execute |
| Data feed stale | Check feed connection; system uses last-known-good with flag |
| Score reliability LOW | Investigate missing data; communicate to PM |
| Kill switch triggered | Immediate PM + Risk Officer review required |
| OMS submission failed | Pre-trade check logs; manual escalation to trading desk |

---

## 1. System Overview for On-Call

The MSRE runs as a set of Docker services:

```
msre_pipeline    — Core pipeline worker; processes events
msre_api         — FastAPI REST server; serves dashboard and downstream
```

Supporting infrastructure (managed separately):
```
TimescaleDB      — Market data time-series
PostgreSQL       — Event metadata, alerts, order audit
Redis            — Hot cache
Elasticsearch    — Audit logs
```

The system is **advisory-only**. It generates risk scores and hedge recommendations, but it does NOT execute trades. No market action occurs without explicit PM authorization.

---

## 2. Routine Health Monitoring

### Daily Checks (automated)

The following should run automatically via cron or alerting:

```bash
# Full system health check
python scripts/health_check.py --env production --verbose

# Post daily smoke test
python scripts/smoke_test.py --env production --scenario hawkish_surprise
```

Expected healthy output includes:
- API liveness: ✓
- Pipeline imports: ✓
- All database connections: ✓

### Key Metrics Dashboard

| Metric | Healthy Range | Alert Threshold |
|--------|--------------|-----------------|
| API p99 latency | < 500ms | > 2000ms |
| Pipeline heartbeat gap | < 5min | > 10min |
| Risk score computation time | < 1s | > 5s |
| Data feed staleness | within configured limits | exceed limits |
| Unacknowledged CRITICAL alerts | 0 | > 0 for 15min |

---

## 3. Common Incidents and Resolution

### INC-001: API Server Not Responding

**Symptoms:** Dashboard shows "API error", health check fails  
**Likely causes:** Container crashed, OOM, misconfigured env vars  

```bash
# Check service status
docker service ps msre_api

# View recent logs
docker service logs msre_api --tail 100

# Restart service (zero-downtime rolling restart)
docker service update --force msre_api

# Verify recovery
curl http://msre-api.internal:8000/health
```

**Escalate if:** Not recovered within 5 minutes.

---

### INC-002: Pipeline Not Processing Events

**Symptoms:** No new risk scores appearing; heartbeat alerts firing  
**Likely causes:** Event feed disconnected, database write failure, unhandled exception  

```bash
# Check pipeline logs for errors
docker service logs msre_pipeline --tail 200 | grep -i error

# Check database write latency
docker exec msre_timescaledb psql -U msre -d market_data \
  -c "SELECT MAX(timestamp) FROM risk_scores;"

# Restart pipeline worker
docker service update --force msre_pipeline

# Verify pipeline is alive
python scripts/health_check.py --env production --component pipeline_import
```

**Escalate if:** Not recovered within 10 minutes. PM to be notified if any scheduled event window was missed.

---

### INC-003: Data Feed Stale or Disconnected

**Symptoms:** Risk scores showing `score_reliability: LOW`; data quality < 50%  
**Likely causes:** Bloomberg B-PIPE disconnected, FRED API limit reached, Redis cache stale  

```bash
# Check which feeds are stale
docker service logs msre_pipeline --tail 200 | grep stale

# Test Bloomberg connectivity (production)
python -c "
from macro_shock.data.feed_provider import BloombergFeedProvider
from macro_shock.event_detection.calendar import MarketCalendar
p = BloombergFeedProvider(MarketCalendar())
print('Bloomberg healthy:', p.is_healthy())
"

# If Bloomberg unavailable, system uses last-known-good values
# with has_critical_data_gap=True flag. This is handled gracefully.
# Duration limit: 30 minutes before escalation.
```

**Escalate if:** Feed down > 30 minutes during market hours. Notify PM that risk scores are operating on stale data.

---

### INC-004: CRITICAL Risk Alert Firing

**This is not an incident — this is the system working.**

1. **Immediately notify** PM and Risk Officer via the alert channels (Slack + PagerDuty)
2. Do NOT execute any trades or hedges automatically
3. PM reviews the alert detail in the dashboard
4. PM decides on hedging action with Risk Officer input
5. PM authorizes specific orders via the order management system
6. Document decision in the alert acknowledgment field

```bash
# View the specific alert details
curl http://msre-api.internal:8000/api/v1/alerts?level=CRITICAL

# Acknowledge alert after PM review
curl -X POST http://msre-api.internal:8000/api/v1/alerts/acknowledge \
  -H "Content-Type: application/json" \
  -d '{"alert_id": "<ALERT_ID>", "acknowledged_by": "pm.name@firm.com"}'
```

---

### INC-005: Kill Switch Flag Triggered

**IMMEDIATE ESCALATION REQUIRED**

The kill switch flag means the composite risk score has exceeded 90/100. This is the most severe risk state.

1. **Within 1 minute:** Page PM and CRO (Chief Risk Officer) directly
2. **Within 5 minutes:** PM and CRO review dashboard together
3. **All pending orders** are held until PM and CRO jointly authorize
4. **Document:** Log the event, the score, and the authorization chain

The kill switch does NOT automatically execute trades. It is a flag requiring human authorization.

---

### INC-006: OMS Order Submission Failed

**Symptoms:** Order stuck in `PENDING_APPROVAL` or `FAILED` state  
**Likely causes:** OMS connectivity failure, authorization token expired, pre-trade check blocked  

```bash
# Check order audit log
curl http://msre-api.internal:8000  # Not exposed via API — check DB directly
docker exec msre_postgres psql -U msre -d msre_meta \
  -c "SELECT order_id, status, failure_reason FROM order_audit ORDER BY created_at DESC LIMIT 10;"

# For pre-trade block: check blocking checks in log
docker service logs msre_pipeline --tail 200 | grep order_blocked
```

**Resolution:** Contact trading desk directly for manual order entry. Never bypass OMS pre-trade checks programmatically.

---

### INC-007: Model Score Suddenly Changed

**Symptoms:** Scores materially higher or lower than historical baseline without obvious market cause  
**Likely causes:** Data feed error feeding extreme values, model calibration drift  

```bash
# Check last 10 scores
docker exec msre_timescaledb psql -U msre -d market_data \
  -c "SELECT composite_score, regime, generated_at FROM risk_scores ORDER BY generated_at DESC LIMIT 10;"

# Compare against historical mean
# If score differs from 30-day rolling mean by >20 points, investigate input data

# Check market data for outliers
docker exec msre_timescaledb psql -U msre -d market_data \
  -c "SELECT timestamp, vix_spot, hy_spread_bps FROM market_snapshots ORDER BY timestamp DESC LIMIT 5;"
```

**Escalate:** If not explained by genuine market conditions, pause scoring and notify quant team.

---

## 4. Rollback Procedure

```bash
# List available production images
docker image ls | grep msre-pipeline

# Rollback to previous version
docker service update --image msre-pipeline:v0.9.x msre_api
docker service update --image msre-pipeline:v0.9.x msre_pipeline

# Verify rollback
python scripts/health_check.py --env production
python scripts/smoke_test.py --env production

# Notify team of rollback
# File incident report within 2 hours
# Post-mortem within 24 hours
```

---

## 5. Maintenance Windows

**Monthly maintenance** (first Sunday, 2 AM - 4 AM ET):
- Database vacuum and statistics update
- Log rotation
- Certificate renewal check
- Model calibration review (quarterly)

```bash
# Announce maintenance (disable alerts temporarily)
# Update docker services
docker service update --force msre_pipeline
docker service update --force msre_api

# Run post-maintenance health check
python scripts/health_check.py --env production --verbose
python scripts/smoke_test.py --env production
```

---

## 6. Emergency Contacts

| Role | Contact | When to Page |
|------|---------|-------------|
| On-Call Engineer | PagerDuty rotation | Any INC-001, 002, 003 |
| Portfolio Manager | [PM contact] | Any CRITICAL alert, INC-004, 005 |
| Risk Officer | [CRO contact] | Kill switch, major scoring anomaly |
| Quant Research | [QR contact] | Model anomaly (INC-007) |
| Infra / DevOps | [DevOps contact] | Database, infrastructure issues |

---

## 7. Log Locations

| Log Type | Location | Retention |
|----------|----------|-----------|
| Application logs | `/var/log/msre/` | 90 days |
| Audit trail (JSONL) | `/var/log/msre/audit/` | 7 years |
| Database slow query | PostgreSQL pg_stat | 30 days |
| Alert history | PostgreSQL `alert_history` | 7 years |
| Order audit | PostgreSQL `order_audit` | 7 years |
| Docker service logs | `docker service logs` | 7 days |

---

## 8. Regulatory and Compliance Notes

- All risk scores and recommendations are logged with immutable audit trail
- All order authorizations require named PM sign-off (logged)
- Alert acknowledgments are timestamped and attributed
- No data is deleted from audit tables (append-only)
- Score reliability is always communicated alongside the score itself
- System never represents a guarantee of market outcome
