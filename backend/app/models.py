"""Request and response schemas. Field names match openapi.yaml."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["teacher", "student"]
WindowMode = Literal["week", "cumulative"]
NameMode = Literal["full", "nickname", "initials"]

Weight = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Weights = dict[str, Weight]

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


class Error(BaseModel):
    detail: str


class Account(BaseModel):
    id: str
    role: Role
    student_id: str | None
    external_id: str


class DemoAccount(Account):
    email: str
    password: str


class LoginRequest(BaseModel):
    # A plain pattern rather than EmailStr: the demo domain `.test` is reserved and
    # rejected by strict email validators.
    email: str = Field(pattern=EMAIL_PATTERN, json_schema_extra={"format": "email"})
    password: str = Field(json_schema_extra={"format": "password"})


class GoogleLoginRequest(BaseModel):
    id_token: str


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


class WeightsResponse(BaseModel):
    class_id: str
    weights: Weights


class SaveWeightsRequest(BaseModel):
    weights: Weights


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


class Explanation(BaseModel):
    student_id: str
    display_name: str
    rank: int = Field(ge=1)
    tied: bool
    score: float
    parts: list[ScorePart]
    gap_to_next: float | None
    gap_to_below: float | None
    above: str | None
    week_id: str
    window_mode: WindowMode


class Status(BaseModel):
    last_updated: datetime | None
    stale: bool
    issues: list[Issue]
    source: SourceInfo


class RefreshResult(BaseModel):
    last_updated: datetime
    issues: list[Issue]
    stale: bool
