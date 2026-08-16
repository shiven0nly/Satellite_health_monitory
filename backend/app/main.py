"""
backend/app/main.py — FastAPI Anomaly Engine (port 8000)

Endpoints
---------
POST /analyze      Receive telemetry, detect anomalies, forward alerts to receiver
GET  /health       Liveness probe
GET  /stats        In-memory counters
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from typing import List

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .engine import detect
from .llm_service import explain_alert
from .schemas import AnalyzeResponse, TelemetryReading

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

RECEIVER_URL = os.getenv("RECEIVER_URL", "http://localhost:8502/receive_alert")

app = FastAPI(
    title="Satellite Anomaly Engine",
    description="Detects anomalies in satellite telemetry and forwards alerts.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory stats ───────────────────────────────────────────────────────────
_stats: dict = defaultdict(int)
_recent_alerts: deque = deque(maxlen=100)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _forward_alert(alert: AnalyzeResponse) -> None:
    """Fire-and-forget POST to receiver.  Never raises."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(RECEIVER_URL, json=alert.model_dump())
    except Exception as exc:
        logger.warning("Could not forward alert to receiver: %s", exc)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "service": "backend-anomaly-engine"}


@app.get("/stats", tags=["meta"])
async def stats():
    return dict(_stats)


@app.post("/analyze", response_model=AnalyzeResponse, tags=["telemetry"])
async def analyze(reading: TelemetryReading):
    _stats["total_readings"] += 1

    status, severity, anomalies = detect(reading)

    explanation: str | None = None
    if anomalies:
        _stats["anomalies_detected"] += 1
        explanation = explain_alert(
            satellite_id=reading.satellite_id,
            anomalies=anomalies,
            raw_values=reading.model_dump(),
            severity=severity,
        )

    alert = AnalyzeResponse(
        satellite_id=reading.satellite_id,
        timestamp=reading.timestamp,
        severity=severity,
        status=status,
        anomalies=anomalies,
        raw_values=reading.model_dump(),
        explanation=explanation,
    )

    if anomalies:
        _recent_alerts.appendleft(alert.model_dump())
        await _forward_alert(alert)

    logger.info(
        "satellite=%s  severity=%s  anomalies=%s",
        reading.satellite_id,
        severity,
        anomalies,
    )
    return alert
