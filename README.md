# Satellite Health Monitor

A reproducible multi-service monorepo that simulates satellite telemetry, detects anomalies, and displays live alerts — all in-memory, no database required.

## Architecture

```
┌────────────────────┐  POST /analyze    ┌──────────────────────┐
│  sender/           │ ──────────────►   │  backend/            │
│  Streamlit :8501   │                   │  FastAPI :8000       │
│  Telemetry Sim     │                   │  Anomaly Engine      │
└────────────────────┘                   └──────────┬───────────┘
                                                     │ POST /receive_alert
                                                     ▼
                                         ┌──────────────────────┐
                                         │  receiver/           │
                                         │  FastAPI API :8502   │◄── stores alerts
                                         │  Streamlit   :8503   │──► polls :8502
                                         └──────────────────────┘
```

## Quickstart (Windows)

```bat
run_all.bat
```

This opens 4 terminal windows, one per process. Then visit:

| Service | URL |
|---|---|
| 🛰️ Sender (telemetry sim) | http://localhost:8501 |
| ⚙️ Backend API docs | http://localhost:8000/docs |
| 📥 Receiver API docs | http://localhost:8502/docs |
| 🚨 Alert Dashboard | http://localhost:8503 |

## Manual Start (each in its own terminal)

```powershell
# Terminal 1 — Receiver API (start first!)
cd receiver
uv run uvicorn api:app --port 8502 --reload

# Terminal 2 — Alert Dashboard
cd receiver
uv run streamlit run dashboard.py --server.port 8503

# Terminal 3 — Backend Anomaly Engine
cd backend
uv run uvicorn app.main:app --port 8000 --reload

# Terminal 4 — Sender Telemetry Simulator
cd sender
uv run streamlit run app.py --server.port 8501
```

## Groq LLM Explanations (optional)

Copy `.env.example` to `backend/.env` and set `GROQ_API_KEY`:

```
GROQ_API_KEY=gsk_...
```

The backend will automatically generate plain-English explanations for each anomaly alert. If the key is absent, everything still works — alerts just won't have an `explanation` field.

## Service Dependency Graph

```
sender → backend → receiver/api ← receiver/dashboard
```

- **Sender** → backend `/analyze`
- **Backend** → receiver `/receive_alert` (fire-and-forget; won't crash if receiver is down)
- **Dashboard** → receiver `/alerts` (poll every N seconds)

## Project Structure

```
satellite-health-monitor/
├── sender/
│   ├── pyproject.toml
│   └── app.py                  ← Streamlit telemetry simulator
├── backend/
│   ├── pyproject.toml
│   └── app/
│       ├── main.py             ← FastAPI entry point
│       ├── engine.py           ← Threshold + trend anomaly detection
│       ├── llm_service.py      ← Groq alert explanation (optional)
│       └── schemas.py          ← Pydantic v2 models
├── receiver/
│   ├── pyproject.toml
│   ├── api.py                  ← FastAPI alert intake (:8502)
│   └── dashboard.py            ← Streamlit live dashboard (:8503)
├── .env.example
├── run_all.bat
└── README.md
```

## Design Notes

- **No database**: all alerts stored in a `deque(maxlen=500)` in the receiver API process. Resets on restart — intentional for this demo.
- **No message queue**: plain HTTP POST from backend → receiver is sufficient at simulation scale.
- **Anomaly engine** uses two layers:
  1. *Threshold checks* — instantaneous out-of-band values (configurable in `engine.py`)
  2. *Trend detection* — rolling linear regression slope on battery, temperature and solar panel voltage
- **Groq LLM** (CASSANDRA persona) generates ≤3-sentence operator briefs per anomaly.
