"""Response schemas. Field names match openapi.yaml exactly."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WindowMode = Literal["week", "rolling", "cumulative"]
NameMode = Literal["full", "initials", "nickname"]


class Error(BaseModel):
    message: str
    status: int | None = None


class Class(BaseModel):
    id: str
    instructor_id: str
    name: str
    term_id: str
    external_id: str | None = None
    sheet_id: str | None = None


class Week(BaseModel):
    id: str
    term_id: str
    week_number: int
    start_date: str
    end_date: str


class Criterion(BaseModel):
    id: str
    class_id: str
    key: str
    label: str
    unit: str | None = None
    default_weight: float
    sort_order: int


class Account(BaseModel):
    id: str
    role: Literal["instructor", "student"]
    student_id: str | None = None
    class_ids: list[str]
    external_id: str | None = None


class Hours(BaseModel):
    work: float = 0
    childcare: float = 0
    eldercare: float = 0


class TypeWeights(BaseModel):
    work: float = 1
    childcare: float = 1
    eldercare: float = 1


class LeagueSettings(BaseModel):
    weights: dict[str, float] | None = None
    typeWeights: TypeWeights = Field(default_factory=TypeWeights)
    rate: float = 0.01
    cap: float = 1.25
    tieBreakers: list[str] = Field(default_factory=lambda: ["attendance", "homework"])


class LeagueSettingsPatch(BaseModel):
    weights: dict[str, float] | None = None
    typeWeights: TypeWeights | None = None
    rate: float | None = None
    cap: float | None = None
    tieBreakers: list[str] | None = None


class SourceInfo(BaseModel):
    kind: str
    label: str
    demo: bool
    store: str


class Issue(BaseModel):
    level: Literal["error", "warning"]
    where: str
    message: str


class ScorePart(BaseModel):
    key: str
    label: str
    earned: float | None = None
    possible: float | None = None
    normalised: float | None = None
    weight: float
    effectiveWeight: float
    points: float
    missing: bool


class RankingRow(BaseModel):
    student_id: str
    display_name: str
    score: float
    rank: int
    tied: bool
    rank_delta: int | None = None
    gap_to_next: float | None = None
    gap_to_below: float | None = None
    missing: list[str] = Field(default_factory=list)
    is_self: bool = False
    raw: float | None = None
    factor: float | None = None
    weighted_hours: float | None = None
    capped: bool | None = None
    hours_source: str | None = None


class RankingResponse(BaseModel):
    classId: str
    weekId: str
    windowMode: str
    rollingN: int
    criteriaKeys: list[str]
    weights: dict[str, float]
    rows: list[RankingRow]
    weekCount: int
    lastUpdated: int
    stale: bool
    issues: list[Issue] = Field(default_factory=list)


class WeekScore(BaseModel):
    week_number: int
    raw: float
    weighted_hours: float
    factor: float
    adjusted: float
    capped: bool


class Explanation(BaseModel):
    student_id: str
    display_name: str
    rank: int
    tied: bool
    score: float
    raw: float
    focusRaw: float
    focusAdjusted: float
    focusCapped: bool
    factor: float
    weighted_hours: float
    capped: bool
    hours: Hours
    hours_source: str | None = None
    typeWeights: TypeWeights
    rate: float
    cap: float
    focusWeek: int
    parts: list[ScorePart]
    weeks: list[WeekScore]
    gap_to_next: float | None = None
    gap_to_below: float | None = None
    above: str | None = None
    weekId: str
    windowMode: str


class Explainer(BaseModel):
    typeWeights: TypeWeights
    rate: float
    cap: float
    table: list[dict[str, float]]
    example: dict[str, Any]


class Bootstrap(BaseModel):
    klass: Class
    classes: list[Class]
    weeks: list[Week]
    criteria: list[Criterion]
    weights: dict[str, float]
    defaultWeights: dict[str, float]
    settings: dict[str, Any]
    tieBreakers: list[str]
    accounts: list[Account]
    weeksWithData: list[str]
    latestCompleteWeekId: str | None = None
    source: SourceInfo
    lastUpdated: int
    issues: list[Issue] = Field(default_factory=list)
    rollingN: int = 4


class Baseline(BaseModel):
    id: str | None = None
    student_id: str
    work_hours: float = 0
    childcare_hours: float = 0
    eldercare_hours: float = 0
    status: str
    effective_from_week: int | None = None
    submitted_at: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None


class WeeklyUpdate(BaseModel):
    id: str | None = None
    student_id: str
    week_id: str
    week_number: int
    work_hours: float = 0
    childcare_hours: float = 0
    eldercare_hours: float = 0
    entered_at: str | None = None
    reversed_by: str | None = None
    reversed_at: str | None = None


class Commitments(BaseModel):
    studentId: str
    baseline: Baseline | None = None
    weeklyUpdates: list[WeeklyUpdate] = Field(default_factory=list)
    byWeek: list[dict[str, Any]]


class Signal(BaseModel):
    key: str
    label: str
    active: bool
    on: bool
    summary: str
    evidence: list[dict[str, str]]


class RiskMetrics(BaseModel):
    declineRun: int = 0
    missedAssignments: int = 0
    attendancePct: float | None = None
    participationPct: float | None = None
    projected: float | None = None
    hours: float | None = None
    missingRun: int = 0


class RiskThresholds(BaseModel):
    declineWeeks: int = 3
    missedAssignments: int = 2
    attendancePct: float = 70
    participationPct: float = 50
    projectedGrade: float = 60
    commitmentHours: float = 20
    missingWeeks: int = 2


class RiskSettings(BaseModel):
    thresholds: RiskThresholds = Field(default_factory=RiskThresholds)
    active: dict[str, bool] = Field(default_factory=lambda: {
        "downward_trend": True, "missed_engagement": True, "low_projected_grade": True,
        "heavy_commitments": True, "missing_data": True})


class RiskSettingsPatch(BaseModel):
    thresholds: dict[str, float | int] | None = None
    active: dict[str, bool] | None = None


class DigestRow(BaseModel):
    student_id: str
    display_name: str
    level: str
    status: Literal["new", "still", "cleared"]
    priorLevel: str | None = None
    signals: list[str] = Field(default_factory=list)
    notes: int = 0


class DigestGroup(BaseModel):
    classId: str
    className: str
    week: int
    comparedWith: int | None = None
    rows: list[DigestRow] = Field(default_factory=list)


class Digest(BaseModel):
    instructorId: str
    groups: list[DigestGroup] = Field(default_factory=list)
    computedAt: str


class Note(BaseModel):
    id: str
    instructor_id: str
    class_id: str
    student_id: str
    body: str
    created_at: str


class NoteRequest(BaseModel):
    body: str


class RiskRecord(BaseModel):
    classId: str
    className: str
    student_id: str
    display_name: str
    week: int
    level: str
    oneAway: str | None = None
    signals: list[Signal]
    metrics: RiskMetrics
    thresholds: RiskThresholds
    history: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)


class Standing(BaseModel):
    student_id: str
    display_name: str
    week: int
    level: str
    signals: list[Signal]
    metrics: RiskMetrics
    help: str


class RefreshResult(BaseModel):
    lastUpdated: int
    issues: list[Issue] = Field(default_factory=list)
    stale: bool


class StatusResult(BaseModel):
    lastUpdated: int | None = None
    stale: bool = False
    issues: list[Issue] = Field(default_factory=list)
    source: SourceInfo
