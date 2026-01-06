import json
import os
import time
import uuid
from typing import Callable, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request

try:
    from .json_extract import JsonExtractError, extract_json
    from .quality import compute_quality_report
    from .schemas import (
        HiringPackV1,
        LLMGeneratedArtifactsV1,
        ScorecardV1,
        VacancyProfileV1,
        sanitize_pydantic_errors,
    )
except ImportError:  # pragma: no cover
    from json_extract import JsonExtractError, extract_json
    from quality import compute_quality_report
    from schemas import HiringPackV1, LLMGeneratedArtifactsV1, ScorecardV1, VacancyProfileV1, sanitize_pydantic_errors

app = FastAPI()


def log_event(event: str, level: str = "info", **fields):
    payload = {
        "event": event,
        "level": level,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = value
    print(json.dumps(payload, ensure_ascii=False))


@app.get("/health")
def health():
    return {"status": "ok"}


def _build_free_report_json(profile: VacancyProfileV1) -> dict:
    role_title = profile.role.title
    salary_min = profile.compensation.range.min
    salary_max = profile.compensation.range.max

    headline = f"Держи бесплатный результат поиска по {role_title.lower()}"
    where_to_search = [
        {
            "title": "Основные площадки",
            "bullets": [
                "HeadHunter (HH) — основной источник резюме",
                "LinkedIn — проверь профили и Recruiter функции",
            ],
        }
    ]
    what_to_screen = [
        {
            "title": "Быстрые критерии скрининга",
            "bullets": [
                "Опыт по ключевому стеку",
                "Коммерческие кейсы и результат",
                "Коммуникация и самостоятельность",
            ],
        }
    ]
    budget_reality_check = {
        "status": "unknown",
        "bullets": [
            f"Бюджет: {salary_min}–{salary_max} ₽",
            "Сверь вилку с аналогичными позициями на рынке.",
        ],
    }
    next_steps = [
        "Сформулировать требования и процесс интервью.",
        "Выбрать 2–3 канала и запустить поиск.",
        "Провести короткий скрининг и собрать шортлист.",
    ]

    return {
        "headline": headline,
        "where_to_search": where_to_search,
        "what_to_screen": what_to_screen,
        "budget_reality_check": budget_reality_check,
        "next_steps": next_steps,
    }


def _build_free_report_md(profile: VacancyProfileV1) -> str:
    role_title = profile.role.title
    salary_min = profile.compensation.range.min
    salary_max = profile.compensation.range.max
    return (
        f"# Бесплатный результат\n\n"
        f"Роль: **{role_title}**\n\n"
        f"Бюджет: {salary_min}–{salary_max} ₽\n\n"
        "## Следующие шаги\n"
        "- Сформулировать требования и процесс интервью\n"
        "- Запустить поиск в 2–3 каналах\n"
        "- Провести короткий скрининг\n"
    )


def _build_scorecard() -> dict:
    return {
        "scale": "1-5",
        "anchors": [
            {"score": 1, "label": "Не соответствует"},
            {"score": 2, "label": "Скорее не подходит"},
            {"score": 3, "label": "Условно подходит"},
            {"score": 4, "label": "Хорошо подходит"},
            {"score": 5, "label": "Сильный кандидат"},
        ],
        "competencies": [
            {"id": "role_fit", "title": "Соответствие роли", "weight": 3, "rubric": []},
            {"id": "communication", "title": "Коммуникация", "weight": 2, "rubric": []},
        ],
    }


def _build_role_snapshot_json(profile: VacancyProfileV1) -> dict:
    return {
        "role": {
            "title": profile.role.title,
            "domain": profile.role.domain,
            "seniority": profile.role.seniority,
        },
        "one_liner": f"{profile.role.title} для закрытия ключевых задач в команде.",
        "must_have": ["Python", "Опыт production", "Коммуникация"],
        "nice_to_have": ["Docker", "PostgreSQL"],
        "deal_breakers": ["Нет коммерческого опыта"],
    }


def _build_sourcing_pack_json(profile: VacancyProfileV1) -> dict:
    location = profile.company.location.city or ""
    return {
        "target_profile": {"title": profile.role.title, "location": location or "remote"},
        "channels": [
            {"name": "HeadHunter", "priority": "high", "notes": "Основной поток резюме"},
            {"name": "LinkedIn", "priority": "medium", "notes": "Поиск по профилям"},
        ],
        "boolean_search_queries": [f"({profile.role.title} AND Python)"],
        "outreach_templates": [
            {
                "channel": "LinkedIn",
                "language": "ru",
                "subject": f"{profile.role.title}",
                "message": f"Привет! Есть роль {profile.role.title}. Интересно обсудить?",
            }
        ],
    }


def _build_screening_script_json(profile: VacancyProfileV1) -> dict:
    return {
        "opening": "Привет! Короткий скрининг на 10–15 минут.",
        "questions": [
            {"id": "q1", "text": "Сколько лет коммерческого опыта с Python?", "type": "open"},
            {"id": "q2", "text": "Какие проекты были наиболее сложными и почему?", "type": "open"},
            {"id": "q3", "text": "Какие ожидания по зарплате и формату работы?", "type": "open"},
        ],
        "closing": "Спасибо! Дальше — техническое интервью при совпадении ожиданий.",
    }


def _build_budget_reality_check_json(profile: VacancyProfileV1) -> dict:
    return {
        "currency": profile.compensation.range.currency,
        "salary_min": profile.compensation.range.min,
        "salary_max": profile.compensation.range.max,
        "market_band": {"p25": None, "p50": None, "p75": None},
        "status": "unknown",
        "explanation": "Нет данных рынка: требуется сверка с бенчмарками.",
        "recommendations": ["Сравнить вилку с аналогичными вакансиями."],
    }


def _build_compliance_checks_json(profile: VacancyProfileV1) -> dict:
    # Minimal placeholder for high-risk roles
    return {
        "risk_level": getattr(profile.role, "risk_level", None) or "high",
        "checks": [
            {"id": "consent", "status": "todo", "details": "Проверь согласие на обработку данных"},
            {"id": "pii", "status": "todo", "details": "Убедись, что PII не логируется"},
        ],
    }


def _schema_hint_for_llm() -> str:
    return (
        "JSON-объект верхнего уровня с ключами:\n"
        "- role_snapshot_json (object)\n"
        "- sourcing_pack_json (object)\n"
        "- screening_script_json (object)\n"
        "- budget_reality_check_json (object)\n"
        "- scorecard_json (object; scale=\"1-5\"; anchors scores 1..5)\n"
        "- free_report_json (object)\n"
        "- free_report_md (string markdown)\n"
        "Без комментариев, без лишнего текста."
    )


def _default_llm_call(profile: VacancyProfileV1, prompt: str) -> str:
    # Offline-safe stub: returns a valid JSON bundle by deterministic builders.
    bundle = {
        "role_snapshot_json": _build_role_snapshot_json(profile),
        "sourcing_pack_json": _build_sourcing_pack_json(profile),
        "screening_script_json": _build_screening_script_json(profile),
        "budget_reality_check_json": _build_budget_reality_check_json(profile),
        "scorecard_json": _build_scorecard(),
        "free_report_json": _build_free_report_json(profile),
        "free_report_md": _build_free_report_md(profile),
    }
    return json.dumps(bundle, ensure_ascii=False)


def _make_mock_llm_call(mode: str, profile: VacancyProfileV1) -> Callable[[VacancyProfileV1, str], str]:
    mode = (mode or "").strip().lower()
    counter = {"n": 0}

    def _bundle_full() -> dict:
        return {
            "role_snapshot_json": _build_role_snapshot_json(profile),
            "sourcing_pack_json": _build_sourcing_pack_json(profile),
            "screening_script_json": _build_screening_script_json(profile),
            "budget_reality_check_json": _build_budget_reality_check_json(profile),
            "scorecard_json": _build_scorecard(),
            "free_report_json": _build_free_report_json(profile),
            "free_report_md": _build_free_report_md(profile),
        }

    def _bundle_missing_fields() -> dict:
        data = _bundle_full()
        # Remove one required key to force schema validation failure.
        data.pop("screening_script_json", None)
        return data

    def llm_call(_profile: VacancyProfileV1, _prompt: str) -> str:
        n = counter["n"]
        counter["n"] = n + 1

        if mode == "good":
            return json.dumps(_bundle_full(), ensure_ascii=False)
        if mode == "non_json":
            return "это не json"
        if mode == "wrapped_json":
            return "Вот результат:\n```json\n" + json.dumps(_bundle_full(), ensure_ascii=False) + "\n```\n"
        if mode == "missing_fields":
            if n == 0:
                return json.dumps(_bundle_missing_fields(), ensure_ascii=False)
            # Return repaired JSON on repair attempt.
            return "```json\n" + json.dumps(_bundle_full(), ensure_ascii=False) + "\n```"

        # Unknown mode: stay offline-safe and return good.
        return json.dumps(_bundle_full(), ensure_ascii=False)

    return llm_call


def _validate_llm_bundle_dict(data: dict) -> LLMGeneratedArtifactsV1:
    # LLM bundle can omit meta fields; our v1 models have defaults.
    return LLMGeneratedArtifactsV1.model_validate(data)


def _run_llm_pipeline(
    profile: VacancyProfileV1,
    request_id: str,
    llm_call: Callable[[VacancyProfileV1, str], str],
) -> tuple[Optional[LLMGeneratedArtifactsV1], bool]:
    # Returns (bundle, used_fallback)
    raw = llm_call(profile, f"Сгенерируй артефакты по вакансии.\n\n{_schema_hint_for_llm()}")

    extracted: Optional[dict] = None
    try:
        extracted = extract_json(raw)
    except JsonExtractError:
        log_event("llm_json_extract_failed", level="warn", request_id=request_id)

    if extracted is not None:
        try:
            return _validate_llm_bundle_dict(extracted), False
        except Exception as exc:
            errors = sanitize_pydantic_errors(exc) if hasattr(exc, "errors") else [{"msg": str(exc)}]
            log_event("llm_schema_validation_failed", level="warn", request_id=request_id, errors=errors)

    # Repair attempts
    last_text = raw
    for attempt in (1, 2):
        log_event("llm_repair_attempt", request_id=request_id, attempt=attempt)
        repair_prompt = (
            "Верни только JSON по схеме ниже. Без комментариев.\n\n"
            f"{_schema_hint_for_llm()}\n\n"
            "Если нужно — исправь/дополни пропущенные поля.\n"
            "Предыдущий ответ (для контекста):\n"
            f"{last_text[:4000]}"
        )
        repaired = llm_call(profile, repair_prompt)
        last_text = repaired

        try:
            extracted = extract_json(repaired)
        except JsonExtractError:
            log_event("llm_json_extract_failed", level="warn", request_id=request_id, attempt=attempt)
            continue

        try:
            bundle = _validate_llm_bundle_dict(extracted)
            log_event("llm_repair_ok", request_id=request_id, attempt=attempt)
            return bundle, False
        except Exception as exc:
            errors = sanitize_pydantic_errors(exc) if hasattr(exc, "errors") else [{"msg": str(exc)}]
            log_event("llm_schema_validation_failed", level="warn", request_id=request_id, attempt=attempt, errors=errors)

    log_event("llm_repair_failed", level="warn", request_id=request_id)
    return None, True


def _build_quality_report_content(status: str, warnings: list[str], validated_artifacts: list[dict]) -> dict:
    return {
        "summary": {"status": status, "issues_count": 0, "warnings_count": len(warnings)},
        "warnings": warnings,
        "checks": [],
        "artifacts_validated": validated_artifacts,
    }


def build_hiring_pack(profile: VacancyProfileV1, bundle: Optional[LLMGeneratedArtifactsV1] = None, degraded: bool = False) -> dict:
    pack_id = f"pack_{datetime.utcnow().isoformat()}Z_{uuid.uuid4().hex[:8]}"
    generated_at_iso = datetime.utcnow().isoformat() + "Z"

    def aid(kind: str) -> str:
        # Stable-ish ids by kind for easier debugging.
        return f"art_{kind}_001"

    free_report_json_content = (bundle.free_report_json.model_dump(exclude={"meta"}) if bundle else _build_free_report_json(profile))
    free_report_md_text = (bundle.free_report_md if bundle else _build_free_report_md(profile))
    scorecard_content = (bundle.scorecard_json.model_dump(exclude={"meta"}) if bundle else _build_scorecard())

    # Validate scorecard structure early (anchors 1..5 required)
    ScorecardV1.model_validate({"meta": {"contract_version": "v1", "kind": "scorecard_json"}, **scorecard_content})

    user_artifacts = [
        {
            "artifact_id": aid("role_snapshot_json"),
            "kind": "role_snapshot_json",
            "meta": {"legacy_kind": None},
            "content": (bundle.role_snapshot_json.model_dump(exclude={"meta"}) if bundle else _build_role_snapshot_json(profile)),
        },
        {
            "artifact_id": aid("sourcing_pack_json"),
            "kind": "sourcing_pack_json",
            "meta": {"legacy_kind": None},
            "content": (bundle.sourcing_pack_json.model_dump(exclude={"meta"}) if bundle else _build_sourcing_pack_json(profile)),
        },
        {
            "artifact_id": aid("screening_script_json"),
            "kind": "screening_script_json",
            "meta": {"legacy_kind": None},
            "content": (bundle.screening_script_json.model_dump(exclude={"meta"}) if bundle else _build_screening_script_json(profile)),
        },
        {
            "artifact_id": aid("budget_reality_check_json"),
            "kind": "budget_reality_check_json",
            "meta": {"legacy_kind": None},
            "content": (bundle.budget_reality_check_json.model_dump(exclude={"meta"}) if bundle else _build_budget_reality_check_json(profile)),
        },
        {
            "artifact_id": aid("scorecard_json"),
            "kind": "scorecard_json",
            "meta": {"legacy_kind": None},
            "content": scorecard_content,
        },
        {
            "artifact_id": aid("free_report_json"),
            "kind": "free_report_json",
            "meta": {"legacy_kind": None},
            "content": free_report_json_content,
        },
        {
            "artifact_id": aid("free_report_md"),
            "kind": "free_report_md",
            "meta": {"legacy_kind": None},
            "content": {"markdown": free_report_md_text},
        },
    ]

    if getattr(profile.role, "risk_level", None) == "high":
        user_artifacts.append(
            {
                "artifact_id": aid("compliance_checks_json"),
                "kind": "compliance_checks_json",
                "meta": {"legacy_kind": None},
                "content": _build_compliance_checks_json(profile),
            }
        )

    manifest_content = {
        "pack_id": pack_id,
        "generated_at_iso": generated_at_iso,
        "artifacts": [
            {"artifact_id": a["artifact_id"], "layer": "user_result", "kind": a["kind"], "content_ref": "inline"}
            for a in user_artifacts
        ]
        + [
            {"artifact_id": aid("quality_report"), "layer": "trace", "kind": "quality_report", "content_ref": "inline"},
            {"artifact_id": aid("manifest"), "layer": "trace", "kind": "manifest", "content_ref": "inline"},
        ],
        "kinds_dictionary": {},
        "legacy_kinds": {},
    }

    extra_warnings = ["FALLBACK_USED", "LLM_OUTPUT_INVALID"] if degraded else []

    # We compute quality gates before inserting quality_report artifact into trace, but
    # we still want coverage_ok to consider that it exists in trace.
    trace_stub = [
        {"artifact_id": aid("manifest"), "kind": "manifest", "meta": {"legacy_kind": None}, "content": {}},
        {"artifact_id": aid("quality_report"), "kind": "quality_report", "meta": {"legacy_kind": None}, "content": {}},
    ]
    quality_report_content = compute_quality_report(
        profile,
        user_artifacts=user_artifacts,
        trace_artifacts=trace_stub,
        schema_ok=True,
        extra_warnings=extra_warnings,
    )

    validated_refs = [{"artifact_id": a["artifact_id"], "kind": a["kind"]} for a in user_artifacts]
    quality_report_content["artifacts_validated"] = validated_refs

    pack = {
        "meta": {"contract_version": "v1", "kind": "hiring_pack"},
        "pack_id": pack_id,
        "user_result": {"artifacts": user_artifacts},
        "trace": {
            "quality": quality_report_content,
            "artifacts": [
                {
                    "artifact_id": aid("quality_report"),
                    "kind": "quality_report",
                    "meta": {"legacy_kind": None},
                    "content": quality_report_content,
                },
                {
                    "artifact_id": aid("manifest"),
                    "kind": "manifest",
                    "meta": {"legacy_kind": None},
                    "content": manifest_content,
                },
            ]
        },
    }

    HiringPackV1.model_validate(pack)
    return pack


@app.post("/run")
async def run(payload: dict, request: Request):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    return run_core(payload, request_id=request_id)


def run_core(
    payload: dict,
    request_id: str = "unknown",
    llm_call: Optional[Callable[[VacancyProfileV1, str], str]] = None,
) -> dict:
    start_time = time.perf_counter()
    log_event("ml_run_received", request_id=request_id)

    try:
        profile = VacancyProfileV1.model_validate(payload)
    except Exception as exc:
        if hasattr(exc, "errors"):
            errors = sanitize_pydantic_errors(exc)  # type: ignore[arg-type]
        else:
            errors = [{"msg": str(exc)}]

        log_event(
            "ml_run_validation_error",
            level="warn",
            request_id=request_id,
            duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
            errors=errors,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_input",
                "request_id": request_id,
                "errors": errors,
            },
        )

    if llm_call is None:
        mock_mode = (os.environ.get("MOCK_MODE") or "").strip().lower()
        if mock_mode:
            llm_call = _make_mock_llm_call(mock_mode, profile)
            log_event("mock_mode_enabled", request_id=request_id, mock_mode=mock_mode)
        else:
            llm_call = _default_llm_call

    bundle, used_fallback = _run_llm_pipeline(profile, request_id=request_id, llm_call=llm_call)
    if used_fallback:
        log_event("fallback_used", level="warn", request_id=request_id)
    pack = build_hiring_pack(profile, bundle=bundle, degraded=used_fallback)
    log_event(
        "ml_run_finished",
        request_id=request_id,
        duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
    )
    return pack
