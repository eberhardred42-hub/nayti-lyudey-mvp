from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


ContractVersion = Literal["v1"]


class MetaV1(BaseModel):
    contract_version: ContractVersion = "v1"
    kind: str
    legacy_kind: Optional[Literal["tasks_summary", "screening_questions", "sourcing_pack"]] = None


WorkFormat = Literal["office", "hybrid", "remote", "unknown"]
EmploymentType = Literal["full-time", "part-time", "project", "unknown"]
EducationLevel = Literal["courses", "higher", "specialized", "unknown"]
Currency = Literal["RUB"]


class RoleV1(BaseModel):
    title: str
    domain: Optional[str] = None
    seniority: Optional[str] = None
    risk_level: Optional[Literal["low", "medium", "high"]] = None


class LocationV1(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None


class CompanyV1(BaseModel):
    name: Optional[str] = None
    location: LocationV1 = Field(default_factory=LocationV1)
    work_format: WorkFormat


class CompensationRangeV1(BaseModel):
    currency: Currency = "RUB"
    min: int
    max: int

    @field_validator("min", "max")
    @classmethod
    def non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value

    @model_validator(mode="after")
    def check_min_le_max(self) -> "CompensationRangeV1":
        if self.min > self.max:
            raise ValueError("compensation.range.min must be <= compensation.range.max")
        return self


class CompensationV1(BaseModel):
    range: CompensationRangeV1
    comment: Optional[str] = None


class EmploymentV1(BaseModel):
    employment_type: EmploymentType = "unknown"
    schedule_comment: Optional[str] = None


class RequirementsV1(BaseModel):
    experience_years_min: Optional[int] = None
    education_level: EducationLevel = "unknown"
    hard_skills: List[str] = Field(default_factory=list)
    soft_skills: List[str] = Field(default_factory=list)


class ResponsibilitiesV1(BaseModel):
    tasks: List[str] = Field(default_factory=list)
    raw_vacancy_text: Optional[str] = None


class SourcingV1(BaseModel):
    suggested_channels: List[str] = Field(default_factory=list)


class VacancyProfileV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="vacancy_profile"))

    role: RoleV1
    company: CompanyV1
    compensation: CompensationV1
    employment: EmploymentV1 = Field(default_factory=EmploymentV1)
    requirements: RequirementsV1 = Field(default_factory=RequirementsV1)
    responsibilities: ResponsibilitiesV1 = Field(default_factory=ResponsibilitiesV1)
    sourcing: SourcingV1 = Field(default_factory=SourcingV1)


class FreeReportSectionV1(BaseModel):
    title: str
    bullets: List[str]


BudgetStatus = Literal["ok", "low", "high", "unknown"]


class FreeReportBudgetRealityCheckV1(BaseModel):
    status: BudgetStatus
    bullets: List[str]


class FreeReportJsonV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="free_report_json"))

    headline: str
    where_to_search: List[FreeReportSectionV1]
    what_to_screen: List[FreeReportSectionV1]
    budget_reality_check: FreeReportBudgetRealityCheckV1
    next_steps: List[str]


class FreeReportMdV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="free_report_md"))

    markdown: str


class RoleSnapshotV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="role_snapshot_json"))

    role: RoleV1
    one_liner: str
    must_have: List[str]
    nice_to_have: List[str] = Field(default_factory=list)
    deal_breakers: List[str] = Field(default_factory=list)


ChannelPriority = Literal["high", "medium", "low"]


class SourcingChannelV1(BaseModel):
    name: str
    priority: ChannelPriority
    notes: Optional[str] = None


class OutreachTemplateV1(BaseModel):
    channel: str
    language: str
    subject: str
    message: str


class SourcingPackV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="sourcing_pack_json"))

    target_profile: Dict[str, Any]
    channels: List[SourcingChannelV1]
    boolean_search_queries: List[str] = Field(default_factory=list)
    outreach_templates: List[OutreachTemplateV1] = Field(default_factory=list)


QuestionType = Literal["open", "yes_no", "scale", "choice"]


class ScreeningQuestionV1(BaseModel):
    id: str
    text: str
    type: QuestionType = "open"


class ScreeningScriptV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="screening_script_json"))

    opening: str
    questions: List[ScreeningQuestionV1]
    closing: str


class MarketBandV1(BaseModel):
    p25: Optional[int] = None
    p50: Optional[int] = None
    p75: Optional[int] = None


class BudgetRealityCheckV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="budget_reality_check_json"))

    currency: Currency = "RUB"
    salary_min: int
    salary_max: int
    market_band: Optional[MarketBandV1] = None
    status: BudgetStatus
    explanation: str
    recommendations: List[str] = Field(default_factory=list)


class ScorecardAnchorV1(BaseModel):
    score: Literal[1, 2, 3, 4, 5]
    label: str
    what_good_looks_like: Optional[str] = None
    red_flags: List[str] = Field(default_factory=list)
    example_questions: List[str] = Field(default_factory=list)


class ScorecardCompetencyV1(BaseModel):
    id: str
    title: str
    weight: int = Field(ge=1)
    rubric: List[str] = Field(default_factory=list)


class ScorecardV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="scorecard_json"))

    scale: Literal["1-5"] = "1-5"
    anchors: List[ScorecardAnchorV1]
    competencies: List[ScorecardCompetencyV1]

    @field_validator("anchors")
    @classmethod
    def require_anchors_1_to_5(cls, value: List[ScorecardAnchorV1]) -> List[ScorecardAnchorV1]:
        scores = {a.score for a in value}
        required = {1, 2, 3, 4, 5}
        if scores != required:
            missing = sorted(required - scores)
            extra = sorted(scores - required)
            raise ValueError(f"anchors must include scores 1..5 exactly once; missing={missing} extra={extra}")
        if len(value) != 5:
            raise ValueError("anchors must contain exactly 5 items (scores 1..5)")
        return value


class QualityCheckV1(BaseModel):
    id: str
    status: Literal["pass", "warn", "fail"]
    details: Optional[str] = None


class QualitySummaryV1(BaseModel):
    status: Literal["pass", "fail", "degraded"]
    issues_count: int = Field(ge=0)
    warnings_count: int = Field(ge=0)


class ValidatedArtifactRefV1(BaseModel):
    artifact_id: str
    kind: str


class QualityReportV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="quality_report"))

    summary: QualitySummaryV1
    gates: Dict[str, bool] = Field(default_factory=dict)
    score: float = 0.0
    warnings: List[str] = Field(default_factory=list)
    checks: List[QualityCheckV1] = Field(default_factory=list)
    artifacts_validated: List[ValidatedArtifactRefV1] = Field(default_factory=list)


class LLMGeneratedArtifactsV1(BaseModel):
    role_snapshot_json: RoleSnapshotV1
    sourcing_pack_json: SourcingPackV1
    screening_script_json: ScreeningScriptV1
    budget_reality_check_json: BudgetRealityCheckV1
    scorecard_json: ScorecardV1
    free_report_json: FreeReportJsonV1
    free_report_md: str


class ManifestArtifactV1(BaseModel):
    artifact_id: str
    layer: Literal["user_result", "trace"]
    kind: str
    content_ref: Literal["inline", "ref"] = "inline"


class ManifestV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="manifest"))

    pack_id: str
    generated_at_iso: str
    artifacts: List[ManifestArtifactV1]
    kinds_dictionary: Dict[str, str] = Field(default_factory=dict)
    legacy_kinds: Dict[str, str] = Field(default_factory=dict)


class ArtifactMetaV1(BaseModel):
    legacy_kind: Optional[Literal["tasks_summary", "screening_questions", "sourcing_pack"]] = None


class ArtifactEnvelopeV1(BaseModel):
    artifact_id: str
    kind: str
    meta: ArtifactMetaV1 = Field(default_factory=ArtifactMetaV1)
    content: Dict[str, Any]


class ArtifactLayerV1(BaseModel):
    artifacts: List[ArtifactEnvelopeV1]
    quality: Dict[str, Any] = Field(default_factory=dict)


class HiringPackV1(BaseModel):
    meta: MetaV1 = Field(default_factory=lambda: MetaV1(kind="hiring_pack"))
    pack_id: str
    user_result: ArtifactLayerV1
    trace: ArtifactLayerV1

    @model_validator(mode="after")
    def validate_required_kinds_and_shapes(self) -> "HiringPackV1":
        user_kinds = {a.kind for a in self.user_result.artifacts}
        trace_kinds = {a.kind for a in self.trace.artifacts}

        required_user = {"free_report_json", "free_report_md"}
        required_trace = {"manifest", "quality_report"}

        missing_user = sorted(required_user - user_kinds)
        missing_trace = sorted(required_trace - trace_kinds)
        if missing_user or missing_trace:
            raise ValueError(f"missing required kinds: user_result={missing_user} trace={missing_trace}")

        # Validate known artifact content structures
        for artifact in self.user_result.artifacts + self.trace.artifacts:
            if artifact.kind == "free_report_json":
                FreeReportJsonV1.model_validate({"meta": {"contract_version": "v1", "kind": "free_report_json"}, **artifact.content})
            elif artifact.kind == "free_report_md":
                FreeReportMdV1.model_validate({"meta": {"contract_version": "v1", "kind": "free_report_md"}, **artifact.content})
            elif artifact.kind == "role_snapshot_json":
                RoleSnapshotV1.model_validate({"meta": {"contract_version": "v1", "kind": "role_snapshot_json"}, **artifact.content})
            elif artifact.kind == "sourcing_pack_json":
                SourcingPackV1.model_validate({"meta": {"contract_version": "v1", "kind": "sourcing_pack_json"}, **artifact.content})
            elif artifact.kind == "screening_script_json":
                ScreeningScriptV1.model_validate({"meta": {"contract_version": "v1", "kind": "screening_script_json"}, **artifact.content})
            elif artifact.kind == "budget_reality_check_json":
                BudgetRealityCheckV1.model_validate({"meta": {"contract_version": "v1", "kind": "budget_reality_check_json"}, **artifact.content})
            elif artifact.kind == "scorecard_json":
                ScorecardV1.model_validate({"meta": {"contract_version": "v1", "kind": "scorecard_json"}, **artifact.content})
            elif artifact.kind == "quality_report":
                QualityReportV1.model_validate({"meta": {"contract_version": "v1", "kind": "quality_report"}, **artifact.content})
            elif artifact.kind == "manifest":
                ManifestV1.model_validate({"meta": {"contract_version": "v1", "kind": "manifest"}, **artifact.content})

        return self


def sanitize_pydantic_errors(exc: ValidationError) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for err in exc.errors():
        err = dict(err)
        err.pop("input", None)
        err.pop("ctx", None)
        sanitized.append(err)
    return sanitized
