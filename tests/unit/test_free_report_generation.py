#!/usr/bin/env python3
"""Unit tests for free report generation.

This is a standalone script (no FastAPI required).
Canonical location: tests/unit/test_free_report_generation.py
Legacy entrypoint: tests/test-free-report.py (wrapper).
"""

from __future__ import annotations

import json
import sys


def make_empty_vacancy_kb():
    return {
        "role": {"role_title": "", "role_domain": "", "role_seniority": ""},
        "company": {
            "company_location_city": "",
            "company_location_region": "",
            "work_format": "unknown",
        },
        "compensation": {"salary_min_rub": 0, "salary_max_rub": 0, "salary_comment": ""},
        "employment": {"employment_type": "unknown", "schedule_comment": ""},
        "responsibilities": {"tasks": [], "raw_vacancy_text": ""},
        "meta": {"filled_fields_count": 0, "missing_fields": []},
    }


def make_it_vacancy_kb():
    kb = make_empty_vacancy_kb()
    kb["role"]["role_title"] = "Senior Python Developer"
    kb["responsibilities"]["raw_vacancy_text"] = "Need python backend engineer"
    kb["compensation"]["salary_min_rub"] = 200000
    kb["compensation"]["salary_max_rub"] = 350000
    kb["company"]["company_location_city"] = "москва"
    kb["company"]["work_format"] = "hybrid"
    return kb


def make_creative_vacancy_kb():
    kb = make_empty_vacancy_kb()
    kb["role"]["role_title"] = "UI/UX Designer"
    kb["responsibilities"]["raw_vacancy_text"] = "Дизайнер с опытом Figma и Adobe"
    kb["company"]["company_location_city"] = "санкт-петербург"
    kb["company"]["work_format"] = "office"
    return kb


def make_sales_vacancy_kb():
    kb = make_empty_vacancy_kb()
    kb["role"]["role_title"] = "Sales Manager"
    kb["responsibilities"]["raw_vacancy_text"] = "Развитие бизнеса, B2B продажи"
    kb["compensation"]["salary_min_rub"] = 100000
    kb["compensation"]["salary_max_rub"] = 200000
    return kb


def generate_free_report(kb, profession_query=""):
    role_title = kb.get("role", {}).get("role_title", "")
    raw_text = kb.get("responsibilities", {}).get("raw_vacancy_text", "")
    salary_min = kb.get("compensation", {}).get("salary_min_rub", 0)
    salary_max = kb.get("compensation", {}).get("salary_max_rub", 0)
    city = kb.get("company", {}).get("company_location_city", "").lower()
    work_format = kb.get("company", {}).get("work_format", "unknown").lower()

    combined_text = f"{role_title} {raw_text} {profession_query}".lower()

    domain = "unknown"
    it_keywords = [
        "python",
        "java",
        "golang",
        "программ",
        "разработ",
        "backend",
        "frontend",
        "react",
        "node",
        "devops",
        "docker",
    ]
    creative_keywords = ["дизайн", "маркетинг", "реклам", "контент", "figma", "adobe", "ui", "ux"]
    sales_keywords = ["продажа", "sales", "менеджер", "бизнес-развитие", "account manager"]

    if any(k in combined_text for k in it_keywords):
        domain = "IT"
    elif any(k in combined_text for k in creative_keywords):
        domain = "Creative"
    elif any(k in combined_text for k in sales_keywords):
        domain = "Sales"

    headline = f"Держи бесплатный результат по {role_title if role_title else 'твоей вакансии'} 🎯"

    where_to_search = [
        {"title": "HeadHunter", "bullets": ["Основной канал поиска в России"]},
        {"title": "LinkedIn", "bullets": ["Поиск интернационального опыта"]},
    ]

    if domain == "IT":
        where_to_search.extend(
            [
                {"title": "Habr Career", "bullets": ["IT специалисты", "Профессиональное сообщество"]},
                {"title": "GitHub", "bullets": ["Поиск по профилям", "Pet projects"]},
            ]
        )
    elif domain == "Creative":
        where_to_search.extend(
            [
                {"title": "Behance/Dribbble", "bullets": ["Портфолио дизайнеров"]},
                {"title": "Telegram каналы", "bullets": ["Творческие сообщества"]},
            ]
        )
    elif domain == "Sales":
        where_to_search.extend(
            [
                {"title": "Telegram бизнес-сообщества", "bullets": ["Нетворкинг", "Рекомендации"]},
                {"title": "Referrals", "bullets": ["Личные рекомендации"]},
            ]
        )

    if city and work_format in ["office", "hybrid"]:
        where_to_search.append(
            {
                "title": f"Локальные каналы ({city.capitalize()})",
                "bullets": ["Telegram группы", "VK группы", "Рекомендации"],
            }
        )

    what_to_screen = [
        "Резюме: актуальность и ясность технического стека",
        "Примеры работ / кейсы, релевантные к твоим задачам",
        "Мягкие навыки: общительность, ответственность",
        "Понимание твоих задач и требований",
        "Отсутствие красных флагов в истории",
        "Соответствие этике найма",
    ]

    if domain == "IT":
        what_to_screen.extend(
            [
                "Знание инструментов из твоего стека",
                "Pet projects или open source вклады",
                "Способность объяснить архитектурные решения",
            ]
        )
    elif domain == "Creative":
        what_to_screen.extend(
            [
                "Чувство стиля и актуальные тренды",
                "Объяснение процесса работы",
                "Консистентность стиля в портфолио",
            ]
        )
    elif domain == "Sales":
        what_to_screen.extend(
            [
                "Track record с конкретными числами",
                "Энергия и амбиции",
                "Коммуникабельность",
            ]
        )

    budget_status = "unknown"
    budget_bullets = []

    if salary_min > 0:
        budget_bullets.append(f"Твой бюджет: {salary_min:,} - {salary_max:,} руб/месяц")
        if salary_min < 100000:
            budget_bullets.append("Рассмотри джуниора с потенциалом и наставничеством")
            budget_status = "low"
        elif salary_min > 300000:
            budget_bullets.append("Фокусируйся на сеньорах с доказанным опытом")
            budget_status = "high"
        else:
            budget_bullets.append("Баланс опыта и стоимости: ищи миддла с нужным стеком")
            budget_status = "ok"

    if not budget_bullets:
        budget_bullets = ["Проведи рыночное исследование", "Тестовое задание помогает оценить качество"]
        budget_status = "unknown"

    budget_bullets.append("Опцион: тестовое задание экономит время на неподходящих кандидатах")

    budget_reality_check = {
        "status": budget_status,
        "bullets": budget_bullets,
    }

    next_steps = [
        "1. Формирование вакансии: ясные требования, стек, условия работы",
        "2. Выбор каналов: начни с 2–3 основных (HH + ещё 1–2)",
        "3. Быстрый скрининг резюме: 'может ли он/она это делать?'",
        "4. Первое интервью: 30 мин, проверка fit и понимания",
        "5. Тестовое задание (если нужно, 1–2 часа работы)",
    ]

    if work_format in ["office", "hybrid"]:
        next_steps.append("6. Обсуждение оборудования и офисного пространства (если office)")

    return {
        "headline": headline,
        "where_to_search": where_to_search,
        "what_to_screen": what_to_screen,
        "budget_reality_check": budget_reality_check,
        "next_steps": next_steps,
    }


def test_structure():
    print("Test 1: Structure validation...")
    kb = make_empty_vacancy_kb()
    report = generate_free_report(kb)

    required_sections = ["headline", "where_to_search", "what_to_screen", "budget_reality_check", "next_steps"]
    for section in required_sections:
        assert section in report, f"❌ Missing section: {section}"
        assert report[section] is not None, f"❌ Null section: {section}"

    print("✅ Structure test passed")


def test_fields():
    print("Test 2: Field content validation...")
    kb = make_empty_vacancy_kb()
    report = generate_free_report(kb)

    assert isinstance(report["headline"], str), "❌ headline must be string"
    assert len(report["headline"]) > 0, "❌ headline cannot be empty"

    assert isinstance(report["where_to_search"], list), "❌ where_to_search must be list"
    assert len(report["where_to_search"]) > 0, "❌ where_to_search cannot be empty"
    for item in report["where_to_search"]:
        assert isinstance(item, dict), "❌ where_to_search items must be dicts"
        assert "title" in item and "bullets" in item, "❌ Missing title or bullets"
        assert isinstance(item["bullets"], list), "❌ bullets must be list"
        assert len(item["bullets"]) > 0, "❌ bullets cannot be empty"

    assert isinstance(report["what_to_screen"], list), "❌ what_to_screen must be list"
    assert len(report["what_to_screen"]) > 0, "❌ what_to_screen cannot be empty"
    for item in report["what_to_screen"]:
        assert isinstance(item, str), "❌ what_to_screen items must be strings"
        assert len(item) > 0, "❌ what_to_screen items cannot be empty"

    assert isinstance(report["budget_reality_check"], dict), "❌ budget_reality_check must be dict"
    assert "status" in report["budget_reality_check"], "❌ Missing status"
    status = report["budget_reality_check"]["status"]
    assert status in ["ok", "low", "high", "unknown"], f"❌ Invalid status: {status}"
    assert "bullets" in report["budget_reality_check"], "❌ Missing bullets"
    assert isinstance(report["budget_reality_check"]["bullets"], list), "❌ bullets must be list"
    assert len(report["budget_reality_check"]["bullets"]) > 0, "❌ bullets cannot be empty"

    assert isinstance(report["next_steps"], list), "❌ next_steps must be list"
    assert len(report["next_steps"]) > 0, "❌ next_steps cannot be empty"
    for item in report["next_steps"]:
        assert isinstance(item, str), "❌ next_steps items must be strings"
        assert len(item) > 0, "❌ next_steps items cannot be empty"

    print("✅ Field content test passed")


def test_domain_detection():
    print("Test 3: Domain detection...")

    kb_it = make_it_vacancy_kb()
    report_it = generate_free_report(kb_it)
    titles = [s["title"] for s in report_it["where_to_search"]]
    assert "Habr Career" in titles or "GitHub" in titles, "❌ IT domain should have IT platforms"
    assert report_it["budget_reality_check"]["status"] in ["ok", "low", "high"], "❌ IT with salary should have status"
    print("  ✓ IT domain detection")

    kb_creative = make_creative_vacancy_kb()
    report_creative = generate_free_report(kb_creative)
    titles = [s["title"] for s in report_creative["where_to_search"]]
    assert "Behance" in str(titles) or "Dribbble" in str(titles), "❌ Creative domain should have design platforms"
    print("  ✓ Creative domain detection")

    kb_sales = make_sales_vacancy_kb()
    report_sales = generate_free_report(kb_sales)
    what_to_screen = " ".join(report_sales["what_to_screen"]).lower()
    assert "track" in what_to_screen or "числа" in what_to_screen, "❌ Sales should mention track record"
    print("  ✓ Sales domain detection")

    print("✅ Domain detection test passed")


def test_location_awareness():
    print("Test 4: Location awareness...")
    kb = make_it_vacancy_kb()
    kb["company"]["company_location_city"] = "москва"
    kb["company"]["work_format"] = "office"
    report = generate_free_report(kb)

    titles = [s["title"] for s in report["where_to_search"]]
    assert any("москва" in t.lower() or "локальные" in t.lower() for t in titles), "❌ Should mention Moscow"
    print("✅ Location awareness test passed")


def test_budget_awareness():
    print("Test 5: Budget awareness...")

    kb_low = make_empty_vacancy_kb()
    kb_low["compensation"]["salary_min_rub"] = 50000
    kb_low["compensation"]["salary_max_rub"] = 80000
    report_low = generate_free_report(kb_low)
    assert report_low["budget_reality_check"]["status"] == "low", "❌ Low salary should be 'low' status"

    kb_high = make_empty_vacancy_kb()
    kb_high["compensation"]["salary_min_rub"] = 400000
    kb_high["compensation"]["salary_max_rub"] = 600000
    report_high = generate_free_report(kb_high)
    assert report_high["budget_reality_check"]["status"] == "high", "❌ High salary should be 'high' status"

    kb_unknown = make_empty_vacancy_kb()
    report_unknown = generate_free_report(kb_unknown)
    assert report_unknown["budget_reality_check"]["status"] == "unknown", "❌ No salary should be 'unknown' status"

    print("✅ Budget awareness test passed")


def test_json_serializable():
    print("Test 6: JSON serialization...")
    kb = make_it_vacancy_kb()
    report = generate_free_report(kb)

    json_str = json.dumps(report, ensure_ascii=False, indent=2)
    assert len(json_str) > 0, "❌ JSON serialization failed"

    parsed = json.loads(json_str)
    assert parsed == report, "❌ JSON roundtrip failed"

    print("✅ JSON serialization test passed")


def main() -> int:
    try:
        test_structure()
        test_fields()
        test_domain_detection()
        test_location_awareness()
        test_budget_awareness()
        test_json_serializable()

        print("\n" + "=" * 50)
        print("🎉 All tests passed! (6/6)")
        print("=" * 50)
        return 0
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
