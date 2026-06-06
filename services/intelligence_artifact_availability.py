from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from services.intelligence_artifact_store import (
    STORE_ENV_VAR,
    IntelligenceArtifactStoreUnavailable,
    PublicArtifactType,
    configured_intelligence_artifact_store,
)


class IntelligenceArtifactAvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    STORE_UNAVAILABLE = "store_unavailable"
    ARTIFACT_NOT_FOUND = "artifact_not_found"


@dataclass(frozen=True)
class IntelligenceArtifactRouteTarget:
    artifact_type: PublicArtifactType
    artifact_id: str | None = None


@dataclass(frozen=True)
class IntelligenceArtifactAvailabilityResult:
    status: IntelligenceArtifactAvailabilityStatus
    artifact_type: PublicArtifactType
    artifact_id: str | None = None
    message: str | None = None

    @property
    def available(self) -> bool:
        return self.status == IntelligenceArtifactAvailabilityStatus.AVAILABLE

    @property
    def error_code(self) -> str | None:
        if self.status == IntelligenceArtifactAvailabilityStatus.STORE_UNAVAILABLE:
            return "intelligence_artifact_store_unavailable"
        if self.status == IntelligenceArtifactAvailabilityStatus.ARTIFACT_NOT_FOUND:
            return "intelligence_artifact_not_found"
        return None

    @property
    def status_code(self) -> int | None:
        if self.status == IntelligenceArtifactAvailabilityStatus.STORE_UNAVAILABLE:
            return 503
        if self.status == IntelligenceArtifactAvailabilityStatus.ARTIFACT_NOT_FOUND:
            return 404
        return None


def match_paid_intelligence_artifact_route(
    method: str | None,
    path: str,
) -> IntelligenceArtifactRouteTarget | None:
    if (method or "").upper() != "GET":
        return None

    normalized_path = path.split("?", 1)[0]
    parts = [part for part in normalized_path.split("/") if part]
    if len(parts) != 4 or parts[0] != "v1" or parts[1] != "intelligence":
        return None

    family = parts[2]
    artifact_id = parts[3]
    if family == "guidance":
        artifact_type: PublicArtifactType = "market_guidance"
    elif family == "research":
        artifact_type = "market_research_report"
    else:
        return None

    if artifact_id == "latest":
        return IntelligenceArtifactRouteTarget(artifact_type=artifact_type)

    if not _is_valid_manifest_artifact_id(artifact_id):
        return None

    return IntelligenceArtifactRouteTarget(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
    )


def check_intelligence_artifact_availability(
    method: str | None,
    path: str,
) -> IntelligenceArtifactAvailabilityResult | None:
    target = match_paid_intelligence_artifact_route(method, path)
    if target is None:
        return None

    try:
        store = configured_intelligence_artifact_store()
        if target.artifact_id is None:
            artifact = store.get_latest(target.artifact_type)
        else:
            artifact = store.get_by_id(
                target.artifact_id,
                artifact_type=target.artifact_type,
            )
    except IntelligenceArtifactStoreUnavailable as exc:
        return IntelligenceArtifactAvailabilityResult(
            status=IntelligenceArtifactAvailabilityStatus.STORE_UNAVAILABLE,
            artifact_type=target.artifact_type,
            artifact_id=target.artifact_id,
            message=str(exc),
        )

    if artifact is None:
        return IntelligenceArtifactAvailabilityResult(
            status=IntelligenceArtifactAvailabilityStatus.ARTIFACT_NOT_FOUND,
            artifact_type=target.artifact_type,
            artifact_id=target.artifact_id,
        )

    return IntelligenceArtifactAvailabilityResult(
        status=IntelligenceArtifactAvailabilityStatus.AVAILABLE,
        artifact_type=target.artifact_type,
        artifact_id=target.artifact_id,
    )


def intelligence_artifact_availability_error_detail(
    result: IntelligenceArtifactAvailabilityResult,
    *,
    request_id: str | None,
) -> dict[str, Any]:
    if result.status == IntelligenceArtifactAvailabilityStatus.STORE_UNAVAILABLE:
        return {
            "error": "intelligence_artifact_store_unavailable",
            "message": "Published intelligence artifacts are not available.",
            "config": {"env_var": STORE_ENV_VAR},
        }

    if result.status == IntelligenceArtifactAvailabilityStatus.ARTIFACT_NOT_FOUND:
        detail: dict[str, Any] = {
            "request_id": request_id,
            "error": "intelligence_artifact_not_found",
            "artifact_type": result.artifact_type,
        }
        if result.artifact_id is not None:
            detail["artifact_id"] = result.artifact_id
        return detail

    raise ValueError("Availability error detail is only defined for unavailable artifacts.")


def _is_valid_manifest_artifact_id(artifact_id: str) -> bool:
    return bool(artifact_id) and "/" not in artifact_id and "\\" not in artifact_id and ".." not in artifact_id
