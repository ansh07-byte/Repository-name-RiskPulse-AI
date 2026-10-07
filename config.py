import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"
REPORT_DIR = ROOT / "reports"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://riskpulse:riskpulse@localhost:5432/riskpulse",
)
ALLOW_SQLITE_FALLBACK = os.getenv("ALLOW_SQLITE_FALLBACK", "true").lower() == "true"
SQLITE_FALLBACK_URL = f"sqlite:///{(ROOT / 'data' / 'riskpulse_fallback.db').as_posix()}"
RISK_THRESHOLD = float(os.getenv("RISK_THRESHOLD", "0.70"))
STREAM_INTERVAL_SECONDS = float(os.getenv("STREAM_INTERVAL_SECONDS", "1.0"))
VELOCITY_WINDOW_SECONDS = float(os.getenv("VELOCITY_WINDOW_SECONDS", "5.0"))
VELOCITY_THRESHOLD_TPM = float(os.getenv("VELOCITY_THRESHOLD_TPM", "1800"))
FRESHNESS_THRESHOLD_MS = float(os.getenv("FRESHNESS_THRESHOLD_MS", "1000"))
VELOCITY_TEST_EVENT_COUNT = int(os.getenv("VELOCITY_TEST_EVENT_COUNT", "160"))
BLOCKCHAIN_RPC_URL = os.getenv("BLOCKCHAIN_RPC_URL", "http://127.0.0.1:8545")
BLOCKCHAIN_CONTRACT_ADDRESS = os.getenv("BLOCKCHAIN_CONTRACT_ADDRESS", "")
