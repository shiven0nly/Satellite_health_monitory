"""
backend/app/llm_service.py — Groq-powered alert explanation
============================================================

Provides a single public function:

    explain_alert(flags: list[dict]) -> str

The function always returns a non-empty string.  If Groq is unavailable
(missing key, network error, import failure) it falls back to a deterministic
plain-text summary built directly from the flag data — so downstream callers
never have to handle None or catch exceptions.

The LLM layer is the ONLY place where any "AI" framing is used.
The upstream anomaly detection (engine.py) is rule + trend logic only.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Optional Groq import ──────────────────────────────────────────────────────
try:
    from groq import Groq  # type: ignore
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False
    logger.info("groq package not installed — LLM explanations will use built-in fallback.")

_client: "Groq | None" = None


def _get_client() -> "Groq | None":
    """Lazily initialise the Groq client; returns None if unavailable."""
    global _client
    if _client is not None:
        return _client
    if not _GROQ_AVAILABLE:
        return None
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        logger.debug("GROQ_API_KEY not set — LLM explanation disabled.")
        return None
    _client = Groq(api_key=api_key)
    return _client


# ── System persona ────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are CASSANDRA — a satellite health monitoring assistant.
Your job is to translate raw anomaly flag data into a concise operator brief.

Rules:
- Respond in exactly 3 sentences or fewer.
- Sentence 1: state the most critical anomaly and its severity.
- Sentence 2: state the likely cause category (power, thermal, navigation, attitude, or comms).
- Sentence 3: recommend ONE immediate action the operator should take.
- Use precise engineering language; do not be vague.
- Do not say "I" or refer to yourself.
- Do not mention Groq, LLMs, or AI.
"""


# ── Deterministic fallback ────────────────────────────────────────────────────

def _template_explanation(flags: list[dict[str, Any]]) -> str:
    """
    Build a plain-English summary without Groq.

    Called when the Groq client is unavailable or the API call fails.
    Always returns a non-empty string.
    """
    if not flags:
        return "All subsystems nominal — no anomalies detected."

    # Split into breach vs trend
    breaches = [f for f in flags if f.get("type") == "threshold_breach"]
    trends   = [f for f in flags if f.get("type") == "trending_toward_failure"]

    parts: list[str] = []

    if breaches:
        worst = breaches[0]          # list is already ordered by engine output
        parts.append(
            f"CRITICAL — {worst['channel']} has breached its operational limit "
            f"(value={worst['value']}, limit={worst['limit']})."
        )
        if len(breaches) > 1:
            others = ", ".join(b["channel"] for b in breaches[1:])
            parts.append(f"Additional breaches: {others}.")

    if trends:
        t = trends[0]
        steps = t.get("projected_breach_in_steps", "?")
        parts.append(
            f"WARNING — {t['channel']} is trending toward its limit "
            f"and may breach within ~{steps} telemetry steps."
        )

    parts.append("Recommend immediate review of affected subsystems and consider safe-mode activation.")
    return " ".join(parts)


# ── Public API ────────────────────────────────────────────────────────────────

def explain_alert(flags: list[dict[str, Any]]) -> str:
    """
    Generate a human-readable explanation for a list of anomaly flags.

    Parameters
    ----------
    flags : list[dict]
        Engine flag dicts as returned by ``check_telemetry()``.
        Each dict has at minimum: ``channel``, ``type``, ``value``, ``severity``.
        Threshold breach adds ``limit``; trend adds ``projected_breach_in_steps``.

    Returns
    -------
    str
        Always a non-empty string.  Either a Groq-generated operator brief
        or a deterministic template-based fallback — never raises, never
        returns None or empty string.

    Fallback chain
    --------------
    1. Groq API call succeeds → return LLM response.
    2. Groq unavailable (no key / import error / network) → template fallback.
    3. Groq call raises any exception → log warning + template fallback.
    """
    if not flags:
        return "All subsystems nominal — no anomalies detected."

    client = _get_client()
    if client is None:
        return _template_explanation(flags)

    # ── Build the user message from structured flag data ──────────────────
    flag_lines: list[str] = []
    for f in flags:
        if f.get("type") == "threshold_breach":
            flag_lines.append(
                f"  • {f['channel']}: THRESHOLD BREACH  "
                f"value={f['value']}  limit={f['limit']}  severity={f['severity']}"
            )
        else:
            steps = f.get("projected_breach_in_steps", "?")
            flag_lines.append(
                f"  • {f['channel']}: TRENDING TOWARD FAILURE  "
                f"value={f['value']}  projected_breach_in={steps}_steps  severity={f['severity']}"
            )

    overall_severity = (
        "CRITICAL" if any(f.get("severity") == "critical" for f in flags) else "WARNING"
    )

    user_msg = (
        f"Overall severity: {overall_severity}\n"
        f"Anomaly flags ({len(flags)} total):\n"
        + "\n".join(flag_lines)
    )

    # ── Groq API call ─────────────────────────────────────────────────────
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=150,
            temperature=0.25,
        )
        result = response.choices[0].message.content.strip()
        if result:
            return result
        # Empty response — fall through to template
        logger.warning("Groq returned empty content; using template fallback.")
    except Exception as exc:
        logger.warning("Groq API call failed (%s); using template fallback.", exc)

    return _template_explanation(flags)
