#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

try:
    from pydantic import ValidationError
    from fastapi import HTTPException
except ModuleNotFoundError:
    print("stage8 schemas: SKIP (missing pydantic/fastapi in environment)")
    raise SystemExit(0)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ml.main import build_hiring_pack, run_core
from ml.schemas import HiringPackV1, ScorecardV1, VacancyProfileV1


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


def test_valid_fixture_ok() -> None:
    profile = VacancyProfileV1.model_validate(valid_profile_fixture())
    pack_dict = build_hiring_pack(profile)
    HiringPackV1.model_validate(pack_dict)


def test_missing_compensation_max_fails() -> None:
    bad = valid_profile_fixture()
    del bad["compensation"]["range"]["max"]
    try:
        run_core(bad, request_id="test")
    except HTTPException as exc:
        assert exc.status_code == 400
        return
    raise AssertionError("Expected HTTPException(400) for missing compensation.range.max")


def test_missing_scorecard_anchors_fails() -> None:
    bad_scorecard = {
        "meta": {"contract_version": "v1", "kind": "scorecard_json"},
        "scale": "1-5",
        "anchors": [
            {"score": 1, "label": "x"},
            {"score": 2, "label": "x"},
            {"score": 3, "label": "x"},
            {"score": 4, "label": "x"},
            # score 5 missing
        ],
        "competencies": [{"id": "c1", "title": "t", "weight": 1, "rubric": []}],
    }
    try:
        ScorecardV1.model_validate(bad_scorecard)
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for missing anchor score 5")


if __name__ == "__main__":
    test_valid_fixture_ok()
    test_missing_compensation_max_fails()
    test_missing_scorecard_anchors_fails()
    print("stage8 schemas: OK")
