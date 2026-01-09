import hashlib
import json
from typing import Any, Dict, Optional


def text_fingerprint(text: str, limit: int = 1000) -> Dict[str, Any]:
    """Return safe preview + metadata for storing user/LLM text.

    Never returns the full text; only preview + length + sha256.
    """
    s = text if isinstance(text, str) else str(text)
    full_length = len(s)
    preview = s[: max(0, int(limit or 0))]
    return {
        "preview": preview,
        "full_length": full_length,
        "sha256": hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest(),
        "truncated": full_length > len(preview),
        "preview_length": len(preview),
    }


def json_fingerprint(obj: Any, limit: int = 1200) -> Dict[str, Any]:
    """Serialize obj to JSON and return safe preview+hash metadata."""
    try:
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except Exception:
        raw = str(obj)
    return text_fingerprint(raw, limit=limit)


def trace_artifact(
    *,
    session_id: Optional[str],
    kind: str,
    request_id: str,
    payload_json: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort persist a trace event as an artifact.

    Uses existing artifacts table via db.create_artifact, and swallows all errors.
    """
    try:
        from db import create_artifact  # local import to avoid cycles

        create_artifact(
            session_id=session_id,
            kind=kind,
            format="json",
            payload_json=payload_json or {},
            meta=meta or {},
            request_id=request_id,
        )
    except Exception:
        return
