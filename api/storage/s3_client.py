import json
import os
import time
from urllib.parse import urlparse
from datetime import datetime
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config

from alerts import send_alert


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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_endpoint(raw: Optional[str], *, default_scheme: str) -> Optional[str]:
    if raw is None:
        return None
    v = raw.strip()
    if not v:
        return None
    if "://" not in v:
        return f"{default_scheme}://{v}"
    return v


def _host_from_endpoint(endpoint: Optional[str]) -> Optional[str]:
    if not endpoint:
        return None
    try:
        u = urlparse(endpoint)
        return (u.netloc or "").strip() or None
    except Exception:
        return None


def _s3_settings() -> Dict[str, Any]:
    endpoint = _normalize_endpoint(os.environ.get("S3_ENDPOINT"), default_scheme="http")
    presign_endpoint = _normalize_endpoint(os.environ.get("S3_PRESIGN_ENDPOINT"), default_scheme="https")
    region = (os.environ.get("S3_REGION") or "us-east-1").strip()
    access_key = (os.environ.get("S3_ACCESS_KEY") or "").strip() or None
    secret_key = (os.environ.get("S3_SECRET_KEY") or "").strip() or None

    use_ssl_env = os.environ.get("S3_USE_SSL")
    if use_ssl_env is None:
        use_ssl = None
    else:
        use_ssl = use_ssl_env.strip().lower() in {"1", "true", "yes", "y", "on"}

    if use_ssl is None and endpoint:
        use_ssl = endpoint.lower().startswith("https://")
    if use_ssl is None:
        use_ssl = True

    return {
        "endpoint": endpoint,
        "presign_endpoint": presign_endpoint,
        "region": region,
        "access_key": access_key,
        "secret_key": secret_key,
        "use_ssl": use_ssl,
    }


_client_cache: Dict[str, Any] = {}


def _client(endpoint_override: Optional[str] = None):
    s = _s3_settings()

    endpoint = endpoint_override if endpoint_override is not None else s["endpoint"]
    cache_key = endpoint or "<none>"
    cached = _client_cache.get(cache_key)
    if cached is not None:
        return cached

    # When overriding endpoint (e.g. for presign URLs), compute use_ssl from
    # that endpoint if possible; otherwise fall back to S3_USE_SSL logic.
    if endpoint and endpoint.lower().startswith("https://"):
        use_ssl = True
    elif endpoint and endpoint.lower().startswith("http://"):
        use_ssl = False
    else:
        use_ssl = bool(s["use_ssl"])

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=s["region"],
        aws_access_key_id=s["access_key"],
        aws_secret_access_key=s["secret_key"],
        use_ssl=use_ssl,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    _client_cache[cache_key] = client
    return client


def upload_bytes(
    bucket: str,
    key: str,
    data: bytes,
    content_type: str,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    """Upload bytes to S3-compatible storage."""
    start = time.perf_counter()
    size_bytes = len(data)

    log_event(
        "s3_upload_start",
        request_id=request_id,
        bucket=bucket,
        object_key=key,
        size_bytes=size_bytes,
        content_type=content_type,
    )

    try:
        resp = _client().put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        etag = resp.get("ETag")
        log_event(
            "s3_upload_ok",
            request_id=request_id,
            bucket=bucket,
            object_key=key,
            size_bytes=size_bytes,
            etag=etag,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return {"etag": etag, "size_bytes": size_bytes}
    except Exception as e:
        log_event(
            "s3_upload_error",
            level="error",
            request_id=request_id,
            bucket=bucket,
            object_key=key,
            size_bytes=size_bytes,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            error=str(e),
        )
        send_alert(
            severity="error",
            event="s3_upload_error",
            request_id=request_id,
            context={
                "bucket": bucket,
                "object_key": key,
                "size_bytes": size_bytes,
                "error": str(e),
            },
        )
        raise


def presign_get(
    bucket: str,
    key: str,
    expires_sec: int = 600,
    request_id: str = "unknown",
) -> str:
    """Generate presigned GET url.

    IMPORTANT: Do not log the presigned URL.
    """
    start = time.perf_counter()
    try:
        s = _s3_settings()
        endpoint_for_url = s.get("presign_endpoint") or s.get("endpoint")
        url = _client(endpoint_override=endpoint_for_url).generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_sec,
        )
        log_event(
            "s3_presign_ok",
            request_id=request_id,
            bucket=bucket,
            object_key=key,
            expires_sec=expires_sec,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return url
    except Exception as e:
        log_event(
            "s3_presign_error",
            level="error",
            request_id=request_id,
            bucket=bucket,
            object_key=key,
            expires_sec=expires_sec,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            error=str(e),
        )
        send_alert(
            severity="error",
            event="s3_presign_error",
            request_id=request_id,
            context={
                "bucket": bucket,
                "object_key": key,
                "expires_sec": expires_sec,
                "error": str(e),
            },
        )
        raise


def health_s3_env() -> Dict[str, Any]:
    """Env-only health payload for S3 (no network requests)."""
    provider = (os.environ.get("S3_PROVIDER") or "s3").strip().lower()
    bucket = (os.environ.get("S3_BUCKET") or "").strip() or None
    s = _s3_settings()
    endpoint = s.get("endpoint")
    presign_endpoint = s.get("presign_endpoint")

    has_credentials = bool(s.get("access_key")) and bool(s.get("secret_key"))

    ok = bool(bucket) and bool(endpoint) and provider == "s3"

    return {
        "ok": ok,
        "provider": "s3",
        "endpoint": endpoint,
        "s3_endpoint_host": _host_from_endpoint(endpoint),
        "s3_presign_host": _host_from_endpoint(presign_endpoint),
        "bucket": bucket,
        "has_credentials": has_credentials,
    }


def head_bucket_if_debug(bucket: str) -> Optional[bool]:
    """Optional lightweight check used only in DEBUG mode."""
    if not _env_bool("DEBUG", False):
        return None
    try:
        _client().head_bucket(Bucket=bucket)
        return True
    except Exception:
        return False
