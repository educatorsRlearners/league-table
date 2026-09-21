"""Request and response schemas. Field names match openapi.yaml."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.store import BaselineStatus, Role

__all__ = ["Role", "BaselineStatus"]

WindowMode = Literal["week", "cumulative", "rolling"]
NameMode = Literal["full", "nickname", "initials"]

Weight = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Weights = dict[str, Weight]
Hours = dict[str, Annotated[float, Field(allow_inf_nan=False)]]


class Error(BaseModel):
    detail: str


class Account(BaseModel):
    id: str
    role: Role
    student_id: str | None
    external_id: str


class DemoAccount(Account):
    name: str
    code: str


class LoginRequest(BaseModel):
    code: str = Field(min_length=1, json_schema_extra={"format": "password"})


class Class(BaseModel):
    id: str
    external_id: str
    name: str
    term_id: str


class Week(BaseModel):
    id: str
    term_id: str
    week_number: int
    start_date: date
    end_date: date


class Criterion(BaseModel):
    id: str
    class_id: str
    key: str
    label: str
    unit: str
    default_weight: Weight
    sort_order: int


class SourceInfo(BaseModel):
    kind: str
    label: str
    demo: bool


class Issue(BaseModel):
    level: Literal["error", "warning"]
    where: str
    message: str


class ClassBootstrap(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_: Class = Field(alias="class")
    weeks: list[Week]
    criteria: list[Criterion]
    weights: Weights
    tie_breakers: list[str]
    source: SourceInfo
    last_updated: datetime
    issues: list[Issue]


class RankingRow(BaseModel):
    """What every signed-in person sees of a classmate: the adjusted score and rank only."""

    student_id: str
    display_name: str
    score: float
    rank: int = Field(ge=1)
    tied: bool
    rank_delta: int | None
    missing: list[str]
    gap_to_next: float | None
    gap_to_below: float | None


class Ranking(BaseModel):
    class_id: str
    week_id: str
    window_mode: WindowMode
    rolling_weeks: int | None
    criteria_keys: list[str]
    weights: Weights
    rows: list[RankingRow]
    last_updated: datetime
    stale: bool
    issues: list[Issue]


class ScorePart(BaseModel):
    key: str
    label: str
    earned: float | None
    possible: float | None
    normalised: float | None
    weight: float
    effective_weight: float
    points: float
    missing: bool


class WeekBreakdown(BaseModel):
    """One week of a student's score, before and after the adjustment."""

    week_id: str
    week_number: int
    raw_score: float
    weighted_hours: float
    factor: float
    adjusted_score: float
    capped: bool


class Explanation(BaseModel):
    """How a rank was reached. `score` is the adjusted score the table ranks on.

    In a window of several weeks each week is scored on its own and the weekly scores are
    averaged, so `raw_score` and `score` are means and `parts` average the weekly points.
    `factor`, `weighted_hours` and `hours` are only given for a single week.
    """

    student_id: str
    display_name: str
    rank: int = Field(ge=1)
    tied: bool
    score: float
    raw_score: float
    factor: float | None
    weighted_hours: float | None
    hours: Hours | None = Field(description="Weighted hours by commitment type, for a single week.")
    capped: bool
    parts: list[ScorePart]
    weeks: list[WeekBreakdown]
    gap_to_next: float | None
    gap_to_below: float | None
    above: str | None
    week_id: str
    window_mode: WindowMode
    rolling_weeks: int | None


class Status(BaseModel):
    last_updated: datetime | None
    stale: bool
    issues: list[Issue]
    source: SourceInfo


class RefreshResult(BaseModel):
    last_updated: datetime
    issues: list[Issue]
    stale: bool


# Commitments


class CommitmentType(BaseModel):
    key: str
    label: str


class HourLimits(BaseModel):
    step: float
    per_type_max: float
    total_max: float


class HoursRequest(BaseModel):
    hours: Hours = Field(description="Hours per week by commitment type; a type left out counts as 0.")


class Baseline(BaseModel):
    id: str
    student_id: str
    hours: Hours
    status: BaselineStatus
    effective_from_week: int | None
    submitted_at: datetime
    decided_at: datetime | None


class WeeklyUpdate(BaseModel):
    week_id: str
    week_number: int
    hours: Hours | None = Field(description="`null` means the student reset this week to their baseline.")
    entered_at: datetime
    editable: bool


class WeekFactor(BaseModel):
    week_id: str
    week_number: int
    source: Literal["none", "baseline", "weekly"]
    hours: Hours | None
    weighted_hours: float
    factor: float


class EditWindow(BaseModel):
    current_week_id: str | None
    editable_week_ids: list[str]


class MyCommitments(BaseModel):
    types: list[CommitmentType]
    limits: HourLimits
    baseline: Baseline | None = Field(description="The latest submission, whatever its status.")
    in_effect: Baseline | None = Field(description="The approved baseline that counts now, if any.")
    weekly_updates: list[WeeklyUpdate]
    weeks: list[WeekFactor]
    edit_window: EditWindow


class PreviewRequest(BaseModel):
    hours: Hours
    week_id: str | None = Field(default=None, description="Defaults to the student's latest week with scores.")


class Preview(BaseModel):
    week_id: str
    raw_score: float
    weighted_hours: float
    factor: float
    adjusted_score: float
    capped: bool


class PendingApproval(BaseModel):
    id: str
    student_id: str
    display_name: str
    hours: Hours
    submitted_at: datetime
    is_change: bool = Field(description="`true` when the student already has an approved baseline.")
    current: Hours | None = Field(description="The approved baseline's hours, for comparison.")
    suggested_effective_week: int | None


class Approvals(BaseModel):
    pending: list[PendingApproval]
    current_week: int | None


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    effective_week: int | None = Field(
        default=None, ge=1, description="Week the baseline counts from. Defaults to the current week."
    )


class StudentCommitments(BaseModel):
    student_id: str
    display_name: str
    status: Literal["none", "pending", "approved", "rejected"]
    hours: Hours | None
    effective_from_week: int | None
    weighted_hours: float
    factor: float


class LogEntry(BaseModel):
    id: str
    actor_id: str
    actor_name: str
    action: str
    student_id: str | None
    student_name: str | None
    week_id: str | None
    week_number: int | None
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    at: datetime
    flagged: bool = Field(description="A weekly entry that differs from the baseline by more than the threshold.")
    reversible: bool


# Settings and explainer


class AdjustmentSettings(BaseModel):
    type_weights: Weights
    rate: float
    cap: float
    flag_hours: float


class AdjustmentPatch(BaseModel):
    type_weights: Weights | None = None
    rate: float | None = None
    cap: float | None = None
    flag_hours: float | None = None


class Settings(BaseModel):
    weights: Weights
    adjustment: AdjustmentSettings


class SaveSettingsRequest(BaseModel):
    weights: Weights | None = None
    adjustment: AdjustmentPatch | None = None


class FactorRow(BaseModel):
    weighted_hours: float
    factor: float


class WorkedExample(BaseModel):
    title: str
    raw_score: float
    hours: Hours
    weighted_hours: float
    factor: float
    adjusted_score: float
    capped: bool
    steps: list[str]


class Explainer(BaseModel):
    """The formula and the current parameters, with no personal data."""

    formula: list[str]
    types: list[CommitmentType]
    type_weights: Weights
    rate: float
    cap: float
    limits: HourLimits
    factor_table: list[FactorRow]
    examples: list[WorkedExample]
    rules: list[str]
