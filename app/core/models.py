from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


InvestigationStatus = Literal["pending", "running", "completed", "failed"]


class InvestigationRequest(BaseModel):
    incident_name: str = Field(..., min_length=3, max_length=200)
    namespace: str = Field(default="default", min_length=1, max_length=120)
    target: str | None = Field(default=None, max_length=200)
    workload_type: str | None = Field(default=None, max_length=50)  # pods, deployments, statefulsets, etc.
    scenario: str | None = Field(
        default=None,
        description="Optional mock scenario: crashloop-missing-env, image-pull-backoff, oomkilled, pending-resource, service-selector-mismatch, dns-failure",
    )


class SignalBundle(BaseModel):
    pods: list[dict[str, Any]] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    deployments: list[dict[str, Any]] = Field(default_factory=list)
    network: list[dict[str, Any]] = Field(default_factory=list)
    target: str | None = Field(default=None)  # Target workload being investigated


class InvestigationReport(BaseModel):
    root_cause: str
    confidence: float = Field(..., ge=0, le=100)
    evidence: list[str] = Field(default_factory=list)
    recommended_fixes: list[str] = Field(default_factory=list)
    prevention: list[str] = Field(default_factory=list)
    resolution_steps: list[dict] = Field(default_factory=list)


class InvestigationProgress(BaseModel):
    step: str
    detail: str
    timestamp: str = Field(default_factory=utc_now_iso)


class InvestigationState(BaseModel):
    id: str
    request: InvestigationRequest
    status: InvestigationStatus = "pending"
    progress: list[InvestigationProgress] = Field(default_factory=list)
    report: InvestigationReport | None = None
    error: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class InvestigationCreateResponse(BaseModel):
    id: str
    status: InvestigationStatus
    message: str


class InvestigationEvent(BaseModel):
    investigation_id: str
    status: InvestigationStatus
    progress: InvestigationProgress | None = None
    report: InvestigationReport | None = None
    error: str | None = None
    updated_at: str = Field(default_factory=utc_now_iso)
