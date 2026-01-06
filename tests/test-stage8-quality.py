#!/usr/bin/env python3

from __future__ import annotations

import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def valid_profile_fixture() -> dict:
    return {
        "meta": {"contract_version": "v1", "kind": "vacancy_profile"},
        "role": {"title": "Senior Python Developer", "domain": "it", "seniority": "senior"},
        "company": {"name": None, "location": {"city": "Москва", "region": None, "country": "RU"}, "work_format": "hybrid"},
        "compensation": {"range": {"currency": "RUB", "min": 250000, "max": 350000}, "comment": "250–350k"},
        "employment": {"employment_type": "full-time", "schedule_comment": None},
        "requirements": {"experience_years_min": 5, "education_level": "unknown", "hard_skills": ["Python"], "soft_skills": []},
        "responsibilities": {"tasks": ["Backend"], "raw_vacancy_text": None},
        "sourcing": {"suggested_channels": []},
    }


def find_artifact(pack: dict, kind: str) -> dict | None:
    for layer in ("user_result", "trace"):
        for a in (pack.get(layer, {}) or {}).get("artifacts", []) or []:
            if a.get("kind") == kind:
                return a
    return None


def test_happy_path_gates_true() -> None:
    from ml.main import run_core

    prev = os.environ.get("MOCK_MODE")
    os.environ["MOCK_MODE"] = "good"
    try:
        pack = run_core(valid_profile_fixture(), request_id="q1")
    finally:
        if prev is None:
            os.environ.pop("MOCK_MODE", None)
        else:
            os.environ["MOCK_MODE"] = prev
    q = find_artifact(pack, "quality_report")
    assert q is not None
    content = q.get("content") or {}

    gates = content.get("gates") or {}
    assert gates.get("schema_ok") is True
    assert gates.get("coverage_ok") is True
    assert gates.get("actionability_ok") is True
    assert gates.get("comparability_ok") is True
    assert gates.get("risk_checks_ok") is True
    assert gates.get("tone_ty_ok") is True
    assert gates.get("no_emojis_ok") is True


def test_case_without_anchors_comparability_false() -> None:
    from ml.quality import compute_quality_report
    from ml.schemas import VacancyProfileV1

    profile = VacancyProfileV1.model_validate(valid_profile_fixture())

    # Minimal artifacts with broken scorecard (missing anchor 5)
    user_artifacts = [
        {"kind": "free_report_json", "content": {"next_steps": ["x"], "headline": "h", "where_to_search": [], "what_to_screen": [], "budget_reality_check": {"status": "unknown", "bullets": []}}},
        {"kind": "free_report_md", "content": {"markdown": "# t\n\n- step"}},
        {"kind": "role_snapshot_json", "content": {"role": {"title": "t", "domain": None, "seniority": None}, "one_liner": "x", "must_have": ["x"], "nice_to_have": [], "deal_breakers": []}},
        {"kind": "sourcing_pack_json", "content": {"target_profile": {"title": "t"}, "channels": [{"name": "n", "priority": "high", "notes": None}], "boolean_search_queries": [], "outreach_templates": [{"channel": "c", "language": "ru", "subject": "s", "message": "m"}]}},
        {"kind": "screening_script_json", "content": {"opening": "o", "questions": [{"id": "q1", "text": "t", "type": "open"}], "closing": "c"}},
        {"kind": "budget_reality_check_json", "content": {"currency": "RUB", "salary_min": 1, "salary_max": 2, "market_band": {"p25": None, "p50": None, "p75": None}, "status": "unknown", "explanation": "e", "recommendations": []}},
        {"kind": "scorecard_json", "content": {"scale": "1-5", "anchors": [{"score": 1, "label": "1"}, {"score": 2, "label": "2"}, {"score": 3, "label": "3"}, {"score": 4, "label": "4"}], "competencies": [{"id": "c1", "title": "t", "weight": 1, "rubric": []}]}},
    ]
    trace_artifacts = [
        {"kind": "manifest", "content": {}},
        {"kind": "quality_report", "content": {}},
    ]

    q = compute_quality_report(profile, user_artifacts=user_artifacts, trace_artifacts=trace_artifacts, schema_ok=False)
    gates = q.get("gates") or {}
    assert gates.get("comparability_ok") is False
    warnings = q.get("warnings") or []
    assert "COMPARABILITY_ANCHORS_INVALID" in warnings


if __name__ == "__main__":
    test_happy_path_gates_true()
    test_case_without_anchors_comparability_false()
    print("stage8 quality: OK")
