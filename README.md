# RiskPulse AI v3 — IEEE-CIS Upgrade

This version replaces generated training data with the anonymized real-world IEEE-CIS fraud dataset, compares five models across chronological 80/20, chronological 80/10/10 and stratified-random 80/20 evaluation, replays unseen held-out records as a real-time authorization stream, uses PostgreSQL as the primary operational database, exports a Power BI-ready table, and includes a Solidity audit contract for high-risk alerts.

## Honest implementation status

- Implemented in code: IEEE-CIS ingestion, 39 engineered/direct features, three evaluation views including a true validation set, separately saved 80/10/10 classifiers, validation-based champion selection, final champion refit on the first 90%, live latest-10% replay, interactive Model Lab, risk decisions, FastAPI/WebSockets, PostgreSQL persistence, SQLite emergency fallback, Power BI CSV export, upgraded dashboard, and optional Web3 audit writer.
- Requires user-supplied data: Kaggle does not permit this project to redistribute the competition CSV files.
- Requires deployment: compile/deploy the Solidity contract and configure its address before blockchain status becomes `verified`.
- Power BI Desktop must connect to PostgreSQL or import `powerbi/riskpulse_transactions.csv`; a `.pbix` file cannot be generated or verified in this Linux environment.

## Setup

This evaluation-ready package already includes the trained deployment model, four comparison artifacts, and the held-out replay stream. The Tuned Random Forest entry in Model Lab uses the same exported `champion_model.joblib`, avoiding a duplicate 68 MB model copy. Raw Kaggle training files and report-rendering intermediates are intentionally omitted so the package is easier to download; they are not required to run the demonstration.

1. Download the IEEE-CIS competition archive and copy `train_transaction.csv` and `train_identity.csv` to `data/raw/`.
2. With Docker Desktop installed, run `docker compose up -d postgres ganache`.
3. Double-click `train_models.bat`.
4. Double-click `run.bat` and open `http://127.0.0.1:8000`.

Training creates `reports/model_comparison.csv`, `reports/model_comparison.json`, `reports/IEEE_CIS_Model_Comparison_Report.docx`, one chronological `.joblib` artifact per model, `models/champion_model.joblib`, and `data/processed/holdout_stream.csv`.

The baseline is `DummyClassifier`. “Regression” is Logistic Regression because the target is binary classification. Random Forest and Extra Trees are nonlinear ensemble candidates. The champion is selected by chronological PR-AUC, not accuracy. The dashboard's “Compare all models” button runs the same holdout transaction through all five saved pipelines.

## Verified model results

The supplied labelled training file contained 377,181 records. A chronological split used 301,744 records for training and 75,437 later records for testing.

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|---:|---:|
| Random Forest Tuned | 0.9714 | 0.6997 | 0.3386 | 0.4563 | 0.8752 | 0.4645 |
| Random Forest Base | 0.9478 | 0.3396 | 0.5041 | 0.4059 | 0.8771 | 0.4571 |
| Extra Trees | 0.8912 | 0.1673 | 0.5213 | 0.2533 | 0.8206 | 0.2719 |
| Logistic Regression | 0.6127 | 0.0692 | 0.7989 | 0.1274 | 0.7876 | 0.2139 |
| Most-frequent baseline | 0.9646 | 0.0000 | 0.0000 | 0.0000 | 0.5000 | 0.0354 |

Tuned Random Forest is the exported champion. Under chronological 80/10/10, validation PR-AUC selected it and the untouched latest 10% produced precision 0.6956, recall 0.3405, F1 0.4572, ROC-AUC 0.8790 and PR-AUC 0.4675. On the stratified random split it reached PR-AUC 0.7280 and F1 0.6927, but that less realistic split is reported only for comparison. The baseline's higher accuracy is not useful: it predicts every transaction as genuine and detects zero fraud cases.

## Chronological 80/10/10 workflow

Run `python train_801010.py` after the standard model comparison. The first 80% trains all candidates, the next 10% selects the champion by validation PR-AUC, and the latest 10% is used once for final evaluation. The selected algorithm is then refitted on the first 90% and exported as `models/champion_model.joblib` for the application.

## PostgreSQL and Power BI

PostgreSQL is primary because it supports concurrent access and Power BI. If unavailable, the app uses a visibly reported SQLite fallback unless `ALLOW_SQLITE_FALLBACK=false`.

Power BI Desktop: Get Data → PostgreSQL database → `riskpulse` → `events`. Alternatively import `powerbi/riskpulse_transactions.csv` or download `/api/powerbi/export.csv`.

Suggested visuals: fraud rate, amount at risk, decisions by time, device/product risk, score distribution, false positives/negatives, and inference latency.

The export also includes `velocity_tpm`, `velocity_alert`, `source_timestamp`, `freshness_ms`, and `freshness_alert` for Power BI monitoring visuals.

## Automatic velocity and freshness monitoring

Monitoring runs continuously for every processed transaction; the three test buttons only create controlled evaluation conditions.

- **Velocity:** transactions observed during the latest 5 seconds are converted to transactions per minute. The default threshold is 1800 TPM. At the normal one-event-per-second replay rate, the KPI stabilizes near 60 TPM.
- **Freshness:** `freshness_ms` is the difference between `source_timestamp` and processing-complete `timestamp`. It is separate from `inference_ms`. The default breach threshold is 1000 ms.
- **Independent alerts:** the Critical Alerts panel can show `FRAUD_RISK`, `VELOCITY`, and `FRESHNESS` messages independently.
- **Evaluation controls:** `Test Fraud Alert` selects a transaction whose actual model probability reaches the 70% risk threshold; `Test Velocity Spike` persists a controlled burst; and `Test Freshness Breach` submits a deliberately delayed event.

On first startup after this upgrade, RiskPulse detects missing database columns, creates a timestamped backup of the existing `events` table, and then adds the monitoring fields. SQLite fallback also receives a timestamped database-file backup.

## Blockchain

`blockchain/FraudAudit.sol` stores only the high-risk record hash, risk basis points, decision, and timestamp—not sensitive transaction data. Deploy it to Ganache, set `BLOCKCHAIN_CONTRACT_ADDRESS`, and restart. Until configured, the dashboard truthfully shows `not configured`.

After `docker compose up -d ganache`, run `deploy_blockchain.bat`. Copy the printed address into the environment as `BLOCKCHAIN_CONTRACT_ADDRESS` before starting `run.bat`.

## Evaluation statement

“The model is trained on anonymized real-world IEEE-CIS records. Held-out later records are replayed through the authorization pipeline to demonstrate streaming inference. The prototype is not connected to a live banking network.”
