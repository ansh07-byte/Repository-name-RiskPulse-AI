"""IEEE-CIS preprocessing, model comparison, report generation, and champion export."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from docx import Document
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, confusion_matrix, f1_score,
    precision_score, recall_score, roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.model_selection import train_test_split

from config import MODEL_DIR, PROCESSED_DIR, RAW_DIR, REPORT_DIR

TARGET = "isFraud"
NUMERIC = [
    "TransactionAmt", "TransactionDT", "transaction_hour", "transaction_day",
    "amount_log", "hour_sin", "hour_cos", "is_night", "has_identity",
    "dist1", "dist2", "C1", "C2", "C4", "C5", "C6", "C8", "C9", "C10",
    "C11", "C12", "C13", "C14", "D1", "D2", "D3", "D4", "D10", "D15",
    "missing_count",
]
CATEGORICAL = [
    "ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain",
    "DeviceType", "device_family", "addr1", "addr2",
]
FEATURES = NUMERIC + CATEGORICAL


def _device_family(value):
    value = str(value).lower()
    if value in {"nan", "none"}: return "unknown"
    for family in ("windows", "ios", "mac", "android", "linux", "samsung", "huawei"):
        if family in value: return family
    return "other"


def load_ieee(max_rows: int | None = None) -> pd.DataFrame:
    tx_path = RAW_DIR / "train_transaction.csv"
    id_path = RAW_DIR / "train_identity.csv"
    if not tx_path.exists():
        raise FileNotFoundError(
            f"Missing {tx_path}. Download the IEEE-CIS Kaggle files and place "
            "train_transaction.csv and train_identity.csv in data/raw/."
        )
    transaction_needed = {"TransactionID", TARGET, "DeviceType", "DeviceInfo"}
    transaction_needed.update(c for c in FEATURES if c not in {"transaction_hour", "transaction_day", "missing_count", "device_family", "DeviceType"})
    tx_header = pd.read_csv(tx_path, nrows=0).columns
    tx = pd.read_csv(tx_path, usecols=[c for c in tx_header if c in transaction_needed], nrows=max_rows)
    if id_path.exists():
        id_header = pd.read_csv(id_path, nrows=0).columns
        identity = pd.read_csv(id_path, usecols=[c for c in id_header if c in {"TransactionID", "DeviceType", "DeviceInfo"}])
        tx = tx.merge(identity, on="TransactionID", how="left", validate="one_to_one")
    else:
        tx["DeviceType"] = np.nan
        tx["DeviceInfo"] = np.nan
    return tx.sort_values("TransactionDT").reset_index(drop=True)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["transaction_hour"] = ((out["TransactionDT"] // 3600) % 24).astype("int16")
    out["transaction_day"] = (out["TransactionDT"] // 86400).astype("int16")
    out["amount_log"] = np.log1p(out["TransactionAmt"].clip(lower=0))
    out["hour_sin"] = np.sin(2 * np.pi * out["transaction_hour"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["transaction_hour"] / 24)
    out["is_night"] = out["transaction_hour"].isin([0, 1, 2, 3, 4, 5]).astype("int8")
    out["has_identity"] = out.get("DeviceType", pd.Series(index=out.index, dtype=object)).notna().astype("int8")
    out["device_family"] = out.get("DeviceInfo", pd.Series(index=out.index, dtype=object)).map(_device_family)
    source_columns = [c for c in df.columns if c not in {TARGET, "TransactionID"}]
    out["missing_count"] = out[source_columns].isna().sum(axis=1).astype("int16")
    for col in FEATURES:
        if col not in out: out[col] = np.nan
    return out


def build_preprocessor():
    numeric = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=20)),
    ])
    return ColumnTransformer([("num", numeric, NUMERIC), ("cat", categorical, CATEGORICAL)])


def model_candidates():
    return {
        "Baseline (Most Frequent)": DummyClassifier(strategy="most_frequent"),
        "Logistic Regression": LogisticRegression(
            max_iter=600, class_weight="balanced", solver="liblinear", random_state=42
        ),
        "Random Forest Base": RandomForestClassifier(
            n_estimators=140, max_depth=16, min_samples_leaf=3,
            class_weight="balanced_subsample", n_jobs=-1, random_state=42,
        ),
        "Extra Trees Classifier": ExtraTreesClassifier(
            n_estimators=160, max_depth=20, min_samples_leaf=2,
            class_weight="balanced", n_jobs=-1, random_state=42,
        ),
        "Random Forest Tuned": RandomForestClassifier(
            n_estimators=220, max_depth=24, min_samples_leaf=2,
            max_features="sqrt", class_weight="balanced_subsample",
            n_jobs=-1, random_state=42,
        ),
    }


def safe_auc(y, probability, metric):
    try: return float(metric(y, probability))
    except ValueError: return 0.0


def evaluate(name, pipeline, x_train, y_train, x_test, y_test):
    started = time.perf_counter()
    pipeline.fit(x_train, y_train)
    train_seconds = time.perf_counter() - started
    started = time.perf_counter()
    probabilities = pipeline.predict_proba(x_test)
    classes = list(pipeline.named_steps["classifier"].classes_)
    probability = probabilities[:, classes.index(1)] if 1 in classes else np.zeros(len(x_test))
    inference_ms_per_row = (time.perf_counter() - started) * 1000 / max(len(x_test), 1)
    prediction = (probability >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_test, prediction, labels=[0, 1]).ravel()
    return {
        "model": name,
        "accuracy": accuracy_score(y_test, prediction),
        "precision": precision_score(y_test, prediction, zero_division=0),
        "recall": recall_score(y_test, prediction, zero_division=0),
        "f1": f1_score(y_test, prediction, zero_division=0),
        "roc_auc": safe_auc(y_test, probability, roc_auc_score),
        "pr_auc": safe_auc(y_test, probability, average_precision_score),
        "true_negative": int(tn), "false_positive": int(fp),
        "false_negative": int(fn), "true_positive": int(tp),
        "train_seconds": train_seconds,
        "inference_ms_per_row": inference_ms_per_row,
    }


def write_docx(results: pd.DataFrame, metadata: dict):
    doc = Document()
    doc.add_heading("RiskPulse AI — IEEE-CIS Model Comparison Report", 0)
    doc.add_paragraph(
        "This report compares a non-learning baseline, Logistic Regression, tree ensembles, and a "
        "tuned Random Forest on anonymized IEEE-CIS transaction data. A chronological split keeps "
        "later transactions for realistic production selection; a stratified random split shows "
        "how split choice changes reported performance."
    )
    doc.add_heading("Dataset and evaluation", level=1)
    for key, value in metadata.items(): doc.add_paragraph(f"{key.replace('_', ' ').title()}: {value}")
    doc.add_heading("Model comparison", level=1)
    columns = ["split", "model", "precision", "recall", "f1", "roc_auc", "pr_auc"]
    table = doc.add_table(rows=1, cols=len(columns)); table.style = "Table Grid"
    for i, col in enumerate(columns): table.rows[0].cells[i].text = col.replace("_", " ").title()
    for _, row in results.iterrows():
        cells = table.add_row().cells
        for i, col in enumerate(columns):
            value = row[col]
            cells[i].text = f"{value:.4f}" if isinstance(value, float) else str(value)
    doc.add_heading("Interpretation", level=1)
    doc.add_paragraph(
        "Accuracy is not the primary selection metric because fraud is rare. PR-AUC summarizes "
        "performance on the minority fraud class; recall measures detected frauds, while precision "
        "measures how many alerts are genuinely fraudulent. Operational threshold selection should "
        "balance fraud loss against false-positive review cost."
    )
    doc.add_heading("Conclusion", level=1)
    doc.add_paragraph(f"The exported champion is {metadata['champion_model']}, selected by PR-AUC.")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    doc.save(REPORT_DIR / "IEEE_CIS_Model_Comparison_Report.docx")


def _safe_name(name):
    return name.lower().replace("(", "").replace(")", "").replace(" ", "_")


def train_compare(max_rows=None):
    for path in (MODEL_DIR, REPORT_DIR, PROCESSED_DIR): path.mkdir(parents=True, exist_ok=True)
    raw = load_ieee(max_rows=max_rows)
    data = engineer_features(raw)
    split = int(len(data) * 0.80)
    chronological_train, chronological_test = data.iloc[:split], data.iloc[split:]
    random_train, random_test = train_test_split(
        data, test_size=0.20, stratify=data[TARGET], random_state=42
    )
    all_rows, chronological_models = [], {}
    for split_name, train, test in [
        ("chronological_80_20", chronological_train, chronological_test),
        ("stratified_random_80_20", random_train, random_test),
    ]:
        x_train, y_train = train[FEATURES], train[TARGET].astype(int)
        x_test, y_test = test[FEATURES], test[TARGET].astype(int)
        for name, estimator in model_candidates().items():
            pipeline = Pipeline([("preprocess", build_preprocessor()), ("classifier", estimator)])
            row = evaluate(name, pipeline, x_train, y_train, x_test, y_test)
            row["split"] = split_name
            all_rows.append(row)
            if split_name == "chronological_80_20":
                chronological_models[name] = pipeline
                joblib.dump(pipeline, MODEL_DIR / f"{_safe_name(name)}_chronological.joblib", compress=3)
    results = pd.DataFrame(all_rows).sort_values(["split", "pr_auc"], ascending=[True, False]).reset_index(drop=True)
    chronological_results = results[results["split"] == "chronological_80_20"]
    champion = chronological_results.iloc[0]["model"]
    joblib.dump(chronological_models[champion], MODEL_DIR / "champion_model.joblib", compress=3)
    train, test = chronological_train, chronological_test
    y_train, y_test = train[TARGET].astype(int), test[TARGET].astype(int)
    stream_cols = ["TransactionID", TARGET] + FEATURES
    test[stream_cols].head(10000).to_csv(PROCESSED_DIR / "holdout_stream.csv", index=False)
    results.to_csv(REPORT_DIR / "model_comparison.csv", index=False)
    metadata = {
        "dataset": "IEEE-CIS Fraud Detection",
        "source_files": "train_transaction.csv + train_identity.csv",
        "training_rows": len(train), "testing_rows": len(test),
        "fraud_rate_train": round(float(y_train.mean()), 6),
        "fraud_rate_test": round(float(y_test.mean()), 6),
        "split_strategy": "chronological 80/20 (production selection); stratified random 80/20 (comparison)",
        "champion_model": champion, "decision_threshold": 0.70,
        "candidate_models": list(model_candidates()),
        "feature_count": len(FEATURES),
    }
    (MODEL_DIR / "model_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (REPORT_DIR / "model_comparison.json").write_text(results.to_json(orient="records", indent=2), encoding="utf-8")
    write_docx(results, metadata)
    print(results.to_string(index=False))
    print(f"\nChampion: {champion}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rows", type=int, default=None, help="Optional development row limit")
    args = parser.parse_args()
    train_compare(args.max_rows)
