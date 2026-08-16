"""
receiver/api.py — Alert Intake API (FastAPI, port 8502)

Endpoints
---------
POST /receive_alert   Accept an AnomalyAlert from the backend (port 8000)
GET  /alerts          Return all stored alerts (newest first)
GET  /alerts/stats    Severity counts
GET  /health          Liveness probe
DELETE /alerts        Clear all alerts (useful during demos)
"""
from __future__ import annotations

import logging
from collections import deque
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Satellite Alert Receiver",
    description="Ingests anomaly alerts from the backend and exposes them for the dashboard.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store (resets on restart — intentional for demo) ────────────────
MAX_ALERTS = 500
_alerts: deque = deque(maxlen=MAX_ALERTS)


# ── Schemas ───────────────────────────────────────────────────────────────────

class AlertPayload(BaseModel):
    satellite_id: str
    timestamp: str
    severity: str
    status: str
    anomalies: List[str]
    raw_values: dict
    explanation: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "service": "receiver-api", "alert_count": len(_alerts)}


@app.post("/receive_alert", status_code=202, tags=["alerts"])
async def receive_alert(alert: AlertPayload):
    _alerts.appendleft(alert.model_dump())
    logger.info(
        "Alert received: satellite=%s  severity=%s  anomalies=%s",
        alert.satellite_id,
        alert.severity,
        alert.anomalies,
    )
    return {"accepted": True, "total_stored": len(_alerts)}


@app.get("/alerts", response_model=List[AlertPayload], tags=["alerts"])
async def get_alerts(limit: int = 100):
    return list(_alerts)[:limit]


@app.get("/alerts/stats", tags=["alerts"])
async def alert_stats():
    counts: dict[str, int] = {"normal": 0, "warning": 0, "critical": 0}
    for a in _alerts:
        counts[a.get("severity", "normal")] = counts.get(a.get("severity", "normal"), 0) + 1
    return {"total": len(_alerts), "severity_counts": counts}


@app.delete("/alerts", tags=["alerts"])
async def clear_alerts():
    _alerts.clear()
    return {"cleared": True}
