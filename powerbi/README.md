# Power BI connection

Preferred connection: Power BI Desktop → Get Data → PostgreSQL database → server `localhost`, database `riskpulse`, table `events`.

Portable fallback: import `riskpulse_transactions.csv`, which the running backend refreshes after every saved transaction. The same export is available at `/api/powerbi/export.csv`.

Recommended report pages:

1. Executive overview: total transactions, fraud rate, amount at risk, holds/blocks
2. Fraud analysis: score distribution, device type, product code, time trend
3. Model operations: inference latency, actual label vs decision, false positives/negatives
4. Audit: blockchain status and transaction hash coverage

