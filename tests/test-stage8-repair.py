#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
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


def test_non_json_falls_back() -> None:
    from ml.main import run_core

    prev = os.environ.get("MOCK_MODE")
    os.environ["MOCK_MODE"] = "non_json"
    try:
        pack = run_core(valid_profile_fixture(), request_id="t1")
    finally:
        if prev is None:
            os.environ.pop("MOCK_MODE", None)
        else:
            os.environ["MOCK_MODE"] = prev

    q = find_artifact(pack, "quality_report")
    assert q is not None
    summary = (q.get("content") or {}).get("summary") or {}
    assert summary.get("status") == "degraded", summary

    warnings = (q.get("content") or {}).get("warnings") or []
    assert "FALLBACK_USED" in warnings
    assert "LLM_OUTPUT_INVALID" in warnings

    m = find_artifact(pack, "manifest")
    assert m is not None
    items = (m.get("content") or {}).get("artifacts") or []
    assert any(i.get("kind") == "manifest" for i in items)


def test_wrapped_json_extracts_ok() -> None:
    from ml.main import run_core

    prev = os.environ.get("MOCK_MODE")
    os.environ["MOCK_MODE"] = "wrapped_json"
    try:
        pack = run_core(valid_profile_fixture(), request_id="t2")
    finally:
        if prev is None:
            os.environ.pop("MOCK_MODE", None)
        else:
            os.environ["MOCK_MODE"] = prev

    q = find_artifact(pack, "quality_report")
    assert q is not None
    summary = (q.get("content") or {}).get("summary") or {}
    assert summary.get("status") == "pass", summary


def test_missing_fields_repairs_or_falls_back() -> None:
    from ml.main import run_core

    prev = os.environ.get("MOCK_MODE")
    os.environ["MOCK_MODE"] = "missing_fields"
    try:
        pack = run_core(valid_profile_fixture(), request_id="t3")
    finally:
        if prev is None:
            os.environ.pop("MOCK_MODE", None)
        else:
            os.environ["MOCK_MODE"] = prev

    q = find_artifact(pack, "quality_report")
    assert q is not None
    summary = (q.get("content") or {}).get("summary") or {}
    status = summary.get("status")
    assert status in ("pass", "degraded"), status

    # If repair succeeded, it should be pass; if not, it must include fallback warnings.
    if status == "degraded":
        warnings = (q.get("content") or {}).get("warnings") or []
        assert "FALLBACK_USED" in warnings
        assert "LLM_OUTPUT_INVALID" in warnings


if __name__ == "__main__":
    test_non_json_falls_back()
    test_wrapped_json_extracts_ok()
    test_missing_fields_repairs_or_falls_back()
    print("stage8 repair: OK")
