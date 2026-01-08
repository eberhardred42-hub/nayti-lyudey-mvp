import json
import os
import time
import urllib.request
import urllib.error


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
    seen = set()
    quick_replies_unique = []
    for qr in quick_replies:
        if qr not in seen:
            quick_replies_unique.append(qr)
            seen.add(qr)
    return questions, quick_replies_unique[:6]


def _llm_settings() -> dict:
    provider_raw = (os.environ.get("LLM_PROVIDER") or "").strip().lower()

    api_key = (
        (os.environ.get("LLM_API_KEY") or "").strip()
        or (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        or (os.environ.get("OPENAI_API_KEY") or "").strip()
    )

    base_url = (
        (os.environ.get("LLM_BASE_URL") or "").strip()
        or (os.environ.get("OPENROUTER_BASE_URL") or "").strip()
        or (os.environ.get("OPENAI_BASE_URL") or "").strip()
    )

    if not base_url:
        if (os.environ.get("OPENROUTER_API_KEY") or "").strip():
            base_url = "https://openrouter.ai/api/v1"
        elif (os.environ.get("OPENAI_API_KEY") or "").strip():
            base_url = "https://api.openai.com/v1"

    model = (os.environ.get("LLM_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"

    if provider_raw in {"mock", "openai_compat"}:
        provider = provider_raw
    else:
        provider = "openai_compat" if (api_key and base_url) else "mock"

    return {"provider": provider, "base_url": base_url, "api_key": api_key, "model": model}


def current_llm_provider() -> str:
    return str(_llm_settings().get("provider") or "mock")


def generate_json_mock(prompt: str, schema_hint: dict, request_id: str, session_id: str):
    missing_fields = schema_hint.get("missing_fields") or []
    questions, quick_replies = _template_from_missing(missing_fields)
    if not questions:
        questions = ["Уточни город и формат работы", "Расскажи про бюджет", "Какая занятость подходит?"]
    if not quick_replies:
        quick_replies = ["Офис", "Гибрид", "Удаленка", "Полный день", "Есть бюджет"][:6]
    return {"questions": questions[:3], "quick_replies": quick_replies[:6]}


def generate_json_openai_compat(prompt: str, schema_hint: dict, request_id: str, session_id: str):
    s = _llm_settings()
    if not s["base_url"] or not s["api_key"]:
        raise RuntimeError("missing api_key or base_url")
    url = str(s["base_url"]).rstrip("/") + "/chat/completions"
    body = {
        "model": s["model"],
        "messages": [
            {"role": "system", "content": "You are a concise assistant that returns JSON only."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {s['api_key']}")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"http_error {e.code} {e.reason}")
    except Exception as e:
        raise RuntimeError(str(e))
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    _log_event(
        "llm_response",
        provider="openai_compat",
        model=s["model"],
        request_id=request_id,
        session_id=session_id,
        duration_ms=duration_ms,
        llm_response_chars=len(raw),
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
        return json.loads(content)
    except Exception as e:
        _log_event(
            "llm_invalid_output",
            level="error",
            provider="openai_compat",
            model=s["model"],
            request_id=request_id,
            session_id=session_id,
            error=f"invalid_content_json {e}",
        )
        raise RuntimeError(f"invalid_content_json {e}")


def generate_json_openai_compat_messages(messages: list[dict], request_id: str, session_id: str) -> dict:
    """Call OpenAI-compatible /chat/completions with a full messages array.

    Must return a JSON object (via response_format).
    """
    s = _llm_settings()
    if not s["base_url"] or not s["api_key"]:
        raise RuntimeError("missing api_key or base_url")
    url = str(s["base_url"]).rstrip("/") + "/chat/completions"
    body = {
        "model": s["model"],
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {s['api_key']}")

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"http_error {e.code} {e.reason}")
    except Exception as e:
        raise RuntimeError(str(e))

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    prompt_chars = 0
    try:
        prompt_chars = sum(len(str(m.get("content") or "")) for m in (messages or []))
    except Exception:
        prompt_chars = 0
    _log_event(
        "llm_response",
        provider="openai_compat",
        model=s["model"],
        request_id=request_id,
        session_id=session_id,
        duration_ms=duration_ms,
        prompt_chars=prompt_chars,
        llm_response_chars=len(raw),
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
        out = json.loads(content)
    except Exception as e:
        _log_event(
            "llm_invalid_output",
            level="error",
            provider="openai_compat",
            model=s["model"],
            request_id=request_id,
            session_id=session_id,
            error=f"invalid_content_json {e}",
        )
        raise RuntimeError(f"invalid_content_json {e}")
    if not isinstance(out, dict):
        raise RuntimeError("result_not_dict")
    return out


def generate_json_messages(messages: list[dict], request_id: str, session_id: str, fallback: dict) -> dict:
    """Provider wrapper returning JSON dict; never raises."""
    s = _llm_settings()
    provider = s["provider"]
    try:
        if provider == "openai_compat":
            return generate_json_openai_compat_messages(messages, request_id=request_id, session_id=session_id)
        return fallback
    except Exception as e:
        _log_event(
            "llm_error",
            level="error",
            provider=provider,
            model=s["model"],
            request_id=request_id,
            session_id=session_id,
            error=str(e),
        )
        return fallback


def generate_questions_and_quick_replies(context: dict) -> dict:
    request_id = context.get("request_id", "unknown")
    session_id = context.get("session_id", "unknown")
    missing_fields = context.get("missing_fields") or []

    s = _llm_settings()
    provider = s["provider"]

    prompt_parts = [
        "Ты помогаешь рекрутеру уточнить вводные. Верни JSON с ключами questions и quick_replies.",
        f"Профиль: {context.get('profession_query') or 'не указан'}",
        f"Последнее сообщение: {context.get('last_user_message') or 'нет'}",
        f"Недостающие поля: {', '.join(missing_fields) or 'нет'}",
    ]
    prompt = "\n".join(prompt_parts)

    _log_event(
        "llm_request",
        provider=provider,
        model=s["model"],
        request_id=request_id,
        session_id=session_id,
        prompt_chars=len(prompt),
    )

    schema_hint = {"missing_fields": missing_fields}
    start = time.perf_counter()
    try:
        if provider == "openai_compat":
            result = generate_json_openai_compat(prompt, schema_hint, request_id, session_id)
        else:
            result = generate_json_mock(prompt, schema_hint, request_id, session_id)
    except Exception as e:
        _log_event(
            "llm_error",
            level="error",
            provider=provider,
            model=s["model"],
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
        model=s["model"],
        request_id=request_id,
        session_id=session_id,
        duration_ms=duration_ms,
        llm_response_chars=len(json.dumps(result)) if isinstance(result, dict) else None,
    )

    if not isinstance(result, dict):
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
    s = _llm_settings()
    provider = s["provider"]
    if provider == "mock":
        return {"ok": True, "provider": "mock"}
    if provider == "openai_compat":
        if not s["base_url"] or not s["api_key"]:
            return {"ok": False, "provider": "openai_compat", "reason": "missing api_key or base_url"}
        return {"ok": True, "provider": "openai_compat"}
    return {"ok": False, "provider": provider, "reason": "unsupported provider"}
