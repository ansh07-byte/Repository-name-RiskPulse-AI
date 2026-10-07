# Velocity and Freshness Monitoring Update

## Implemented

- Continuous 5-second rolling transaction velocity converted to TPM
- Velocity threshold of 1800 TPM
- Source-to-processing freshness measured separately from inference latency
- Freshness threshold of 1000 ms
- Independent `FRAUD_RISK`, `VELOCITY`, and `FRESHNESS` alerts
- `Test Fraud Alert`, `Test Velocity Spike`, and `Test Freshness Breach` controls
- PostgreSQL/SQLite persistence and Power BI CSV export for all monitoring fields
- Safe events-table backup and automatic schema migration

## Verified test results

- Fraud test probability: 70.7654% (crossed the 70% threshold)
- Velocity test: at least 1944 TPM (crossed the 1800 TPM threshold)
- Freshness test: at least 1500 ms (crossed the 1000 ms threshold)
- `/health`, WebSocket-compatible event payloads, dashboard JavaScript, and Power BI export fields verified

## Power BI monitoring fields

- `velocity_tpm`
- `velocity_alert`
- `source_timestamp`
- `freshness_ms`
- `freshness_alert`

Monitoring is automatic. The test buttons only generate controlled threshold breaches for evaluation.
