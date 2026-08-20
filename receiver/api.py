"""
receiver/api.py — Alert Intake API (FastAPI, port 8502)

Endpoints
---------
POST /receive_alert   Accept alert JSON from backend, store in memory
GET  /alerts          Return full alerts list (newest first), optional ?since=<ISO timestamp>
GET  /health          Liveness probe
DELETE /alerts        Clear all alerts
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Satellite Alert Receiver API",
    description="Ingests anomaly alerts from the backend and serves them to the dashboard.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory alert store (newest first)
MAX_ALERTS = 500
alerts: deque[dict[str, Any]] = deque(maxlen=MAX_ALERTS)


class AlertPayload(BaseModel):
    satellite_id: Optional[str] = Field(default="satellite-sim-01")
    timestamp: Optional[str] = None
    severity: Optional[str] = Field(default="warning")
    status: Optional[str] = Field(default="anomaly_detected")
    anomalies: Optional[List[str]] = Field(default_factory=list)
    flags: Optional[List[dict]] = Field(default_factory=list)
    raw_values: Optional[dict] = Field(default_factory=dict)
    explanation: Optional[str] = None
    received_at: Optional[str] = None


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "service": "receiver-api", "alert_count": len(alerts)}


@app.post("/receive_alert", tags=["alerts"])
async def receive_alert(payload: dict[str, Any]):
    """Accept alert JSON from backend, timestamp it, and store in-memory."""
    received_time = datetime.now(timezone.utc).isoformat()
    entry = dict(payload)
    entry["received_at"] = received_time
    if not entry.get("timestamp"):
        entry["timestamp"] = received_time

    alerts.appendleft(entry)
    logger.info(
        "Alert received: satellite=%s severity=%s flags=%d",
        entry.get("satellite_id", "unknown"),
        entry.get("severity", "unknown"),
        len(entry.get("flags", []) or entry.get("anomalies", [])),
    )
    return {"status": "received", "total_alerts": len(alerts)}


@app.get("/alerts", tags=["alerts"])
async def get_alerts(since: Optional[str] = Query(None, description="ISO timestamp filter")):
    """Return stored alerts (most recent first), optionally filtered by ?since=<timestamp>."""
    if not since:
        return list(alerts)

    filtered = []
    for a in alerts:
        ts = a.get("received_at") or a.get("timestamp")
        if ts and ts >= since:
            filtered.append(a)
    return filtered


@app.delete("/alerts", tags=["alerts"])
async def clear_alerts():
    alerts.clear()
    return {"status": "cleared", "total_alerts": 0}