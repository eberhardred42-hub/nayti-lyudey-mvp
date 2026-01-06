from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

try:
    from .schemas import ScorecardV1, VacancyProfileV1
except ImportError:  # pragma: no cover
    from schemas import ScorecardV1, VacancyProfileV1


def _iter_strings(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
        return
    if isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)
        return


def contains_emoji(text: str) -> bool:
    # Minimal heuristic: detect common emoji ranges.
    # This is intentionally conservative and fast.
    for ch in text:
        code = ord(ch)
        if 0x1F300 <= code <= 0x1FAFF:
            return True
        if 0x2600 <= code <= 0x26FF:
            return True
        if 0x2700 <= code <= 0x27BF:
            return True
    return False


def _artifact_map(artifacts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for a in artifacts or []:
        kind = a.get("kind")
        if isinstance(kind, str):
            out[kind] = a
    return out


def compute_quality_report(
    profile: VacancyProfileV1,
    user_artifacts: List[Dict[str, Any]],
    trace_artifacts: List[Dict[str, Any]],
    schema_ok: bool,
    extra_warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Compute quality gates + score + warnings and return quality_report.content dict.

    Does NOT raise on bad artifacts; instead sets gates=false and emits warning codes.
    """

    had_extra_warnings = bool(extra_warnings)
    warnings: List[str] = list(extra_warnings or [])

    user_by_kind = _artifact_map(user_artifacts)
    trace_by_kind = _artifact_map(trace_artifacts)

    required_user = {
        "role_snapshot_json",
        "sourcing_pack_json",
        "screening_script_json",
        "budget_reality_check_json",
        "scorecard_json",
        "free_report_json",
        "free_report_md",
    }
    required_trace = {"manifest", "quality_report"}

    gates: Dict[str, bool] = {}

    gates["schema_ok"] = bool(schema_ok)

    missing_user = sorted(required_user - set(user_by_kind.keys()))
    missing_trace = sorted(required_trace - set(trace_by_kind.keys()))
    coverage_ok = (not missing_user) and (not missing_trace)
    gates["coverage_ok"] = coverage_ok
    if missing_user:
        warnings.append("COVERAGE_MISSING_USER_ARTIFACTS")
    if missing_trace:
        warnings.append("COVERAGE_MISSING_TRACE_ARTIFACTS")

    # actionability_ok: next_steps/timebox or structured steps
    actionability_ok = False
    free_report = user_by_kind.get("free_report_json")
    if free_report:
        content = free_report.get("content") or {}
        next_steps = content.get("next_steps")
        if isinstance(next_steps, list) and len([x for x in next_steps if isinstance(x, str) and x.strip()]) > 0:
            actionability_ok = True

    if not actionability_ok:
        md = user_by_kind.get("free_report_md")
        if md:
            md_text = (md.get("content") or {}).get("markdown")
            if isinstance(md_text, str) and ("Следующие шаги" in md_text or "-" in md_text):
                actionability_ok = True

    gates["actionability_ok"] = actionability_ok
    if not actionability_ok:
        warnings.append("ACTIONABILITY_MISSING")

    # comparability_ok: scorecard + anchors 1..5
    comparability_ok = False
    scorecard = user_by_kind.get("scorecard_json")
    if not scorecard:
        warnings.append("COMPARABILITY_SCORECARD_MISSING")
    else:
        content = scorecard.get("content") or {}
        try:
            ScorecardV1.model_validate({"meta": {"contract_version": "v1", "kind": "scorecard_json"}, **content})
            comparability_ok = True
        except Exception:
            warnings.append("COMPARABILITY_ANCHORS_INVALID")
            comparability_ok = False

    gates["comparability_ok"] = comparability_ok

    # risk_checks_ok
    risk_level = getattr(profile.role, "risk_level", None)
    risk_checks_ok = True
    if risk_level == "high":
        compliance = user_by_kind.get("compliance_checks_json") or trace_by_kind.get("compliance_checks_json")
        if not compliance:
            risk_checks_ok = False
            warnings.append("RISK_COMPLIANCE_CHECKS_MISSING")
    gates["risk_checks_ok"] = risk_checks_ok

    # no_emojis_ok + tone_ty_ok
    all_text = []
    for a in (user_artifacts or []) + (trace_artifacts or []):
        all_text.extend(list(_iter_strings(a.get("content"))))

    no_emojis_ok = not any(contains_emoji(s) for s in all_text)
    gates["no_emojis_ok"] = no_emojis_ok
    if not no_emojis_ok:
        warnings.append("EMOJIS_PRESENT")

    # tone_ty_ok: very light heuristic (no aggressive punctuation / rude words)
    bad_markers = ("!!!", "идиот", "туп", "ненавиж")
    tone_ty_ok = True
    for s in all_text:
        low = s.lower()
        if any(m in low for m in bad_markers):
            tone_ty_ok = False
            break
    gates["tone_ty_ok"] = tone_ty_ok
    if not tone_ty_ok:
        warnings.append("TONE_BAD")

    # Score: mean of gates (0..1)
    score = round(sum(1 for v in gates.values() if v) / max(1, len(gates)), 3)

    status = "pass" if score == 1.0 else "degraded"
    if not gates["schema_ok"]:
        status = "fail"
    elif had_extra_warnings:
        status = "degraded"

    issues_count = sum(1 for v in gates.values() if not v)

    return {
        "summary": {"status": status, "issues_count": issues_count, "warnings_count": len(warnings)},
        "gates": gates,
        "score": score,
        "warnings": warnings,
        "checks": [],
        "artifacts_validated": [],
    }
