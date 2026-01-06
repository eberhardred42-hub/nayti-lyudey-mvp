import json
import time
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import uuid
import re
import os
import urllib.request
import urllib.error
from datetime import datetime
from db import init_db, health_check, create_session as db_create_session
from db import get_session, update_session, add_message, get_session_messages
from db import add_artifact as db_add_artifact, list_artifacts as db_list_artifacts
from llm_client import generate_questions_and_quick_replies, health_llm

app = FastAPI()
SESSIONS = {}

ML_BASE_URL = os.environ.get("ML_BASE_URL", "http://localhost:8001").strip() or "http://localhost:8001"


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


class MlJobRequest(BaseModel):
    session_id: str
    vacancy_profile: dict | None = None


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
        return {
            "reply": reply,
            "quick_replies": quick_replies,
            "clarifying_questions": clarifying_questions,
            "should_show_free_result": False,
        }

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


def normalize_kind_and_meta(kind: str, meta: dict | None) -> tuple[str, dict]:
    meta = dict(meta or {})
    legacy_map = {
        "tasks_summary": "role_snapshot_json",
        "screening_questions": "screening_script_json",
        "sourcing_pack": "sourcing_pack_json",
    }
    if kind in legacy_map:
        meta.setdefault("legacy_kind", kind)
        return legacy_map[kind], meta
    return kind, meta


def infer_format(kind: str, payload_json: dict | None, payload_text: str | None) -> str:
    if payload_json is not None:
        return "json"
    if payload_text is not None:
        if kind.endswith("_md"):
            return "md"
        return "text"
    # defensive default (should not happen)
    return "json"


def call_ml_run(vacancy_profile: dict, request_id: str, session_id: str) -> dict:
    url = ML_BASE_URL.rstrip("/") + "/run"
    payload_bytes = json.dumps(vacancy_profile, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        method="POST",
        headers={"Content-Type": "application/json", "X-Request-Id": request_id},
    )
    log_event(
        "ml_request",
        request_id=request_id,
        session_id=session_id,
        url=url,
        payload_chars=len(payload_bytes),
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"error": "ml_http_error", "body": body[:1000]}
        # If ML returns structured 400, pass it through
        if e.code == 400:
            raise HTTPException(status_code=400, detail=parsed)
        raise HTTPException(status_code=502, detail={"error": "ml_failed", "status": e.code, "detail": parsed})
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "ml_unavailable", "detail": str(e)})


def default_vacancy_profile_from_session(session_id: str, profession_query: str, kb: dict) -> dict:
    role_title = (kb.get("role") or {}).get("role_title") or profession_query or "Role"
    work_format = (kb.get("company") or {}).get("work_format") or "unknown"
    city = (kb.get("company") or {}).get("company_location_city")
    region = (kb.get("company") or {}).get("company_location_region")
    salary_min = (kb.get("compensation") or {}).get("salary_min_rub")
    salary_max = (kb.get("compensation") or {}).get("salary_max_rub")
    # tolerate missing/invalid: default to 0..0 but keep structure valid for ML
    try:
        salary_min = int(salary_min) if salary_min is not None else 0
    except Exception:
        salary_min = 0
    try:
        salary_max = int(salary_max) if salary_max is not None else salary_min
    except Exception:
        salary_max = salary_min

    return {
        "meta": {"contract_version": "v1", "kind": "vacancy_profile"},
        "role": {"title": role_title, "domain": None, "seniority": None},
        "company": {
            "name": None,
            "location": {"city": city, "region": region, "country": "RU"},
            "work_format": work_format,
        },
        "compensation": {"range": {"currency": "RUB", "min": salary_min, "max": salary_max}, "comment": None},
    }


@app.post("/ml/job")
def ml_job(body: MlJobRequest, request: Request):
    """Run ML job and persist artifacts with stable {kind, format, payload_json/payload_text} contract."""
    start_time = time.perf_counter()
    request_id = get_request_id_from_request(request)
    session_id = body.session_id

    db_session = get_session(session_id, request_id=request_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")

    kb = db_session.get("vacancy_kb") or {}
    vacancy_profile = body.vacancy_profile or default_vacancy_profile_from_session(
        session_id=session_id,
        profession_query=db_session.get("profession_query") or "",
        kb=kb,
    )

    pack = call_ml_run(vacancy_profile, request_id=request_id, session_id=session_id)

    # Persist artifacts (normalized)
    items_for_manifest: list[dict] = []

    def persist_envelope(envelope: dict):
        artifact_id = envelope.get("artifact_id") or str(uuid.uuid4())
        kind = envelope.get("kind") or "unknown"
        meta = (envelope.get("meta") or {})
        content = envelope.get("content")

        kind_norm, meta_norm = normalize_kind_and_meta(kind, meta)

        payload_json = content if isinstance(content, dict) else None
        payload_text = content if isinstance(content, str) else None
        if payload_text is None and isinstance(content, dict) and "markdown" in content and isinstance(content.get("markdown"), str):
            # allow content={markdown: "..."} to be treated as md
            payload_text = content.get("markdown")
            payload_json = None
            kind_norm = "free_report_md" if kind_norm == "free_report_md" else kind_norm

        fmt = infer_format(kind_norm, payload_json=payload_json, payload_text=payload_text)

        # never store format as None
        db_add_artifact(
            session_id=session_id,
            artifact_id=artifact_id,
            kind=kind_norm,
            format=fmt,
            payload_json=payload_json,
            payload_text=payload_text,
            meta=meta_norm,
            request_id=request_id,
        )
        items_for_manifest.append({"artifact_id": artifact_id, "kind": kind_norm, "format": fmt})

    for layer_name in ["user_result", "trace"]:
        layer = (pack.get(layer_name) or {})
        for env in (layer.get("artifacts") or []):
            if isinstance(env, dict):
                persist_envelope(env)

    # Always persist manifest artifact (with items)
    manifest_artifact_id = f"manifest_{uuid.uuid4().hex[:8]}"
    db_add_artifact(
        session_id=session_id,
        artifact_id=manifest_artifact_id,
        kind="manifest",
        format="json",
        payload_json={"items": items_for_manifest},
        payload_text=None,
        meta={},
        request_id=request_id,
    )

    log_event(
        "ml_job_saved",
        request_id=request_id,
        session_id=session_id,
        route=str(request.url.path),
        method=request.method,
        duration_ms=compute_duration_ms(start_time),
        artifacts_saved=len(items_for_manifest) + 1,
    )

    return {"session_id": session_id, "manifest_artifact_id": manifest_artifact_id}


@app.get("/artifacts")
def list_artifacts_endpoint(session_id: str, request: Request):
    request_id = get_request_id_from_request(request)
    db_session = get_session(session_id, request_id=request_id)
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    artifacts = db_list_artifacts(session_id, request_id=request_id)
    # Ensure format is never None in response
    for a in artifacts:
        if not a.get("format"):
            a["format"] = infer_format(a.get("kind") or "unknown", a.get("payload_json"), a.get("payload_text"))
    return {"session_id": session_id, "artifacts": artifacts}


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
