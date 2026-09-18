from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pydantic import BaseModel, Field, field_validator, model_validator

UTC = timezone.utc


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Time must include a UTC offset")
    return value.astimezone(UTC)


class Mode(StrEnum):
    current = "current"
    reconstruction = "reconstruction"
    replay = "replay"


class AnalysisRequest(BaseModel):
    mode: Mode
    start: datetime
    duration_hours: float = Field(ge=1, le=8)
    search_hours: float = Field(gt=0, le=24)
    cutoff: datetime | None = None
    requires_sunlight: bool = True
    refresh: bool = False

    @field_validator("start", "cutoff")
    @classmethod
    def utc_time(cls, v: datetime | None) -> datetime | None:
        return aware(v) if v is not None else None

    @model_validator(mode="after")
    def check_dates(self):
        if self.mode == Mode.replay and (self.cutoff is None or self.cutoff > self.start):
            raise ValueError("Replay requires cutoff at or before start")
        if self.mode != Mode.current and not (
            datetime(2024, 5, 1, tzinfo=UTC) <= self.start < datetime(2024, 7, 1, tzinfo=UTC)
        ):
            raise ValueError("Historical start must be within May–June 2024")
        return self


class Window(BaseModel):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def utc_time(cls, v: datetime) -> datetime:
        return aware(v)

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


class RawRecord(BaseModel):
    id: str
    source: str
    url: str
    content_sha256: str
    retrieved_at: datetime
    published_at: datetime | None = None
    http_status: int = 200
    parser_version: str = "1"
    cache_state: str = "fresh"

    @field_validator("retrieved_at", "published_at")
    @classmethod
    def utc_time(cls, v: datetime | None) -> datetime | None:
        return aware(v) if v is not None else None


class ExternalEvent(BaseModel):
    id: str
    mechanism: str
    kind: str
    quantity: str
    value: float
    unit: str
    valid_start: datetime
    valid_end: datetime
    published_at: datetime
    observed_at: datetime | None = None
    raw_record_id: str
    source_url: str
    limitations: list[str] = []

    @field_validator("valid_start", "valid_end", "published_at", "observed_at")
    @classmethod
    def utc_time(cls, v: datetime | None) -> datetime | None:
        return aware(v) if v is not None else None


class OrbitState(BaseModel):
    at: datetime
    position_teme_km: tuple[float, float, float]
    epoch: datetime
    source_url: str
    raw_record_id: str
    classification: str

    @field_validator("at", "epoch")
    @classmethod
    def utc_time(cls, v: datetime) -> datetime:
        return aware(v)


class FactorAssessment(BaseModel):
    mechanism: str
    state: str
    covered_minutes: float
    overlap_minutes: float | None
    completeness: str
    freshness: str
    evidence: list[dict] = []
    limitations: list[str] = []
    algorithm_version: str


class WindowAssessment(BaseModel):
    window: Window
    factors: list[FactorAssessment]
    orbit: list[OrbitState]
    limitations: list[str] = []


class Comparison(BaseModel):
    outcome: str
    preferred_index: int | None = None
    reasons: list[str]
    algorithm_version: str


class SavedAnalysis(BaseModel):
    id: str
    request: AnalysisRequest
    windows: list[WindowAssessment]
    comparison: Comparison
    created_at: datetime
    algorithm_version: str
    source_records: list[RawRecord]

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, v: datetime) -> datetime:
        return aware(v)
