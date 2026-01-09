import json
import os
import socket
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Mapping, Sequence, TypedDict, cast

JSONDict = dict[str, Any]
Message = dict[str, Any]


class LLMUnavailable(RuntimeError):
    def __init__(self, reason: str, message: str = "LLM unavailable"):
        super().__init__(message)
        self.reason = reason


class LLMSettings(TypedDict):
    provider: str
    provider_raw: str
    provider_effective: str
    reason: str
    require_key: bool
    base_url: str
    api_key: str
    key_present: bool
    key_source: str
    model: str
    deployment: str


def _log_event(event: str, level: str = "info", **fields: Any) -> None:
    try:
        from main import log_event as main_log_event  # type: ignore
    except Exception:
        main_log_event = None
    if main_log_event:
        main_log_event(event, level=level, **fields)
    else:
        payload: JSONDict = {"event": event, "level": level, **fields}
        print(json.dumps(payload, ensure_ascii=False))


def _template_from_missing(missing_fields: Sequence[str]) -> tuple[list[str], list[str]]:
    questions: list[str] = []
    quick_replies: list[str] = []
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
    seen: set[str] = set()
    quick_replies_unique: list[str] = []
    for qr in quick_replies:
        if qr not in seen:
            quick_replies_unique.append(qr)
            seen.add(qr)
    return questions, quick_replies_unique[:6]


def _deployment_env() -> str:
    """Return deployment environment selector.

    - "dev" / "prod" activate DEV_LLM_* / PROD_LLM_* resolution.
    - empty/other keeps backward-compatible local env (LLM_*).
    """
    return (os.environ.get("NLY_ENV") or "").strip().lower()


def _llm_settings() -> LLMSettings:
    provider_raw = (os.environ.get("LLM_PROVIDER") or "").strip().lower()

    def _bool_env(name: str) -> bool:
        return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}

    require_key = _bool_env("LLM_REQUIRE_KEY") or _bool_env("REQUIRE_LLM")

    deployment = _deployment_env()

    api_key = ""
    key_source = "none"
    base_url = ""
    model = ""

    if deployment in {"dev", "prod"}:
        prefix = "DEV_LLM_" if deployment == "dev" else "PROD_LLM_"
        base_url = (os.environ.get(prefix + "BASE_URL") or "").strip()
        model = (os.environ.get(prefix + "MODEL") or "").strip()
        api_key = (os.environ.get(prefix + "API_KEY") or "").strip()
        if api_key:
            key_source = prefix + "API_KEY"
        if not model:
            model = "gpt-4o-mini"
    else:
        # Local/backward-compatible env names.
        api_key = (os.environ.get("LLM_API_KEY") or "").strip() or (os.environ.get("OPENAI_API_KEY") or "").strip()
        if (os.environ.get("LLM_API_KEY") or "").strip():
            key_source = "LLM_API_KEY"
        elif (os.environ.get("OPENAI_API_KEY") or "").strip():
            key_source = "OPENAI_API_KEY"
        base_url = (os.environ.get("LLM_BASE_URL") or "").strip() or (os.environ.get("OPENAI_BASE_URL") or "").strip()
        model = (os.environ.get("LLM_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"

    key_present = bool(api_key)

    # Determine effective provider.
    provider_effective = "openai_compat"
    reason = "ok"

    if provider_raw == "mock":
        provider_effective = "mock"
        reason = "provider_forced_mock"
    elif provider_raw == "openai_compat":
        provider_effective = "openai_compat"
        reason = "provider_forced_openai_compat"
    else:
        # Auto mode
        if require_key:
            provider_effective = "openai_compat"
            reason = "provider_auto_openai_compat"
        else:
            if key_present and base_url:
                provider_effective = "openai_compat"
                reason = "provider_auto_openai_compat"
            else:
                provider_effective = "mock"
                reason = "missing_api_key" if not key_present else "missing_base_url"

    return {
        "provider": provider_effective,
        "provider_raw": provider_raw,
        "provider_effective": provider_effective,
        "reason": reason,
        "require_key": require_key,
        "base_url": base_url,
        "api_key": api_key,
        "key_present": key_present,
        "key_source": key_source,
        "model": model,
        "deployment": deployment,
    }


def current_llm_provider() -> str:
    return str(_llm_settings().get("provider") or "mock")


def _require_llm_configured(s: Mapping[str, Any]) -> None:
    if not s.get("require_key"):
        return
    if s.get("provider_effective") == "mock":
        # Only allowed if forced explicitly.
        if (s.get("provider_raw") or "") == "mock":
            return
        raise LLMUnavailable("provider_forced_mock", "LLM is required but provider_effective is mock")
    if not s.get("key_present"):
        raise LLMUnavailable("missing_api_key", "LLM is not configured: missing_api_key")
    if not (s.get("base_url") or ""):
        raise LLMUnavailable("missing_base_url", "LLM is not configured: missing_base_url")


def generate_json_mock(prompt: str, schema_hint: JSONDict, request_id: str, session_id: str) -> JSONDict:
    missing_fields_raw = schema_hint.get("missing_fields")
    missing_fields: list[str] = []
    if isinstance(missing_fields_raw, list):
        for item in cast(list[Any], missing_fields_raw):
            missing_fields.append(str(item))
    questions, quick_replies = _template_from_missing(missing_fields)
    if not questions:
        questions = ["Уточни город и формат работы", "Расскажи про бюджет", "Какая занятость подходит?"]
    if not quick_replies:
        quick_replies = ["Офис", "Гибрид", "Удаленка", "Полный день", "Есть бюджет"][:6]
    return {"questions": questions[:3], "quick_replies": quick_replies[:6]}


def generate_json_openai_compat(prompt: str, schema_hint: JSONDict, request_id: str, session_id: str) -> JSONDict:
    s = _llm_settings()
    _require_llm_configured(s)
    if not s["base_url"] or not s["api_key"]:
        raise LLMUnavailable("missing_api_key", "LLM is not configured")
    url = str(s["base_url"]).rstrip("/") + "/chat/completions"
    body: JSONDict = {
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


def generate_json_openai_compat_messages(messages: list[Message], request_id: str, session_id: str) -> JSONDict:
    """Call OpenAI-compatible /chat/completions with a full messages array.

    Must return a JSON object (via response_format).
    """
    s = _llm_settings()
    _require_llm_configured(s)
    if not s["base_url"] or not s["api_key"]:
        raise LLMUnavailable("missing_api_key", "LLM is not configured")
    url = str(s["base_url"]).rstrip("/") + "/chat/completions"
    body: JSONDict = {
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
        out_any: Any = json.loads(content)
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
    if not isinstance(out_any, dict):
        raise RuntimeError("result_not_dict")
    out: JSONDict = cast(JSONDict, out_any)
    return out


def generate_json_messages(messages: list[Message], request_id: str, session_id: str, fallback: JSONDict) -> JSONDict:
    """Provider wrapper returning JSON dict; never raises."""
    return generate_json_messages_observable(messages, request_id, session_id, fallback)


def generate_json_messages_observable(
    messages: list[Message],
    request_id: str,
    session_id: str,
    fallback: JSONDict,
    *,
    flow: str | None = None,
    doc_id: str | None = None,
    attempt: int = 1,
) -> JSONDict:
    """Provider wrapper returning JSON dict.

    Emits llm_request/llm_response/llm_error via log_event(); persistence is handled centrally.
    """
    s = _llm_settings()
    provider = s["provider"]
    provider_s = str(provider)

    _require_llm_configured(s)

    start_total = time.perf_counter()

    prompt_chars = 0
    try:
        prompt_chars = sum(len(str(m.get("content") or "")) for m in (messages or []))
    except Exception:
        prompt_chars = 0

    _log_event(
        "llm_request",
        provider=provider_s,
        model=s["model"],
        request_id=request_id,
        session_id=session_id,
        flow=flow,
        doc_id=doc_id,
        attempt=int(attempt or 1),
        prompt_chars=int(prompt_chars),
        mode="real" if provider_s != "mock" else "mock",
        base_url=(s.get("base_url") or ""),
    )
    try:
        if provider_s == "openai_compat":
            start = time.perf_counter()
            out = generate_json_openai_compat_messages(messages, request_id=request_id, session_id=session_id)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            _log_event(
                "llm_response",
                provider=provider_s,
                model=s["model"],
                request_id=request_id,
                session_id=session_id,
                flow=flow,
                doc_id=doc_id,
                attempt=int(attempt or 1),
                duration_ms=duration_ms,
                ok=True,
                fallback=False,
                parsed_ok=True,
                llm_response_chars=len(json.dumps(out, ensure_ascii=False)),
                mode="real",
                base_url=(s.get("base_url") or ""),
            )
            return out

        _log_event(
            "llm_response",
            provider=provider_s,
            model=s["model"],
            request_id=request_id,
            session_id=session_id,
            flow=flow,
            doc_id=doc_id,
            attempt=int(attempt or 1),
            duration_ms=None,
            ok=False,
            fallback=True,
            parsed_ok=False,
            llm_response_chars=None,
            mode="mock",
            base_url=(s.get("base_url") or ""),
        )
        return fallback
    except Exception as e:
        _log_event(
            "llm_error",
            level="error",
            provider=provider,
            model=s["model"],
            request_id=request_id,
            session_id=session_id,
            flow=flow,
            doc_id=doc_id,
            attempt=int(attempt or 1),
            duration_ms=round((time.perf_counter() - start_total) * 1000, 2),
            error=str(e),
            base_url=(s.get("base_url") or ""),
        )
        # If LLM is required and misconfigured, surface as 503 upstream.
        _require_llm_configured(s)
        return fallback


def generate_questions_and_quick_replies(context: JSONDict) -> JSONDict:
    request_id = str(context.get("request_id") or "unknown")
    session_id = str(context.get("session_id") or "unknown")
    missing_fields_raw = context.get("missing_fields")
    missing_fields: list[str] = []
    if isinstance(missing_fields_raw, list):
        for item in cast(list[Any], missing_fields_raw):
            missing_fields.append(str(item))

    s = _llm_settings()
    provider = s["provider"]

    _require_llm_configured(s)

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
        flow="intro_questions",
        attempt=1,
        prompt_chars=len(prompt),
        mode="real" if provider != "mock" else "mock",
        base_url=(s.get("base_url") or ""),
    )

    schema_hint: JSONDict = {"missing_fields": missing_fields}
    start = time.perf_counter()
    try:
        if provider == "openai_compat":
            result: JSONDict = generate_json_openai_compat(prompt, schema_hint, request_id, session_id)
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
            flow="intro_questions",
            attempt=1,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            error=str(e),
            base_url=(s.get("base_url") or ""),
        )
        questions, quick_replies = _template_from_missing(missing_fields)
        _require_llm_configured(s)
        return {"questions": questions[:3], "quick_replies": quick_replies[:6]}

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    provider_s = str(provider)
    _log_event(
        "llm_response",
        provider=provider_s,
        model=s["model"],
        request_id=request_id,
        session_id=session_id,
        flow="intro_questions",
        attempt=1,
        duration_ms=duration_ms,
        llm_response_chars=len(json.dumps(result, ensure_ascii=False)),
        ok=True,
        fallback=False,
        parsed_ok=True,
        mode="real" if provider_s != "mock" else "mock",
        base_url=(s.get("base_url") or ""),
    )

    questions_any = result.get("questions")
    quick_replies_any = result.get("quick_replies")
    questions: list[Any] = cast(list[Any], questions_any) if isinstance(questions_any, list) else []
    quick_replies: list[Any] = cast(list[Any], quick_replies_any) if isinstance(quick_replies_any, list) else []
    if not questions:
        questions, _qr = _template_from_missing(missing_fields)
        quick_replies = quick_replies or _qr
    if not quick_replies:
        _q, quick_replies = _template_from_missing(missing_fields)
    return {
        "questions": [q for q in questions if isinstance(q, str)][:3],
        "quick_replies": [q for q in quick_replies if isinstance(q, str)][:6],
    }


def health_llm() -> JSONDict:
    s = _llm_settings()

    provider_effective = s.get("provider_effective") or s.get("provider") or "mock"
    provider_raw = s.get("provider_raw") or ""
    model = s.get("model")
    key_present = bool(s.get("key_present"))
    key_source = s.get("key_source") or "none"
    require_key = bool(s.get("require_key"))

    base_url_raw = (s.get("base_url") or "").strip()
    base_url_safe = ""
    try:
        if base_url_raw:
            parsed = urllib.parse.urlparse(base_url_raw)
            base_url_safe = urllib.parse.urlunparse(
                (parsed.scheme or "https", parsed.netloc, parsed.path, "", "", "")
            )
    except Exception:
        base_url_safe = ""

    ok = True
    reason = "ok"
    if provider_effective == "openai_compat":
        if not key_present:
            ok = False
            reason = "missing_api_key"
        elif not base_url_raw:
            ok = False
            reason = "missing_base_url"
    elif provider_effective == "mock":
        # If mock is effective, always explain why.
        if provider_raw == "mock":
            reason = "provider_forced_mock"
        else:
            reason = s.get("reason") or "unknown"
    else:
        ok = False
        reason = "unsupported_provider"

    resp: JSONDict = {
        "ok": ok,
        "provider": provider_effective,
        "provider_effective": provider_effective,
        "model": model,
        "base_url": base_url_safe,
        "key_present": key_present,
        "key_source": key_source,
        "reason": reason,
        "llm_require_key": require_key,
    }

    if provider_effective == "mock" and not resp.get("reason"):
        resp["reason"] = "unknown"
    return resp


def llm_ping(*, request_id: str, session_id: str = "llm_ping") -> JSONDict:
    """Run a single short real completion to verify provider connectivity."""
    s = _llm_settings()
    provider = s.get("provider_effective") or s.get("provider") or "mock"
    model = s.get("model") or ""

    base_url = (s.get("base_url") or "").strip()

    def _trunc(text: str, limit: int = 400) -> str:
        t = (text or "").strip()
        if len(t) <= limit:
            return t
        return t[:limit]

    _log_event(
        "llm_ping_request",
        provider=provider,
        model=model,
        request_id=request_id,
        session_id=session_id,
        base_url=base_url,
        mode="real" if provider != "mock" else "mock",
    )

    # Validate config (strict mode may raise). Convert to structured response.
    try:
        _require_llm_configured(s)
    except LLMUnavailable as e:
        msg = _trunc(str(e))
        _log_event(
            "llm_ping_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            provider_effective=provider,
            base_url=base_url,
            model=model,
            status_code=503,
            error_class="config",
            message_trunc=_trunc(str(e.reason or "")) or msg,
        )
        _log_event(
            "llm_ping_response",
            provider=provider,
            model=model,
            request_id=request_id,
            session_id=session_id,
            ok=False,
            status=str(e.reason or "llm_unavailable"),
            latency_ms=0,
            base_url=base_url,
        )
        return {
            "ok": False,
            "provider_effective": provider,
            "model": model,
            "base_url": base_url,
            "latency_ms": 0,
            "status_code": 503,
            "error_class": "config",
            "reason": str(e.reason or "llm_unavailable"),
            "message_trunc": _trunc(str(e.reason or "")) or msg,
        }

    if provider != "openai_compat":
        # If mock is effective, treat as unavailable in strict mode.
        msg = "LLM ping requires real provider (provider_effective is mock)"
        _log_event(
            "llm_ping_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            provider_effective=provider,
            base_url=base_url,
            model=model,
            status_code=503,
            error_class="config",
            message_trunc=_trunc(msg),
        )
        _log_event(
            "llm_ping_response",
            provider=provider,
            model=model,
            request_id=request_id,
            session_id=session_id,
            ok=False,
            status="provider_effective_mock",
            latency_ms=0,
            base_url=base_url,
        )
        return {
            "ok": False,
            "provider_effective": provider,
            "model": model,
            "base_url": base_url,
            "latency_ms": 0,
            "status_code": 503,
            "error_class": "config",
            "reason": "provider_effective_mock",
            "message_trunc": _trunc(msg),
        }

    url = str(base_url).rstrip("/") + "/chat/completions"
    body: JSONDict = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with OK"},
            {"role": "user", "content": "Reply with OK"},
        ],
        "max_tokens": 2,
        "temperature": 0,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {s['api_key']}")

    start = time.perf_counter()
    ok = False
    status = "error"
    status_code: int | None = None
    error_class: str | None = None
    message_trunc: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            _ = resp.read()
        ok = True
        status = "ok"
    except urllib.error.HTTPError as e:
        status_code = int(getattr(e, "code", 0) or 0) or None
        status = f"http_{status_code or 'error'}"
        error_class = "http_error"
        body_bytes = b""
        try:
            body_bytes = e.read(4096) or b""
        except Exception:
            body_bytes = b""
        body_text = ""
        try:
            body_text = body_bytes.decode("utf-8", errors="ignore")
        except Exception:
            body_text = ""
        message_trunc = _trunc((body_text or "") or f"{e.reason}")
    except Exception as e:
        status = "exception"
        # Classify common failure modes.
        if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
            error_class = "timeout"
            status_code = 504
        elif isinstance(e, urllib.error.URLError):
            if isinstance(getattr(e, "reason", None), socket.gaierror):
                error_class = "dns"
                status_code = 502
            else:
                error_class = "network"
                status_code = 502
        else:
            error_class = "exception"
            status_code = 502
        message_trunc = _trunc(str(e))
    finally:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        _log_event(
            "llm_ping_response",
            provider=provider,
            model=model,
            request_id=request_id,
            session_id=session_id,
            ok=ok,
            status=status,
            latency_ms=latency_ms,
            base_url=base_url,
        )

    if not ok:
        _log_event(
            "llm_ping_error",
            level="error",
            request_id=request_id,
            session_id=session_id,
            status_code=status_code,
            provider_effective=provider,
            base_url=base_url,
            model=model,
            error_class=error_class,
            message_trunc=message_trunc,
        )
        return {
            "ok": False,
            "provider_effective": provider,
            "model": model,
            "base_url": base_url,
            "latency_ms": latency_ms,
            "status_code": status_code,
            "error_class": error_class,
            "message_trunc": message_trunc,
        }

    return {
        "ok": True,
        "provider_effective": provider,
        "model": model,
        "base_url": base_url,
        "latency_ms": latency_ms,
    }
