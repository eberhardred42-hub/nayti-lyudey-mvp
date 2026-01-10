from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

JsonDict = Dict[str, Any]


def _as_json_dict(v: object) -> JsonDict:
    if isinstance(v, dict):
        return cast(JsonDict, v)
    return {}

MAX_INTRO_QUESTIONS = 10

P0_ORDER: List[str] = [
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


def init_brief_state(profession_query: str, entry_mode: str = "C") -> JsonDict:
    pq = (profession_query or "").strip()
    em = (entry_mode or "").strip().upper() or "C"
    if em not in {"A", "B", "C", "D"}:
        em = "C"
    bs: JsonDict = {"entry_mode": em}
    if pq:
        bs["role_title"] = pq
    return bs


def _p0_field_present(brief_state: object, field_name: str) -> bool:
    bs = _as_json_dict(brief_state)
    v = bs.get(field_name)
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, list):
        return any(bool(str(item).strip()) for item in cast(List[Any], v))
    if isinstance(v, dict):
        return len(cast(JsonDict, v)) > 0
    if isinstance(v, bool):
        return True
    return True


def p0_missing_fields(brief_state: object) -> List[str]:
    missing: List[str] = []
    for field in P0_ORDER:
        if not _p0_field_present(brief_state, field):
            missing.append(field)
    return missing


def choose_next_field(brief_state: object) -> Tuple[List[str], Optional[str]]:
    bs = _as_json_dict(brief_state)
    entry_mode = str(bs.get("entry_mode") or "").strip().upper()
    if entry_mode == "A" and not _p0_field_present(bs, "vacancy_text"):
        missing = p0_missing_fields(bs)
        return (["vacancy_text"] + missing), "vacancy_text"
    missing = p0_missing_fields(bs)
    return missing, (missing[0] if missing else None)


def question_for_field(field_name: str) -> Tuple[str, List[str]]:
    if field_name == "vacancy_text":
        return (
            "Вставьте текст вакансии (можно без контактов). Я извлеку ключевые требования и уточню спорные места.",
            [],
        )
    if field_name == "source_mode":
        return (
            "Откуда у вас задача на найм?",
            ["Новая вакансия", "Замена", "Рост команды", "Другое"],
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


def detect_confirm(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    return low in {"да", "ага", "ок", "окей", "верно", "подтверждаю", "подтвердить", "yes"}


def parse_work_format(text: str) -> Optional[str]:
    low = text.lower()
    if "удал" in low or "remote" in low or "дистанц" in low:
        return "remote"
    if "гибрид" in low:
        return "hybrid"
    if "офис" in low or "office" in low:
        return "office"
    return None


def parse_salary(text: str):
    cleaned = text.replace("\xa0", " ")
    numbers: List[int] = []
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


def parse_location(text: str):
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


def apply_answer_heuristic(brief_state: object, field_name: str, text: str, profession_query: str) -> JsonDict:
    patch: JsonDict = {}
    t = (text or "").strip()
    if not t:
        return patch

    if field_name == "source_mode":
        low = t.lower()
        if low.startswith("a") or "текст ваканс" in low or "ваканси" in low:
            patch[field_name] = "vacancy_text"
        elif low.startswith("b") or "своими" in low or "задач" in low or "опис" in low:
            patch[field_name] = "free_text"
        elif low.startswith("c") or "вопрос" in low:
            patch[field_name] = "questions"
        elif low.startswith("d") or "пропуст" in low:
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
        items: List[str] = []
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


def deep_merge_dict(base: JsonDict, patch: JsonDict) -> JsonDict:
    out: JsonDict = dict(base or {})
    for k, v in (patch or {}).items():
        existing = out.get(k)
        if isinstance(v, dict) and isinstance(existing, dict):
            out[k] = deep_merge_dict(cast(JsonDict, existing), cast(JsonDict, v))
        else:
            out[k] = v
    return out


def brief_snapshot_p0(brief_state: object) -> JsonDict:
    bs = _as_json_dict(brief_state)
    snap: JsonDict = {}
    for f in P0_ORDER:
        if f in bs:
            snap[f] = bs.get(f)
        else:
            snap[f] = None
    if "incomplete_fields" in bs:
        snap["incomplete_fields"] = bs.get("incomplete_fields")
    return snap


def _intro_meta(brief_state: JsonDict) -> JsonDict:
    intro = brief_state.get("intro")
    if isinstance(intro, dict):
        return cast(JsonDict, intro)
    return {}


def _set_intro_meta(brief_state: JsonDict, intro: JsonDict) -> None:
    brief_state["intro"] = intro


def progress_dict(asked: int, max_questions: int = MAX_INTRO_QUESTIONS) -> JsonDict:
    a = int(asked or 0)
    mx = int(max_questions)
    if mx <= 0:
        mx = MAX_INTRO_QUESTIONS
    remaining = max(0, mx - a)
    return {"asked": a, "max": mx, "remaining": remaining}


LLMExtractFn = Callable[[str, str, JsonDict, str], Tuple[JsonDict, Optional[str], str]]


def intro_start(brief_state: object) -> Tuple[JsonDict, JsonDict]:
    bs = _as_json_dict(brief_state)
    intro = dict(_intro_meta(bs))
    asked = int(intro.get("asked") or 0)

    missing, chosen = choose_next_field(bs)
    if not chosen:
        chosen = "source_mode"
        missing = P0_ORDER[:]

    q, qrs = question_for_field(chosen)

    asked = min(MAX_INTRO_QUESTIONS, asked + 1)
    intro["asked"] = asked
    intro["current_field"] = chosen
    intro.pop("pending", None)
    _set_intro_meta(bs, intro)

    resp: JsonDict = {
        "type": "intro_question",
        "progress": progress_dict(asked),
        "target_field": chosen,
        "question_text": q,
        "propose_value": None,
        "ui_mode": "free_text",
        "brief_snapshot": brief_snapshot_p0(bs),
        "missing_fields": missing,
        "quick_replies": qrs[:6],
        "ready_to_search": False,
    }
    return bs, resp


def _next_pending_item(intro: JsonDict) -> Optional[JsonDict]:
    q = intro.get("pending_queue")
    if not isinstance(q, list) or not q:
        return None
    item = q.pop(0)
    intro["pending_queue"] = q
    return item if isinstance(item, dict) else None


def intro_message(
    brief_state: object,
    text: str,
    profession_query: str,
    llm_extract: Optional[LLMExtractFn],
) -> Tuple[JsonDict, JsonDict]:
    bs = _as_json_dict(brief_state)

    # STOP rule: if the brief is already marked ready, do not ask questions and do not call LLM.
    if bool(bs.get("ready_to_search")):
        missing = p0_missing_fields(bs)
        bs["incomplete_fields"] = bs.get("incomplete_fields") or missing
        resp_done: JsonDict = {
            "type": "intro_done",
            "progress": progress_dict(int(_intro_meta(bs).get("asked") or 0)),
            "target_field": None,
            "question_text": "",
            "propose_value": None,
            "ui_mode": "free_text",
            "brief_snapshot": brief_snapshot_p0(bs),
            "missing_fields": [],
            "quick_replies": [],
            "ready_to_search": True,
            "incomplete_fields": bs.get("incomplete_fields") or missing,
        }
        return bs, resp_done

    intro = dict(_intro_meta(bs))
    asked = int(intro.get("asked") or 0)
    current_field = str(intro.get("current_field") or "").strip()

    # If we have a pending proposed value, the user's reply is either confirm or correction.
    pending = intro.get("pending") if isinstance(intro.get("pending"), dict) else None
    brief_patch: JsonDict = {}

    if pending and str(pending.get("field") or ""):
        pf = str(pending.get("field") or "")
        pv = pending.get("value")
        if detect_confirm(text):
            brief_patch = {pf: pv}
        else:
            # correction: take the user's text as authoritative value
            brief_patch = apply_answer_heuristic(bs, pf, text, profession_query)
        intro.pop("pending", None)
        current_field = pf

        # If there is a pending queue, continue confirmations without consuming a question.
        nxt = _next_pending_item(intro)
        if nxt and str(nxt.get("field") or ""):
            nf = str(nxt.get("field") or "")
            intro["pending"] = {"field": nf, "value": nxt.get("value"), "propose": nxt.get("propose")}
            _set_intro_meta(bs, intro)

            bs2 = deep_merge_dict(bs, brief_patch) if brief_patch else bs
            propose = str(nxt.get("propose") or nxt.get("value") or "").strip()
            resp_q: JsonDict = {
                "type": "intro_question",
                "progress": progress_dict(asked),
                "target_field": nf,
                "question_text": f"Понял(а): {propose}. Подтвердить?",
                "propose_value": propose or None,
                "ui_mode": "confirm_correct",
                "brief_snapshot": brief_snapshot_p0(bs2),
                "missing_fields": p0_missing_fields(bs2),
                "quick_replies": ["Да", "Исправить"],
                "ready_to_search": False,
            }
            return bs2, resp_q

    elif current_field and text:
        if llm_extract:
            llm_patch, propose_value, ui_mode = llm_extract(current_field, text, bs, profession_query)
            if llm_patch:
                brief_patch = llm_patch
            else:
                brief_patch = apply_answer_heuristic(bs, current_field, text, profession_query)

            # Support multi-field confirm queue (used by entry_mode=A vacancy_text extraction).
            queue = None
            if isinstance(llm_patch, dict) and isinstance(llm_patch.get("__pending_queue"), list):
                queue = cast(list, llm_patch.get("__pending_queue"))
                brief_patch = dict(llm_patch)
                brief_patch.pop("__pending_queue", None)
                intro["pending_queue"] = queue

            # If we have a proposed value, we pause and ask for confirmation in the same turn.
            if propose_value is not None and ui_mode == "confirm_correct":
                intro["pending"] = {"field": current_field, "value": llm_patch.get(current_field), "propose": propose_value}
                _set_intro_meta(bs, intro)

                # keep asked unchanged: we're not asking a new field, just confirming
                resp: JsonDict = {
                    "type": "intro_question",
                    "progress": progress_dict(asked),
                    "target_field": current_field,
                    "question_text": f"Понял(а): {propose_value}. Подтвердить?",
                    "propose_value": propose_value,
                    "ui_mode": "confirm_correct",
                    "brief_snapshot": brief_snapshot_p0(deep_merge_dict(bs, brief_patch)),
                    "missing_fields": p0_missing_fields(deep_merge_dict(bs, brief_patch)),
                    "quick_replies": ["Да", "Исправить"],
                    "ready_to_search": False,
                }
                return deep_merge_dict(bs, brief_patch), resp

            # If we have a queued confirmation, ask for the first item.
            if isinstance(intro.get("pending_queue"), list) and intro.get("pending_queue") and not intro.get("pending"):
                nxt = _next_pending_item(intro)
                if nxt and str(nxt.get("field") or ""):
                    nf = str(nxt.get("field") or "")
                    propose = str(nxt.get("propose") or nxt.get("value") or "").strip()
                    intro["pending"] = {"field": nf, "value": nxt.get("value"), "propose": propose}
                    _set_intro_meta(bs, intro)
                    bs2 = deep_merge_dict(bs, brief_patch)
                    resp_q: JsonDict = {
                        "type": "intro_question",
                        "progress": progress_dict(asked),
                        "target_field": nf,
                        "question_text": f"Понял(а): {propose}. Подтвердить?",
                        "propose_value": propose or None,
                        "ui_mode": "confirm_correct",
                        "brief_snapshot": brief_snapshot_p0(bs2),
                        "missing_fields": p0_missing_fields(bs2),
                        "quick_replies": ["Да", "Исправить"],
                        "ready_to_search": False,
                    }
                    return bs2, resp_q

        else:
            brief_patch = apply_answer_heuristic(bs, current_field, text, profession_query)

    if brief_patch:
        bs = deep_merge_dict(bs, brief_patch)

    missing, chosen = choose_next_field(bs)

    # Force done if max questions reached.
    if asked >= MAX_INTRO_QUESTIONS or not chosen:
        bs["ready_to_search"] = True
        bs["incomplete_fields"] = missing
        intro.pop("pending", None)
        _set_intro_meta(bs, intro)
        resp_done: JsonDict = {
            "type": "intro_done",
            "progress": progress_dict(asked),
            "target_field": None,
            "question_text": "",
            "propose_value": None,
            "ui_mode": "free_text",
            "brief_snapshot": brief_snapshot_p0(bs),
            "missing_fields": [],
            "quick_replies": [],
            "ready_to_search": True,
            "incomplete_fields": missing,
        }
        return bs, resp_done

    q, qrs = question_for_field(chosen)
    asked = min(MAX_INTRO_QUESTIONS, asked + 1)
    intro["asked"] = asked
    intro["current_field"] = chosen
    intro.pop("pending", None)
    _set_intro_meta(bs, intro)

    resp_next: JsonDict = {
        "type": "intro_question",
        "progress": progress_dict(asked),
        "target_field": chosen,
        "question_text": q,
        "propose_value": None,
        "ui_mode": "free_text",
        "brief_snapshot": brief_snapshot_p0(bs),
        "missing_fields": missing,
        "quick_replies": qrs[:6],
        "ready_to_search": False,
    }
    return bs, resp_next
