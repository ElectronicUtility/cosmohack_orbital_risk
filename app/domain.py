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
    # A plan-specific constraint must be supplied by the analyst, not invented by the service.
    requires_sunlight: bool
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
    archive_last_modified_at: datetime | None = None
    publication_basis: str = "unknown"
    artifact_path: str | None = None
    source_revision: str | None = None
    http_status: int = 200
    parser_version: str = "1"
    cache_state: str = "fresh"

    @field_validator("retrieved_at", "published_at", "archive_last_modified_at")
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


class ConjunctionEvent(BaseModel):
    id: str
    tca: datetime
    min_separation_km: float = Field(ge=0)
    relative_speed_km_s: float = Field(ge=0)
    object_norad_id: int
    object_name: str | None = None
    object_element_epoch: datetime | None = None
    iss_element_epoch: datetime | None = None
    max_probability: float | None = Field(default=None, ge=0, le=1)
    published_at: datetime | None = None
    source_record_ids: list[str]
    source_url: str
    classification: str
    limitations: list[str] = []
    algorithm_version: str

    @field_validator("tca", "published_at", "object_element_epoch", "iss_element_epoch")
    @classmethod
    def utc_time(cls, v: datetime | None) -> datetime | None:
        return aware(v) if v is not None else None


class FactorAssessment(BaseModel):
    mechanism: str
    role: str = "risk_mechanism"
    decision_eligible: bool = True
    eligibility_reason: str | None = None
    state: str
    covered_minutes: float
    overlap_minutes: float | None
    forecast_probability_percent: float | None = None
    forecast_horizon_hours: float | None = None
    supports_next_6h_horizon: bool | None = None
    forecast_temporal_resolution: str | None = None
    forecast_basis: str | None = None
    comparison_value: float | None = None
    comparison_unit: str | None = None
    comparison_quantity: str | None = None
    comparison_direction: str = "lower_is_better"
    comparison_tolerance: float = 0.0
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
    pareto_frontier_indices: list[int] = []
    reasons: list[str]
    decision_mechanisms: list[str] = []
    excluded_mechanisms: list[dict] = []
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
