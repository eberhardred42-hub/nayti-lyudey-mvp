import json
import os
import time
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional


def log_event(event: str, level: str = "info", **fields):
    payload: Dict[str, Any] = {
        "event": event,
        "level": level,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = value
    print(json.dumps(payload, ensure_ascii=False))


def send_alert(
    severity: str,
    event: str,
    context: Optional[Dict[str, Any]] = None,
    request_id: str = "unknown",
) -> bool:
    """Send an alert to a configured webhook.

    Uses env `ALERT_WEBHOOK_URL`. If not set, it's a no-op.
    Never logs the webhook URL.
    """
    webhook_url = (os.environ.get("ALERT_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        return False

    payload = {
        "severity": severity,
        "event": event,
        "request_id": request_id,
        "ts": datetime.utcnow().isoformat() + "Z",
        "context": context or {},
    }

    start = time.perf_counter()
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            status = getattr(resp, "status", None)
            log_event(
                "alert_sent",
                request_id=request_id,
                alert_event=event,
                severity=severity,
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            return True
    except Exception as e:
        log_event(
            "alert_send_error",
            level="error",
            request_id=request_id,
            alert_event=event,
            severity=severity,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            error=str(e),
        )
        return False
