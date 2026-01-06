import json
import time
import os
import secrets
import random
import hashlib
import hmac
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import uuid
import redis
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from db import init_db, health_check, create_session as db_create_session
from db import get_session, update_session, add_message, get_session_messages
from db import set_session_user, create_artifact, create_artifact_file, get_file_download_info_for_user
from db import list_user_files
from db import (
    create_pack,
    create_render_job,
    get_latest_file_id_for_render_job,
    get_pack,
    get_render_job,
    list_latest_render_jobs_for_pack,
    list_packs_for_user,
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
from llm_client import generate_questions_and_quick_replies, health_llm
from storage.s3_client import health_s3_env, head_bucket_if_debug
from storage.s3_client import upload_bytes, presign_get

app = FastAPI()
SESSIONS = {}


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
            out.add(v)
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
        user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "nly:phone:" + phone))
        return {"user_id": user_id, "phone_e164": phone}

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
    print(json.dumps(payload, ensure_ascii=False))


def get_request_id_from_request(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def compute_duration_ms(start_time: float) -> float:
    return round((time.perf_counter() - start_time) * 1000, 2)


def _get_user_id(request: Request) -> str | None:
    # Bearer token has priority, then X-User-Id fallback (used by older front).
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

    raw = request.headers.get("X-User-Id")
    if raw:
        v = raw.strip()
        return v or None
    return None


def _require_user_id(request: Request) -> str:
    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


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
    phone = (body.phone or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")

    # Minimal mock: always generate a code; in real mode we would send SMS.
    code = str(int(time.time()))[-6:].rjust(6, "0")
    OTP_LATEST[phone] = code
    log_event(
        "auth_otp_requested",
        request_id=request_id,
        provider=provider,
    )
    return {"ok": True}


@app.get("/debug/otp/latest")
def debug_otp_latest(phone: str, request: Request):
    if not _is_debug_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    request_id = get_request_id_from_request(request)
    code = OTP_LATEST.get(phone)
    if not code:
        raise HTTPException(status_code=404, detail="No OTP")
    log_event("debug_otp_latest", request_id=request_id)
    return {"ok": True, "phone": phone, "code": code}


@app.post("/auth/otp/verify")
def auth_otp_verify(body: OtpVerify, request: Request):
    request_id = get_request_id_from_request(request)
    phone = (body.phone or "").strip()
    code = (body.code or "").strip()
    expected = OTP_LATEST.get(phone)
    if not expected or code != expected:
        raise HTTPException(status_code=401, detail="Invalid code")
    # Stable UUID for this phone (server-side; no PII in user_id).
    user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "nly:phone:" + phone))
    token = str(uuid.uuid4())
    TOKENS[token] = {"user_id": user_id, "phone_e164": phone}
    try:
        ensure_user(user_id=user_id, phone_e164=phone, request_id=request_id)
    except Exception:
        # best-effort
        pass
    log_event("auth_otp_verified", request_id=request_id)
    return {"ok": True, "token": token, "user_id": user_id}


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


def _load_documents_registry() -> list[dict]:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "documents.v1.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        docs = data.get("documents")
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
        pass
    return []


def _doc_title(doc: dict) -> str:
    t = doc.get("title")
    return str(t) if t else str(doc.get("doc_id") or "document")


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


class ChatMessage(BaseModel):
    session_id: str
    type: str
    text: str | None = None


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
def create_session_endpoint(body: SessionCreate, request: Request):
    """Create a new session and persist to database."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    session_id = str(uuid.uuid4())
    
    # Create in-memory session for backward compatibility
    SESSIONS[session_id] = {
        "profession_query": body.profession_query,
        "state": "awaiting_flow",
        "vacancy_text": None,
        "tasks": None,
        "clarifications": [],
        "vacancy_kb": make_empty_vacancy_kb(),
    }
    
    # Also save to database
    try:
        kb = make_empty_vacancy_kb()
        db_create_session(session_id, body.profession_query, kb, request_id=request_id)
        user_id = _get_user_id(request)
        if user_id:
            set_session_user(session_id, user_id, request_id=request_id)
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
    docs = [d for d in _load_documents_registry() if bool(d.get("is_enabled"))]
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

        render_request = _build_render_request(
            doc_id=doc_id,
            title=_doc_title(d),
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

    docs = _load_documents_registry()
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

    docs = [d for d in _load_documents_registry() if bool(d.get("is_enabled"))]
    latest_jobs = list_latest_render_jobs_for_pack(pack_id, request_id=request_id)
    by_doc = {str(j.get("doc_id")): j for j in latest_jobs}

    out = []
    for d in docs:
        doc_id = str(d.get("doc_id") or "").strip()
        if not doc_id:
            continue
        j = by_doc.get(doc_id)
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
                "title": _doc_title(d),
                "status": status,
                "file_id": file_id,
                "attempts": attempts,
                "last_error": last_error,
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
