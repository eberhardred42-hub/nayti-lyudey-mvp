import json
import time
import os
import secrets
import random
import hashlib
import hmac
import urllib.request
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uuid
import redis
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from alerts import send_alert
from db import init_db, health_check, create_session as db_create_session
from db import get_session, update_session, add_message, get_session_messages
from db import set_session_user, create_artifact, create_artifact_file, get_file_download_info_for_user
from db import list_user_files, list_user_intro_documents
from db import (
    activate_document_template,
    create_document_record,
    create_document_template_version,
    find_document_for_idempotency,
    find_latest_document_by_identity,
    get_active_document_template,
    get_document_for_user,
    get_document_template_by_id,
    list_document_templates,
    list_documents_for_user,
    update_document_record,
)
from db import (
    create_pack,
    create_render_job,
    get_latest_file_id_for_render_job,
    get_pack,
    get_render_job,
    list_latest_render_jobs_for_pack,
    list_packs_admin,
    list_packs_for_user,
)
from db import (
    get_file_download_info,
    has_active_render_job,
    list_artifacts_for_render_job,
    list_failed_render_jobs,
    list_render_jobs_admin,
)
from db import (
    ensure_user,
    get_user_by_id,
    create_admin_session,
    get_admin_session_by_token_hash,
    revoke_admin_session,
    create_admin_audit_log,
    list_admin_audit_log,
)
from db import (
    ack_alert_event,
    list_alert_events,
    list_artifacts_admin,
    get_artifact_by_id,
)
from db import (
    create_config_version,
    get_active_config_store,
    get_config_version,
    get_latest_inactive_version,
    get_previous_valid_version,
    list_config_versions,
    publish_config_version,
    set_config_validation,
    update_config_payload,
)
from db import (
    get_document_access_map,
    get_document_metadata_map,
    get_artifact_by_session_kind,
    upsert_document_access,
    upsert_document_metadata,
)
from llm_client import (
    current_llm_provider,
    generate_questions_and_quick_replies,
    generate_json_messages,
    generate_json_messages_observable,
    health_llm,
    LLMUnavailable,
)
from trace import text_fingerprint, trace_artifact
from storage.s3_client import health_s3_env, head_bucket_if_debug
from storage.s3_client import upload_bytes, presign_get, stream_get

app = FastAPI()
SESSIONS = {}


# ==========================================================================
# Config resolver (file/db) with 30s cache + fallback + alert
# ==========================================================================


CONFIG_SOURCE = (os.environ.get("CONFIG_SOURCE") or "file").strip().lower() or "file"
CONFIG_CACHE_TTL_SEC = 30.0

# key -> {expires_at: float, payload: object, meta: dict}
_CONFIG_CACHE: dict[str, dict] = {}


def _config_cache_get(key: str) -> tuple[object | None, dict | None]:
    rec = _CONFIG_CACHE.get(key)
    if not rec:
        return None, None
    try:
        if time.time() >= float(rec.get("expires_at") or 0):
            return None, None
    except Exception:
        return None, None
    return rec.get("payload"), (rec.get("meta") or {})


def _config_cache_set(key: str, payload: object, meta: dict) -> None:
    _CONFIG_CACHE[key] = {
        "expires_at": time.time() + CONFIG_CACHE_TTL_SEC,
        "payload": payload,
        "meta": meta,
    }


def _stable_hash(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


SUPPORTED_CONFIG_KEYS = ["documents_registry", "blueprint", "resources"]


def _load_file_config(key: str) -> object:
    # file sources are minimal for now; documents_registry is backed by api/documents.v1.json
    if key == "documents_registry":
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "documents.v1.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Other keys have no file backing yet.
    return {}


def resolve_config(key: str, request_id: str) -> tuple[object, dict]:
    cached_payload, cached_meta = _config_cache_get(key)
    if cached_payload is not None and cached_meta is not None:
        return cached_payload, cached_meta

    # Default: file
    if CONFIG_SOURCE != "db":
        payload = _load_file_config(key)
        meta = {"source": "file", "version": 0, "hash": _stable_hash(payload)}
        _config_cache_set(key, payload, meta)
        return payload, meta

    # DB source: use active valid config, else fallback
    try:
        row = get_active_config_store(key, request_id=request_id)
    except Exception as e:
        row = None
        log_event(
            "config_db_error",
            level="error",
            request_id=request_id,
            key=key,
            error=str(e),
        )

    if row and str(row.get("validation_status") or "").lower() == "valid":
        payload = row.get("payload_json")
        meta = {
            "source": "db",
            "version": int(row.get("version") or 0),
            "hash": _stable_hash(payload),
        }
        _config_cache_set(key, payload, meta)
        return payload, meta

    # Fallback
    payload = _load_file_config(key)
    reason = "missing_active" if not row else f"status_{row.get('validation_status')}"
    log_event(
        "bad_config_fallback",
        level="warning",
        request_id=request_id,
        key=key,
        reason=reason,
    )
    try:
        send_alert(
            severity="warning",
            event="bad_config_fallback",
            request_id=request_id,
            context={"key": key, "reason": reason},
        )
    except Exception:
        pass
    meta = {"source": "file", "version": 0, "hash": _stable_hash(payload), "fallback": True, "reason": reason}
    _config_cache_set(key, payload, meta)
    return payload, meta


# ==========================================================================
# Admin auth: phone allowlist + password hash + 12h DB-backed admin sessions
# ==========================================================================


def _admin_phone_allowlist() -> set[str]:
    raw = (os.environ.get("ADMIN_PHONE_ALLOWLIST") or "").strip()
    if not raw:
        return set()
    out: set[str] = set()
    for part in raw.split(","):
        v = part.strip()
        if v:
            try:
                out.add(_normalize_phone_e164(v))
            except HTTPException:
                continue
    return out


def _admin_password_hash_hex() -> str | None:
    v = (os.environ.get("ADMIN_PASSWORD_HASH") or "").strip().lower()
    return v or None


def _admin_password_salt() -> str | None:
    v = (os.environ.get("ADMIN_PASSWORD_SALT") or "").strip()
    return v or None


def _admin_session_ttl_hours() -> int:
    raw = (os.environ.get("ADMIN_SESSION_TTL_HOURS") or "").strip()
    try:
        v = int(raw)
        return v if v > 0 else 12
    except Exception:
        return 12


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if not s:
        return default
    return s in {"1", "true", "yes", "y", "on"}


def _pbkdf2_hex(value: str, salt: str, iterations: int = 100_000) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return dk.hex()


def _mask_phone(phone_e164: str | None) -> str:
    if not phone_e164:
        return "unknown"
    s = phone_e164.strip()
    if len(s) <= 4:
        return "****"
    return f"{s[:2]}****{s[-2:]}"


def _normalize_phone_e164(raw: str) -> str:
    s = (raw or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        raise HTTPException(status_code=400, detail="phone is required")
    # Common RU formats:
    # - 8XXXXXXXXXX (11 digits) -> +7XXXXXXXXXX
    # - 7XXXXXXXXXX (11 digits) -> +7XXXXXXXXXX
    # - XXXXXXXXXX  (10 digits) -> +7XXXXXXXXXX
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        raise HTTPException(status_code=400, detail="invalid phone")
    return "+" + digits


def _verify_admin_password(admin_password: str) -> bool:
    stored = _admin_password_hash_hex()
    salt = _admin_password_salt()
    if not stored or not salt:
        return False
    computed = _pbkdf2_hex(admin_password, salt)
    return hmac.compare_digest(computed, stored)


def _record_admin_event(
    event_type: str,
    request: Request,
    admin_user_id: str | None,
    request_id: str,
) -> None:
    try:
        ip = getattr(getattr(request, "client", None), "host", None)
        ua = request.headers.get("User-Agent")
        payload = {
            "event_type": event_type,
            "admin_user_id": admin_user_id,
            "request_id": request_id,
            "meta": {"ip": ip, "ua": ua},
        }
        create_artifact(
            session_id=None,
            kind="admin_event",
            format="json",
            payload_json=payload,
            meta=None,
            request_id=request_id,
        )
    except Exception:
        # best-effort
        pass


def _stable_obj_hash(obj: object | None) -> str | None:
    if obj is None:
        return None
    try:
        raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except Exception:
        return None


def record_admin_audit(
    request: Request,
    admin_user_id: str,
    admin_session_id: str,
    action: str,
    target_type: str,
    target_id: str | None,
    before_obj: object | None = None,
    after_obj: object | None = None,
    summary: str | None = None,
):
    request_id = get_request_id_from_request(request)
    ip = getattr(getattr(request, "client", None), "host", None)
    ua = request.headers.get("User-Agent")

    before_hash = _stable_obj_hash(before_obj)
    after_hash = _stable_obj_hash(after_obj)

    # DB row (contains ip/ua by requirement)
    create_admin_audit_log(
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_hash=before_hash,
        after_hash=after_hash,
        summary=summary,
        request_id=request_id,
        ip=ip,
        user_agent=ua,
        request_id_log=request_id,
    )

    # Artifact (no PII/tokens)
    try:
        create_artifact(
            session_id=None,
            kind="admin_event",
            format="json",
            payload_json={
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "request_id": request_id,
            },
            meta=None,
            request_id=request_id,
        )
    except Exception:
        pass


def _require_bearer_user(request: Request) -> dict:
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Support mock token for local manual tests.
    # Format: Bearer mockphone:+79991234567
    if token.startswith("mockphone:") and len(token) > 10:
        phone = token.split(":", 1)[1].strip()
        if not phone:
            raise HTTPException(status_code=401, detail="Unauthorized")
        phone_e164 = _normalize_phone_e164(phone)
        user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "nly:phone:" + phone_e164))
        return {"user_id": user_id, "phone_e164": phone_e164}

    rec = TOKENS.get(token)
    if not rec:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return rec


def _require_admin(request: Request) -> dict:
    request_id = get_request_id_from_request(request)
    token_plain = (request.headers.get("X-Admin-Token") or "").strip()
    if not token_plain:
        raise HTTPException(status_code=401, detail="missing_admin_token")
    salt = _admin_password_salt() or ""
    if not salt:
        raise HTTPException(status_code=503, detail="admin_login_disabled")
    token_hash = _pbkdf2_hex(token_plain, salt)
    sess = get_admin_session_by_token_hash(token_hash, request_id=request_id)
    if not sess:
        raise HTTPException(status_code=401, detail="invalid_admin_token")
    if sess.get("revoked_at") is not None:
        raise HTTPException(status_code=401, detail="invalid_admin_token")

    expires_at = sess.get("expires_at")
    try:
        if isinstance(expires_at, datetime):
            exp = expires_at
        else:
            exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= exp:
            raise HTTPException(status_code=401, detail="expired_admin_token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="invalid_admin_token")

    user_id = str(sess.get("user_id"))
    u = get_user_by_id(user_id, request_id=request_id)
    return {
        "admin_session": sess,
        "admin_user": {"id": user_id, "phone": (u or {}).get("phone_e164")},
    }


class AdminLoginBody(BaseModel):
    admin_password: str


@app.post("/admin/login")
def admin_login(body: AdminLoginBody, request: Request):
    request_id = get_request_id_from_request(request)

    # Brute-force barrier: add a small delay on any failure.
    def fail(detail: str, phone_e164: str | None = None):
        time.sleep(0.5 + random.random() * 0.3)
        log_event(
            "admin_login_fail",
            level="warning",
            request_id=request_id,
            phone=_mask_phone(phone_e164),
            reason=detail,
        )
        _record_admin_event("login_fail", request=request, admin_user_id=None, request_id=request_id)
        raise HTTPException(status_code=401, detail=detail)

    allow = _admin_phone_allowlist()
    if not allow:
        fail("admin_login_disabled")

    user = _require_bearer_user(request)
    user_id = str(user.get("user_id") or "")
    phone = str(user.get("phone_e164") or "").strip()
    if not user_id or not phone:
        fail("Unauthorized")
    if phone not in allow:
        fail("not_allowed", phone_e164=phone)

    pwd = (body.admin_password or "").strip()
    if not pwd:
        raise HTTPException(status_code=400, detail="password_required")
    if not _verify_admin_password(pwd):
        fail("invalid_password", phone_e164=phone)

    ttl_hours = _admin_session_ttl_hours()
    expires_in_sec = ttl_hours * 3600
    expires_dt = datetime.now(timezone.utc) + timedelta(seconds=expires_in_sec)

    token_plain = secrets.token_urlsafe(36)
    salt = _admin_password_salt() or ""
    token_hash = _pbkdf2_hex(token_plain, salt)

    ensure_user(user_id=user_id, phone_e164=phone, request_id=request_id)
    created = create_admin_session(
        user_id=user_id,
        token_hash=token_hash,
        salt=salt,
        expires_at=expires_dt,
        request_id=request_id,
    )

    log_event(
        "admin_login_ok",
        request_id=request_id,
        phone=_mask_phone(phone),
        ttl_hours=ttl_hours,
    )
    try:
        record_admin_audit(
            request=request,
            admin_user_id=user_id,
            admin_session_id=str(created.get("id") or ""),
            action="admin_login",
            target_type="admin_session",
            target_id=str(created.get("id") or ""),
            before_obj=None,
            after_obj={"expires_at": str(created.get("expires_at")), "ttl_hours": ttl_hours},
            summary=None,
        )
    except Exception:
        # best-effort; should not block login
        pass

    return {"ok": True, "admin_token": token_plain, "expires_in_sec": expires_in_sec}


@app.get("/admin/me")
def admin_me(request: Request):
    auth = _require_admin(request)
    sess = auth.get("admin_session") or {}
    user = auth.get("admin_user") or {}
    exp = sess.get("expires_at")
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        expires_at = exp.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    else:
        expires_at = str(exp)
    return {"ok": True, "admin_user": user, "expires_at": expires_at}


@app.post("/admin/logout")
def admin_logout(request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    sess = auth.get("admin_session") or {}
    user = auth.get("admin_user") or {}
    admin_session_id = str(sess.get("id"))
    if admin_session_id:
        revoke_admin_session(admin_session_id, request_id=request_id)
    log_event(
        "admin_logout",
        request_id=request_id,
        phone=_mask_phone(user.get("phone")),
    )
    try:
        record_admin_audit(
            request=request,
            admin_user_id=str(user.get("id") or ""),
            admin_session_id=admin_session_id,
            action="admin_logout",
            target_type="admin_session",
            target_id=admin_session_id,
            before_obj={"revoked": False},
            after_obj={"revoked": True},
            summary=None,
        )
    except Exception:
        pass
    return {"ok": True}


@app.get("/admin/audit")
def admin_audit(limit: int = 50, action: str = "", target_type: str = "", request: Request = None):
    # FastAPI will still pass Request by injection even with default None.
    request_id = get_request_id_from_request(request) if request else "unknown"
    _ = _require_admin(request)
    rows = list_admin_audit_log(
        limit=limit,
        action=(action or "").strip() or None,
        target_type=(target_type or "").strip() or None,
        request_id=request_id,
    )
    return {"ok": True, "items": rows}


def _normalize_validation_errors(errors: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in errors or []:
        if not isinstance(e, dict):
            continue
        out.append(
            {
                "code": str(e.get("code") or "INVALID").strip() or "INVALID",
                "path": str(e.get("path") or "$").strip() or "$",
                "message": str(e.get("message") or "").strip() or "Invalid",
            }
        )
    return out


def _validate_documents_registry(payload: object) -> tuple[str, list[dict]]:
    errors: list[dict] = []
    if not isinstance(payload, dict):
        return "invalid", [{"code": "TYPE", "path": "$", "message": "Expected object"}]
    docs = payload.get("documents")
    if not isinstance(docs, list):
        return "invalid", [{"code": "REQUIRED", "path": "$.documents", "message": "documents must be a list"}]

    seen: set[str] = set()
    for i, d in enumerate(docs):
        p = f"$.documents[{i}]"
        if not isinstance(d, dict):
            errors.append({"code": "TYPE", "path": p, "message": "Expected object"})
            continue
        doc_id = (d.get("doc_id") or "").strip()
        if not doc_id:
            errors.append({"code": "REQUIRED", "path": p + ".doc_id", "message": "doc_id is required"})
        else:
            if doc_id in seen:
                errors.append({"code": "DUPLICATE", "path": p + ".doc_id", "message": "doc_id must be unique"})
            seen.add(doc_id)
        title = d.get("title")
        if title is None or not str(title).strip():
            errors.append({"code": "REQUIRED", "path": p + ".title", "message": "title is required"})
        is_enabled = d.get("is_enabled")
        if not isinstance(is_enabled, bool):
            errors.append({"code": "TYPE", "path": p + ".is_enabled", "message": "is_enabled must be boolean"})

    return ("valid" if not errors else "invalid"), errors


def _validate_config_payload(key: str, payload: object) -> tuple[str, list[dict]]:
    # Allow storing invalid JSON drafts by keeping raw text inside payload.
    # When present, validation must fail with a parse error.
    if isinstance(payload, dict) and "__invalid_json__" in payload:
        raw = payload.get("__invalid_json__")
        msg = "Invalid JSON"
        if isinstance(raw, str) and raw.strip():
            # Keep message short; raw text is stored for editing via admin UI.
            msg = "Invalid JSON (cannot parse)"
        return "invalid", [{"code": "JSON_PARSE_ERROR", "path": "$", "message": msg}]
    if key == "documents_registry":
        return _validate_documents_registry(payload)
    if key in {"blueprint", "resources"}:
        if isinstance(payload, dict):
            return "valid", []
        return "invalid", [{"code": "TYPE", "path": "$", "message": "Expected object"}]
    return "invalid", [{"code": "UNSUPPORTED_KEY", "path": "$", "message": "Unsupported key"}]


def _config_snapshot(request_id: str) -> dict:
    active_versions: dict[str, int] = {}
    hashes: dict[str, str] = {}
    sources: set[str] = set()
    for k in SUPPORTED_CONFIG_KEYS:
        payload, meta = resolve_config(k, request_id=request_id)
        try:
            v = int(meta.get("version") or 0)
        except Exception:
            v = 0
        active_versions[k] = v
        hashes[k] = str(meta.get("hash") or "")
        sources.add(str(meta.get("source") or "file"))

    source = "db" if (sources == {"db"}) else "file"
    return {"source": source, "active_versions": active_versions, "hashes": hashes}


def _record_config_snapshot_artifact(
    *,
    session_id: str,
    pack_id: str,
    doc_id: str,
    render_job_id: str,
    request_id: str,
):
    try:
        snap = _config_snapshot(request_id=request_id)
        create_artifact(
            session_id=session_id,
            kind="config_snapshot",
            format="json",
            payload_json=snap,
            meta={"pack_id": pack_id, "doc_id": doc_id, "render_job_id": render_job_id},
            request_id=request_id,
        )
    except Exception:
        pass


RENDER_DRYRUN_URL = (os.environ.get("RENDER_URL") or "").strip() or "http://localhost:8002"


def _http_post_json_bytes(url: str, payload: dict, timeout_sec: float = 10.0) -> tuple[bool, bytes | None, str | None]:
    try:
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
                return False, None, f"http_{status}"
            return True, body, None
    except Exception as e:
        return False, None, str(e)


@app.get("/admin/config/keys")
def admin_config_keys(request: Request):
    _ = _require_admin(request)
    return {"ok": True, "keys": SUPPORTED_CONFIG_KEYS}


@app.get("/admin/config/{key}/versions")
def admin_config_versions(key: str, request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)
    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)
    rows = list_config_versions(key, request_id=request_id)
    items = []
    for r in rows:
        items.append(
            {
                "id": str(r.get("id")),
                "key": str(r.get("key")),
                "version": int(r.get("version") or 0),
                "is_active": bool(r.get("is_active")),
                "validation_status": str(r.get("validation_status") or "draft"),
                "validation_errors": r.get("validation_errors") or [],
                "comment": r.get("comment"),
                "created_at": to_iso(r.get("created_at")),
            }
        )
    return {"ok": True, "items": items}


@app.get("/admin/config/{key}/versions/{version}")
def admin_config_get(key: str, version: int, request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)
    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)
    row = get_config_version(key, int(version), request_id=request_id)
    if not row:
        _admin_error("VERSION_NOT_FOUND", "Version not found", 404)

    payload_json = row.get("payload_json") or {}
    payload_text: str | None = None
    if isinstance(payload_json, dict) and "__invalid_json__" in payload_json:
        raw = payload_json.get("__invalid_json__")
        if isinstance(raw, str):
            payload_text = raw
    return {
        "ok": True,
        "item": {
            "id": str(row.get("id")),
            "key": str(row.get("key")),
            "version": int(row.get("version") or 0),
            "is_active": bool(row.get("is_active")),
            "validation_status": str(row.get("validation_status") or "draft"),
            "validation_errors": row.get("validation_errors") or [],
            "comment": row.get("comment"),
            "payload_json": payload_json,
            "payload_text": payload_text,
            "created_at": to_iso(row.get("created_at")),
        },
    }


@app.post("/admin/config/{key}/draft")
def admin_config_draft(key: str, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)

    active = get_active_config_store(key, request_id=request_id)
    if active:
        base_payload = active.get("payload_json") or {}
        active_version = int(active.get("version") or 0)
    else:
        base_payload = _load_file_config(key)
        active_version = 0

    # Pick a new version that cannot conflict with existing rows.
    try:
        existing = list_config_versions(key, request_id=request_id)
        max_existing_version = max([int(r.get("version") or 0) for r in existing] or [0])
    except Exception:
        max_existing_version = 0
    new_version = max(active_version, max_existing_version) + 1

    created = create_config_version(
        key=key,
        version=new_version,
        payload_json=base_payload if isinstance(base_payload, dict) else {},
        is_active=False,
        validation_status="draft",
        validation_errors=[],
        comment=None,
        created_by_user_id=admin_user_id or None,
        request_id=request_id,
    )

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="config_draft",
        target_type="config_store",
        target_id=f"{key}:{new_version}",
        before_obj={"base": "active" if bool(active) else "file"},
        after_obj={"key": key, "version": new_version},
        summary=None,
    )

    return {"ok": True, "key": key, "version": int(created.get("version") or new_version)}


class AdminConfigUpdateBody(BaseModel):
    # Support both parsed JSON and raw text. Raw text allows saving drafts even
    # when JSON is invalid; validation will surface JSON_PARSE_ERROR.
    payload_json: dict | None = None
    payload_text: str | None = None
    comment: str | None = None


@app.post("/admin/config/{key}/update")
def admin_config_update(key: str, body: AdminConfigUpdateBody, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)

    v = get_latest_inactive_version(key, request_id=request_id)
    if v is None:
        _admin_error("NO_DRAFT", "No draft version", 400)

    payload_to_store: dict
    if body.payload_text is not None:
        raw = str(body.payload_text)
        try:
            parsed = json.loads(raw)
            payload_to_store = parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            payload_to_store = {"__invalid_json__": raw}
    else:
        payload_to_store = body.payload_json or {}

    updated = update_config_payload(
        key=key,
        version=int(v),
        payload_json=payload_to_store,
        comment=(body.comment or None),
        request_id=request_id,
    )
    if not updated:
        _admin_error("UPDATE_FAILED", "Failed to update draft", 500)

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="config_update",
        target_type="config_store",
        target_id=f"{key}:{v}",
        before_obj=None,
        after_obj={"key": key, "version": int(v)},
        summary=None,
    )

    return {"ok": True, "key": key, "version": int(v)}


@app.post("/admin/config/{key}/validate")
def admin_config_validate(key: str, version: int, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)
    row = get_config_version(key, int(version), request_id=request_id)
    if not row:
        _admin_error("VERSION_NOT_FOUND", "Version not found", 404)

    status, errors = _validate_config_payload(key, row.get("payload_json"))
    errors = _normalize_validation_errors(errors)
    set_config_validation(
        key=key,
        version=int(version),
        validation_status=status,
        validation_errors=errors,
        request_id=request_id,
    )

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="config_validate",
        target_type="config_store",
        target_id=f"{key}:{version}",
        before_obj=None,
        after_obj={"status": status, "errors": errors},
        summary=None,
    )

    return {"ok": True, "status": status, "errors": errors}


@app.post("/admin/config/{key}/dry-run")
def admin_config_dry_run(key: str, version: int, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)
    row = get_config_version(key, int(version), request_id=request_id)
    if not row:
        _admin_error("VERSION_NOT_FOUND", "Version not found", 404)

    # If the selected version is invalid, dry-run must not crash; surface the reason.
    v_status, v_errors = _validate_config_payload(key, row.get("payload_json"))
    v_errors = _normalize_validation_errors(v_errors)
    if v_status != "valid":
        out = {
            "ok": False,
            "error": {"code": "INVALID_CONFIG", "message": "Config is invalid", "details": v_errors},
        }
        record_admin_audit(
            request=request,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            action="config_dry_run",
            target_type="config_store",
            target_id=f"{key}:{version}",
            before_obj=None,
            after_obj={"ok": False, "error": out.get("error")},
            summary=None,
        )
        return out

    # Pre-flight: build minimal render payload using current docs registry.
    if key == "documents_registry":
        payload = row.get("payload_json") or {}
        docs_payload = payload.get("documents") if isinstance(payload, dict) else None
        docs = [d for d in (docs_payload or []) if isinstance(d, dict) and bool(d.get("is_enabled"))]
    else:
        docs = [d for d in _load_documents_registry(request_id=request_id) if bool(d.get("is_enabled"))]
    if not docs:
        out = {"ok": False, "error": {"code": "NO_DOCUMENTS", "message": "No enabled documents"}}
        record_admin_audit(
            request=request,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            action="config_dry_run",
            target_type="config_store",
            target_id=f"{key}:{version}",
            before_obj=None,
            after_obj={"ok": False, "error": out.get("error")},
            summary=None,
        )
        return out

    doc0 = docs[0]
    doc_id = str(doc0.get("doc_id") or "").strip() or "free_report"
    title = _doc_title(doc0)
    render_request = _build_render_request(doc_id=doc_id, title=title, pack_id="dryrun", session_id="dryrun")

    start = time.perf_counter()
    ok, pdf_bytes, err = _http_post_json_bytes(f"{RENDER_DRYRUN_URL.rstrip('/')}/render", render_request, timeout_sec=10.0)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    if not ok or not pdf_bytes:
        out = {
            "ok": False,
            "error": {"code": "RENDER_UNAVAILABLE", "message": err or "render failed"},
            "elapsed_ms": elapsed_ms,
        }
        record_admin_audit(
            request=request,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            action="config_dry_run",
            target_type="config_store",
            target_id=f"{key}:{version}",
            before_obj=None,
            after_obj={"ok": False, "error": out.get("error"), "elapsed_ms": elapsed_ms},
            summary=None,
        )
        return out

    if not pdf_bytes.startswith(b"%PDF"):
        out = {
            "ok": False,
            "error": {"code": "INVALID_PDF", "message": "Render returned non-PDF"},
            "elapsed_ms": elapsed_ms,
        }
        record_admin_audit(
            request=request,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            action="config_dry_run",
            target_type="config_store",
            target_id=f"{key}:{version}",
            before_obj=None,
            after_obj={"ok": False, "error": out.get("error"), "elapsed_ms": elapsed_ms},
            summary=None,
        )
        return out

    out = {"ok": True, "pdf_bytes_size": len(pdf_bytes), "elapsed_ms": elapsed_ms}
    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="config_dry_run",
        target_type="config_store",
        target_id=f"{key}:{version}",
        before_obj=None,
        after_obj=out,
        summary=None,
    )
    return out


@app.post("/admin/config/{key}/publish")
def admin_config_publish(key: str, version: int, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)
    row = get_config_version(key, int(version), request_id=request_id)
    if not row:
        _admin_error("VERSION_NOT_FOUND", "Version not found", 404)
    if str(row.get("validation_status") or "").lower() != "valid":
        _admin_error("PUBLISH_FORBIDDEN", "Config must be valid to publish", 400)

    before_active = get_active_config_store(key, request_id=request_id)
    before_obj = {
        "active_version": int(before_active.get("version") or 0) if before_active else None,
        "active_hash": _stable_hash(before_active.get("payload_json")) if before_active else None,
    }
    ok = publish_config_version(key, int(version), request_id=request_id)
    if not ok:
        _admin_error("PUBLISH_FAILED", "Failed to publish", 500)
    after_row = get_active_config_store(key, request_id=request_id)
    after_obj = {
        "active_version": int(after_row.get("version") or 0) if after_row else None,
        "active_hash": _stable_hash(after_row.get("payload_json")) if after_row else None,
    }

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="config_publish",
        target_type="config_store",
        target_id=f"{key}:{version}",
        before_obj=before_obj,
        after_obj=after_obj,
        summary=None,
    )

    # drop cache for this key so next resolver sees new active
    _CONFIG_CACHE.pop(key, None)
    return {"ok": True}


@app.post("/admin/config/{key}/rollback")
def admin_config_rollback(key: str, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    key = (key or "").strip()
    if key not in SUPPORTED_CONFIG_KEYS:
        _admin_error("UNSUPPORTED_KEY", "Unsupported key", 400)

    active = get_active_config_store(key, request_id=request_id)
    if not active:
        _admin_error("NO_ACTIVE", "No active config", 400)
    cur_v = int(active.get("version") or 0)
    prev_v = get_previous_valid_version(key, cur_v, request_id=request_id)
    if prev_v is None:
        _admin_error("NO_ROLLBACK", "No previous valid version", 400)

    before_obj = {
        "active_version": cur_v,
        "active_hash": _stable_hash(active.get("payload_json")),
    }
    ok = publish_config_version(key, int(prev_v), request_id=request_id)
    if not ok:
        _admin_error("ROLLBACK_FAILED", "Failed to rollback", 500)
    after = get_active_config_store(key, request_id=request_id)
    after_obj = {
        "active_version": int(after.get("version") or 0) if after else None,
        "active_hash": _stable_hash(after.get("payload_json")) if after else None,
    }

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="config_rollback",
        target_type="config_store",
        target_id=f"{key}:{prev_v}",
        before_obj=before_obj,
        after_obj=after_obj,
        summary=None,
    )
    _CONFIG_CACHE.pop(key, None)
    return {"ok": True, "active_version": int(prev_v)}


def _admin_error(code: str, message: str, status_code: int):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@app.get("/admin/overview")
def admin_overview(request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)
    # Minimal operator overview (can be extended later).
    return {
        "ok": True,
        "request_id": request_id,
        "config": {
            "config_source": CONFIG_SOURCE,
            "cache_ttl_sec": CONFIG_CACHE_TTL_SEC,
        },
    }


@app.get("/admin/alerts")
def admin_alerts_list(
    limit: int = 100,
    severity: str = "",
    event: str = "",
    request: Request = None,
):
    request_id = get_request_id_from_request(request) if request else "unknown"
    _ = _require_admin(request)
    rows = list_alert_events(
        limit=limit,
        severity=(severity or "").strip() or None,
        event=(event or "").strip() or None,
        request_id=request_id,
    )
    items: list[dict] = []
    for r in rows:
        payload = r.get("payload_json") or {}
        meta = r.get("meta") or {}
        items.append(
            {
                "id": str(r.get("id")),
                "severity": (payload.get("severity") if isinstance(payload, dict) else None),
                "event": (payload.get("event") if isinstance(payload, dict) else None),
                "request_id": (payload.get("request_id") if isinstance(payload, dict) else None),
                "ts": (payload.get("ts") if isinstance(payload, dict) else None),
                "context": (payload.get("context") if isinstance(payload, dict) else None),
                "acked_at": (meta.get("acked_at") if isinstance(meta, dict) else None),
                "acked_by_user_id": (meta.get("acked_by_user_id") if isinstance(meta, dict) else None),
                "created_at": to_iso(r.get("created_at")),
            }
        )
    return {"ok": True, "items": items}


@app.post("/admin/alerts/{alert_id}/ack")
def admin_alerts_ack(alert_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    alert_id = (alert_id or "").strip()
    if not alert_id:
        _admin_error("BAD_REQUEST", "alert_id is required", 400)

    before = None
    try:
        prev = get_artifact_by_id(artifact_id=alert_id, request_id=request_id)
        if prev and str(prev.get("kind")) == "alert_event":
            before = {"meta": prev.get("meta"), "payload": prev.get("payload_json")}
    except Exception:
        before = None

    updated = ack_alert_event(alert_id=alert_id, admin_user_id=admin_user_id or None, request_id=request_id)
    if not updated:
        _admin_error("ALERT_NOT_FOUND", "Alert not found", 404)

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="alert_ack",
        target_type="alert_event",
        target_id=alert_id,
        before_obj=before,
        after_obj={"meta": updated.get("meta")},
        summary=None,
    )

    return {"ok": True, "id": alert_id, "meta": updated.get("meta")}


@app.get("/admin/logs")
def admin_logs(
    kind: str = "",
    pack_id: str = "",
    doc_id: str = "",
    status: str = "",
    limit: int = 200,
    request: Request = None,
):
    request_id = get_request_id_from_request(request) if request else "unknown"
    _ = _require_admin(request)

    safe_limit = int(limit or 200)
    if safe_limit <= 0:
        safe_limit = 200
    if safe_limit > 1000:
        safe_limit = 1000

    kind_q = (kind or "").strip()
    pack_q = (pack_id or "").strip() or None
    doc_q = (doc_id or "").strip() or None
    status_q = (status or "").strip() or None

    include_jobs = (not kind_q) or (kind_q == "render_job")
    include_artifacts = (not kind_q) or (kind_q != "render_job")

    items: list[dict] = []
    if include_artifacts:
        rows = list_artifacts_admin(
            kind=(kind_q if kind_q and kind_q != "render_job" else None),
            pack_id=pack_q,
            doc_id=doc_q,
            limit=safe_limit,
            request_id=request_id,
        )
        for r in rows:
            items.append(
                {
                    "source": "artifact",
                    "id": str(r.get("id")),
                    "kind": str(r.get("kind")),
                    "created_at": to_iso(r.get("created_at")),
                    "payload_json": r.get("payload_json"),
                    "meta": r.get("meta"),
                    "session_id": r.get("session_id"),
                }
            )

    if include_jobs:
        rows = list_render_jobs_admin(
            status=status_q,
            pack_id=pack_q,
            doc_id=doc_q,
            limit=safe_limit,
            request_id=request_id,
        )
        for r in rows:
            items.append(
                {
                    "source": "render_job",
                    "id": str(r.get("id")),
                    "kind": "render_job",
                    "created_at": to_iso(r.get("updated_at") or r.get("created_at")),
                    "payload_json": {
                        "pack_id": str(r.get("pack_id")),
                        "doc_id": str(r.get("doc_id")),
                        "status": r.get("status"),
                        "attempts": int(r.get("attempts") or 0),
                        "max_attempts": int(r.get("max_attempts") or 0),
                        "last_error": r.get("last_error"),
                        "updated_at": to_iso(r.get("updated_at")),
                        "created_at": to_iso(r.get("created_at")),
                    },
                    "meta": None,
                    "session_id": None,
                }
            )

    def _ts_key(it: dict) -> str:
        return str(it.get("created_at") or "")

    items.sort(key=_ts_key, reverse=True)
    items = items[:safe_limit]
    return {"ok": True, "items": items}


class AdminTemplateCreateBody(BaseModel):
    doc_id: str
    name: str
    body: str


@app.get("/admin/templates")
def admin_templates_list(doc_id: str = "", limit: int = 200, request: Request = None):
    request_id = get_request_id_from_request(request) if request else "unknown"
    _ = _require_admin(request)

    did = (doc_id or "").strip() or None
    safe_limit = int(limit or 200)
    if safe_limit <= 0:
        safe_limit = 200
    if safe_limit > 1000:
        safe_limit = 1000

    rows = list_document_templates(request_id=request_id, doc_id=did, limit=safe_limit)
    items: list[dict] = []
    for r in rows:
        items.append(
            {
                "id": str(r.get("id")),
                "doc_id": r.get("doc_id"),
                "name": r.get("name"),
                "version": int(r.get("version") or 0),
                "is_active": bool(r.get("is_active")),
                "created_at": to_iso(r.get("created_at")),
                "body": r.get("body"),
            }
        )
    return {"ok": True, "items": items}


@app.post("/admin/templates")
def admin_templates_create(body: AdminTemplateCreateBody, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)

    doc_id = (body.doc_id or "").strip()
    name = (body.name or "").strip()
    template_body = body.body or ""
    if not doc_id or not name or not template_body.strip():
        _admin_error("BAD_REQUEST", "doc_id, name, body are required", 400)

    if not _catalog_item(doc_id):
        _admin_error("DOC_NOT_FOUND", "doc_id not found in catalog", 404)

    row = create_document_template_version(
        doc_id=doc_id,
        name=name,
        body=template_body,
        make_active=True,
        request_id=request_id,
    )

    try:
        admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
        admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")
        record_admin_audit(
            request=request,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            action="template_create",
            target_type="document_template",
            target_id=str(row.get("id")),
            before_obj=None,
            after_obj={"doc_id": doc_id, "name": name, "version": row.get("version"), "is_active": True},
            summary=None,
        )
    except Exception:
        pass

    return {"ok": True, "template": row}


@app.post("/admin/templates/{template_id}/activate")
def admin_templates_activate(template_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)

    tid = (template_id or "").strip()
    if not tid:
        _admin_error("BAD_REQUEST", "template_id is required", 400)

    row = activate_document_template(template_id=tid, request_id=request_id)
    if not row:
        _admin_error("NOT_FOUND", "Template not found", 404)

    try:
        admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
        admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")
        record_admin_audit(
            request=request,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            action="template_activate",
            target_type="document_template",
            target_id=str(row.get("id")),
            before_obj=None,
            after_obj={"doc_id": row.get("doc_id"), "version": row.get("version"), "is_active": True},
            summary=None,
        )
    except Exception:
        pass

    return {"ok": True, "template": row}


class AdminDocumentMetadataBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class AdminDocumentAccessBody(BaseModel):
    enabled: bool
    tier: str


@app.get("/admin/documents")
def admin_documents_list(request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)
    docs = _load_documents_registry(request_id=request_id)
    doc_ids = [str(d.get("doc_id") or "").strip() for d in docs if str(d.get("doc_id") or "").strip()]

    meta_map = get_document_metadata_map(doc_ids, request_id=request_id)
    access_map = get_document_access_map(doc_ids, request_id=request_id)

    items: list[dict] = []
    for d in docs:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        meta_row = meta_map.get(doc_id)
        access_row = access_map.get(doc_id)
        items.append(
            {
                "doc_id": doc_id,
                "title": _effective_doc_title(d, meta_row),
                "description": (meta_row or {}).get("description") if isinstance(meta_row, dict) else None,
                "registry": {
                    "title": _doc_title(d),
                    "is_enabled": bool(d.get("is_enabled")) if d.get("is_enabled") is not None else True,
                },
                "metadata": {
                    "title": (meta_row or {}).get("title") if isinstance(meta_row, dict) else None,
                    "description": (meta_row or {}).get("description") if isinstance(meta_row, dict) else None,
                },
                "access": {
                    "enabled": bool((access_row or {}).get("enabled")) if isinstance(access_row, dict) and access_row.get("enabled") is not None else None,
                    "tier": (access_row or {}).get("tier") if isinstance(access_row, dict) else None,
                    "effective": _doc_access_info(d, access_row),
                },
            }
        )

    return {"ok": True, "items": items}


@app.post("/admin/documents/{doc_id}/metadata")
def admin_document_metadata_update(doc_id: str, body: AdminDocumentMetadataBody, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    doc_id = (doc_id or "").strip()
    if not doc_id:
        _admin_error("BAD_REQUEST", "doc_id is required", 400)

    docs = _load_documents_registry(request_id=request_id)
    registry_doc = None
    for d in docs:
        if str(d.get("doc_id") or "").strip() == doc_id:
            registry_doc = d
            break
    if not registry_doc:
        _admin_error("DOC_NOT_FOUND", "Document not found in registry", 404)

    before = get_document_metadata_map([doc_id], request_id=request_id).get(doc_id)

    title = body.title
    if title is not None:
        title = str(title)
        if not title.strip():
            title = None

    description = body.description
    if description is not None:
        description = str(description)
        if not description.strip():
            description = None

    row = upsert_document_metadata(
        doc_id=doc_id,
        title=title,
        description=description,
        updated_by_user_id=admin_user_id or None,
        request_id=request_id,
    )

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="document_metadata_update",
        target_type="document",
        target_id=doc_id,
        before_obj=before,
        after_obj=row,
        summary=None,
    )

    return {"ok": True, "doc_id": doc_id, "metadata": row}


@app.post("/admin/documents/{doc_id}/access")
def admin_document_access_update(doc_id: str, body: AdminDocumentAccessBody, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    doc_id = (doc_id or "").strip()
    if not doc_id:
        _admin_error("BAD_REQUEST", "doc_id is required", 400)

    tier = str(body.tier or "").strip().lower()
    if tier not in {"free", "paid"}:
        _admin_error("INVALID_TIER", "tier must be free|paid", 400)

    docs = _load_documents_registry(request_id=request_id)
    registry_doc = None
    for d in docs:
        if str(d.get("doc_id") or "").strip() == doc_id:
            registry_doc = d
            break
    if not registry_doc:
        _admin_error("DOC_NOT_FOUND", "Document not found in registry", 404)

    before = get_document_access_map([doc_id], request_id=request_id).get(doc_id)

    row = upsert_document_access(
        doc_id=doc_id,
        enabled=bool(body.enabled),
        tier=tier,
        updated_by_user_id=admin_user_id or None,
        request_id=request_id,
    )

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="document_access_update",
        target_type="document",
        target_id=doc_id,
        before_obj=before,
        after_obj=row,
        summary=None,
    )

    # For response: effective without registry context (fallback tier=free)
    return {"ok": True, "doc_id": doc_id, "access": row, "effective": _doc_access_info({"doc_id": doc_id}, row)}


@app.get("/admin/render-jobs")
def admin_render_jobs_list(
    status: str = "",
    pack_id: str = "",
    doc_id: str = "",
    limit: int = 100,
    request: Request = None,
):
    request_id = get_request_id_from_request(request) if request else "unknown"
    _ = _require_admin(request)
    rows = list_render_jobs_admin(
        status=(status or "").strip() or None,
        pack_id=(pack_id or "").strip() or None,
        doc_id=(doc_id or "").strip() or None,
        limit=limit,
        request_id=request_id,
    )
    normalized = []
    for r in rows:
        normalized.append(
            {
                "id": str(r.get("id")),
                "pack_id": str(r.get("pack_id")),
                "doc_id": str(r.get("doc_id")),
                "status": r.get("status"),
                "attempts": int(r.get("attempts") or 0),
                "max_attempts": int(r.get("max_attempts") or 0),
                "last_error": r.get("last_error"),
                "created_at": to_iso(r.get("created_at")),
                "updated_at": to_iso(r.get("updated_at")),
            }
        )
    return {"ok": True, "items": normalized}


@app.get("/admin/render-jobs/{job_id}")
def admin_render_jobs_get(job_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)
    job_id = (job_id or "").strip()
    if not job_id:
        _admin_error("BAD_REQUEST", "job_id is required", 400)

    row = get_render_job(job_id, request_id=request_id)
    if not row:
        _admin_error("JOB_NOT_FOUND", "Job not found", 404)

    artifacts = list_artifacts_for_render_job(job_id, request_id=request_id)
    normalized_artifacts = []
    for a in artifacts:
        normalized_artifacts.append(
            {
                "artifact_id": str(a.get("artifact_id")),
                "kind": a.get("kind"),
                "format": a.get("format"),
                "created_at": to_iso(a.get("created_at")),
                "file_id": str(a.get("file_id")) if a.get("file_id") else None,
                "content_type": a.get("content_type"),
                "size_bytes": a.get("size_bytes"),
            }
        )

    latest_file_id = None
    try:
        latest_file_id = get_latest_file_id_for_render_job(job_id, request_id=request_id)
    except Exception:
        latest_file_id = None

    job = {
        "id": str(row.get("id")),
        "pack_id": str(row.get("pack_id")),
        "doc_id": str(row.get("doc_id")),
        "status": row.get("status"),
        "attempts": int(row.get("attempts") or 0),
        "max_attempts": int(row.get("max_attempts") or 0),
        "last_error": row.get("last_error"),
        "created_at": to_iso(row.get("created_at")),
        "updated_at": to_iso(row.get("updated_at")),
    }
    return {
        "ok": True,
        "job": job,
        "artifacts": normalized_artifacts,
        "latest_file_id": latest_file_id,
    }


def _enqueue_render_job_same_as_user_endpoints(
    *,
    pack_id: str,
    session_id: str,
    doc_id: str,
    request_id: str,
):
    # Same payload format as /packs/{pack_id}/render/{doc_id}
    docs = _load_documents_registry(request_id=request_id)
    title = doc_id
    for d in docs:
        if str(d.get("doc_id")) == doc_id:
            title = _doc_title(d)
            break

    render_request = _build_render_request(
        doc_id=doc_id,
        title=title,
        pack_id=pack_id,
        session_id=session_id,
    )
    msg = json.dumps(
        {
            "job_id": None,  # filled by caller
            "pack_id": pack_id,
            "session_id": session_id,
            "doc_id": doc_id,
            "render_request": render_request,
        },
        ensure_ascii=False,
    )
    return render_request, msg


@app.post("/admin/render-jobs/{job_id}/requeue")
def admin_render_jobs_requeue(job_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    job_id = (job_id or "").strip()
    if not job_id:
        _admin_error("BAD_REQUEST", "job_id is required", 400)

    old = get_render_job(job_id, request_id=request_id)
    if not old:
        _admin_error("JOB_NOT_FOUND", "Job not found", 404)

    old_status = str(old.get("status") or "")
    if old_status != "failed":
        _admin_error("INVALID_STATUS", "Only failed jobs can be requeued", 400)

    pack_id = str(old.get("pack_id") or "")
    session_id = str(old.get("session_id") or "")
    doc_id = str(old.get("doc_id") or "")
    if not pack_id or not session_id or not doc_id:
        _admin_error("JOB_INCOMPLETE", "Job record is incomplete", 500)

    if has_active_render_job(pack_id=pack_id, doc_id=doc_id, request_id=request_id):
        _admin_error("ALREADY_IN_PROGRESS", "Job already queued/rendering for this pack+doc", 409)

    new_job = create_render_job(
        pack_id=pack_id,
        session_id=session_id,
        user_id=None,
        doc_id=doc_id,
        status="queued",
        max_attempts=int(old.get("max_attempts") or 5),
        request_id=request_id,
    )
    new_job_id = str(new_job.get("id") or "")
    if not new_job_id:
        _admin_error("CREATE_FAILED", "Failed to create render job", 500)

    render_request, msg_template = _enqueue_render_job_same_as_user_endpoints(
        pack_id=pack_id,
        session_id=session_id,
        doc_id=doc_id,
        request_id=request_id,
    )
    payload = json.loads(msg_template)
    payload["job_id"] = new_job_id
    msg = json.dumps(payload, ensure_ascii=False)
    try:
        _redis_client().rpush(RENDER_QUEUE_NAME, msg)
    except Exception as e:
        _admin_error("ENQUEUE_FAILED", f"Failed to enqueue render job: {e}", 500)

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="render_job_requeue",
        target_type="render_job",
        target_id=job_id,
        before_obj={
            "job_id": job_id,
            "status": old_status,
            "attempts": int(old.get("attempts") or 0),
            "last_error": old.get("last_error"),
        },
        after_obj={
            "new_job_id": new_job_id,
            "pack_id": pack_id,
            "doc_id": doc_id,
            "status": "queued",
            "render_request_meta": (render_request or {}).get("meta") if isinstance(render_request, dict) else None,
        },
        summary=None,
    )

    return {"ok": True, "old_job_id": job_id, "new_job_id": new_job_id}


@app.post("/admin/render-jobs/requeue-failed")
def admin_render_jobs_requeue_failed(limit: int = 50, request: Request = None):
    request_id = get_request_id_from_request(request) if request else "unknown"
    auth = _require_admin(request)
    admin_user_id = str((auth.get("admin_user") or {}).get("id") or "")
    admin_session_id = str((auth.get("admin_session") or {}).get("id") or "")

    rows = list_failed_render_jobs(limit=limit, request_id=request_id)
    enqueued = 0
    skipped_in_progress = 0
    skipped_incomplete = 0
    errors: list[str] = []

    for old in rows:
        try:
            pack_id = str(old.get("pack_id") or "")
            session_id = str(old.get("session_id") or "")
            doc_id = str(old.get("doc_id") or "")
            if not pack_id or not session_id or not doc_id:
                skipped_incomplete += 1
                continue
            if has_active_render_job(pack_id=pack_id, doc_id=doc_id, request_id=request_id):
                skipped_in_progress += 1
                continue
            new_job = create_render_job(
                pack_id=pack_id,
                session_id=session_id,
                user_id=None,
                doc_id=doc_id,
                status="queued",
                max_attempts=int(old.get("max_attempts") or 5),
                request_id=request_id,
            )
            new_job_id = str(new_job.get("id") or "")
            if not new_job_id:
                errors.append("create_failed")
                continue
            _, msg_template = _enqueue_render_job_same_as_user_endpoints(
                pack_id=pack_id,
                session_id=session_id,
                doc_id=doc_id,
                request_id=request_id,
            )
            payload = json.loads(msg_template)
            payload["job_id"] = new_job_id
            msg = json.dumps(payload, ensure_ascii=False)
            _redis_client().rpush(RENDER_QUEUE_NAME, msg)
            enqueued += 1
        except Exception as e:
            errors.append(str(e))

    record_admin_audit(
        request=request,
        admin_user_id=admin_user_id,
        admin_session_id=admin_session_id,
        action="render_job_requeue_failed_bulk",
        target_type="render_job",
        target_id="bulk",
        before_obj={"failed_considered": len(rows)},
        after_obj={
            "enqueued": enqueued,
            "skipped_in_progress": skipped_in_progress,
            "skipped_incomplete": skipped_incomplete,
            "errors": len(errors),
        },
        summary=None,
    )

    return {
        "ok": True,
        "failed_considered": len(rows),
        "enqueued": enqueued,
        "skipped_in_progress": skipped_in_progress,
        "skipped_incomplete": skipped_incomplete,
        "errors": errors[:10],
    }


@app.get("/admin/files/{file_id}/download")
def admin_files_download(file_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)

    row = get_file_download_info(file_id=file_id, request_id=request_id)
    if not row:
        _admin_error("FILE_NOT_FOUND", "File not found", 404)
    bucket = row.get("bucket")
    key = row.get("object_key")
    if not bucket or not key:
        _admin_error("FILE_INCOMPLETE", "File record is incomplete", 500)
    expires = 600
    url = presign_get(bucket=bucket, key=key, expires_sec=expires, request_id=request_id)
    return {"ok": True, "url": url, "expires_in_sec": expires}


def log_event(event: str, level: str = "info", **fields):
    payload = {
        "event": event,
        "level": level,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        else:
            payload[key] = value

    # Stage 9.5+: optional DB-backed event persistence for LLM events only.
    # Default: enabled (LOG_EVENTS_TO_DB=1). Disable with LOG_EVENTS_TO_DB=0.
    try:
        log_events_to_db = (os.environ.get("LOG_EVENTS_TO_DB") or "1").strip().lower() not in {"0", "false", "no"}
    except Exception:
        log_events_to_db = True

    if log_events_to_db and event in {"llm_request", "llm_response", "llm_error"}:
        try:
            import hashlib

            session_id = payload.get("session_id")
            request_id = payload.get("request_id") or "unknown"

            allowed_keys = {
                "request_id",
                "session_id",
                "provider",
                "model",
                "mode",
                "base_url",
                "flow",
                "doc_id",
                "pack_id",
                "attempt",
                "duration_ms",
                "prompt_chars",
                "llm_response_chars",
                "response_chars",
                "ok",
                "fallback",
                "parsed_ok",
            }
            event_payload = {"level": level, "ts": payload.get("ts")}
            for key in allowed_keys:
                if key in payload and payload[key] is not None:
                    event_payload[key] = payload[key]

            # No raw text in DB: store only hash + length for errors.
            if event == "llm_error":
                raw_error = str(payload.get("error") or "")
                event_payload.pop("error", None)
                event_payload["error_length"] = len(raw_error)
                event_payload["error_sha256"] = hashlib.sha256(raw_error.encode("utf-8", errors="ignore")).hexdigest()

            meta = {
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                "flow": payload.get("flow"),
                "doc_id": payload.get("doc_id"),
                "pack_id": payload.get("pack_id"),
                "attempt": payload.get("attempt"),
                "mode": payload.get("mode"),
            }
            meta = {k: v for k, v in meta.items() if v is not None}

            create_artifact(
                session_id=session_id,
                kind=event,
                format="json",
                payload_json=event_payload,
                meta=meta,
                request_id=str(request_id),
            )
        except Exception:
            # best-effort, never break request flow
            pass

    print(json.dumps(payload, ensure_ascii=False))


def get_request_id_from_request(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def compute_duration_ms(start_time: float) -> float:
    return round((time.perf_counter() - start_time) * 1000, 2)


def _get_user_id(request: Request) -> str | None:
    """Resolve current user_id.

    Priority:
    1) Bearer token
    2) Signed auth cookie
    3) X-User-Id legacy header fallback
    """

    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            rec = TOKENS.get(token)
            if isinstance(rec, dict):
                user_id = (rec.get("user_id") or "").strip()
                if user_id:
                    return user_id
            # Support simple inline tokens for local smoke.
            if token.startswith("mock:") and len(token) > 5:
                return token[5:]

    # Cookie auth
    cookie_val = (request.cookies.get(_auth_cookie_name()) or "").strip()
    if cookie_val:
        user_id = _parse_auth_cookie_user_id(cookie_val)
        if user_id:
            return user_id

    # Legacy header fallback (older front)
    raw = request.headers.get("X-User-Id")
    if raw:
        v = raw.strip()
        return v or None
    return None


def _require_user_id(request: Request) -> str:
    """Require auth. 401 only when auth was present but invalid, or missing."""

    # If a cookie exists but is invalid/expired, return a reason.
    cookie_val = (request.cookies.get(_auth_cookie_name()) or "").strip()
    if cookie_val:
        try:
            uid = _parse_auth_cookie_user_id(cookie_val)
            if uid:
                return uid
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="invalid_cookie")

    # If bearer token exists but invalid, keep 401.
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="invalid_token")

    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


# ============================================================================
# Guest cookie auth (for DEV/PROD without login)
# ============================================================================

AUTH_COOKIE_MAX_AGE_SEC = 180 * 24 * 3600  # ~180 days


def _auth_cookie_name() -> str:
    return "nly_auth"


def _auth_cookie_secret() -> str:
    # Prefer dedicated secret; fallback to admin salt; last-resort insecure default.
    v = (os.environ.get("AUTH_COOKIE_SECRET") or "").strip()
    if v:
        return v
    v = (os.environ.get("ADMIN_PASSWORD_SALT") or "").strip()
    if v:
        return "cookie:" + v
    return "cookie:insecure-default"


def _is_https_request(request: Request) -> bool:
    xf = (request.headers.get("X-Forwarded-Proto") or "").strip().lower()
    if xf:
        return xf == "https"
    try:
        return (request.url.scheme or "").lower() == "https"
    except Exception:
        return False


def _cookie_domain_for_request(request: Request) -> str | None:
    host = (request.headers.get("host") or "").split(":", 1)[0].strip().lower()
    if not host:
        return None
    if host in {"localhost", "127.0.0.1"}:
        return None
    # Share across dev/prod subdomains.
    if host == "naitilyudei.ru" or host.endswith(".naitilyudei.ru"):
        return ".naitilyudei.ru"
    return None


def _auth_cookie_sig(user_id: str, issued_at: int) -> str:
    msg = f"{user_id}.{issued_at}".encode("utf-8")
    key = _auth_cookie_secret().encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _make_auth_cookie_value(user_id: str, issued_at: int | None = None) -> str:
    ts = int(issued_at or int(time.time()))
    sig = _auth_cookie_sig(user_id, ts)
    return f"{user_id}.{ts}.{sig}"


def _parse_auth_cookie_user_id(cookie_val: str) -> str | None:
    """Return user_id or raise HTTPException(401, reason) if malformed/invalid/expired."""
    parts = [p for p in (cookie_val or "").split(".") if p]
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="invalid_cookie")
    user_id, ts_raw, sig = parts

    try:
        ts = int(ts_raw)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid_cookie")

    age = int(time.time()) - ts
    if age < 0 or age > AUTH_COOKIE_MAX_AGE_SEC:
        raise HTTPException(status_code=401, detail="expired_cookie")

    expected = _auth_cookie_sig(user_id, ts)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="invalid_cookie")

    return user_id


def _issue_guest_cookie_if_missing(request: Request, response: Response) -> str | None:
    """Ensure a valid auth entity exists by issuing a guest cookie when missing.

    - If Bearer/cookie auth exists and valid: no-op.
    - If no auth: reuse X-User-Id if present, else create UUID, then set cookie.
    - If cookie exists but invalid/expired: do NOT mint a new one here; caller should surface 401.
    """

    request_id = get_request_id_from_request(request)

    # If Bearer is present, it must be valid; otherwise return 401 (do not mint guest).
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token.startswith("mock:") and len(token) > 5:
            return token[5:]
        rec = TOKENS.get(token)
        if isinstance(rec, dict) and (rec.get("user_id") or "").strip():
            return str(rec.get("user_id")).strip()
        raise HTTPException(status_code=401, detail="invalid_token")

    # If cookie exists, it must be valid; otherwise return 401 (do not mint guest).
    cookie_val = (request.cookies.get(_auth_cookie_name()) or "").strip()
    if cookie_val:
        return _parse_auth_cookie_user_id(cookie_val)

    # Already authenticated via legacy header? We'll reuse it but still set cookie.
    user_id = None
    try:
        existing = _get_user_id(request)
        if existing:
            user_id = existing
    except HTTPException:
        raise

    if not user_id:
        raw = (request.headers.get("X-User-Id") or "").strip()
        user_id = raw or str(uuid.uuid4())

    try:
        cookie_val = _make_auth_cookie_value(user_id)
        domain = _cookie_domain_for_request(request)
        response.set_cookie(
            key=_auth_cookie_name(),
            value=cookie_val,
            max_age=AUTH_COOKIE_MAX_AGE_SEC,
            httponly=True,
            secure=_is_https_request(request),
            samesite="lax",
            path="/",
            domain=domain,
        )
        log_event(
            "auth_guest_issued",
            request_id=request_id,
            user=_anon_user_key(user_id),
            domain=(domain or ""),
        )
        return user_id
    except Exception as e:
        log_event(
            "auth_missing",
            level="warning",
            request_id=request_id,
            reason=str(type(e).__name__),
        )
        return None


# ============================================================================
# Mock auth (OTP + offer) for local smoke tests
# ============================================================================

OTP_LATEST: dict[str, str] = {}
TOKENS: dict[str, dict] = {}


class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str


@app.post("/auth/otp/request")
def auth_otp_request(body: OtpRequest, request: Request):
    request_id = get_request_id_from_request(request)
    provider = (os.environ.get("SMS_PROVIDER") or "mock").strip().lower()
    phone_raw = (body.phone or "").strip()
    phone_e164 = _normalize_phone_e164(phone_raw)

    stage_static_code = (os.environ.get("STAGE_STATIC_OTP_CODE") or "").strip()
    if provider == "mock" and stage_static_code:
        # Stage-only convenience: when SMS_PROVIDER=mock and STAGE_STATIC_OTP_CODE is set,
        # issue the same 6-digit code for everyone.
        OTP_LATEST[phone_e164] = stage_static_code
        log_event("auth_otp_requested", request_id=request_id, provider=provider)
        return {"ok": True}

    def _digits(s: str) -> str:
        return "".join(ch for ch in s if ch.isdigit())

    # Backward-compatible convenience: fixed code for a fixed phone.
    static_phone = (os.environ.get("STATIC_OTP_PHONE") or "89062592834").strip()
    static_code = (os.environ.get("STATIC_OTP_CODE") or "1573").strip()
    if provider == "mock" and static_code and _digits(phone_raw) == _digits(static_phone):
        OTP_LATEST[phone_e164] = static_code
        log_event("auth_otp_requested", request_id=request_id, provider=provider)
        return {"ok": True}

    # Minimal mock: always generate a code; in real mode we would send SMS.
    code = str(int(time.time()))[-6:].rjust(6, "0")
    OTP_LATEST[phone_e164] = code
    log_event("auth_otp_requested", request_id=request_id, provider=provider)
    return {"ok": True}


@app.get("/debug/otp/latest")
def debug_otp_latest(phone: str, request: Request):
    if not _is_debug_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    request_id = get_request_id_from_request(request)
    phone_e164 = _normalize_phone_e164(phone)
    code = OTP_LATEST.get(phone_e164)
    if not code:
        raise HTTPException(status_code=404, detail="No OTP")
    log_event("debug_otp_latest", request_id=request_id)
    return {"ok": True, "phone": phone_e164, "code": code}


@app.post("/auth/otp/verify")
def auth_otp_verify(body: OtpVerify, request: Request):
    request_id = get_request_id_from_request(request)
    provider = (os.environ.get("SMS_PROVIDER") or "mock").strip().lower()
    phone_raw = (body.phone or "").strip()
    phone_e164 = _normalize_phone_e164(phone_raw)
    code = (body.code or "").strip()

    stage_static_code = (os.environ.get("STAGE_STATIC_OTP_CODE") or "").strip()
    if provider == "mock" and stage_static_code:
        if not hmac.compare_digest(code, stage_static_code):
            raise HTTPException(status_code=401, detail="Invalid code")
    else:
        expected = OTP_LATEST.get(phone_e164)

        def _digits(s: str) -> str:
            return "".join(ch for ch in s if ch.isdigit())

        static_phone = (os.environ.get("STATIC_OTP_PHONE") or "89062592834").strip()
        static_code = (os.environ.get("STATIC_OTP_CODE") or "1573").strip()

        if not expected or code != expected:
            if provider == "mock" and static_code and _digits(phone_raw) == _digits(static_phone):
                if not hmac.compare_digest(code, static_code):
                    raise HTTPException(status_code=401, detail="Invalid code")
            else:
                raise HTTPException(status_code=401, detail="Invalid code")

    # Stable UUID for this phone (server-side; no PII in user_id).
    user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "nly:phone:" + phone_e164))
    token = str(uuid.uuid4())
    TOKENS[token] = {"user_id": user_id, "phone_e164": phone_e164}
    try:
        ensure_user(user_id=user_id, phone_e164=phone_e164, request_id=request_id)
    except Exception:
        # best-effort
        pass
    log_event("auth_otp_verified", request_id=request_id)
    allow = _admin_phone_allowlist()
    return {
        "ok": True,
        "token": token,
        "user_id": user_id,
        "is_admin_candidate": (phone_e164 in allow),
    }


@app.post("/legal/offer/accept")
def legal_offer_accept(request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_user_id(request)
    log_event("legal_offer_accepted", request_id=request_id)
    return {"ok": True}


def _is_debug_enabled() -> bool:
    return (os.environ.get("DEBUG") or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _anon_user_key(user_id: str | None) -> str:
    if not user_id:
        return "anon"
    import hashlib
    return "u_" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]


def _make_minimal_pdf_bytes() -> bytes:
    """Generate a tiny valid PDF (with xref/startxref)."""
    parts: list[bytes] = []
    parts.append(b"%PDF-1.4\n")

    offsets: list[int] = []

    def add_obj(num: int, body: bytes):
        offsets.append(sum(len(p) for p in parts))
        parts.append(f"{num} 0 obj\n".encode("ascii"))
        parts.append(body)
        if not body.endswith(b"\n"):
            parts.append(b"\n")
        parts.append(b"endobj\n")

    add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>\n")
    add_obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n")
    add_obj(3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>\n")
    add_obj(4, b"<< /Length 0 >>\nstream\n\nendstream\n")

    xref_offset = sum(len(p) for p in parts)
    obj_count = 4
    parts.append(b"xref\n")
    parts.append(f"0 {obj_count + 1}\n".encode("ascii"))
    parts.append(b"0000000000 65535 f \n")
    for off in offsets:
        parts.append(f"{off:010d} 00000 n \n".encode("ascii"))
    parts.append(b"trailer\n")
    parts.append(f"<< /Size {obj_count + 1} /Root 1 0 R >>\n".encode("ascii"))
    parts.append(b"startxref\n")
    parts.append(f"{xref_offset}\n".encode("ascii"))
    parts.append(b"%%EOF\n")
    return b"".join(parts)


def _redis_client() -> redis.Redis:
    url = (os.environ.get("REDIS_URL") or "").strip() or "redis://localhost:6379/0"
    return redis.Redis.from_url(url, decode_responses=True)


RENDER_QUEUE_NAME = (os.environ.get("RENDER_QUEUE") or "render_jobs").strip() or "render_jobs"


def _load_documents_registry(request_id: str = "unknown") -> list[dict]:
    try:
        payload, _meta = resolve_config("documents_registry", request_id=request_id)
        if not isinstance(payload, dict):
            return []
        docs = payload.get("documents")
        if isinstance(docs, list):
            out = []
            for d in docs:
                if not isinstance(d, dict):
                    continue
                doc_id = (d.get("doc_id") or "").strip()
                if not doc_id:
                    continue
                out.append(d)
            return out
    except Exception:
        return []
    return []


def _doc_title(doc: dict) -> str:
    t = doc.get("title")
    return str(t) if t else str(doc.get("doc_id") or "document")


def _effective_doc_title(doc: dict, meta_row: dict | None) -> str:
    if meta_row and isinstance(meta_row, dict):
        t = meta_row.get("title")
        if t is not None and str(t).strip():
            return str(t)
    return _doc_title(doc)


def _effective_doc_enabled(doc: dict, access_row: dict | None) -> bool:
    # DB overlay wins. If no DB row, keep registry behavior (default True).
    if access_row and isinstance(access_row, dict):
        v = access_row.get("enabled")
        if v is not None:
            return bool(v)
    v = doc.get("is_enabled")
    if v is None:
        return True
    return bool(v)


def _doc_access_info(doc: dict, access_row: dict | None) -> dict:
    # Tier defaults to registry, DB overlay wins.
    tier = "free"
    enabled = True

    t0 = str((doc or {}).get("tier") or "").strip().lower()
    if t0 in {"free", "paid"}:
        tier = t0

    if access_row and isinstance(access_row, dict):
        t = str(access_row.get("tier") or "").strip().lower()
        if t in {"free", "paid"}:
            tier = t
        if access_row.get("enabled") is not None:
            enabled = bool(access_row.get("enabled"))

    force_all_free = _env_bool("DOCS_FORCE_ALL_FREE", False)
    paid_visible = _env_bool("PAID_DOCS_VISIBLE", True)

    eff_tier = "free" if force_all_free else tier
    is_locked = False
    reason: str | None = None
    if not enabled:
        reason = "DISABLED"
    elif eff_tier == "paid" and not force_all_free:
        is_locked = True
        reason = "PAID_DOCS_HIDDEN" if not paid_visible else "PAID_DOCS_LOCKED"

    return {
        "tier": eff_tier,
        "enabled": bool(enabled),
        "is_locked": bool(is_locked),
        "reason": reason,
    }


def _build_render_request(doc_id: str, title: str, pack_id: str, session_id: str) -> dict:
    return {
        "doc_id": doc_id,
        "title": title,
        "sections": [
            {"kind": "text", "title": "Содержимое", "text": "Базовый layout. Данные будут добавлены позже."}
        ],
        "meta": {"pack_id": pack_id, "session_id": session_id},
    }


class RenderJobCreateBody(BaseModel):
    pack_id: uuid.UUID
    session_id: uuid.UUID
    doc_id: str
    title: str
    sections: list[dict] = []
    meta: dict = {}


class RenderJobCreateResponse(BaseModel):
    ok: bool
    job_id: str
    status: str


class RenderJobStatusResponse(BaseModel):
    ok: bool
    job_id: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None = None


class MlJobCreateBody(BaseModel):
    session_id: str


class MlJobCreateResponse(BaseModel):
    ok: bool
    pack_id: str
    session_id: str


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.perf_counter()
    log_event(
        "request_received",
        request_id=request_id,
        route=str(request.url.path),
        method=request.method,
        content_length=request.headers.get("content-length"),
    )
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = compute_duration_ms(start_time)
        log_event(
            "request_error",
            level="error",
            request_id=request_id,
            route=str(request.url.path),
            method=request.method,
            duration_ms=duration_ms,
            error=str(exc),
        )
        raise
    log_event(
        "request_finished",
        request_id=request_id,
        route=str(request.url.path),
        method=request.method,
        status_code=response.status_code,
        duration_ms=compute_duration_ms(start_time),
    )
    response.headers["X-Request-Id"] = request_id
    return response

# Initialize database on startup
try:
    init_db()
except Exception as e:
    log_event(
        "db_error",
        level="error",
        route="startup",
        method="system",
        error=str(e),
    )

class SessionCreate(BaseModel):
    profession_query: str
    flow: str | None = None


class ChatMessage(BaseModel):
    session_id: str
    type: str
    text: str | None = None


class IntroDialogueResponse(BaseModel):
    assistant_text: str
    quick_replies: list[str] = []
    brief_patch: dict = {}
    ready_to_search: bool = False
    missing_fields: list[str] = []


P0_ORDER = [
    "source_mode",
    "problem",
    "hiring_goal",
    "role_title",
    "level",
    "location",
    "work_format",
    "salary_range",
    "urgency",
    "tasks_90d",
    "must_have",
]


def _p0_field_present(brief_state: dict, field_name: str) -> bool:
    bs = brief_state if isinstance(brief_state, dict) else {}
    v = bs.get(field_name)
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, list):
        return any(bool(str(x).strip()) for x in v)
    if isinstance(v, dict):
        return len(v) > 0
    if isinstance(v, bool):
        return True
    return True


def _intro_p0_missing_fields(brief_state: dict) -> list[str]:
    missing: list[str] = []
    for field in P0_ORDER:
        if not _p0_field_present(brief_state, field):
            missing.append(field)
    return missing


def _intro_choose_next_field(brief_state: dict) -> tuple[list[str], str | None]:
    missing = _intro_p0_missing_fields(brief_state)
    chosen = missing[0] if missing else None
    return missing, chosen


def _intro_question_for_field(field_name: str) -> tuple[str, list[str]]:
    if field_name == "source_mode":
        return (
            "Как удобнее дать вводные?",
            ["A — текст вакансии", "B — своими словами", "C — вопросы", "D — пропустить"],
        )
    if field_name == "problem":
        return ("Какая проблема/контекст у найма? (1–3 фразы)", [])
    if field_name == "hiring_goal":
        return ("Какая цель найма? Что должно измениться после выхода человека?", [])
    if field_name == "role_title":
        return ("Как называется роль (должность)?", [])
    if field_name == "level":
        return ("Какой уровень нужен (jun/mid/senior/lead)?", ["Junior", "Middle", "Senior", "Lead"])
    if field_name == "location":
        return ("Локация: город/регион?", ["Москва", "СПб", "Удалённо", "Любой город"])
    if field_name == "work_format":
        return ("Формат работы: офис/гибрид/удалёнка?", ["Офис", "Гибрид", "Удалённо"])
    if field_name == "salary_range":
        return ("Бюджет/вилка по оплате?", ["Есть вилка", "Обсудим", "Не знаю"])
    if field_name == "urgency":
        return ("Срочность: когда нужен человек?", ["Срочно", "1–2 месяца", "3+ месяца"])
    if field_name == "tasks_90d":
        return ("Какие 3–5 задач на первые 90 дней? (списком)", [])
    if field_name == "must_have":
        return ("Must-have требования: 3–7 пунктов? (списком)", [])
    return ("Уточни, пожалуйста, вводные.", [])


def _intro_apply_answer_to_field(brief_state: dict, field_name: str, text: str, profession_query: str) -> dict:
    patch: dict = {}
    t = (text or "").strip()
    if not t:
        return patch

    if field_name == "source_mode":
        mode = _intro_detect_mode(t)
        if mode == "A":
            patch[field_name] = "vacancy_text"
        elif mode == "B":
            patch[field_name] = "free_text"
        elif mode == "C":
            patch[field_name] = "questions"
        elif mode == "D":
            patch[field_name] = "skip"
        else:
            patch[field_name] = t[:80]
        return patch

    if field_name == "work_format":
        wf = parse_work_format(t)
        patch[field_name] = wf or t[:120]
        return patch

    if field_name == "location":
        city, region = parse_location(t)
        patch[field_name] = city or region or t[:120]
        return patch

    if field_name == "salary_range":
        s_min, s_max, s_comment = parse_salary(t)
        if s_min is not None or s_max is not None:
            patch[field_name] = {"min": s_min, "max": s_max}
        else:
            patch[field_name] = (s_comment or t)[:200]
        return patch

    if field_name in {"tasks_90d", "must_have"}:
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        items: list[str] = []
        for ln in lines:
            clean = re.sub(r"^[\-•*]\s*", "", ln)
            clean = re.sub(r"^\d+[\.)]\s*", "", clean)
            if clean:
                items.append(clean[:200])
        patch[field_name] = items[:10] if items else [t[:200]]
        return patch

    if field_name == "role_title":
        patch[field_name] = t[:120] or (profession_query or "")[:120]
        return patch

    patch[field_name] = t[:500]
    return patch


def _intro_mode_question() -> tuple[str, list[str]]:
    text = (
        "Как удобнее дать вводные?\n"
        "A) Вставить текст вакансии\n"
        "B) Описать своими словами\n"
        "C) Отвечать на короткие вопросы\n"
        "D) Пропустить и начать поиск"
    )
    qrs = ["A — текст вакансии", "B — своими словами", "C — вопросы", "D — пропустить"]
    return text, qrs


def _intro_detect_mode(text: str) -> str | None:
    low = (text or "").strip().lower()
    if not low:
        return None
    if low.startswith("a") or "текст ваканс" in low or "ваканси" in low:
        return "A"
    if low.startswith("b") or "своими" in low or "задач" in low or "опис" in low:
        return "B"
    if low.startswith("c") or "вопрос" in low:
        return "C"
    if low.startswith("d") or "пропуст" in low or "поехали" in low:
        return "D"
    # Compatibility with existing UI quick replies
    if "есть текст" in low and "ваканс" in low:
        return "A"
    if "нет ваканс" in low and "задач" in low:
        return "B"
    return None


def _intro_apply_text_to_kb(kb: dict, text: str, profession_query: str) -> None:
    if not isinstance(kb, dict):
        return
    t = (text or "").strip()
    if not t:
        return

    # Keep original text as raw vacancy/context (best-effort).
    try:
        if isinstance(kb.get("responsibilities"), dict):
            if not kb["responsibilities"].get("raw_vacancy_text"):
                kb["responsibilities"]["raw_vacancy_text"] = t
    except Exception:
        pass

    # Parse work format / employment / salary / location.
    try:
        wf = parse_work_format(t)
        if wf and isinstance(kb.get("company"), dict) and kb["company"].get("work_format") is None:
            kb["company"]["work_format"] = wf
    except Exception:
        pass

    try:
        emp = parse_employment_type(t)
        if emp and isinstance(kb.get("employment"), dict) and kb["employment"].get("employment_type") is None:
            kb["employment"]["employment_type"] = emp
    except Exception:
        pass

    try:
        s_min, s_max, s_comment = parse_salary(t)
        if isinstance(kb.get("compensation"), dict):
            if s_min is not None and kb["compensation"].get("salary_min_rub") is None:
                kb["compensation"]["salary_min_rub"] = s_min
            if s_max is not None and kb["compensation"].get("salary_max_rub") is None:
                kb["compensation"]["salary_max_rub"] = s_max
            if s_comment and kb["compensation"].get("salary_comment") is None:
                kb["compensation"]["salary_comment"] = s_comment
    except Exception:
        pass

    try:
        city, region = parse_location(t)
        if isinstance(kb.get("company"), dict):
            if city and kb["company"].get("company_location_city") is None:
                kb["company"]["company_location_city"] = city
            if region and kb["company"].get("company_location_region") is None:
                kb["company"]["company_location_region"] = region
    except Exception:
        pass

    # Fill role title if empty.
    try:
        if isinstance(kb.get("role"), dict):
            if kb["role"].get("role_title") is None:
                kb["role"]["role_title"] = (profession_query or t)[:120]
    except Exception:
        pass

    # Extract tasks from message if it looks like a list.
    try:
        if isinstance(kb.get("responsibilities"), dict) and isinstance(kb["responsibilities"].get("tasks"), list):
            if not kb["responsibilities"]["tasks"]:
                lines = [ln.strip(" \t\r") for ln in t.split("\n") if ln.strip()]
                bullets = []
                for ln in lines:
                    if ln.startswith(("-", "•", "*")):
                        bullets.append(ln.lstrip("-*• ").strip())
                if bullets:
                    kb["responsibilities"]["tasks"] = [b for b in bullets if b][:10]
                elif len(t) <= 180:
                    kb["responsibilities"]["tasks"] = [t]
    except Exception:
        pass

    try:
        update_meta(kb)
    except Exception:
        pass


def _brief_state_from_kb(profession_query: str, kb: dict, prev: dict | None = None) -> dict:
    bs = dict(prev or {})
    role_title = ""
    try:
        role_title = str(((kb.get("role") or {}).get("role_title") or "") if isinstance(kb.get("role"), dict) else "").strip()
    except Exception:
        role_title = ""
    role_title = role_title or (profession_query or "").strip()

    # Keep legacy shape for documents pipeline.
    constraints: dict = {}
    try:
        company = kb.get("company") if isinstance(kb.get("company"), dict) else {}
        comp = kb.get("compensation") if isinstance(kb.get("compensation"), dict) else {}
        location = ""
        city = str(company.get("company_location_city") or "").strip()
        region = str(company.get("company_location_region") or "").strip()
        wf = str(company.get("work_format") or "").strip()
        if city:
            location = city
        elif region:
            location = region
        if wf:
            location = (location + ", " + wf) if location else wf
        if location:
            constraints["location"] = location

        budget = ""
        smin = comp.get("salary_min_rub")
        smax = comp.get("salary_max_rub")
        scomment = str(comp.get("salary_comment") or "").strip()
        if scomment:
            budget = scomment
        elif smin is not None and smax is not None:
            budget = f"{smin}–{smax}"
        elif smin is not None:
            budget = str(smin)
        elif smax is not None:
            budget = str(smax)
        if budget:
            constraints["budget"] = budget
    except Exception:
        constraints = {}

    if role_title:
        bs["role"] = role_title
    # Goal is optional; keep if already present.
    if "goal" not in bs:
        bs["goal"] = ""
    bs["constraints"] = constraints
    return bs


def _intro_summary_text(profession_query: str, kb: dict) -> str:
    parts: list[str] = []
    role = ""
    try:
        role = str(((kb.get("role") or {}).get("role_title") or "") if isinstance(kb.get("role"), dict) else "").strip()
    except Exception:
        role = ""
    role = role or (profession_query or "").strip()
    if role:
        parts.append(f"- Роль: {role}")

    try:
        company = kb.get("company") if isinstance(kb.get("company"), dict) else {}
        city = str(company.get("company_location_city") or "").strip()
        region = str(company.get("company_location_region") or "").strip()
        wf = str(company.get("work_format") or "").strip()
        loc = city or region
        if loc or wf:
            value = (loc + ", " + wf) if (loc and wf) else (loc or wf)
            parts.append(f"- Локация/формат: {value}")
    except Exception:
        pass

    try:
        emp = kb.get("employment") if isinstance(kb.get("employment"), dict) else {}
        et = str(emp.get("employment_type") or "").strip()
        if et:
            parts.append(f"- Занятость: {et}")
    except Exception:
        pass

    try:
        comp = kb.get("compensation") if isinstance(kb.get("compensation"), dict) else {}
        smin = comp.get("salary_min_rub")
        smax = comp.get("salary_max_rub")
        scomment = str(comp.get("salary_comment") or "").strip()
        budget = scomment
        if not budget and smin is not None and smax is not None:
            budget = f"{smin}–{smax}"
        elif not budget and smin is not None:
            budget = str(smin)
        elif not budget and smax is not None:
            budget = str(smax)
        if budget:
            parts.append(f"- Бюджет: {budget}")
    except Exception:
        pass

    if not parts:
        return "Собрал вводные, можно начинать поиск."
    return "Собрал вводные:\n" + "\n".join(parts)


def _read_prompt_file(rel_path: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, rel_path)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _deep_merge_dict(base: dict, patch: dict) -> dict:
    out = dict(base or {})
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out.get(k) or {}, v)
        else:
            out[k] = v
    return out


def _intro_missing_fields(brief_state: dict) -> list[str]:
    role = (brief_state.get("role") or "").strip() if isinstance(brief_state.get("role"), str) else ""
    goal = (brief_state.get("goal") or "").strip() if isinstance(brief_state.get("goal"), str) else ""
    constraints = brief_state.get("constraints") if isinstance(brief_state.get("constraints"), dict) else {}

    location = (constraints.get("location") or "").strip() if isinstance(constraints.get("location"), str) else ""
    timeline = (constraints.get("timeline") or "").strip() if isinstance(constraints.get("timeline"), str) else ""
    budget = (constraints.get("budget") or "").strip() if isinstance(constraints.get("budget"), str) else ""

    missing: list[str] = []
    if not role:
        missing.append("role")
    if not goal:
        missing.append("goal")
    if not (location or timeline or budget):
        missing.append("constraints")
    return missing


def _intro_fallback_question(missing_fields: list[str]) -> tuple[str, list[str]]:
    if "role" in missing_fields:
        return "Кого ищем: какая роль и уровень?", ["Продакт", "Разработчик", "Маркетолог", "Другое"]
    if "goal" in missing_fields:
        return "Зачем нужен человек: какая цель/задача найма?", ["Усилить команду", "Срочно закрыть", "Проект", "Другое"]
    return "Есть ли ограничения: город/удалёнка, сроки или бюджет?", ["Город", "Сроки", "Бюджет", "Без ограничений"]


def _intro_heuristic_patch(text: str, missing_fields: list[str]) -> dict:
    """Best-effort parser to progress intro when LLM is unavailable.

    We deliberately keep it minimal: interpret the user's message as the value
    of the currently-missing top-level field.
    """
    t = (text or "").strip()
    if not t:
        return {}

    if "role" in (missing_fields or []):
        return {"role": t}
    if "goal" in (missing_fields or []):
        return {"goal": t}
    if "constraints" in (missing_fields or []):
        low = t.lower()
        constraints: dict = {}

        # Extremely lightweight signal extraction.
        if any(k in low for k in ["удал", "remote", "онлайн"]):
            constraints["location"] = "удалённо"
        elif any(k in low for k in ["офис", "очно"]):
            constraints["location"] = "офис"
        elif any(k in low for k in ["гибрид"]):
            constraints["location"] = "гибрид"

        # Budget/timeline hints.
        if any(k in low for k in ["руб", "₽", "к", "тыс", "млн", "budget", "бюджет"]):
            constraints["budget"] = t
        if any(k in low for k in ["недел", "месяц", "дн", "срок", "до "]):
            constraints["timeline"] = t

        # If nothing detected, store as location note to satisfy constraints.
        if not constraints:
            constraints["location"] = t

        return {"constraints": constraints}
    return {}


def _build_intro_messages(
    profession_query: str,
    brief_state: dict,
    last_user_message: str,
    missing_fields: list[str],
) -> list[dict]:
    system = _read_prompt_file("prompts/intro_system.md")
    tmpl = _read_prompt_file("prompts/intro_user_template.md")

    user = tmpl
    user = user.replace("{{profession_query}}", profession_query or "")
    user = user.replace("{{brief_state_json}}", json.dumps(brief_state or {}, ensure_ascii=False))
    user = user.replace("{{last_user_message}}", last_user_message or "")
    user = user.replace("{{missing_fields_csv}}", ", ".join(missing_fields or []) or "нет")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ----------------------------------------------------------------------
# Documents pipeline v1 helpers
# ----------------------------------------------------------------------


class DocContentResponse(BaseModel):
    doc_markdown: str = ""
    missing_fields: list[str] = []
    quality_notes: str | None = None


_DOC_CATALOG_CACHE: dict[str, object] = {"expires_at": 0.0, "items": []}


def _load_documents_catalog() -> list[dict]:
    now = time.time()
    try:
        if now < float(_DOC_CATALOG_CACHE.get("expires_at") or 0):
            cached = _DOC_CATALOG_CACHE.get("items")
            if isinstance(cached, list):
                return cached
    except Exception:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "documents", "catalog.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []

    _DOC_CATALOG_CACHE["items"] = items
    _DOC_CATALOG_CACHE["expires_at"] = now + 30.0
    return items


def _catalog_item(doc_id: str) -> Optional[dict]:
    did = (doc_id or "").strip()
    for item in _load_documents_catalog():
        if str((item or {}).get("id") or "").strip() == did:
            return item
    return None


def _get_by_path(obj: object, path: str) -> object:
    if not path:
        return None
    cur: object = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur.get(part)
        else:
            return None
    return cur


def _required_fields_missing(brief_state: dict, required_fields: list[str]) -> list[str]:
    missing: list[str] = []
    bs = brief_state if isinstance(brief_state, dict) else {}

    for field in (required_fields or []):
        f = str(field or "").strip()
        if not f:
            continue

        if f == "constraints":
            c = bs.get("constraints") if isinstance(bs.get("constraints"), dict) else {}
            location = (c.get("location") or "").strip() if isinstance(c.get("location"), str) else ""
            timeline = (c.get("timeline") or "").strip() if isinstance(c.get("timeline"), str) else ""
            budget = (c.get("budget") or "").strip() if isinstance(c.get("budget"), str) else ""
            if not (location or timeline or budget):
                missing.append("constraints")
            continue

        value = _get_by_path(bs, f)
        ok = False
        if isinstance(value, str):
            ok = bool(value.strip())
        elif isinstance(value, (list, dict)):
            ok = len(value) > 0
        else:
            ok = value is not None
        if not ok:
            missing.append(f)
    return missing


def _build_doc_messages(doc_id: str, profession_query: str, brief_state: dict) -> list[dict]:
    try:
        system = _read_prompt_file(f"prompts/docs/{doc_id}/system.md")
        tmpl = _read_prompt_file(f"prompts/docs/{doc_id}/user_template.md")
    except FileNotFoundError:
        cat = _catalog_item(doc_id) or {}
        title = str(cat.get("title") or doc_id).strip() or doc_id
        system = (
            "Ты — ассистент, который готовит контент документа для найма.\n\n"
            "Верни строго JSON (без Markdown и без пояснений):\n"
            "{\n"
            "  \"doc_markdown\": \"...\",\n"
            "  \"missing_fields\": [\"...\"],\n"
            "  \"quality_notes\": \"...\"\n"
            "}\n\n"
            "Правила:\n"
            "- Ничего не выдумывай.\n"
            "- Если данных не хватает — перечисли missing_fields.\n"
            "- doc_markdown: простой markdown (заголовки #/##, списки, абзацы).\n"
        )
        tmpl = (
            f"Сгенерируй документ: {title} (doc_id={doc_id}).\n\n"
            "Контекст:\n"
            "- profession_query: {{profession_query}}\n"
            "- brief_state (JSON):\n"
            "{{brief_state_json}}\n\n"
            "Требования к doc_markdown:\n"
            "- Структурируй материал с подзаголовками и списками.\n"
            "- Дай практичные шаблоны/скрипты/чеклисты там, где это уместно.\n"
            "Если не хватает данных — верни missing_fields (doc_markdown может быть неполным).\n"
        )
    user = tmpl
    user = user.replace("{{profession_query}}", profession_query or "")
    user = user.replace("{{brief_state_json}}", json.dumps(brief_state or {}, ensure_ascii=False))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _heuristic_doc_markdown(doc_id: str, title: str, profession_query: str, brief_state: dict) -> str:
    bs = brief_state if isinstance(brief_state, dict) else {}
    role = str(bs.get("role") or profession_query or "").strip()
    goal = str(bs.get("goal") or "").strip()
    c = bs.get("constraints") if isinstance(bs.get("constraints"), dict) else {}
    location = str(c.get("location") or "").strip()
    timeline = str(c.get("timeline") or "").strip()
    budget = str(c.get("budget") or "").strip()

    lines: list[str] = [f"# {title}", ""]
    lines.append("## Вводные")
    if role:
        lines.append(f"- Роль: {role}")
    if goal:
        lines.append(f"- Цель: {goal}")
    if location or timeline or budget:
        lines.append("- Ограничения:")
        if location:
            lines.append(f"  - Локация/формат: {location}")
        if timeline:
            lines.append(f"  - Сроки: {timeline}")
        if budget:
            lines.append(f"  - Бюджет: {budget}")

    lines.append("")
    if doc_id == "vacancy_draft":
        lines += [
            "## Черновик вакансии",
            f"**Должность:** {role or profession_query or 'Специалист'}",
            "",
            "### Задачи",
            "- (заполнить)",
            "",
            "### Требования",
            "- (заполнить)",
            "",
            "### Условия",
            f"- {location or 'Формат: (уточнить)'}",
            f"- {budget or 'Оплата: (уточнить)'}",
        ]
    elif doc_id == "interview_plan":
        lines += [
            "## План интервью",
            "### Структура (30–45 минут)",
            "- 5 мин — вводные и контекст",
            "- 15 мин — опыт по релевантным кейсам",
            "- 10 мин — разбор задачи/ситуации",
            "- 5 мин — условия и ожидания",
            "- 5 мин — вопросы кандидата",
            "",
            "### Вопросы",
            "- Расскажи о самом похожем проекте",
            "- Как принимаешь решения и оцениваешь риски?",
            "- Что для тебя важно в работе/команде?",
        ]
    else:
        # search_brief and other docs
        lines += [
            "## Критерии кандидата",
            "- Опыт: (уточнить)",
            "- Навыки: (уточнить)",
            "- Софт-скилы: (уточнить)",
            "",
            "## Каналы поиска",
            "- Рекомендации",
            "- Площадки вакансий",
            "- Сообщества",
        ]

    return "\n".join(lines).strip() + "\n"


def _apply_template_body(
    *,
    template_body: str,
    title: str,
    doc_markdown: str,
    generated_at: str,
) -> str:
    body = template_body or "{{doc_markdown}}"
    body = body.replace("{{title}}", title or "")
    body = body.replace("{{generated_at}}", generated_at)
    body = body.replace("{{doc_markdown}}", doc_markdown or "")
    return body


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _render_pdf_bytes(*, title: str, markdown: str, meta: dict) -> tuple[bool, bytes | None, str | None]:
    render_url = (os.environ.get("RENDER_URL") or "").strip() or "http://localhost:8002"
    payload = {"title": title, "markdown": markdown, "meta": meta or {}}
    return _http_post_json_bytes(f"{render_url.rstrip('/')}/render/pdf", payload, timeout_sec=60.0)


def make_empty_vacancy_kb():
    """Create an empty vacancy knowledge base."""
    return {
        "role": {
            "role_title": None,
            "role_domain": None,
            "role_seniority": None,
        },
        "company": {
            "company_location_city": None,
            "company_location_region": None,
            "work_format": None,  # office/hybrid/remote/unknown
        },
        "compensation": {
            "salary_min_rub": None,
            "salary_max_rub": None,
            "salary_comment": None,
        },
        "employment": {
            "employment_type": None,  # full-time/part-time/project/unknown
            "schedule_comment": None,
        },
        "requirements": {
            "experience_years_min": None,
            "education_level": None,  # courses/higher/specialized/unknown
            "hard_skills": [],
            "soft_skills": [],
        },
        "responsibilities": {
            "tasks": [],
            "raw_vacancy_text": None,
        },
        "sourcing": {
            "suggested_channels": [],
        },
        "meta": {
            "filled_fields_count": 0,
            "missing_fields": [],
            "last_updated_iso": None,
        },
    }


def count_filled_fields(kb):
    """Count filled scalar and list fields in vacancy KB."""
    count = 0
    for section in kb:
        if section == "meta":
            continue
        for field, value in kb[section].items():
            if isinstance(value, list):
                count += len(value)
            elif value is not None and value != "":
                count += 1
    return count


def compute_missing_fields(kb):
    """Compute required missing fields for MVP."""
    missing = []
    
    # Must-have 1: role title OR tasks not empty
    has_role_title = kb["role"]["role_title"] is not None
    has_tasks = len(kb["responsibilities"]["tasks"]) > 0
    if not (has_role_title or has_tasks):
        missing.append("role.role_title OR responsibilities.tasks")
    
    # Must-have 2: work format
    if kb["company"]["work_format"] is None:
        missing.append("company.work_format")
    
    # Must-have 3: location (city OR region)
    has_city = kb["company"]["company_location_city"] is not None
    has_region = kb["company"]["company_location_region"] is not None
    if not (has_city or has_region):
        missing.append("company.company_location_city OR company_location_region")
    
    # Must-have 4: employment type
    if kb["employment"]["employment_type"] is None:
        missing.append("employment.employment_type")
    
    # Must-have 5: compensation (at least one of three)
    has_salary = (
        kb["compensation"]["salary_min_rub"] is not None
        or kb["compensation"]["salary_max_rub"] is not None
        or kb["compensation"]["salary_comment"] is not None
    )
    if not has_salary:
        missing.append("compensation (min/max/comment)")
    
    return missing


def to_iso(dt_value):
    """Convert datetime to ISO string if applicable."""
    if isinstance(dt_value, datetime):
        return dt_value.isoformat()
    return dt_value


def update_meta(kb):
    """Update meta fields: filled_fields_count, missing_fields, last_updated_iso."""
    kb["meta"]["filled_fields_count"] = count_filled_fields(kb)
    kb["meta"]["missing_fields"] = compute_missing_fields(kb)
    kb["meta"]["last_updated_iso"] = datetime.utcnow().isoformat() + "Z"


def kb_meta_counts(kb):
    meta = kb.get("meta", {})
    missing_fields = meta.get("missing_fields") or []
    return {
        "filled_fields_count": meta.get("filled_fields_count", 0),
        "missing_fields_count": len(missing_fields),
    }


def template_questions_and_quick_replies(missing_fields):
    questions = []
    quick_replies = []
    if any("company.work_format" in f for f in missing_fields):
        questions.append("Какой формат работы: офис, гибрид или удаленка?")
        quick_replies.extend(["Офис", "Гибрид", "Удаленка"])
    if any("company_location" in f for f in missing_fields):
        questions.append("В каком городе или регионе ищешь?")
        quick_replies.append("Москва")
    if any("employment.employment_type" in f for f in missing_fields):
        questions.append("Какая занятость: полный день, частичная или проект?")
        quick_replies.append("Полный день")
    if any("compensation" in f for f in missing_fields):
        questions.append("Какой бюджет или вилка по оплате?")
        quick_replies.append("Есть бюджет")

    # Deduplicate quick replies
    seen = set()
    unique_qr = []
    for qr in quick_replies:
        if qr not in seen:
            unique_qr.append(qr)
            seen.add(qr)
    return questions, unique_qr[:6]


def build_clarification_prompt(session_id, kb, profession_query, last_user_message, request):
    request_id = get_request_id_from_request(request)
    missing_fields = kb.get("meta", {}).get("missing_fields", [])
    context = {
        "session_id": session_id,
        "profession_query": profession_query,
        "missing_fields": missing_fields,
        "vacancy_kb": kb,
        "last_user_message": last_user_message,
        "request_id": request_id,
    }
    questions = []
    quick_replies = []

    try:
        result = generate_questions_and_quick_replies(context)
        if isinstance(result, dict):
            questions = result.get("questions") or []
            quick_replies = result.get("quick_replies") or []
    except LLMUnavailable as e:
        log_event(
            "llm_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            route=str(request.url.path),
            method=request.method,
            reason=str(getattr(e, "reason", "llm_unavailable")),
            error=str(e),
        )
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {getattr(e, 'reason', 'missing_api_key')}")
    except Exception as e:
        log_event(
            "llm_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            route=str(request.url.path),
            method=request.method,
            error=str(e),
        )

    if not questions:
        questions, _qr = template_questions_and_quick_replies(missing_fields)
        quick_replies = quick_replies or _qr
    if not quick_replies:
        _q, quick_replies = template_questions_and_quick_replies(missing_fields)

    questions = [q for q in questions if isinstance(q, str)][:3]
    quick_replies = [qr for qr in quick_replies if isinstance(qr, str)][:6]

    reply_lines = ["Давай уточним, чтобы собрать отчет:"]
    for q in questions:
        reply_lines.append(f"- {q}")
    reply_text = "\n".join(reply_lines)

    return reply_text, quick_replies, questions


def parse_work_format(text):
    """Simple heuristic for work_format from text."""
    low = text.lower()
    if "удал" in low or "remote" in low or "дистанц" in low:
        return "remote"
    if "гибрид" in low:
        return "hybrid"
    if "офис" in low or "office" in low:
        return "office"
    return None


def parse_employment_type(text):
    low = text.lower()
    if "проект" in low or "project" in low or "контракт" in low:
        return "project"
    if "част" in low or "part" in low:
        return "part-time"
    if "полный" in low or "full" in low:
        return "full-time"
    return None


def parse_salary(text):
    cleaned = text.replace("\xa0", " ")
    numbers = []
    for match in re.findall(r"\b\d{2,6}\b", cleaned):
        try:
            numbers.append(int(match.replace(" ", "")))
        except ValueError:
            continue
    numbers = [n for n in numbers if n > 0]
    if len(numbers) >= 2:
        low, high = min(numbers), max(numbers)
        return low, high, None
    if len(numbers) == 1:
        return numbers[0], None, None
    low_text = cleaned.lower()
    if any(word in low_text for word in ["бюджет", "вилка", "зарп"]):
        return None, None, cleaned.strip()
    return None, None, None


def parse_location(text):
    low = text.lower()
    city_map = {
        "моск": "Москва",
        "moscow": "Москва",
        "спб": "Санкт-Петербург",
        "питер": "Санкт-Петербург",
        "санкт-петербург": "Санкт-Петербург",
        "казан": "Казань",
        "новосиб": "Новосибирск",
        "екатеринбург": "Екатеринбург",
    }
    for key, city in city_map.items():
        if key in low:
            return city, None

    match = re.search(r"в\s+([A-Za-zА-Яа-яЁё\-\s]{3,30})", text)
    if match:
        candidate = match.group(1).strip()
        if candidate:
            return candidate.title(), None

    if any(word in low for word in ["регион", "любой город", "удал"]):
        return None, text.strip() if len(text.strip()) < 100 else None
    return None, None


def ensure_session(sid: str, profession_query: str | None = None):
    if sid not in SESSIONS:
        SESSIONS[sid] = {
            "profession_query": profession_query or "",
            "state": "awaiting_flow",
            "vacancy_text": None,
            "tasks": None,
            "clarifications": [],
            "vacancy_kb": make_empty_vacancy_kb(),
        }
    return SESSIONS[sid]


@app.post("/chat/message")
def chat_message(body: ChatMessage, request: Request):
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    sid = body.session_id
    msg_type = body.type
    text = (body.text or "").strip()

    # Ensure session exists
    session = ensure_session(sid)
    
    # Try to load from database
    try:
        db_session = get_session(sid, request_id=request_id)
        if db_session:
            session = {
                "profession_query": db_session.get("profession_query", ""),
                "state": db_session.get("chat_state", "awaiting_flow"),
                "vacancy_text": None,
                "tasks": None,
                "clarifications": [],
                "vacancy_kb": db_session.get("vacancy_kb", make_empty_vacancy_kb()),
                "phase": db_session.get("phase"),
                "brief_state": db_session.get("brief_state") or {},
            }
            SESSIONS[sid] = session
    except Exception as e:
        log_event(
            "db_error",
            level="error",
            request_id=request_id,
            session_id=sid,
            route=str(request.url.path),
            method=request.method,
            error=str(e),
        )

    kb_counts = kb_meta_counts(session.get("vacancy_kb", make_empty_vacancy_kb()))
    state_before = session.get("state")
    log_event(
        "chat_message_received",
        request_id=request_id,
        session_id=sid,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
        message_type=msg_type,
        chat_state_before=state_before,
        filled_fields_count=kb_counts.get("filled_fields_count"),
        missing_fields_count=kb_counts.get("missing_fields_count"),
    )

    def log_reply(event_name="chat_reply_sent", **extra_fields):
        kb_counts_after = kb_meta_counts(session.get("vacancy_kb", make_empty_vacancy_kb()))
        log_event(
            event_name,
            request_id=request_id,
            session_id=sid,
            route=str(request.url.path),
            method=request.method,
            duration_ms=compute_duration_ms(start_time),
            chat_state_after=session.get("state"),
            filled_fields_count=kb_counts_after.get("filled_fields_count"),
            missing_fields_count=kb_counts_after.get("missing_fields_count"),
            **extra_fields,
        )

    # default response
    reply = ""
    quick_replies = []
    clarifying_questions = []
    should_show_free_result = False

    state = session.get("state")

    # ----------------------------------------------------------------------
    # PR-LLM-INTRO-DIALOGUE: intro flow (opt-in via type or session state)
    # ----------------------------------------------------------------------

    is_intro_type = msg_type in {"intro_start", "intro_message", "intro"}
    is_intro_session = str(state or "").strip().lower() == "intro" or str(session.get("phase") or "").strip().upper() in {
        "INTRO",
        "CLARIFY",
        "SEARCH",
        "DONE",
    }

    if is_intro_type or is_intro_session:
        user_id = _get_user_id(request)
        if user_id:
            try:
                set_session_user(sid, user_id, request_id=request_id)
            except Exception:
                pass

        profession_query = str(session.get("profession_query", "") or "")
        brief_state = session.get("brief_state") if isinstance(session.get("brief_state"), dict) else {}
        phase = str(session.get("phase") or "INTRO_P0").strip().upper() or "INTRO_P0"

        # STOP rule: once DONE or ready_to_search is set, never call LLM and never ask questions.
        if phase == "DONE" or bool(brief_state.get("ready_to_search")):
            trace_artifact(
                session_id=sid,
                kind="intro_stop",
                request_id=request_id,
                payload_json={"reason": "already_done"},
                meta={"flow": "intro", "phase": phase},
            )
            return {
                "ok": True,
                "type": "intro_done",
                "reply": "Готово. Можно переходить к документам.",
                "assistant_text": "Готово. Можно переходить к документам.",
                "quick_replies": [],
                "brief_patch": {},
                "brief_state": brief_state,
                "ready_to_search": True,
                "next_action": "show_documents",
                "missing_fields": [],
                "documents_ready": False,
                "documents": [],
            }

        # Ensure stable structure.
        if not isinstance(brief_state, dict):
            brief_state = {}
        intro_meta = brief_state.get("intro") if isinstance(brief_state.get("intro"), dict) else {}

        # Start flow.
        if msg_type in {"intro_start", "intro"}:
            missing, chosen = _intro_choose_next_field(brief_state)
            if not chosen:
                chosen = "source_mode"
                missing = P0_ORDER[:]
            q, qrs = _intro_question_for_field(chosen)
            intro_meta["current_field"] = chosen
            brief_state["intro"] = intro_meta

            trace_artifact(
                session_id=sid,
                kind="intro_missing_fields",
                request_id=request_id,
                payload_json={"missing": missing, "chosen_field": chosen},
                meta={"flow": "intro", "phase": "INTRO_P0"},
            )

            try:
                add_message(sid, "assistant", q, request_id=request_id)
                update_session(
                    sid,
                    chat_state="intro",
                    phase="INTRO_P0",
                    brief_state=brief_state,
                    request_id=request_id,
                )
            except Exception:
                pass
            return {
                "ok": True,
                "type": "intro_question",
                "reply": q,
                "assistant_text": q,
                "quick_replies": qrs,
                "brief_patch": {},
                "brief_state": brief_state,
                "ready_to_search": False,
                "missing_fields": missing,
                "documents_ready": False,
                "documents": [],
            }

        # intro_message
        if text:
            try:
                add_message(sid, "user", text, request_id=request_id)
            except Exception:
                pass

        current_field = str(intro_meta.get("current_field") or "").strip()
        brief_patch: dict = {}
        if current_field and text:
            brief_patch = _intro_apply_answer_to_field(brief_state, current_field, text, profession_query)
            if brief_patch:
                brief_state = _deep_merge_dict(brief_state, brief_patch)

        # Next step: recompute missing and deterministically choose next.
        missing, chosen = _intro_choose_next_field(brief_state)
        if not chosen:
            # DONE
            brief_state["ready_to_search"] = True
            trace_artifact(
                session_id=sid,
                kind="intro_done",
                request_id=request_id,
                payload_json={},
                meta={"flow": "intro", "phase": "DONE"},
            )

            # Idempotent intro_brief artifact (max 1 per session).
            try:
                existing = get_artifact_by_session_kind(session_id=sid, kind="intro_brief", request_id=request_id)
            except Exception:
                existing = None
            if not existing:
                try:
                    create_artifact(
                        session_id=sid,
                        kind="intro_brief",
                        format="json",
                        payload_json={"title": "Бриф поиска", "brief_state": brief_state},
                        meta={"title": "Бриф поиска"},
                        request_id=request_id,
                    )
                except Exception:
                    pass

            try:
                update_session(
                    sid,
                    chat_state="intro",
                    phase="DONE",
                    brief_state=brief_state,
                    request_id=request_id,
                )
            except Exception:
                pass

            assistant_text = "Готово. Можно переходить к документам."
            try:
                add_message(sid, "assistant", assistant_text, request_id=request_id)
            except Exception:
                pass
            return {
                "ok": True,
                "type": "intro_done",
                "reply": assistant_text,
                "assistant_text": assistant_text,
                "quick_replies": [],
                "brief_patch": brief_patch,
                "brief_state": brief_state,
                "ready_to_search": True,
                "next_action": "show_documents",
                "missing_fields": [],
                "documents_ready": False,
                "documents": [],
            }

        # Ask next missing field.
        q, qrs = _intro_question_for_field(chosen)
        intro_meta["current_field"] = chosen
        brief_state["intro"] = intro_meta

        trace_artifact(
            session_id=sid,
            kind="intro_missing_fields",
            request_id=request_id,
            payload_json={"missing": missing, "chosen_field": chosen},
            meta={"flow": "intro", "phase": "INTRO_P0"},
        )

        try:
            update_session(
                sid,
                chat_state="intro",
                phase="INTRO_P0",
                brief_state=brief_state,
                request_id=request_id,
            )
        except Exception:
            pass
        try:
            add_message(sid, "assistant", q, request_id=request_id)
        except Exception:
            pass

        return {
            "ok": True,
            "type": "intro_question",
            "reply": q,
            "assistant_text": q,
            "quick_replies": qrs[:6],
            "brief_patch": brief_patch,
            "brief_state": brief_state,
            "ready_to_search": False,
            "missing_fields": missing,
            "documents_ready": False,
            "documents": [],
        }

    if msg_type == "start":
        session["state"] = "awaiting_flow"
        reply = "Привет! Супер, что ты решил подойти к найму спокойно. Есть текст вакансии или только описание задач?"
        quick_replies = ["Есть текст вакансии", "Нет вакансии, есть задачи"]
        should_show_free_result = False
        
        # Save to DB
        try:
            add_message(sid, "assistant", reply, request_id=request_id)
            update_session(sid, chat_state=session["state"], request_id=request_id)
        except Exception as e:
            log_event(
                "db_error",
                level="error",
                request_id=request_id,
                session_id=sid,
                route=str(request.url.path),
                method=request.method,
                error=str(e),
            )
        
        log_reply(state=session["state"])
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": should_show_free_result}

    # Save user message
    if text:
        try:
            add_message(sid, "user", text, request_id=request_id)
        except Exception as e:
            log_event(
                "db_error",
                level="error",
                request_id=request_id,
                session_id=sid,
                route=str(request.url.path),
                method=request.method,
                error=str(e),
            )

    # user messages
    if state == "awaiting_flow":
        low = text.lower()
        if "есть" in low and "ваканс" in low:
            session["state"] = "awaiting_vacancy_text"
            reply = "Понял — вставь, пожалуйста, текст вакансии целиком."
        elif "нет" in low and ("ваканс" in low or "опис" in low):
            session["state"] = "awaiting_tasks"
            reply = "Хорошо — опиши, пожалуйста, 5–10 задач тезисно."
        else:
            reply = "Не совсем понял. Есть текст вакансии или только задачи?"
            quick_replies = ["Есть текст вакансии", "Нет вакансии, есть задачи"]
        
        try:
            add_message(sid, "assistant", reply, request_id=request_id)
            update_session(sid, chat_state=session["state"], vacancy_kb=session["vacancy_kb"], request_id=request_id)
        except Exception as e:
            log_event(
                "db_error",
                level="error",
                request_id=request_id,
                session_id=sid,
                route=str(request.url.path),
                method=request.method,
                error=str(e),
            )
        
        log_reply(state=session["state"])
        return {
            "reply": reply,
            "quick_replies": quick_replies,
            "clarifying_questions": clarifying_questions,
            "should_show_free_result": False,
        }

    if state == "awaiting_vacancy_text":
        # accept long text
        if len(text) > 200:
            session["vacancy_text"] = text
            session["state"] = "awaiting_clarifications"
            
            # Update KB: raw text and extract tasks
            kb = session["vacancy_kb"]
            kb["responsibilities"]["raw_vacancy_text"] = text
            
            # Simple task extraction: split by newlines, filter empty
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            if lines:
                # Try to find bullet points or numbered items
                tasks = []
                for line in lines:
                    # Remove common prefixes: -, •, number)
                    clean = re.sub(r'^[\-•]\s*', '', line)
                    clean = re.sub(r'^\d+[\.\)]\s*', '', clean)
                    if clean and len(clean) > 5:
                        tasks.append(clean)
                
                if tasks:
                    kb["responsibilities"]["tasks"] = tasks[:10]  # limit to 10
                else:
                    kb["responsibilities"]["tasks"] = ["См. текст вакансии выше"]
            else:
                kb["responsibilities"]["tasks"] = ["См. текст вакансии выше"]
            
            update_meta(kb)
            log_event(
                "vacancy_kb_updated",
                request_id=request_id,
                session_id=sid,
                route=str(request.url.path),
                method=request.method,
                duration_ms=compute_duration_ms(start_time),
            )
            
            reply, quick_replies, clarifying_questions = build_clarification_prompt(
                sid,
                kb,
                session.get("profession_query", ""),
                text,
                request,
            )
        else:
            reply = "Пожалуйста, вставь текст вакансии целиком (подробнее, >200 символов)."
        
        try:
            add_message(sid, "assistant", reply, request_id=request_id)
            update_session(sid, chat_state=session["state"], vacancy_kb=session["vacancy_kb"], request_id=request_id)
        except Exception as e:
            log_event(
                "db_error",
                level="error",
                request_id=request_id,
                session_id=sid,
                route=str(request.url.path),
                method=request.method,
                error=str(e),
            )
        
        log_reply(state=session["state"])
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

    if state == "awaiting_tasks":
        session["tasks"] = text
        session["state"] = "awaiting_clarifications"
        
        # Update KB: parse tasks
        kb = session["vacancy_kb"]
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if lines:
            tasks = []
            for line in lines:
                # Remove common prefixes
                clean = re.sub(r'^[\-•]\s*', '', line)
                clean = re.sub(r'^\d+[\.\)]\s*', '', clean)
                if clean and len(clean) > 3:
                    tasks.append(clean)
            if tasks:
                kb["responsibilities"]["tasks"] = tasks[:10]
        
        update_meta(kb)
        log_event(
            "vacancy_kb_updated",
            request_id=request_id,
            session_id=sid,
            route=str(request.url.path),
            method=request.method,
            duration_ms=compute_duration_ms(start_time),
        )
        
        reply, quick_replies, clarifying_questions = build_clarification_prompt(
            sid,
            kb,
            session.get("profession_query", ""),
            text,
            request,
        )
        
        try:
            add_message(sid, "assistant", reply, request_id=request_id)
            update_session(sid, chat_state=session["state"], vacancy_kb=session["vacancy_kb"], request_id=request_id)
        except Exception as e:
            log_event(
                "db_error",
                level="error",
                request_id=request_id,
                session_id=sid,
                route=str(request.url.path),
                method=request.method,
                error=str(e),
            )
        
        log_reply(state=session["state"])
        return {
            "reply": reply,
            "quick_replies": quick_replies,
            "clarifying_questions": clarifying_questions,
            "should_show_free_result": False,
        }

    if state == "awaiting_clarifications":
        session.setdefault("clarifications", []).append(text)
        session["state"] = "free_ready"
        
        # Update KB: parse clarifications (город/формат, бюджет, занятость)
        kb = session["vacancy_kb"]
        
        # Try to parse work_format
        fmt = parse_work_format(text)
        if fmt:
            kb["company"]["work_format"] = fmt
        
        # Try to parse employment_type
        emp = parse_employment_type(text)
        if emp:
            kb["employment"]["employment_type"] = emp
        
        # Try to parse salary
        sal_min, sal_max, sal_comment = parse_salary(text)
        if sal_min is not None:
            kb["compensation"]["salary_min_rub"] = sal_min
        if sal_max is not None:
            kb["compensation"]["salary_max_rub"] = sal_max
        if sal_comment is not None:
            kb["compensation"]["salary_comment"] = sal_comment
        
        # Try to parse location
        city, region = parse_location(text)
        if city:
            kb["company"]["company_location_city"] = city
        if region:
            kb["company"]["company_location_region"] = region
        
        update_meta(kb)
        log_event(
            "vacancy_kb_updated",
            request_id=request_id,
            session_id=sid,
            route=str(request.url.path),
            method=request.method,
            duration_ms=compute_duration_ms(start_time),
        )
        
        reply = "Готово! Я собрал бесплатный результат ниже."
        should_show_free_result = True
        
        try:
            add_message(sid, "assistant", reply)
            update_session(sid, chat_state=session["state"], vacancy_kb=session["vacancy_kb"])
        except Exception as e:
            log_event(
                "db_error",
                level="error",
                request_id=request_id,
                session_id=sid,
                route=str(request.url.path),
                method=request.method,
                error=str(e),
            )
        
        log_reply(state=session["state"], should_show_free_result=should_show_free_result)
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": should_show_free_result}

    # fallback
    reply = "Хорошо, записал."
    try:
        add_message(sid, "assistant", reply, request_id=request_id)
        update_session(sid, chat_state=session["state"], vacancy_kb=session["vacancy_kb"], request_id=request_id)
    except Exception as e:
        log_event(
            "db_error",
            level="error",
            request_id=request_id,
            session_id=sid,
            route=str(request.url.path),
            method=request.method,
            error=str(e),
        )
    
    log_reply(state=session.get("state"))
    return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db(request: Request):
    """Check database connectivity."""
    request_id = get_request_id_from_request(request)
    db_ok = health_check(request_id=request_id)
    return {"ok": db_ok}


@app.get("/health/llm")
def health_llm_endpoint():
    return health_llm()


@app.get("/health/sms")
def health_sms():
    """Check SMS provider configuration (env-only; no network)."""
    provider = (os.environ.get("SMS_PROVIDER") or "mock").strip().lower()
    # We deliberately don't validate credentials here (Stage 9.3.0 baseline).
    return {
        "ok": True,
        "provider": provider,
    }


@app.get("/health/s3")
def health_s3(request: Request):
    """Check S3 configuration (env-only; no network).

    In DEBUG mode, may run a lightweight head_bucket.
    """
    request_id = get_request_id_from_request(request)
    payload = health_s3_env()
    bucket = payload.get("bucket")
    if bucket:
        debug_head = head_bucket_if_debug(bucket)
        if debug_head is not None:
            payload["debug_head_bucket_ok"] = debug_head
    log_event(
        "health_s3",
        request_id=request_id,
        ok=payload.get("ok"),
        bucket=payload.get("bucket"),
        endpoint=payload.get("endpoint"),
        has_credentials=payload.get("has_credentials"),
    )
    return payload


@app.get("/vacancy")
def get_vacancy(session_id: str, request: Request):
    """Get vacancy knowledge base for a session."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    session = ensure_session(session_id)
    kb = session.get("vacancy_kb", make_empty_vacancy_kb())
    
    # Also try to load from database
    try:
        db_session = get_session(session_id, request_id=request_id)
        if db_session and db_session.get("vacancy_kb"):
            kb = db_session["vacancy_kb"]
    except Exception as e:
        log_event(
            "db_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            route=str(request.url.path),
            method=request.method,
            error=str(e),
        )
    
    log_event(
        "vacancy_kb_read",
        request_id=request_id,
        session_id=session_id,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
    )
    
    return {
        "session_id": session_id,
        "vacancy_kb": kb,
        "missing_fields": kb["meta"]["missing_fields"],
        "filled_fields_count": kb["meta"]["filled_fields_count"],
    }


@app.get("/report/free")
def get_free_report(session_id: str, request: Request):
    """Generate and return a free report from the vacancy KB."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    session = ensure_session(session_id)
    kb = session.get("vacancy_kb", make_empty_vacancy_kb())
    profession_query = session.get("profession_query", "")

    # Try to load from database first
    try:
        db_session = get_session(session_id, request_id=request_id)
        if db_session:
            if db_session.get("free_report"):
                log_event(
                    "free_report_cache_hit",
                    request_id=request_id,
                    session_id=session_id,
                    route=str(request.url.path),
                    method=request.method,
                    duration_ms=compute_duration_ms(start_time),
                )
                return {
                    "session_id": session_id,
                    "free_report": db_session["free_report"],
                    "cached": True,
                    "kb_meta": {
                        "missing_fields": (db_session.get("vacancy_kb") or make_empty_vacancy_kb())["meta"]["missing_fields"],
                        "filled_fields_count": (db_session.get("vacancy_kb") or make_empty_vacancy_kb())["meta"]["filled_fields_count"],
                    },
                }
            if db_session.get("vacancy_kb"):
                kb = db_session["vacancy_kb"]
            if db_session.get("profession_query"):
                profession_query = db_session.get("profession_query")
    except Exception as e:
        log_event(
            "db_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            route=str(request.url.path),
            method=request.method,
            error=str(e),
        )

    # Generate free report
    free_report = generate_free_report(kb, profession_query)

    # Cache in session
    session["free_report"] = free_report
    session["free_report_generated_at"] = datetime.utcnow().isoformat() + "Z"

    # Save to database
    try:
        update_session(session_id, free_report=free_report, request_id=request_id)
    except Exception as e:
        log_event(
            "db_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            route=str(request.url.path),
            method=request.method,
            error=str(e),
        )

    log_event(
        "free_report_generated",
        request_id=request_id,
        session_id=session_id,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
    )

    return {
        "session_id": session_id,
        "free_report": free_report,
        "cached": False,
        "generated_at_iso": session["free_report_generated_at"],
        "kb_meta": {
            "missing_fields": kb["meta"]["missing_fields"],
            "filled_fields_count": kb["meta"]["filled_fields_count"],
        },
    }

def generate_free_report(kb, profession_query=""):
    """Generate a free report from vacancy KB using simple heuristics."""
    
    # Extract useful data from KB
    role_title = kb["role"]["role_title"]
    role_domain = kb["role"]["role_domain"]
    tasks = kb["responsibilities"]["tasks"]
    work_format = kb["company"]["work_format"]
    city = kb["company"]["company_location_city"]
    employment_type = kb["employment"]["employment_type"]
    salary_min = kb["compensation"]["salary_min_rub"]
    salary_max = kb["compensation"]["salary_max_rub"]
    salary_comment = kb["compensation"]["salary_comment"]
    raw_text = kb["responsibilities"]["raw_vacancy_text"] or ""
    
    low_text = raw_text.lower()
    low_query = profession_query.lower()
    
    # 1. Headline
    headline_parts = ["Держи бесплатный результат поиска"]
    if role_title:
        headline_parts.append(f"по {role_title.lower()}")
    elif role_domain:
        headline_parts.append(f"в сфере {role_domain}")
    headline = " ".join(headline_parts)
    
    # 2. Where to search
    where_to_search = []
    
    # Always include HH
    where_to_search.append({
        "title": "Основные площадки",
        "bullets": [
            "HeadHunter (HH) — основной источник резюме",
            "LinkedIn — проверь профили и Recruiter функции",
        ]
    })
    
    # Add location-specific channels if office/hybrid and city known
    if work_format in ["office", "hybrid"] and city:
        where_to_search.append({
            "title": f"Локальные каналы ({city.title()})",
            "bullets": [
                f"Telegram-чаты по IT/бизнесу в {city.title()}",
                "VK сообщества профессионалов",
                "Авито (для линейных/офисных позиций)",
            ]
        })
    
    # Add domain-specific channels
    is_it = "it" in low_query or any(w in low_text for w in ["python", "java", "golang", "программ", "разработ", "backend", "frontend"])
    is_creative = any(w in low_text for w in ["дизайн", "маркетинг", "реклам", "контент", "креатив"])
    is_sales = any(w in low_text for w in ["продажа", "sales", "менеджер", "бизнес-развитие"])
    
    if is_it:
        where_to_search.append({
            "title": "IT-специфичные каналы",
            "bullets": [
                "Habr Career",
                "Telegram IT-чаты по стеку (Python, Go, JS и т.д.)",
                "GitHub (прямой поиск по профилям)",
            ]
        })
    
    if is_creative:
        where_to_search.append({
            "title": "Креативные каналы",
            "bullets": [
                "Behance, Dribbble (портфолио дизайнеров)",
                "Telegram-каналы творческих сообществ",
                "TikTok/YouTube (для контент-мейкеров)",
            ]
        })
    
    if is_sales:
        where_to_search.append({
            "title": "Продажи и управление",
            "bullets": [
                "LinkedIn (сетевой поиск)",
                "Telegram-каналы бизнес-сообществ",
                "Рекомендации и рефералы внутри сети",
            ]
        })
    
    # If no specific domain, add general recommendations
    if not (is_it or is_creative or is_sales) and len(where_to_search) == 1:
        where_to_search.append({
            "title": "Альтернативные каналы",
            "bullets": [
                "Telegram-сообщества профессионалов",
                "VK группы (зачастую живые обсуждения)",
                "Рефералы и личные контакты",
            ]
        })
    
    # 3. What to screen
    what_to_screen = [
        "Резюме/портфолио: актуальность, ясность стека и опыта",
        "Примеры работ/кейсы: релевантность к твоим задачам",
        "Мягкие навыки: общительность, ответственность, проактивность",
    ]
    
    if tasks:
        what_to_screen.append("Понимание твоих задач: может ли кандидат их объяснить своими словами")
    
    if is_it:
        what_to_screen.append("Знание инструментов: какие стеки/фреймворки точно нужны")
        what_to_screen.append("Pet проекты: показывают интерес к профессии")
    
    if is_creative:
        what_to_screen.append("Чувство стиля: соответствует ли эстетика твоему видению")
        what_to_screen.append("Процесс работы: может объяснить решения и ограничения")
    
    if is_sales:
        what_to_screen.append("Track record: цифры, результаты, достижения")
        what_to_screen.append("Энергия и амбициозность: готовность к росту")
    
    what_to_screen.append("Honesty red flags: недовольство предыдущими работодателями, зарплатные скачки без причины")
    what_to_screen.append("Этика найма: убедись, что нет конфликта интересов или действующего контракта")
    
    # 4. Budget reality check
    budget_status = "unknown"
    budget_bullets = []
    
    if salary_min or salary_max or salary_comment:
        budget_bullets = [
            "Если бюджет выше—сконцентрируйся на опыте и уровне сеньёра.",
            "Если бюджет ниже—рассмотри джуна с хорошим потенциалом, part-time или проектную работу.",
            "Опцион: наставничество (junior + ментор) может быть экономичнее середины.",
        ]
        if salary_comment:
            budget_bullets.insert(0, f"Твой бюджет: {salary_comment}")
        elif salary_min and salary_max:
            budget_bullets.insert(0, f"Бюджет: {salary_min:,}–{salary_max:,} ₽")
    else:
        budget_bullets = [
            "Не указан бюджет, но помни: рынок очень вариативен.",
            "Перед размещением вакансии — проверь аналогичные позиции на HH.",
            "Не боись предложить тестовое задание, чтобы оценить реального кандидата.",
        ]
    
    # 5. Next steps
    next_steps = [
        "Формирование вакансии: ясные требования, стек, условия, процесс интервью.",
        "Выбор каналов: начни с 2–3 основных (HH + специализированный).",
        "Быстрый скрининг резюме: ответь на вопрос 'может ли он/она это делать?' за 2 мин.",
    ]
    
    if work_format == "office" or work_format == "hybrid":
        next_steps.append("Организаторский момент: убедись, что есть место для работника и оборудование.")
    
    next_steps.append("Первое интервью: рассказывай о задачах, спрашивай о опыте, проверяй культуру.")
    next_steps.append("Тестовое задание (если уместно): small scope, 2–4 часа работы, реальная задача.")
    
    return {
        "headline": headline,
        "where_to_search": where_to_search,
        "what_to_screen": what_to_screen,
        "budget_reality_check": {
            "status": budget_status,
            "bullets": budget_bullets,
        },
        "next_steps": next_steps,
    }


@app.post("/sessions")
def create_session_endpoint(body: SessionCreate, request: Request, response: Response):
    """Create a new session and persist to database."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    session_id = str(uuid.uuid4())

    # Ensure guest auth is issued early (front always starts with /sessions)
    user_id_issued = _issue_guest_cookie_if_missing(request, response)

    flow = (body.flow or "").strip().lower()
    
    # Create in-memory session for backward compatibility
    SESSIONS[session_id] = {
        "profession_query": body.profession_query,
        "state": "intro" if flow == "intro" else "awaiting_flow",
        "vacancy_text": None,
        "tasks": None,
        "clarifications": [],
        "vacancy_kb": make_empty_vacancy_kb(),
    }
    
    # Also save to database
    try:
        kb = make_empty_vacancy_kb()
        db_create_session(session_id, body.profession_query, kb, request_id=request_id)
        user_id = user_id_issued or _get_user_id(request)
        if user_id:
            set_session_user(session_id, user_id, request_id=request_id)
        if flow == "intro":
            update_session(session_id, chat_state="intro", phase="INTRO", brief_state={}, request_id=request_id)
    except Exception as e:
        log_event(
            "db_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            route=str(request.url.path),
            method=request.method,
            error=str(e),
        )
    
    log_event(
        "session_created",
        request_id=request_id,
        session_id=session_id,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
    )
    return {"session_id": session_id}


@app.post("/debug/s3/put-test-pdf")
def debug_s3_put_test_pdf(request: Request, session_id: str | None = None):
    """DEBUG-only: upload a tiny test PDF to S3 and register artifact + artifact_file."""
    if not _is_debug_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    user_key = _anon_user_key(user_id)

    bucket = (os.environ.get("S3_BUCKET") or "").strip()
    if not bucket:
        raise HTTPException(status_code=500, detail="S3_BUCKET is not configured")

    # Ensure a session exists to attach ownership chain.
    sid = session_id
    if sid:
        existing = get_session(sid, request_id=request_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        sid = str(uuid.uuid4())
        kb = make_empty_vacancy_kb()
        db_create_session(sid, "debug_pdf_test", kb, request_id=request_id)

    if user_id:
        try:
            set_session_user(sid, user_id, request_id=request_id)
        except Exception:
            pass

    artifact = create_artifact(
        session_id=sid,
        kind="pdf_test",
        format="pdf",
        payload_json=None,
        request_id=request_id,
    )
    artifact_id = artifact.get("id")
    if not artifact_id:
        raise HTTPException(status_code=500, detail="Failed to create artifact")

    pdf_bytes = _make_minimal_pdf_bytes()
    key = f"users/{user_key}/test/{artifact_id}.pdf"

    up = upload_bytes(bucket=bucket, key=key, data=pdf_bytes, content_type="application/pdf", request_id=request_id)

    file_row = create_artifact_file(
        artifact_id=str(artifact_id),
        bucket=bucket,
        object_key=key,
        content_type="application/pdf",
        size_bytes=up.get("size_bytes"),
        etag=up.get("etag"),
        meta={},
        request_id=request_id,
    )
    file_id = file_row.get("id")
    if not file_id:
        raise HTTPException(status_code=500, detail="Failed to create artifact file")

    download_url = presign_get(bucket=bucket, key=key, expires_sec=600, request_id=request_id)

    log_event(
        "file_created",
        request_id=request_id,
        artifact_id=str(artifact_id),
        file_id=str(file_id),
        bucket=bucket,
        key=key,
        size_bytes=up.get("size_bytes"),
    )
    log_event(
        "file_presigned",
        request_id=request_id,
        file_id=str(file_id),
        bucket=bucket,
        key=key,
        expires_in_sec=600,
    )
    return {
        "ok": True,
        "artifact_id": str(artifact_id),
        "file_id": str(file_id),
        "bucket": bucket,
        "key": key,
        "download_url": download_url,
    }


@app.get("/files/{file_id}/download")
def files_download(file_id: str, request: Request):
    """Auth-required: return presigned download URL if file belongs to current user."""
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)

    row = get_file_download_info_for_user(file_id=file_id, user_id=user_id, request_id=request_id)
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    bucket = row.get("bucket")
    key = row.get("object_key")
    if not bucket or not key:
        raise HTTPException(status_code=500, detail="File record is incomplete")

    expires = 600
    url = presign_get(bucket=bucket, key=key, expires_sec=expires, request_id=request_id)

    log_event(
        "file_presigned",
        request_id=request_id,
        file_id=file_id,
        bucket=bucket,
        key=key,
        expires_in_sec=expires,
    )
    return {"ok": True, "url": url, "expires_in_sec": expires}


@app.post("/render/jobs", response_model=RenderJobCreateResponse)
def render_jobs_create(body: RenderJobCreateBody, request: Request):
    """Auth-required: create an async render job and enqueue it to Redis."""
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)

    doc_id = (body.doc_id or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id is required")

    session_id_str = str(body.session_id)
    pack_id_str = str(body.pack_id)

    sess = get_session(session_id_str, request_id=request_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    owner = sess.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    job = create_render_job(
        pack_id=pack_id_str,
        session_id=session_id_str,
        user_id=None,
        doc_id=doc_id,
        status="queued",
        max_attempts=5,
        request_id=request_id,
    )
    job_id = str(job.get("id") or "")
    if not job_id:
        raise HTTPException(status_code=500, detail="Failed to create render job")

    _record_config_snapshot_artifact(
        session_id=session_id_str,
        pack_id=pack_id_str,
        doc_id=doc_id,
        render_job_id=job_id,
        request_id=request_id,
    )

    render_request = {
        "doc_id": doc_id,
        "title": body.title,
        "sections": body.sections or [],
        "meta": {**(body.meta or {}), "pack_id": pack_id_str, "session_id": session_id_str},
    }
    msg = json.dumps(
        {
            "job_id": job_id,
            "pack_id": pack_id_str,
            "session_id": session_id_str,
            "doc_id": doc_id,
            "render_request": render_request,
        },
        ensure_ascii=False,
    )
    try:
        _redis_client().rpush(RENDER_QUEUE_NAME, msg)
    except Exception as e:
        log_event(
            "render_error",
            level="error",
            request_id=request_id,
            render_job_id=job_id,
            doc_id=doc_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to enqueue render job")

    log_event(
        "render_job_created",
        request_id=request_id,
        render_job_id=job_id,
        doc_id=doc_id,
        session_id=session_id_str,
        pack_id=pack_id_str,
    )
    return {"ok": True, "job_id": job_id, "status": "queued"}


@app.get("/render/jobs/{job_id}", response_model=RenderJobStatusResponse)
def render_jobs_status(job_id: str, request: Request):
    """Auth-required: read render job status."""
    request_id = get_request_id_from_request(request)
    _ = _require_user_id(request)
    row = get_render_job(job_id, request_id=request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "ok": True,
        "job_id": str(row.get("id")),
        "status": row.get("status"),
        "attempts": int(row.get("attempts") or 0),
        "max_attempts": int(row.get("max_attempts") or 0),
        "last_error": row.get("last_error"),
    }


@app.get("/me/files")
def me_files(request: Request):
    """Auth-required: list files that belong to current user."""
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    rows = list_user_files(user_id=user_id, request_id=request_id)
    normalized = []
    for r in rows:
        normalized.append(
            {
                "file_id": str(r.get("file_id")),
                "artifact_id": str(r.get("artifact_id")),
                "kind": r.get("kind"),
                "created_at": to_iso(r.get("created_at")),
                "content_type": r.get("content_type"),
                "size_bytes": r.get("size_bytes"),
                "doc_id": r.get("doc_id"),
                "status": "ready",
            }
        )
    log_event(
        "me_files_listed",
        request_id=request_id,
        user_id=user_id,
        files_count=len(normalized),
    )
    return {"ok": True, "files": normalized}


@app.get("/me/documents")
def me_documents(request: Request, response: Response):
    """Auth-required: list intro artifacts + generated PDF documents for current user."""
    request_id = get_request_id_from_request(request)
    # Guest-safe: issue cookie when missing; keep 401 for invalid/expired cookie.
    # If token exists but invalid/expired, keep 401 with reason.
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        uid = _get_user_id(request)
        if not uid:
            raise HTTPException(status_code=401, detail="invalid_token")
        user_id = uid
    else:
        user_id = _get_user_id(request)
    if not user_id:
        issued = _issue_guest_cookie_if_missing(request, response)
        if issued:
            user_id = issued
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    catalog = _load_documents_catalog()
    title_map = {str((it or {}).get("id") or "").strip(): (it or {}).get("title") for it in (catalog or [])}

    normalized: list[dict] = []

    # 1) Intro artifacts
    rows = list_user_intro_documents(user_id=user_id, request_id=request_id, limit=50)
    for r in rows:
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        normalized.append(
            {
                "type": "artifact",
                "id": str(r.get("id")),
                "session_id": str(r.get("session_id") or ""),
                "kind": r.get("kind"),
                "format": r.get("format"),
                "title": (meta.get("title") if isinstance(meta, dict) else None) or r.get("kind"),
                "payload": r.get("payload_json") or {},
                "created_at": to_iso(r.get("created_at")),
            }
        )

    # 2) PDF documents
    docs = list_documents_for_user(user_id=user_id, request_id=request_id, limit=100)
    for d in docs:
        doc_id = str(d.get("doc_id") or "").strip()
        status = str(d.get("status") or "")
        normalized.append(
            {
                "type": "pdf",
                "id": str(d.get("id")),
                "session_id": str(d.get("session_id") or ""),
                "doc_id": doc_id,
                "title": (title_map.get(doc_id) or doc_id),
                "status": status,
                "template_id": str(d.get("template_id") or ""),
                "template_version": int(d.get("template_version") or 0),
                "created_at": to_iso(d.get("created_at")),
                "download_url": (f"/api/documents/{str(d.get('id'))}/download" if status == "ready" else None),
            }
        )

    # Newest first (best-effort)
    def _ts_key(it: dict) -> str:
        return str(it.get("created_at") or "")

    normalized.sort(key=_ts_key, reverse=True)
    log_event(
        "me_documents_listed",
        request_id=request_id,
        user_id=user_id,
        documents_count=len(normalized),
    )
    return {"ok": True, "documents": normalized}


@app.get("/documents/catalog")
def documents_catalog(request: Request):
    request_id = get_request_id_from_request(request)
    items = []
    for it in _load_documents_catalog():
        items.append(
            {
                "id": (it or {}).get("id"),
                "title": (it or {}).get("title"),
                "description": (it or {}).get("description"),
                "required_fields": (it or {}).get("required_fields") or [],
                "sort_order": int((it or {}).get("sort_order") or 0),
                "is_free": bool((it or {}).get("is_free")) if (it or {}).get("is_free") is not None else True,
                "available": True,
            }
        )
    items.sort(key=lambda x: int(x.get("sort_order") or 0))
    log_event("documents_catalog_ok", request_id=request_id, items_count=len(items))
    return {"ok": True, "items": items}


class DocumentGenerateBody(BaseModel):
    session_id: str
    doc_id: str
    force: bool = False


class DocumentGeneratePackBody(BaseModel):
    session_id: str
    force: bool = False


@app.post("/documents/generate")
def documents_generate(body: DocumentGenerateBody, request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)

    session_id = (body.session_id or "").strip()
    doc_id = (body.doc_id or "").strip()
    if not session_id or not doc_id:
        raise HTTPException(status_code=400, detail="session_id and doc_id are required")

    cat = _catalog_item(doc_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Document not found in catalog")

    sess = get_session(session_id, request_id=request_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    owner = sess.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        set_session_user(session_id, user_id, request_id=request_id)
    except Exception:
        pass

    brief_state = sess.get("brief_state") if isinstance(sess.get("brief_state"), dict) else {}
    profession_query = str(sess.get("profession_query") or "")

    force = bool(getattr(body, "force", False))

    if not force:
        existing = find_latest_document_by_identity(
            user_id=user_id,
            session_id=session_id,
            doc_id=doc_id,
            request_id=request_id,
        )
        if existing and str(existing.get("status") or "") in {"ready", "pending", "error", "needs_input"}:
            status = str(existing.get("status") or "")
            log_event(
                "doc_generate_cached",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                doc_id=doc_id,
                artifact_id=str(existing.get("id")),
                status=status,
            )
            return {
                "ok": True,
                "cached": True,
                "document": {
                    "id": str(existing.get("id")),
                    "session_id": session_id,
                    "doc_id": doc_id,
                    "title": str(cat.get("title") or doc_id),
                    "status": status,
                    "created_at": to_iso(existing.get("created_at")),
                    "download_url": (f"/api/documents/{str(existing.get('id'))}/download" if status == "ready" else None),
                    "missing_fields": (existing.get("meta") or {}).get("missing_fields") if isinstance(existing.get("meta"), dict) else None,
                },
            }

    active_tpl = get_active_document_template(doc_id=doc_id, request_id=request_id)
    if not active_tpl:
        # Should not happen if seeding worked.
        log_event("doc_generate_error", level="error", request_id=request_id, user_id=user_id, session_id=session_id, doc_id=doc_id, error="missing_active_template")
        return {"ok": True, "cached": False, "status": "error", "error_code": "missing_template", "error_message": "No active template"}

    template_id = str(active_tpl.get("id"))
    template_version = int(active_tpl.get("version") or 0)

    source_hash = _stable_hash({"profession_query": profession_query, "brief_state": brief_state})

    required_fields = cat.get("required_fields") or []
    missing_req = _required_fields_missing(brief_state, required_fields)

    log_event(
        "doc_generate_start",
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        doc_id=doc_id,
        template_id=template_id,
        template_version=template_version,
        required_missing_count=len(missing_req),
    )

    if missing_req:
        row = create_document_record(
            user_id=user_id,
            session_id=session_id,
            doc_id=doc_id,
            template_id=template_id,
            template_version=template_version,
            status="needs_input",
            source_hash=source_hash,
            meta={"missing_fields": missing_req, "required_fields": required_fields},
            request_id=request_id,
        )
        return {
            "ok": True,
            "cached": False,
            "document": {
                "id": str(row.get("id")),
                "session_id": session_id,
                "doc_id": doc_id,
                "title": str(cat.get("title") or doc_id),
                "status": "needs_input",
                "missing_fields": missing_req,
                "created_at": to_iso(row.get("created_at")),
            },
        }

    # Create pending doc row
    row = create_document_record(
        user_id=user_id,
        session_id=session_id,
        doc_id=doc_id,
        template_id=template_id,
        template_version=template_version,
        status="pending",
        source_hash=source_hash,
        meta={"required_fields": required_fields},
        request_id=request_id,
    )
    document_id = str(row.get("id") or "")

    # LLM content generation (1-2 attempts)
    llm_ok = False
    llm_model: DocContentResponse | None = None
    for attempt in [1, 2]:
        try:
            messages = _build_doc_messages(doc_id=doc_id, profession_query=profession_query, brief_state=brief_state)
            fallback = {"doc_markdown": "", "missing_fields": [], "quality_notes": "fallback"}
            raw = generate_json_messages_observable(
                messages=messages,
                request_id=request_id,
                session_id=session_id,
                fallback=fallback,
                flow="doc_generate",
                doc_id=doc_id,
                attempt=attempt,
            )
            m = DocContentResponse.model_validate(raw)
            # Consider empty doc_markdown with empty missing_fields as invalid.
            if (not (m.doc_markdown or "").strip()) and not (m.missing_fields or []):
                raise RuntimeError("empty_doc_markdown")
            llm_ok = True
            llm_model = m
            log_event(
                "llm_ok",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                doc_id=doc_id,
                artifact_id=document_id,
                template_id=template_id,
                attempt=attempt,
                doc_markdown_chars=len(m.doc_markdown or ""),
                missing_fields_count=len(m.missing_fields or []),
            )
            break
        except LLMUnavailable as e:
            # No silent mock in envs where LLM_REQUIRE_KEY=true.
            log_event(
                "llm_error",
                level="error",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                doc_id=doc_id,
                artifact_id=document_id,
                template_id=template_id,
                attempt=attempt,
                reason=str(getattr(e, "reason", "llm_unavailable")),
                error=str(e),
            )
            raise HTTPException(status_code=503, detail=f"LLM unavailable: {getattr(e, 'reason', 'missing_api_key')}")
        except Exception as e:
            log_event(
                "llm_fail",
                level="warning",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                doc_id=doc_id,
                artifact_id=document_id,
                template_id=template_id,
                attempt=attempt,
                error=str(e),
            )

    if (not llm_ok) or (llm_model is None):
        # Dev-friendly fallback: allow end-to-end pipeline without external LLM keys.
        if current_llm_provider() == "mock":
            try:
                llm_model = DocContentResponse(
                    doc_markdown=_heuristic_doc_markdown(
                        doc_id=doc_id,
                        title=str(cat.get("title") or doc_id),
                        profession_query=profession_query,
                        brief_state=brief_state,
                    ),
                    missing_fields=[],
                    quality_notes="heuristic_mock",
                )
                llm_ok = True
                log_event(
                    "llm_mock_fallback",
                    level="warning",
                    request_id=request_id,
                    user_id=user_id,
                    session_id=session_id,
                    doc_id=doc_id,
                    artifact_id=document_id,
                    template_id=template_id,
                )
            except Exception as e:
                log_event(
                    "llm_mock_fallback_failed",
                    level="error",
                    request_id=request_id,
                    user_id=user_id,
                    session_id=session_id,
                    doc_id=doc_id,
                    artifact_id=document_id,
                    template_id=template_id,
                    error=str(e),
                )

    if (not llm_ok) or (llm_model is None):
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="llm_invalid",
            error_message="LLM did not return valid JSON",
            request_id=request_id,
        )
        return {
            "ok": True,
            "cached": False,
            "document": {
                "id": document_id,
                "session_id": session_id,
                "doc_id": doc_id,
                "title": str(cat.get("title") or doc_id),
                "status": "error",
                "error_code": "llm_invalid",
                "error_message": "LLM did not return valid JSON",
            },
        }

    missing_fields = llm_model.missing_fields or []
    doc_markdown = llm_model.doc_markdown or ""
    if missing_fields:
        todo = "\n".join([f"- {str(x)}" for x in missing_fields])
        doc_markdown = (doc_markdown.strip() + "\n\n---\n\n## TODO (не хватает данных)\n\n" + todo + "\n").strip() + "\n"

    generated_at = datetime.utcnow().isoformat() + "Z"
    final_markdown = _apply_template_body(
        template_body=str(active_tpl.get("body") or ""),
        title=str(cat.get("title") or doc_id),
        doc_markdown=doc_markdown,
        generated_at=generated_at,
    )

    ok_pdf, pdf_bytes, render_err = _render_pdf_bytes(
        title=str(cat.get("title") or doc_id),
        markdown=final_markdown,
        meta={"doc_id": doc_id, "session_id": session_id, "user_id": user_id, "template_id": template_id},
    )
    if (not ok_pdf) or (not pdf_bytes) or (not pdf_bytes.startswith(b"%PDF")):
        log_event(
            "render_fail",
            level="error",
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            doc_id=doc_id,
            artifact_id=document_id,
            template_id=template_id,
            error=str(render_err or "invalid_pdf"),
        )
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="render_failed",
            error_message=str(render_err or "render_failed"),
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "doc_id": doc_id, "status": "error", "error_code": "render_failed"}}
    log_event(
        "render_ok",
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        doc_id=doc_id,
        artifact_id=document_id,
        template_id=template_id,
        bytes_size=len(pdf_bytes),
    )

    bucket = (os.environ.get("S3_BUCKET") or "").strip()
    if not bucket:
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="s3_not_configured",
            error_message="S3_BUCKET not configured",
            request_id=request_id,
        )
        return {"ok": True, "cached": False, "document": {"id": document_id, "doc_id": doc_id, "status": "error", "error_code": "s3_not_configured"}}

    sha256 = _sha256_hex(pdf_bytes)
    object_key = f"documents/{user_id}/{session_id}/{doc_id}/{template_version}-{document_id}.pdf"
    try:
        upload_bytes(
            bucket=bucket,
            key=object_key,
            data=pdf_bytes,
            content_type="application/pdf",
            metadata={
                "doc_id": doc_id,
                "user_id": user_id,
                "session_id": session_id,
                "template_id": template_id,
                "sha256": sha256,
            },
            request_id=request_id,
        )
        log_event(
            "s3_ok",
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            doc_id=doc_id,
            artifact_id=document_id,
            template_id=template_id,
            bucket=bucket,
            object_key=object_key,
        )
    except Exception as e:
        log_event(
            "s3_fail",
            level="error",
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            doc_id=doc_id,
            artifact_id=document_id,
            template_id=template_id,
            error=str(e),
        )
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="s3_failed",
            error_message=str(e),
            request_id=request_id,
        )
        return {"ok": True, "cached": False, "document": {"id": document_id, "doc_id": doc_id, "status": "error", "error_code": "s3_failed"}}

    update_document_record(
        document_id=document_id,
        status="ready",
        s3_bucket=bucket,
        s3_key=object_key,
        sha256=sha256,
        meta={"required_fields": required_fields, "missing_fields": missing_fields, "quality_notes": llm_model.quality_notes},
        request_id=request_id,
    )
    log_event(
        "doc_ready",
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        doc_id=doc_id,
        artifact_id=document_id,
        template_id=template_id,
    )
    return {
        "ok": True,
        "cached": False,
        "document": {
            "id": document_id,
            "session_id": session_id,
            "doc_id": doc_id,
            "title": str(cat.get("title") or doc_id),
            "status": "ready",
            "download_url": f"/api/documents/{document_id}/download",
            "created_at": to_iso(row.get("created_at")),
        },
    }


@app.post("/documents/generate_pack")
def documents_generate_pack(body: DocumentGeneratePackBody, request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)

    session_id = (body.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    sess = get_session(session_id, request_id=request_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    owner = sess.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        set_session_user(session_id, user_id, request_id=request_id)
    except Exception:
        pass

    force = bool(getattr(body, "force", False))

    # Strict: only catalog items with auto_generate=true and is_free=true
    catalog = _load_documents_catalog()
    items = [it for it in (catalog or []) if bool((it or {}).get("auto_generate")) and bool((it or {}).get("is_free", True))]
    items.sort(key=lambda x: int((x or {}).get("sort_order") or 0))

    log_event(
        "doc_pack_generate_start",
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        docs_count=len(items),
        force=force,
    )

    results: list[dict] = []
    for it in items:
        doc_id = str((it or {}).get("id") or "").strip()
        if not doc_id:
            continue

        log_event(
            "doc_pack_item_start",
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            doc_id=doc_id,
            force=force,
        )

        try:
            resp = documents_generate(DocumentGenerateBody(session_id=session_id, doc_id=doc_id, force=force), request)
            cached = bool((resp or {}).get("cached")) if isinstance(resp, dict) else False
            doc = (resp or {}).get("document") if isinstance(resp, dict) else None
            doc_status = (doc or {}).get("status") if isinstance(doc, dict) else None

            if cached:
                item_status = "cached"
            else:
                item_status = "generated" if str(doc_status or "") == "ready" else "failed"

            item = {
                "doc_id": doc_id,
                "title": str((it or {}).get("title") or doc_id),
                "status": item_status,
                "artifact_id": (str((doc or {}).get("id")) if isinstance(doc, dict) else None),
                "url": ((doc or {}).get("download_url") if isinstance(doc, dict) else None),
            }
            if item_status == "failed":
                error_code = (doc or {}).get("error_code") if isinstance(doc, dict) else None
                error_message = (doc or {}).get("error_message") if isinstance(doc, dict) else None
                item["error"] = {
                    "code": str(error_code or "failed"),
                    "message": str(error_message or doc_status or "failed"),
                }

            results.append(item)
            log_event(
                "doc_pack_item_done",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                doc_id=doc_id,
                cached=cached,
                status=item_status,
                doc_status=doc_status,
                artifact_id=(str((doc or {}).get("id")) if isinstance(doc, dict) else None),
            )
        except Exception as e:
            # Never fail the whole pack.
            results.append(
                {
                    "doc_id": doc_id,
                    "title": str((it or {}).get("title") or doc_id),
                    "status": "failed",
                    "artifact_id": None,
                    "url": None,
                    "error": {"code": "exception", "message": str(e)},
                }
            )
            log_event(
                "doc_pack_item_failed",
                level="error",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                doc_id=doc_id,
                error=str(e),
            )

    log_event(
        "doc_pack_generate_done",
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        results_count=len(results),
    )
    return {"ok": True, "session_id": session_id, "results": results}


@app.get("/documents/{document_id}/download")
def documents_download(document_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    doc = get_document_for_user(document_id=document_id, user_id=user_id, request_id=request_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc.get("status") or "") != "ready":
        raise HTTPException(status_code=409, detail="Document not ready")
    bucket = str(doc.get("s3_bucket") or "").strip()
    key = str(doc.get("s3_key") or "").strip()
    if not bucket or not key:
        raise HTTPException(status_code=409, detail="Missing S3 pointer")

    filename = f"{str(doc.get('doc_id') or 'document')}.pdf"
    headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
    return StreamingResponse(stream_get(bucket=bucket, key=key, request_id=request_id), media_type="application/pdf", headers=headers)


@app.post("/documents/{document_id}/retry")
def documents_retry(document_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    doc = get_document_for_user(document_id=document_id, user_id=user_id, request_id=request_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    status = str(doc.get("status") or "")
    if status != "error":
        return {"ok": True, "document": {"id": str(doc.get("id")), "status": status}}

    session_id = str(doc.get("session_id") or "").strip()
    sess = get_session(session_id, request_id=request_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    owner = sess.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Prevent retry on stale data: user should call /documents/generate again.
    brief_state = sess.get("brief_state") if isinstance(sess.get("brief_state"), dict) else {}
    profession_query = str(sess.get("profession_query") or "")
    computed_hash = _stable_hash({"profession_query": profession_query, "brief_state": brief_state})
    stored_hash = str(doc.get("source_hash") or "")
    if stored_hash and computed_hash != stored_hash:
        raise HTTPException(status_code=409, detail="Source data changed; call /documents/generate")

    doc_id = str(doc.get("doc_id") or "").strip()
    cat = _catalog_item(doc_id) or {"title": doc_id, "required_fields": []}
    template_id = str(doc.get("template_id") or "")
    template_version = int(doc.get("template_version") or 0)
    tpl = get_document_template_by_id(template_id=template_id, request_id=request_id)
    if not tpl:
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="missing_template",
            error_message="Template not found",
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "status": "error", "error_code": "missing_template"}}

    update_document_record(
        document_id=document_id,
        status="pending",
        clear_error=True,
        request_id=request_id,
    )

    # Re-run generation once (with up to 2 LLM attempts)
    required_fields = cat.get("required_fields") or []
    missing_req = _required_fields_missing(brief_state, required_fields)
    if missing_req:
        update_document_record(
            document_id=document_id,
            status="needs_input",
            meta={"missing_fields": missing_req, "required_fields": required_fields},
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "status": "needs_input", "missing_fields": missing_req}}

    llm_ok = False
    llm_model: DocContentResponse | None = None
    for attempt in [1, 2]:
        try:
            messages = _build_doc_messages(doc_id=doc_id, profession_query=profession_query, brief_state=brief_state)
            fallback = {"doc_markdown": "", "missing_fields": [], "quality_notes": "fallback"}
            raw = generate_json_messages_observable(
                messages=messages,
                request_id=request_id,
                session_id=session_id,
                fallback=fallback,
                flow="doc_generate",
                doc_id=doc_id,
                attempt=attempt,
            )
            m = DocContentResponse.model_validate(raw)
            if (not (m.doc_markdown or "").strip()) and not (m.missing_fields or []):
                raise RuntimeError("empty_doc_markdown")
            llm_ok = True
            llm_model = m
            break
        except LLMUnavailable as e:
            log_event(
                "llm_error",
                level="error",
                request_id=request_id,
                user_id=user_id,
                session_id=session_id,
                doc_id=doc_id,
                artifact_id=document_id,
                attempt=attempt,
                reason=str(getattr(e, "reason", "llm_unavailable")),
                error=str(e),
            )
            raise HTTPException(status_code=503, detail=f"LLM unavailable: {getattr(e, 'reason', 'missing_api_key')}")
        except Exception:
            pass

    if (not llm_ok) or (llm_model is None):
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="llm_invalid",
            error_message="LLM did not return valid JSON",
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "status": "error", "error_code": "llm_invalid"}}

    if llm_model.missing_fields:
        update_document_record(
            document_id=document_id,
            status="needs_input",
            meta={"missing_fields": llm_model.missing_fields, "required_fields": required_fields},
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "status": "needs_input", "missing_fields": llm_model.missing_fields}}

    generated_at = datetime.utcnow().isoformat() + "Z"
    final_markdown = _apply_template_body(
        template_body=str(tpl.get("body") or ""),
        title=str(cat.get("title") or doc_id),
        doc_markdown=llm_model.doc_markdown,
        generated_at=generated_at,
    )

    ok_pdf, pdf_bytes, render_err = _render_pdf_bytes(
        title=str(cat.get("title") or doc_id),
        markdown=final_markdown,
        meta={"doc_id": doc_id, "session_id": session_id, "user_id": user_id, "template_id": template_id},
    )
    if (not ok_pdf) or (not pdf_bytes) or (not pdf_bytes.startswith(b"%PDF")):
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="render_failed",
            error_message=str(render_err or "render_failed"),
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "status": "error", "error_code": "render_failed"}}

    bucket = (os.environ.get("S3_BUCKET") or "").strip()
    if not bucket:
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="s3_not_configured",
            error_message="S3_BUCKET not configured",
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "status": "error", "error_code": "s3_not_configured"}}

    sha256 = _sha256_hex(pdf_bytes)
    object_key = f"documents/{user_id}/{session_id}/{doc_id}/{template_version}-{document_id}.pdf"
    try:
        upload_bytes(
            bucket=bucket,
            key=object_key,
            data=pdf_bytes,
            content_type="application/pdf",
            metadata={
                "doc_id": doc_id,
                "user_id": user_id,
                "session_id": session_id,
                "template_id": template_id,
                "sha256": sha256,
            },
            request_id=request_id,
        )
    except Exception as e:
        update_document_record(
            document_id=document_id,
            status="error",
            error_code="s3_failed",
            error_message=str(e),
            request_id=request_id,
        )
        return {"ok": True, "document": {"id": document_id, "status": "error", "error_code": "s3_failed"}}

    update_document_record(
        document_id=document_id,
        status="ready",
        s3_bucket=bucket,
        s3_key=object_key,
        sha256=sha256,
        request_id=request_id,
    )
    return {"ok": True, "document": {"id": document_id, "status": "ready", "download_url": f"/api/documents/{document_id}/download"}}


@app.post("/ml/job", response_model=MlJobCreateResponse)
def ml_job_mock(body: MlJobCreateBody, request: Request):
    """Mock ML job: creates a pack for a session.

    Stage 9.4 smoke expects /ml/job to return pack_id.
    """
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    session_id = (body.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    sess = get_session(session_id, request_id=request_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    owner = sess.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    row = create_pack(session_id=session_id, user_id=user_id, request_id=request_id)
    pack_id = str(row.get("pack_id") or "")
    if not pack_id:
        raise HTTPException(status_code=500, detail="Failed to create pack")

    log_event(
        "ml_job_created",
        request_id=request_id,
        pack_id=pack_id,
        session_id=session_id,
    )
    return {"ok": True, "pack_id": pack_id, "session_id": session_id}


@app.get("/me/packs")
def me_packs(request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    rows = list_packs_for_user(user_id=user_id, request_id=request_id)
    normalized = []
    for r in rows:
        normalized.append(
            {
                "pack_id": str(r.get("pack_id")),
                "session_id": str(r.get("session_id")),
                "created_at": to_iso(r.get("created_at")),
            }
        )
    log_event(
        "me_packs_listed",
        request_id=request_id,
        user_id=user_id,
        packs_count=len(normalized),
    )
    return {"ok": True, "packs": normalized}


@app.get("/admin/packs")
def admin_packs(request: Request, limit: int = 100, user_id: str = "", phone: str = "", session_id: str = ""):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)

    resolved_user_id: Optional[str] = (user_id or "").strip() or None
    if (phone or "").strip():
        phone_e164 = _normalize_phone_e164(phone)
        resolved_user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "nly:phone:" + phone_e164))

    resolved_session_id: Optional[str] = (session_id or "").strip() or None

    rows = list_packs_admin(
        user_id=resolved_user_id,
        session_id=resolved_session_id,
        limit=limit,
        request_id=request_id,
    )
    items = []
    for r in rows:
        items.append(
            {
                "pack_id": str(r.get("pack_id") or ""),
                "session_id": str(r.get("session_id") or ""),
                "user_id": (str(r.get("user_id")) if r.get("user_id") is not None else None),
                "phone_e164": (str(r.get("phone_e164")) if r.get("phone_e164") is not None else None),
                "created_at": to_iso(r.get("created_at")),
            }
        )
    log_event(
        "admin_packs_listed",
        request_id=request_id,
        user_id=resolved_user_id,
        session_id=resolved_session_id,
        packs_count=len(items),
    )
    return {"ok": True, "items": items}


@app.get("/admin/packs/{pack_id}/documents")
def admin_pack_documents(pack_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    _ = _require_admin(request)

    pack = get_pack(pack_id, request_id=request_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")

    docs_all = _load_documents_registry(request_id=request_id)
    doc_ids = [str(d.get("doc_id") or "").strip() for d in docs_all if str(d.get("doc_id") or "").strip()]
    access_map = get_document_access_map(doc_ids, request_id=request_id)
    meta_map = get_document_metadata_map(doc_ids, request_id=request_id)
    docs = []
    for d in docs_all:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        if _effective_doc_enabled(d, access_map.get(doc_id)):
            docs.append(d)

    latest_jobs = list_latest_render_jobs_for_pack(pack_id, request_id=request_id)
    by_doc = {str(j.get("doc_id")): j for j in latest_jobs}

    out = []
    for d in docs:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        j = by_doc.get(doc_id)
        access_info = _doc_access_info(d, access_map.get(doc_id))
        status = "queued" if j else "queued"
        file_id = None
        attempts = 0
        last_error = None
        if j:
            status = str(j.get("status") or "queued")
            attempts = int(j.get("attempts") or 0)
            last_error = j.get("last_error")
            if status == "ready":
                file_id = get_latest_file_id_for_render_job(str(j.get("id")), request_id=request_id)
        out.append(
            {
                "doc_id": doc_id,
                "title": _effective_doc_title(d, meta_map.get(doc_id)),
                "status": status,
                "file_id": file_id,
                "attempts": attempts,
                "last_error": last_error,
                "access": access_info,
            }
        )

    log_event(
        "admin_render_status_listed",
        request_id=request_id,
        pack_id=pack_id,
        docs_count=len(out),
    )
    return {"ok": True, "pack_id": pack_id, "pack": {"pack_id": str(pack.get("pack_id")), "session_id": str(pack.get("session_id")), "user_id": pack.get("user_id")}, "documents": out}


@app.post("/admin/packs/{pack_id}/render")
def admin_pack_render(pack_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)

    pack = get_pack(pack_id, request_id=request_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")

    session_id = str(pack.get("session_id") or "")
    docs_all = _load_documents_registry(request_id=request_id)
    doc_ids = [str(d.get("doc_id") or "").strip() for d in docs_all if str(d.get("doc_id") or "").strip()]
    access_map = get_document_access_map(doc_ids, request_id=request_id)
    meta_map = get_document_metadata_map(doc_ids, request_id=request_id)
    docs = []
    for d in docs_all:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        if _effective_doc_enabled(d, access_map.get(doc_id)):
            docs.append(d)
    if not docs:
        raise HTTPException(status_code=500, detail="Documents registry is empty")

    log_event(
        "admin_render_pack_requested",
        request_id=request_id,
        pack_id=pack_id,
        docs_total=len(docs),
    )

    existing = list_latest_render_jobs_for_pack(pack_id, request_id=request_id)
    existing_by_doc = {str(r.get("doc_id")): r for r in existing}

    created = 0
    skipped = 0
    enqueued = 0
    rcli = _redis_client()

    for d in docs:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        prev = existing_by_doc.get(doc_id)
        if prev and str(prev.get("status")) in {"queued", "rendering", "ready"}:
            skipped += 1
            continue

        job = create_render_job(
            pack_id=pack_id,
            session_id=session_id,
            user_id=None,
            doc_id=doc_id,
            status="queued",
            max_attempts=5,
            request_id=request_id,
        )
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        created += 1

        _record_config_snapshot_artifact(
            session_id=session_id,
            pack_id=pack_id,
            doc_id=doc_id,
            render_job_id=job_id,
            request_id=request_id,
        )

        render_request = _build_render_request(
            doc_id=doc_id,
            title=_effective_doc_title(d, meta_map.get(doc_id)),
            pack_id=pack_id,
            session_id=session_id,
        )
        msg = json.dumps(
            {
                "job_id": job_id,
                "pack_id": pack_id,
                "session_id": session_id,
                "doc_id": doc_id,
                "render_request": render_request,
            },
            ensure_ascii=False,
        )
        rcli.rpush(RENDER_QUEUE_NAME, msg)
        enqueued += 1

    log_event(
        "admin_render_jobs_enqueued",
        request_id=request_id,
        pack_id=pack_id,
        jobs_created=created,
        jobs_skipped=skipped,
        jobs_enqueued=enqueued,
    )

    try:
        sess = (auth.get("admin_session") or {})
        user = (auth.get("admin_user") or {})
        record_admin_audit(
            request=request,
            admin_user_id=str(user.get("id") or ""),
            admin_session_id=str(sess.get("id") or ""),
            action="pack_render",
            target_type="pack",
            target_id=pack_id,
            before_obj=None,
            after_obj={"jobs_created": created, "jobs_skipped": skipped, "jobs_enqueued": enqueued},
            summary=None,
        )
    except Exception:
        pass

    return {"ok": True, "pack_id": pack_id, "jobs_created": created, "jobs_skipped": skipped}


@app.post("/admin/packs/{pack_id}/render/{doc_id}")
def admin_pack_render_doc(pack_id: str, doc_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    auth = _require_admin(request)

    pack = get_pack(pack_id, request_id=request_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")

    doc_id = (doc_id or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id is required")

    session_id = str(pack.get("session_id") or "")
    log_event(
        "admin_render_doc_regenerate_requested",
        request_id=request_id,
        pack_id=pack_id,
        doc_id=doc_id,
    )

    docs = _load_documents_registry(request_id=request_id)
    registry_doc = None
    for d in docs:
        if str(d.get("doc_id") or "").strip() == doc_id:
            registry_doc = d
            break
    if not registry_doc:
        raise HTTPException(status_code=404, detail="Doc not found")

    access_row = get_document_access_map([doc_id], request_id=request_id).get(doc_id)
    if not _effective_doc_enabled(registry_doc, access_row):
        raise HTTPException(status_code=400, detail="DOCUMENT_DISABLED")

    job = create_render_job(
        pack_id=pack_id,
        session_id=session_id,
        user_id=None,
        doc_id=doc_id,
        status="queued",
        max_attempts=5,
        request_id=request_id,
    )
    job_id = str(job.get("id") or "")
    if not job_id:
        raise HTTPException(status_code=500, detail="Failed to create render job")

    _record_config_snapshot_artifact(
        session_id=session_id,
        pack_id=pack_id,
        doc_id=doc_id,
        render_job_id=job_id,
        request_id=request_id,
    )

    meta_row = get_document_metadata_map([doc_id], request_id=request_id).get(doc_id)
    title = _effective_doc_title(registry_doc, meta_row)

    render_request = _build_render_request(
        doc_id=doc_id,
        title=title,
        pack_id=pack_id,
        session_id=session_id,
    )
    msg = json.dumps(
        {
            "job_id": job_id,
            "pack_id": pack_id,
            "session_id": session_id,
            "doc_id": doc_id,
            "render_request": render_request,
        },
        ensure_ascii=False,
    )
    _redis_client().rpush(RENDER_QUEUE_NAME, msg)
    log_event(
        "admin_render_job_created",
        request_id=request_id,
        render_job_id=job_id,
        pack_id=pack_id,
        doc_id=doc_id,
        session_id=session_id,
    )

    try:
        sess = (auth.get("admin_session") or {})
        user = (auth.get("admin_user") or {})
        record_admin_audit(
            request=request,
            admin_user_id=str(user.get("id") or ""),
            admin_session_id=str(sess.get("id") or ""),
            action="pack_render_doc",
            target_type="pack_doc",
            target_id=f"{pack_id}:{doc_id}",
            before_obj=None,
            after_obj={"job_id": job_id},
            summary=None,
        )
    except Exception:
        pass

    return {"ok": True, "pack_id": pack_id, "doc_id": doc_id, "job_id": job_id}


@app.post("/packs/{pack_id}/render")
def packs_render(pack_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)

    pack = get_pack(pack_id, request_id=request_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    owner = pack.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    session_id = str(pack.get("session_id") or "")
    docs_all = _load_documents_registry(request_id=request_id)
    doc_ids = [str(d.get("doc_id") or "").strip() for d in docs_all if str(d.get("doc_id") or "").strip()]
    access_map = get_document_access_map(doc_ids, request_id=request_id)
    meta_map = get_document_metadata_map(doc_ids, request_id=request_id)
    docs = []
    for d in docs_all:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        if _effective_doc_enabled(d, access_map.get(doc_id)):
            docs.append(d)
    if not docs:
        raise HTTPException(status_code=500, detail="Documents registry is empty")

    log_event(
        "render_pack_requested",
        request_id=request_id,
        pack_id=pack_id,
        docs_total=len(docs),
    )

    existing = list_latest_render_jobs_for_pack(pack_id, request_id=request_id)
    existing_by_doc = {str(r.get("doc_id")): r for r in existing}

    created = 0
    skipped = 0
    enqueued = 0
    rcli = _redis_client()

    for d in docs:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        prev = existing_by_doc.get(doc_id)
        if prev and str(prev.get("status")) in {"queued", "rendering", "ready"}:
            skipped += 1
            continue

        job = create_render_job(
            pack_id=pack_id,
            session_id=session_id,
            user_id=None,
            doc_id=doc_id,
            status="queued",
            max_attempts=5,
            request_id=request_id,
        )
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        created += 1

        _record_config_snapshot_artifact(
            session_id=session_id,
            pack_id=pack_id,
            doc_id=doc_id,
            render_job_id=job_id,
            request_id=request_id,
        )

        render_request = _build_render_request(
            doc_id=doc_id,
            title=_effective_doc_title(d, meta_map.get(doc_id)),
            pack_id=pack_id,
            session_id=session_id,
        )
        msg = json.dumps(
            {
                "job_id": job_id,
                "pack_id": pack_id,
                "session_id": session_id,
                "doc_id": doc_id,
                "render_request": render_request,
            },
            ensure_ascii=False,
        )
        rcli.rpush(RENDER_QUEUE_NAME, msg)
        enqueued += 1

    log_event(
        "render_jobs_enqueued",
        request_id=request_id,
        pack_id=pack_id,
        jobs_created=created,
        jobs_skipped=skipped,
        jobs_enqueued=enqueued,
    )
    return {"ok": True, "pack_id": pack_id, "jobs_created": created, "jobs_skipped": skipped}


@app.post("/packs/{pack_id}/render/{doc_id}")
def packs_render_doc(pack_id: str, doc_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    pack = get_pack(pack_id, request_id=request_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    owner = pack.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    doc_id = (doc_id or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id is required")

    session_id = str(pack.get("session_id") or "")
    log_event(
        "render_doc_regenerate_requested",
        request_id=request_id,
        pack_id=pack_id,
        doc_id=doc_id,
    )

    docs = _load_documents_registry(request_id=request_id)
    registry_doc = None
    for d in docs:
        if str(d.get("doc_id") or "").strip() == doc_id:
            registry_doc = d
            break
    if not registry_doc:
        raise HTTPException(status_code=404, detail="Doc not found")

    access_row = get_document_access_map([doc_id], request_id=request_id).get(doc_id)
    if not _effective_doc_enabled(registry_doc, access_row):
        raise HTTPException(status_code=400, detail="DOCUMENT_DISABLED")

    job = create_render_job(
        pack_id=pack_id,
        session_id=session_id,
        user_id=None,
        doc_id=doc_id,
        status="queued",
        max_attempts=5,
        request_id=request_id,
    )
    job_id = str(job.get("id") or "")
    if not job_id:
        raise HTTPException(status_code=500, detail="Failed to create render job")

    _record_config_snapshot_artifact(
        session_id=session_id,
        pack_id=pack_id,
        doc_id=doc_id,
        render_job_id=job_id,
        request_id=request_id,
    )

    meta_row = get_document_metadata_map([doc_id], request_id=request_id).get(doc_id)
    title = _effective_doc_title(registry_doc, meta_row)

    render_request = _build_render_request(
        doc_id=doc_id,
        title=title,
        pack_id=pack_id,
        session_id=session_id,
    )
    msg = json.dumps(
        {
            "job_id": job_id,
            "pack_id": pack_id,
            "session_id": session_id,
            "doc_id": doc_id,
            "render_request": render_request,
        },
        ensure_ascii=False,
    )
    _redis_client().rpush(RENDER_QUEUE_NAME, msg)
    log_event(
        "render_job_created",
        request_id=request_id,
        render_job_id=job_id,
        pack_id=pack_id,
        doc_id=doc_id,
        session_id=session_id,
    )
    return {"ok": True, "pack_id": pack_id, "doc_id": doc_id, "job_id": job_id}


@app.get("/packs/{pack_id}/documents")
def packs_documents(pack_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    user_id = _require_user_id(request)
    pack = get_pack(pack_id, request_id=request_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    owner = pack.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    docs_all = _load_documents_registry(request_id=request_id)
    doc_ids = [str(d.get("doc_id") or "").strip() for d in docs_all if str(d.get("doc_id") or "").strip()]
    access_map = get_document_access_map(doc_ids, request_id=request_id)
    meta_map = get_document_metadata_map(doc_ids, request_id=request_id)
    docs = []
    for d in docs_all:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        if _effective_doc_enabled(d, access_map.get(doc_id)):
            docs.append(d)
    latest_jobs = list_latest_render_jobs_for_pack(pack_id, request_id=request_id)
    by_doc = {str(j.get("doc_id")): j for j in latest_jobs}

    out = []
    for d in docs:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        j = by_doc.get(doc_id)
        access_info = _doc_access_info(d, access_map.get(doc_id))
        status = "queued" if j else "queued"
        file_id = None
        attempts = 0
        last_error = None
        if j:
            status = str(j.get("status") or "queued")
            attempts = int(j.get("attempts") or 0)
            last_error = j.get("last_error")
            if status == "ready":
                file_id = get_latest_file_id_for_render_job(str(j.get("id")), request_id=request_id)
        out.append(
            {
                "doc_id": doc_id,
                "title": _effective_doc_title(d, meta_map.get(doc_id)),
                "status": status,
                "file_id": file_id,
                "attempts": attempts,
                "last_error": last_error,
                "access": access_info,
            }
        )

    log_event(
        "render_status_listed",
        request_id=request_id,
        pack_id=pack_id,
        docs_count=len(out),
    )
    return {"ok": True, "pack_id": pack_id, "documents": out}


@app.post("/events/client")
async def events_client(request: Request):
    """Receive client-side analytics events (minimal).

    Stores nothing; only logs.
    """
    request_id = get_request_id_from_request(request)
    try:
        body = await request.json()
    except Exception:
        body = None
    event = None
    props = None
    if isinstance(body, dict):
        event = body.get("event")
        props = body.get("props")
    log_event(
        "client_event",
        request_id=request_id,
        client_event=event,
        props=props,
    )
    return {"ok": True}


@app.get("/debug/session")
def debug_session(session_id: str, request: Request):
    """Read-only session debug endpoint."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    db_session = get_session(session_id, request_id=request_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    kb = db_session.get("vacancy_kb") or make_empty_vacancy_kb()
    response = {
        "session_id": session_id,
        "profession_query": db_session.get("profession_query"),
        "chat_state": db_session.get("chat_state"),
        "kb_meta": kb.get("meta", {}),
        "has_free_report": bool(db_session.get("free_report")),
        "updated_at": to_iso(db_session.get("updated_at")),
    }
    log_event(
        "debug_session_read",
        request_id=request_id,
        session_id=session_id,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
    )
    return response


@app.get("/debug/messages")
def debug_messages(session_id: str, request: Request, limit: int = 50):
    """Read-only messages debug endpoint."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    db_session = get_session(session_id, request_id=request_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = get_session_messages(session_id, limit=limit, request_id=request_id)
    normalized = []
    for msg in msgs:
        normalized.append({
            "role": msg.get("role"),
            "text": msg.get("text"),
            "created_at": to_iso(msg.get("created_at")),
        })
    response = {"session_id": session_id, "messages": normalized}
    log_event(
        "debug_messages_read",
        request_id=request_id,
        session_id=session_id,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
        messages_returned=len(normalized),
    )
    return response


@app.get("/debug/report/free")
def debug_report_free(session_id: str, request: Request):
    """Read-only free report debug endpoint."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    db_session = get_session(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    free_report = db_session.get("free_report")
    cached = bool(free_report)
    headline = free_report.get("headline") if cached else None
    response = {
        "session_id": session_id,
        "cached": cached,
        "headline": headline,
        "generated_at_iso": to_iso(db_session.get("updated_at")) if cached else None,
    }
    log_event(
        "debug_report_free_read",
        request_id=request_id,
        session_id=session_id,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
        cached=cached,
    )
    return response
