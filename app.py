from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

import joblib
import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from blockchain.audit import write_audit
from config import (
    FRESHNESS_THRESHOLD_MS,
    MODEL_DIR,
    PROCESSED_DIR,
    RISK_THRESHOLD,
    ROOT,
    STREAM_INTERVAL_SECONDS,
    VELOCITY_TEST_EVENT_COUNT,
    VELOCITY_THRESHOLD_TPM,
    VELOCITY_WINDOW_SECONDS,
)
from ml_pipeline import FEATURES
from storage import BACKEND, count_events, export_powerbi_csv, save_event, save_events

MODEL_PATH = MODEL_DIR / "champion_model.joblib"
METADATA_PATH = MODEL_DIR / "model_metadata.json"
STREAM_PATH = PROCESSED_DIR / "holdout_stream.csv"

if not MODEL_PATH.exists() or not METADATA_PATH.exists() or not STREAM_PATH.exists():
    raise RuntimeError(
        "Model artifacts are missing. Put IEEE-CIS CSV files in data/raw and run: python ml_pipeline.py"
    )

MODEL = joblib.load(MODEL_PATH)
METADATA = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
STREAM = pd.read_csv(STREAM_PATH)
DEPLOYMENT_THRESHOLD = float(METADATA.get("decision_threshold", RISK_THRESHOLD))
MODEL_FILES = {
    "Baseline (Most Frequent)": MODEL_DIR / "baseline_most_frequent_chronological_80_10_10.joblib",
    "Logistic Regression": MODEL_DIR / "logistic_regression_chronological_80_10_10.joblib",
    "Random Forest Base": MODEL_DIR / "random_forest_base_chronological_80_10_10.joblib",
    "Extra Trees Classifier": MODEL_DIR / "extra_trees_classifier_chronological_80_10_10.joblib",
    "Random Forest Tuned": MODEL_DIR / "champion_model.joblib",
}
MODEL_LAB = {}

app = FastAPI(title="RiskPulse AI — IEEE-CIS Fraud Command Center", version="3.0")
clients: set[WebSocket] = set()
last_event = None
stream_index = 0
high_risk_rows = None
low_risk_row = None
arrival_times = deque()
arrival_lock = Lock()


def reasons_for(row, probability):
    reasons = []
    if float(row.get("TransactionAmt", 0) or 0) >= 500: reasons.append("high transaction amount")
    hour = int(row.get("transaction_hour", 12) or 12)
    if hour <= 5 or hour >= 23: reasons.append("unusual transaction hour")
    if str(row.get("DeviceType", "unknown")) not in {"desktop", "mobile", "nan", "unknown"}:
        reasons.append("uncommon device type")
    if float(row.get("missing_count", 0) or 0) > 20: reasons.append("limited identity information")
    if probability >= DEPLOYMENT_THRESHOLD and not reasons: reasons.append("combined ML feature pattern")
    return reasons or ["no major rule-based indicator"]


def decision_for(probability):
    if probability >= 0.90: return "BLOCK_RECOMMENDED"
    if probability >= DEPLOYMENT_THRESHOLD: return "HOLD_FOR_REVIEW"
    if probability >= 0.50: return "ADDITIONAL_VERIFICATION"
    return "APPROVE"


def record_arrival(marker=None):
    marker = time.monotonic() if marker is None else marker
    cutoff = marker - VELOCITY_WINDOW_SECONDS
    with arrival_lock:
        arrival_times.append(marker)
        while arrival_times and arrival_times[0] < cutoff:
            arrival_times.popleft()
        return round(len(arrival_times) * 60.0 / VELOCITY_WINDOW_SECONDS, 1)


def current_velocity():
    marker = time.monotonic()
    cutoff = marker - VELOCITY_WINDOW_SECONDS
    with arrival_lock:
        while arrival_times and arrival_times[0] < cutoff:
            arrival_times.popleft()
        return round(len(arrival_times) * 60.0 / VELOCITY_WINDOW_SECONDS, 1)


def select_stream_row(force_high=False, force_low=False):
    global stream_index, high_risk_rows, low_risk_row
    if force_high:
        if high_risk_rows is None:
            fraud = STREAM[STREAM["isFraud"] == 1]
            probabilities = MODEL.predict_proba(fraud[FEATURES])[:, 1]
            qualified = [(position, float(probability)) for position, probability in enumerate(probabilities)
                         if float(probability) >= DEPLOYMENT_THRESHOLD]
            if not qualified:
                best = max(range(len(probabilities)), key=lambda position: probabilities[position])
                qualified = [(best, float(probabilities[best]))]
            high_risk_rows = [(fraud.iloc[position], probability) for position, probability in qualified]
        row, probability = high_risk_rows[stream_index % len(high_risk_rows)]
    elif force_low:
        if low_risk_row is None:
            sample = STREAM.iloc[: min(512, len(STREAM))]
            probabilities = MODEL.predict_proba(sample[FEATURES])[:, 1]
            position = min(range(len(probabilities)), key=lambda item: probabilities[item])
            low_risk_row = (sample.iloc[position], float(probabilities[position]))
        row, probability = low_risk_row
    else:
        row = STREAM.iloc[stream_index % len(STREAM)]
        probability = None
    stream_index += 1
    return row, probability


def alert_messages(event):
    alerts = []
    if event["is_high_risk"]:
        alerts.append({
            "type": "FRAUD_RISK",
            "message": f"Fraud probability {event['fraud_probability'] * 100:.1f}% crossed the {DEPLOYMENT_THRESHOLD * 100:.0f}% threshold.",
        })
    if event["velocity_alert"]:
        alerts.append({
            "type": "VELOCITY",
            "message": f"Transaction velocity {event['velocity_tpm']:.0f} TPM crossed {VELOCITY_THRESHOLD_TPM:.0f} TPM.",
        })
    if event["freshness_alert"]:
        alerts.append({
            "type": "FRESHNESS",
            "message": f"Event freshness {event['freshness_ms']:.0f} ms crossed {FRESHNESS_THRESHOLD_MS:.0f} ms.",
        })
    return alerts


def make_event(force_high=False, force_low=False, source_delay_ms=0.0, audit=True, velocity_marker=None):
    started = time.perf_counter()
    row, known_probability = select_stream_row(force_high, force_low)
    source_timestamp = datetime.now(timezone.utc) - timedelta(milliseconds=source_delay_ms)
    frame = pd.DataFrame([row])[FEATURES]
    probability = known_probability if known_probability is not None else float(MODEL.predict_proba(frame)[0, 1])
    decision = decision_for(probability)
    inference_ms = round((time.perf_counter() - started) * 1000, 3)
    processing_complete = datetime.now(timezone.utc)
    freshness_ms = round(max(0.0, (processing_complete - source_timestamp).total_seconds() * 1000), 3)
    velocity_tpm = record_arrival(velocity_marker)
    event = {
        "event_id": f"EVT-{uuid.uuid4().hex[:12].upper()}",
        "source_transaction_id": str(int(row["TransactionID"])),
        "timestamp": processing_complete,
        "source_timestamp": source_timestamp,
        "amount": round(float(row.get("TransactionAmt", 0)), 2),
        "product_code": str(row.get("ProductCD", "unknown")),
        "device_type": str(row.get("DeviceType", "unknown")),
        "fraud_probability": round(probability, 6),
        "actual_label": int(row["isFraud"]),
        "decision": decision,
        "reasons": ", ".join(reasons_for(row, probability)),
        "inference_ms": inference_ms,
        "velocity_tpm": velocity_tpm,
        "velocity_alert": velocity_tpm >= VELOCITY_THRESHOLD_TPM,
        "freshness_ms": freshness_ms,
        "freshness_alert": freshness_ms >= FRESHNESS_THRESHOLD_MS,
        "blockchain_status": "not required",
        "blockchain_tx_hash": "",
        "is_high_risk": probability >= DEPLOYMENT_THRESHOLD,
    }
    if event["is_high_risk"] and audit:
        audit = write_audit(event)
        event["blockchain_status"] = audit["status"]
        event["blockchain_tx_hash"] = audit["tx_hash"]
    return event


def serialize_event(event):
    wire = event.copy()
    wire["timestamp"] = event["timestamp"].isoformat()
    wire["source_timestamp"] = event["source_timestamp"].isoformat()
    wire["alerts"] = alert_messages(event)
    return wire


def next_event(force_high=False, source_delay_ms=0.0):
    event = make_event(force_high=force_high, source_delay_ms=source_delay_ms)
    save_event(event)
    return serialize_event(event)


async def broadcast(event):
    dead = []
    for socket in list(clients):
        try: await socket.send_json(event)
        except Exception: dead.append(socket)
    for socket in dead: clients.discard(socket)


async def produce(force_high=False, source_delay_ms=0.0):
    global last_event
    event = await asyncio.to_thread(next_event, force_high, source_delay_ms)
    last_event = event
    await broadcast(event)
    return event


def create_velocity_burst():
    """Create a real persisted test burst that crosses the configured TPM threshold."""
    marker = time.monotonic()
    events = []
    for _ in range(VELOCITY_TEST_EVENT_COUNT):
        events.append(make_event(force_low=True, audit=False, velocity_marker=marker))
    save_events(events)
    return serialize_event(events[-1])


async def produce_velocity_burst():
    global last_event
    event = await asyncio.to_thread(create_velocity_burst)
    last_event = event
    await broadcast(event)
    return event


async def stream_loop():
    while True:
        await produce()
        await asyncio.sleep(STREAM_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup(): app.state.stream_task = asyncio.create_task(stream_loop())


@app.on_event("shutdown")
async def shutdown():
    task = getattr(app.state, "stream_task", None)
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass


@app.get("/")
async def dashboard(): return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
async def health():
    velocity_tpm = current_velocity()
    return {
        "status": "healthy", "dataset": METADATA["dataset"],
        "model": METADATA["champion_model"], "database": BACKEND,
        "decision_threshold": DEPLOYMENT_THRESHOLD,
        "stored_events": count_events(), "connected_clients": len(clients),
        "blockchain_configured": bool(__import__("config").BLOCKCHAIN_CONTRACT_ADDRESS),
        "monitoring": {
            "velocity_tpm": velocity_tpm,
            "velocity_window_seconds": VELOCITY_WINDOW_SECONDS,
            "velocity_threshold_tpm": VELOCITY_THRESHOLD_TPM,
            "velocity_alert": velocity_tpm >= VELOCITY_THRESHOLD_TPM,
            "freshness_threshold_ms": FRESHNESS_THRESHOLD_MS,
            "latest_freshness_ms": last_event.get("freshness_ms") if last_event else None,
            "freshness_alert": last_event.get("freshness_alert") if last_event else False,
        },
        "last_event": last_event,
    }


@app.post("/demo/high-risk")
async def high_risk_demo(): return JSONResponse(await produce(True))


@app.post("/demo/velocity-spike")
async def velocity_spike_demo(): return JSONResponse(await produce_velocity_burst())


@app.post("/demo/freshness-breach")
async def freshness_breach_demo():
    simulated_delay = max(FRESHNESS_THRESHOLD_MS + 500.0, 1500.0)
    return JSONResponse(await produce(False, simulated_delay))


@app.get("/api/models")
async def available_models():
    return {
        "champion": METADATA["champion_model"],
        "selection_split": "chronological_80_10_10_validation",
        "models": [{"name": name, "artifact": path.name} for name, path in MODEL_FILES.items()],
    }


@app.post("/demo/model-comparison")
async def model_comparison():
    """Score one labelled holdout transaction with every separately saved model."""
    global stream_index
    fraud = STREAM[STREAM["isFraud"] == 1]
    row = fraud.iloc[stream_index % len(fraud)] if len(fraud) else STREAM.iloc[stream_index % len(STREAM)]
    stream_index += 1
    frame = pd.DataFrame([row])[FEATURES]
    scores = []
    for name, path in MODEL_FILES.items():
        if name not in MODEL_LAB:
            MODEL_LAB[name] = joblib.load(path)
        model = MODEL_LAB[name]
        probabilities = model.predict_proba(frame)
        classes = list(model.named_steps["classifier"].classes_)
        probability = float(probabilities[0, classes.index(1)]) if 1 in classes else 0.0
        scores.append({
            "model": name, "probability": round(probability, 6),
            "decision": decision_for(probability),
            "is_champion": name == METADATA["champion_model"],
        })
    return {
        "transaction_id": str(int(row["TransactionID"])),
        "actual_label": int(row["isFraud"]),
        "amount": round(float(row["TransactionAmt"]), 2),
        "threshold": DEPLOYMENT_THRESHOLD,
        "scores": scores,
    }


@app.get("/api/powerbi/export.csv")
async def powerbi_export(): return FileResponse(export_powerbi_csv(), filename="riskpulse_transactions.csv")


@app.websocket("/ws")
async def websocket(websocket: WebSocket):
    await websocket.accept(); clients.add(websocket)
    if last_event: await websocket.send_json(last_event)
    try:
        while True: await websocket.receive_text()
    except (WebSocketDisconnect, Exception): clients.discard(websocket)
