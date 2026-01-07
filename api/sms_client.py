import base64
import json
import os
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass
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


def _sms_provider() -> str:
    return (os.environ.get("SMS_PROVIDER") or "mock").strip().lower() or "mock"


def _mask_phone(phone: str) -> str:
    p = (phone or "").strip()
    if len(p) <= 4:
        return "***"
    return "***" + p[-4:]


@dataclass
class SmsSendError(Exception):
    code: str
    retriable: bool = False
    http_status: Optional[int] = None


def health_sms_env() -> Dict[str, Any]:
    provider = _sms_provider()
    if provider == "smsaero":
        email = (os.environ.get("SMSAERO_EMAIL") or "").strip()
        api_key = (os.environ.get("SMSAERO_API_KEY") or "").strip()
        has_key = bool(email) and bool(api_key)
        return {"ok": has_key, "provider": provider, "has_key": has_key, "mode": "smsaero"}
    # default/mock
    return {"ok": True, "provider": provider, "has_key": False, "mode": "mock"}


def send_otp_sms(phone: str, code: str, request_id: str = "unknown") -> None:
    """Send OTP via configured SMS provider.

    IMPORTANT: Never log OTP, API key, or email.
    """
    provider = _sms_provider()
    if provider == "mock":
        return
    if provider != "smsaero":
        raise SmsSendError(code="SMS_PROVIDER_UNSUPPORTED", retriable=False)

    email = (os.environ.get("SMSAERO_EMAIL") or "").strip()
    api_key = (os.environ.get("SMSAERO_API_KEY") or "").strip()
    sender = (os.environ.get("SMS_SENDER") or "").strip() or None

    if not email or not api_key:
        raise SmsSendError(code="SMS_CONFIG_MISSING", retriable=False)

    text = f"Код входа: {code}"

    # SMSAero API: basic auth email:api_key
    auth_raw = f"{email}:{api_key}".encode("utf-8")
    auth = base64.b64encode(auth_raw).decode("ascii")

    url = "https://gate.smsaero.ru/v2/sms/send"
    params = {
        "number": phone,
        "text": text,
    }
    if sender:
        params["sign"] = sender

    # minimal retries
    max_attempts = 3
    timeout_sec = 5

    for attempt in range(1, max_attempts + 1):
        start = time.perf_counter()
        log_event(
            "sms_send_start",
            request_id=request_id,
            provider=provider,
            phone=_mask_phone(phone),
            attempt=attempt,
        )
        try:
            data = urllib.parse.urlencode(params).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {auth}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                status = getattr(resp, "status", None)
                body = resp.read() or b""

            ok = False
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
                ok = bool(payload.get("success") is True)
            except Exception:
                payload = {}

            if status == 200 and ok:
                log_event(
                    "sms_send_ok",
                    request_id=request_id,
                    provider=provider,
                    phone=_mask_phone(phone),
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                )
                return

            # non-success response
            err_code = "SMS_SEND_FAILED"
            log_event(
                "sms_send_error",
                level="error",
                request_id=request_id,
                provider=provider,
                phone=_mask_phone(phone),
                attempt=attempt,
                http_status=status,
                error=err_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            # retry on transient errors
            retriable = status in {None, 429, 500, 502, 503, 504}
            if not retriable or attempt == max_attempts:
                raise SmsSendError(code=err_code, retriable=retriable, http_status=status)

        except SmsSendError:
            raise
        except Exception as e:
            log_event(
                "sms_send_error",
                level="error",
                request_id=request_id,
                provider=provider,
                phone=_mask_phone(phone),
                attempt=attempt,
                error="SMS_SEND_EXCEPTION",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            if attempt == max_attempts:
                raise SmsSendError(code="SMS_SEND_EXCEPTION", retriable=True) from e

        time.sleep(0.5 * attempt)
