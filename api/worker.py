import json
import os
import time
import uuid
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional

import redis

from alerts import send_alert
from db import init_db
from db import (
    create_artifact,
    create_artifact_file,
    get_render_job,
    increment_render_job_attempt,
    mark_render_job_failed,
    mark_render_job_ready,
    try_mark_render_job_rendering,
)
from storage.s3_client import upload_bytes


def log_event(event: str, level: str = "info", **fields: Any) -> None:
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


def _redis_client() -> redis.Redis:
    url = (os.environ.get("REDIS_URL") or "").strip() or "redis://localhost:6379/0"
    return redis.Redis.from_url(url, decode_responses=True)


QUEUE_NAME = (os.environ.get("RENDER_QUEUE") or "render_jobs").strip() or "render_jobs"
RENDER_URL = (os.environ.get("RENDER_URL") or "").strip() or "http://localhost:8002"
RENDER_TIMEOUT_SEC = float((os.environ.get("RENDER_TIMEOUT_SEC") or "120").strip() or "120")
S3_BUCKET = (os.environ.get("S3_BUCKET") or "").strip()


def _http_post_json(url: str, payload: Dict[str, Any], timeout_sec: float) -> bytes:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        status = getattr(resp, "status", None)
        body = resp.read()
        if status != 200:
            raise RuntimeError(f"render_http_{status}")
        return body


def _backoff_seconds(attempts: int) -> float:
    # attempts is already incremented in DB; start with 1s.
    base = 2 ** max(0, attempts - 1)
    return float(min(60, max(1, base)))


def process_message(msg: str) -> None:
    request_id = str(uuid.uuid4())
    try:
        payload = json.loads(msg)
    except Exception:
        log_event("render_error", level="error", request_id=request_id, error="invalid_queue_payload")
        return

    job_id = str(payload.get("job_id") or "").strip()
    doc_id = str(payload.get("doc_id") or "").strip() or None
    render_request = payload.get("render_request")

    if not job_id or not isinstance(render_request, dict):
        log_event(
            "render_error",
            level="error",
            request_id=request_id,
            render_job_id=job_id or None,
            doc_id=doc_id,
            error="missing_job_id_or_render_request",
        )
        return

    job = get_render_job(job_id, request_id=request_id)
    if not job:
        log_event(
            "render_error",
            level="error",
            request_id=request_id,
            render_job_id=job_id,
            doc_id=doc_id,
            error="job_not_found",
        )
        return

    if not try_mark_render_job_rendering(job_id, request_id=request_id):
        # Another worker has it, or it's not queued anymore.
        return

    session_id = str(job.get("session_id"))
    pack_id = str(job.get("pack_id"))

    log_event(
        "render_start",
        request_id=request_id,
        render_job_id=job_id,
        doc_id=doc_id,
    )

    try:
        pdf_bytes = _http_post_json(
            f"{RENDER_URL.rstrip('/')}/render",
            render_request,
            timeout_sec=RENDER_TIMEOUT_SEC,
        )

        if not pdf_bytes.startswith(b"%PDF"):
            raise RuntimeError("render_invalid_pdf")

        if not S3_BUCKET:
            raise RuntimeError("S3_BUCKET_not_configured")

        object_key = f"renders/{job_id}/{(doc_id or 'doc')}.pdf"
        up = upload_bytes(
            bucket=S3_BUCKET,
            key=object_key,
            data=pdf_bytes,
            content_type="application/pdf",
            request_id=request_id,
        )

        artifact = create_artifact(
            session_id=session_id,
            kind=f"{(doc_id or 'doc')}_pdf",
            format="pdf",
            payload_json=None,
            meta={
                "doc_id": doc_id,
                "pack_id": pack_id,
                "render_job_id": job_id,
            },
            request_id=request_id,
        )
        artifact_id = artifact.get("id")
        if not artifact_id:
            raise RuntimeError("artifact_create_failed")

        create_artifact_file(
            artifact_id=str(artifact_id),
            bucket=S3_BUCKET,
            object_key=object_key,
            content_type="application/pdf",
            size_bytes=up.get("size_bytes"),
            etag=up.get("etag"),
            meta={},
            request_id=request_id,
        )

        mark_render_job_ready(job_id, request_id=request_id)
        log_event(
            "render_ok",
            request_id=request_id,
            render_job_id=job_id,
            doc_id=doc_id,
            bytes_size=len(pdf_bytes),
            bucket=S3_BUCKET,
            object_key=object_key,
        )

    except Exception as e:
        err = str(e)
        updated = increment_render_job_attempt(job_id, last_error=err, request_id=request_id)
        attempts = int(updated.get("attempts") or 0)
        max_attempts = int(updated.get("max_attempts") or 0)

        retryable = True
        if err.startswith("render_http_"):
            try:
                code = int(err.split("_")[-1])
            except Exception:
                code = 500
            if 400 <= code < 500:
                retryable = False

        if (not retryable) or (attempts >= max_attempts):
            mark_render_job_failed(job_id, last_error=err, request_id=request_id)
            log_event(
                "render_error",
                level="error",
                request_id=request_id,
                render_job_id=job_id,
                doc_id=doc_id,
                attempts=attempts,
                max_attempts=max_attempts,
                error=err,
            )
            send_alert(
                severity="error",
                event="render_job_failed",
                request_id=request_id,
                context={
                    "render_job_id": job_id,
                    "doc_id": doc_id,
                    "attempts": attempts,
                    "max_attempts": max_attempts,
                    "error": err,
                },
            )
            return

        delay = _backoff_seconds(attempts)
        log_event(
            "render_retry_scheduled",
            request_id=request_id,
            render_job_id=job_id,
            doc_id=doc_id,
            attempts=attempts,
            max_attempts=max_attempts,
            delay_sec=delay,
            error=err,
        )
        time.sleep(delay)
        _redis_client().rpush(QUEUE_NAME, msg)


def main() -> None:
    init_db()
    r = _redis_client()
    log_event("worker_start", queue=QUEUE_NAME, render_url=RENDER_URL)

    while True:
        item = r.blpop(QUEUE_NAME, timeout=5)
        if not item:
            continue
        _, msg = item
        process_message(msg)


if __name__ == "__main__":
    main()
