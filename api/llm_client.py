import json
import os
import time
import urllib.request
import urllib.error
import socket
from typing import Any

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mock").strip().lower() or "mock"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").strip()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip() or "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "z-ai/glm-4.5-air:free").strip() or "z-ai/glm-4.5-air:free"
OPENROUTER_FALLBACK_MODELS = os.environ.get("OPENROUTER_FALLBACK_MODELS", "").strip()
OPENROUTER_HTTP_REFERER = os.environ.get("OPENROUTER_HTTP_REFERER", "https://naitilyudei.ru").strip() or "https://naitilyudei.ru"
OPENROUTER_APP_TITLE = os.environ.get("OPENROUTER_APP_TITLE", "nayti-lyudey").strip() or "nayti-lyudey"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        v = int(str(raw).strip())
        return v if v > 0 else default
    except Exception:
        return default


LLM_TIMEOUT_S = _env_int("LLM_TIMEOUT_S", 20)
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 600)


def _log_event(event: str, level: str = "info", **fields):
    try:
        from main import log_event as main_log_event  # type: ignore
    except Exception:
        main_log_event = None
    if main_log_event:
        main_log_event(event, level=level, **fields)
    else:
        payload = {"event": event, "level": level, **fields}
        print(json.dumps(payload, ensure_ascii=False))


def _template_from_missing(missing_fields):
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
    # Deduplicate while preserving order
    seen = set()
    quick_replies_unique = []
    for qr in quick_replies:
        if qr not in seen:
            quick_replies_unique.append(qr)
            seen.add(qr)
    return questions, quick_replies_unique[:6]


def generate_json_mock(prompt: str, schema_hint: dict, request_id: str, session_id: str):
    missing_fields = schema_hint.get("missing_fields") or []
    questions, quick_replies = _template_from_missing(missing_fields)
    if not questions:
        questions = ["Уточни город и формат работы", "Расскажи про бюджет", "Какая занятость подходит?"]
    if not quick_replies:
        quick_replies = ["Офис", "Гибрид", "Удаленка", "Полный день", "Есть бюджет"][:6]
    return {"questions": questions[:3], "quick_replies": quick_replies[:6]}


def generate_json_openai_compat(prompt: str, schema_hint: dict, request_id: str, session_id: str):
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("missing LLM_BASE_URL or LLM_API_KEY")
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Return ONLY valid JSON. No markdown. No commentary.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": int(LLM_MAX_TOKENS),
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {LLM_API_KEY}")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=float(LLM_TIMEOUT_S)) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"http_error {e.code} {e.reason}")
    except Exception as e:
        raise RuntimeError(str(e))
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    _log_event(
        "llm_response",
        provider="openai_compat",
        model=LLM_MODEL,
        request_id=request_id,
        session_id=session_id,
        duration_ms=duration_ms,
        http_code=200,
    )
    try:
        parsed = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"invalid_json {e}")
    content = None
    try:
        content = parsed["choices"][0]["message"]["content"]
    except Exception:
        pass
    if not content:
        raise RuntimeError("empty_content")
    try:
        return _parse_strict_json(content)
    except Exception as e:
        _log_event(
            "llm_invalid_output",
            level="error",
            provider="openai_compat",
            model=LLM_MODEL,
            request_id=request_id,
            session_id=session_id,
            error=f"invalid_content_json {e}",
        )
        raise RuntimeError(f"invalid_content_json {e}")


def _strip_code_fences(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        # Drop the first fence line and the last fence.
        lines = s.splitlines()
        if len(lines) >= 2:
            # remove first line
            lines = lines[1:]
            # remove last fence if present
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
    return s


def _extract_first_json_object(text: str) -> str | None:
    s = text
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
    return None


def _parse_strict_json(text: str) -> dict:
    s = _strip_code_fences(text)
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    candidate = _extract_first_json_object(s)
    if candidate:
        obj2 = json.loads(candidate)
        if isinstance(obj2, dict):
            return obj2
    raise RuntimeError("invalid_json_output")


def _csv_list(raw: str) -> list[str]:
    out: list[str] = []
    for part in (raw or "").split(","):
        v = part.strip()
        if v:
            out.append(v)
    return out


def _openrouter_models() -> list[str]:
    models = [OPENROUTER_MODEL]
    models.extend(_csv_list(OPENROUTER_FALLBACK_MODELS))
    seen: set[str] = set()
    uniq: list[str] = []
    for m in models:
        if m not in seen:
            uniq.append(m)
            seen.add(m)
    return uniq


def _is_retryable_http(code: int) -> bool:
    if code == 429:
        return True
    return 500 <= code <= 599


def _openrouter_post_chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
    request_id: str,
    session_id: str,
) -> tuple[int, str]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("missing OPENROUTER_API_KEY")
    url = OPENROUTER_BASE_URL.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {OPENROUTER_API_KEY}")
    req.add_header("HTTP-Referer", OPENROUTER_HTTP_REFERER)
    req.add_header("X-Title", OPENROUTER_APP_TITLE)

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            raw = resp.read().decode("utf-8")
            code = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as e:
        code = int(e.code)
        try:
            raw = e.read().decode("utf-8")
        except Exception:
            raw = ""
    except (socket.timeout, TimeoutError):
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        _log_event(
            "llm_response",
            provider="openrouter",
            model=model,
            request_id=request_id,
            session_id=session_id,
            duration_ms=duration_ms,
            http_code="timeout",
        )
        raise
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        _log_event(
            "llm_response",
            provider="openrouter",
            model=model,
            request_id=request_id,
            session_id=session_id,
            duration_ms=duration_ms,
            http_code="error",
        )
        raise
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    _log_event(
        "llm_response",
        provider="openrouter",
        model=model,
        request_id=request_id,
        session_id=session_id,
        duration_ms=duration_ms,
        http_code=code,
    )
    return code, raw


def generate_json_openrouter(prompt: str, request_id: str, session_id: str) -> dict:
    models = _openrouter_models()
    last_error: str | None = None
    for model in models:
        for attempt in range(2):
            try:
                code, raw = _openrouter_post_chat(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Return ONLY valid JSON. No markdown. No commentary.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=int(LLM_MAX_TOKENS),
                    temperature=0.2,
                    timeout_s=float(LLM_TIMEOUT_S),
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception as e:
                last_error = str(e)
                if attempt == 0:
                    continue
                break

            if code != 200:
                if _is_retryable_http(code):
                    if attempt == 0:
                        continue
                    break
                raise RuntimeError(f"http_error {code}")

            try:
                parsed = json.loads(raw)
                content = parsed["choices"][0]["message"]["content"]
            except Exception as e:
                raise RuntimeError(f"invalid_response_shape {e}")
            return _parse_strict_json(str(content))

    raise RuntimeError(last_error or "openrouter_failed")


def generate_questions_and_quick_replies(context: dict) -> dict:
    request_id = context.get("request_id", "unknown")
    session_id = context.get("session_id", "unknown")
    missing_fields = context.get("missing_fields") or []
    provider = LLM_PROVIDER

    prompt_parts = [
        "Ты помогаешь рекрутеру уточнить вводные. Верни JSON с ключами questions и quick_replies.",
        f"Профиль: {context.get('profession_query') or 'не указан'}",
        f"Последнее сообщение: {context.get('last_user_message') or 'нет'}",
        f"Недостающие поля: {', '.join(missing_fields) or 'нет'}",
    ]
    prompt = "\n".join(prompt_parts)

    _log_event("llm_request", provider=provider, model=LLM_MODEL, request_id=request_id, session_id=session_id)

    schema_hint = {"missing_fields": missing_fields}
    start = time.perf_counter()
    try:
        if provider == "openrouter":
            result = generate_json_openrouter(prompt, request_id, session_id)
        elif provider == "openai_compat":
            result = generate_json_openai_compat(prompt, schema_hint, request_id, session_id)
        else:
            result = generate_json_mock(prompt, schema_hint, request_id, session_id)
    except Exception as e:
        _log_event(
            "llm_error",
            level="error",
            provider=provider,
            model=LLM_MODEL,
            request_id=request_id,
            session_id=session_id,
            error=str(e),
        )
        questions, quick_replies = _template_from_missing(missing_fields)
        return {"questions": questions[:3], "quick_replies": quick_replies[:6]}
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    _log_event(
        "llm_response",
        provider=provider,
        model=LLM_MODEL,
        request_id=request_id,
        session_id=session_id,
        duration_ms=duration_ms,
        llm_response_chars=len(json.dumps(result)) if isinstance(result, dict) else None,
    )

    if not isinstance(result, dict):
        _log_event(
            "llm_invalid_output",
            level="error",
            provider=provider,
            model=LLM_MODEL,
            request_id=request_id,
            session_id=session_id,
            error="result_not_dict",
        )
        questions, quick_replies = _template_from_missing(missing_fields)
        return {"questions": questions[:3], "quick_replies": quick_replies[:6]}

    questions = result.get("questions") if isinstance(result, dict) else []
    quick_replies = result.get("quick_replies") if isinstance(result, dict) else []
    if not questions or not isinstance(questions, list):
        questions, _qr = _template_from_missing(missing_fields)
        quick_replies = quick_replies or _qr
    if not quick_replies or not isinstance(quick_replies, list):
        _q, quick_replies = _template_from_missing(missing_fields)
    return {
        "questions": [q for q in questions if isinstance(q, str)][:3],
        "quick_replies": [q for q in quick_replies if isinstance(q, str)][:6],
    }


def health_llm() -> dict:
    provider = LLM_PROVIDER
    if provider == "mock":
        return {"ok": True, "provider": "mock"}
    if provider == "openai_compat":
        if not LLM_BASE_URL or not LLM_API_KEY:
            return {"ok": False, "provider": "openai_compat", "reason": "missing LLM_API_KEY or LLM_BASE_URL"}
        return {"ok": True, "provider": "openai_compat"}
    if provider == "openrouter":
        if not OPENROUTER_API_KEY:
            return {"ok": False, "provider": "openrouter", "reason": "missing OPENROUTER_API_KEY"}
        model = _openrouter_models()[0] if _openrouter_models() else OPENROUTER_MODEL
        try:
            code, _raw = _openrouter_post_chat(
                model=model,
                messages=[
                    {"role": "system", "content": "Respond with pong"},
                    {"role": "user", "content": "ping"},
                ],
                max_tokens=1,
                temperature=0.0,
                timeout_s=min(float(LLM_TIMEOUT_S), 10.0),
                request_id="health",
                session_id="health",
            )
            if code != 200:
                return {
                    "ok": False,
                    "provider": "openrouter",
                    "model": model,
                    "base_url": OPENROUTER_BASE_URL,
                    "reason": f"http_{code}",
                }
        except Exception as e:
            return {
                "ok": False,
                "provider": "openrouter",
                "model": model,
                "base_url": OPENROUTER_BASE_URL,
                "reason": str(e),
            }
        return {"ok": True, "provider": "openrouter", "model": model, "base_url": OPENROUTER_BASE_URL}
    return {"ok": False, "provider": provider, "reason": "unsupported provider"}
