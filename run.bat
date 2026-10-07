@echo off
title RiskPulse AI - IEEE-CIS
cd /d "%~dp0"
if not exist ".venv" python -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist "models\champion_model.joblib" (
  echo Model not found. Place IEEE-CIS CSV files in data\raw and run train_models.bat first.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8000
python -m uvicorn app:app --host 127.0.0.1 --port 8000

