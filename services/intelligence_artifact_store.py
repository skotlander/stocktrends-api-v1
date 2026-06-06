from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


STORE_ENV_VAR = "ST_INTELLIGENCE_ARTIFACTS_DIR"
PUBLIC_CONTRACT_VERSION = "1"
CONTRACT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "intelligence"
    / "public_artifact_envelope.v1.schema.json"
)

PublicArtifactType = Literal[
    "market_guidance",
    "market_research_report",
    "editorial_preview",
    "discovery_metadata",
]
PublicationStatus = Literal[
    "publish_ready",
    "product_grade",
    "agent_actionable",
    "published",
]
ValidationStatus = Literal[
    "validated",
    "validated_with_warnings",
]

_SHA256_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class IntelligenceArtifactStoreUnavailable(RuntimeError):
    """Raised when the artifact store or manifest cannot be trusted."""


class InvalidIntelligenceArtifact(ValueError):
    """Raised for a manifest-referenced artifact that must fail closed."""


class PublicArtifactEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    artifact_id: str = Field(min_length=1)
    artifact_type: PublicArtifactType
    publication_status: PublicationStatus
    validation_status: ValidationStatus
    generated_at: str = Field(min_length=1)
    published_at: str = Field(min_length=1)
    weekdate: str
    exchange: str
    provider: dict[str, Any]
    lineage: dict[str, Any]
    payload: Any
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_endpoints: list[str] | None = None
    input_snapshot_id: str | None = None
    validation_summary: dict[str, Any] | None = None
    guardrail_summary: dict[str, Any] | None = None
    warnings: list[Any] | None = None
    expires_at: str | None = None
    access_tier: str | None = None

    @field_validator("provider", "lineage")
    @classmethod
    def _non_empty_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("must be an object")
        return value

    @model_validator(mode="after")
    def _validate_publication_timestamp(self) -> "PublicArtifactEnvelope":
        if self.published_at == "static":
            if self.artifact_type != "discovery_metadata":
                raise ValueError("published_at='static' is valid only for discovery_metadata")
            return self

        _parse_datetime(self.published_at, field_name="published_at")
        return self


class ArtifactManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    artifact_type: PublicArtifactType
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    exchange: str
    path: str = Field(min_length=1)
    published_at: str = Field(min_length=1)
    weekdate: str


class ArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_count: int = Field(ge=0)
    artifacts: list[ArtifactManifestEntry]
    generated_at: str = Field(min_length=1)
    schema_version: Literal["1"]

    @model_validator(mode="after")
    def _validate_count(self) -> "ArtifactManifest":
        if self.artifact_count != len(self.artifacts):
            raise ValueError("artifact_count must match artifacts length")
        return self


class _EnvelopeContractSchema:
    def __init__(self, schema_path: Path = CONTRACT_SCHEMA_PATH):
        try:
            raw = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntelligenceArtifactStoreUnavailable(
                "Vendored PublicArtifactEnvelope.v1 schema is unavailable."
            ) from exc

        properties = raw.get("properties")
        required = raw.get("required")
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise IntelligenceArtifactStoreUnavailable(
                "Vendored PublicArtifactEnvelope.v1 schema is malformed."
            )

        self._properties = properties
        self._required = set(required)
        self._allowed = set(properties)
        self._additional_properties = raw.get("additionalProperties", True)

    def validate(self, data: dict[str, Any]) -> None:
        missing = self._required - set(data)
        if missing:
            raise InvalidIntelligenceArtifact(
                f"Artifact missing required fields: {', '.join(sorted(missing))}"
            )

        if self._additional_properties is False:
            extra = set(data) - self._allowed
            if extra:
                raise InvalidIntelligenceArtifact(
                    f"Artifact contains unsupported fields: {', '.join(sorted(extra))}"
                )

        self._validate_const(data, "schema_version")
        self._validate_enum(data, "artifact_type")
        self._validate_enum(data, "publication_status")
        self._validate_enum(data, "validation_status")

        content_hash = data.get("content_hash")
        if not isinstance(content_hash, str) or not _SHA256_HASH_RE.match(content_hash):
            raise InvalidIntelligenceArtifact("Artifact content_hash is invalid.")

    def _validate_const(self, data: dict[str, Any], field: str) -> None:
        const = self._properties.get(field, {}).get("const")
        if const is not None and data.get(field) != const:
            raise InvalidIntelligenceArtifact(f"Artifact {field} is unsupported.")

    def _validate_enum(self, data: dict[str, Any], field: str) -> None:
        enum = self._properties.get(field, {}).get("enum")
        if enum and data.get(field) not in enum:
            raise InvalidIntelligenceArtifact(f"Artifact {field} is unsupported.")


def canonical_public_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def compute_public_artifact_content_hash(envelope: dict[str, Any]) -> str:
    normalized = copy.deepcopy(envelope)
    if isinstance(normalized, dict):
        normalized.pop("content_hash", None)
    encoded = canonical_public_json(normalized).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def configured_intelligence_artifact_store() -> "IntelligenceArtifactStore":
    root = (os.getenv(STORE_ENV_VAR) or "").strip()
    if not root:
        raise IntelligenceArtifactStoreUnavailable(
            f"{STORE_ENV_VAR} is not configured."
        )
    return IntelligenceArtifactStore(root)


def _parse_datetime(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sort_datetime(value: str) -> datetime:
    if value == "static":
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return _parse_datetime(value, field_name="timestamp")
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _artifact_sort_key(envelope: PublicArtifactEnvelope) -> tuple[str, datetime, datetime, int, str]:
    return (
        envelope.weekdate,
        _sort_datetime(envelope.published_at),
        _sort_datetime(envelope.generated_at),
        envelope.revision,
        envelope.artifact_id,
    )


class IntelligenceArtifactStore:
    def __init__(
        self,
        root_dir: str | os.PathLike[str],
        *,
        schema_path: Path = CONTRACT_SCHEMA_PATH,
        now: datetime | None = None,
    ):
        self.root_dir = Path(root_dir).resolve()
        self._schema = _EnvelopeContractSchema(schema_path)
        self._now = now

    def get_latest(self, artifact_type: PublicArtifactType) -> PublicArtifactEnvelope | None:
        matches = [
            artifact
            for artifact in self._load_valid_artifacts()
            if artifact.artifact_type == artifact_type
        ]
        if not matches:
            return None
        return sorted(matches, key=_artifact_sort_key, reverse=True)[0]

    def get_by_id(
        self,
        artifact_id: str,
        *,
        artifact_type: PublicArtifactType,
    ) -> PublicArtifactEnvelope | None:
        for artifact in self._load_valid_artifacts():
            if artifact.artifact_id == artifact_id and artifact.artifact_type == artifact_type:
                return artifact
        return None

    def list_valid_artifacts(self) -> list[PublicArtifactEnvelope]:
        return self._load_valid_artifacts()

    def _load_valid_artifacts(self) -> list[PublicArtifactEnvelope]:
        manifest = self._load_manifest()
        artifacts: list[PublicArtifactEnvelope] = []
        for entry in manifest.artifacts:
            artifact = self._load_valid_manifest_entry(entry)
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def _load_manifest(self) -> ArtifactManifest:
        if not self.root_dir.is_dir():
            raise IntelligenceArtifactStoreUnavailable("Artifact store directory is unavailable.")

        manifest_path = self.root_dir / "manifest.json"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ArtifactManifest.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise IntelligenceArtifactStoreUnavailable("Artifact manifest is unavailable or invalid.") from exc

        seen_ids: set[str] = set()
        for entry in manifest.artifacts:
            if entry.artifact_id in seen_ids:
                raise IntelligenceArtifactStoreUnavailable("Artifact manifest contains duplicate artifact_id values.")
            seen_ids.add(entry.artifact_id)
            self._resolve_manifest_path(entry.path)

        return manifest

    def _load_valid_manifest_entry(
        self,
        entry: ArtifactManifestEntry,
    ) -> PublicArtifactEnvelope | None:
        try:
            artifact_path = self._resolve_manifest_path(entry.path)
            raw = json.loads(artifact_path.read_text(encoding="utf-8"))
            return self._validate_artifact(raw, entry)
        except (OSError, json.JSONDecodeError, InvalidIntelligenceArtifact, ValidationError, ValueError):
            return None

    def _validate_artifact(
        self,
        raw: Any,
        entry: ArtifactManifestEntry,
    ) -> PublicArtifactEnvelope:
        if not isinstance(raw, dict):
            raise InvalidIntelligenceArtifact("Artifact JSON root must be an object.")

        self._schema.validate(raw)
        envelope = PublicArtifactEnvelope.model_validate(raw)

        if envelope.artifact_id != entry.artifact_id:
            raise InvalidIntelligenceArtifact("Artifact id does not match manifest entry.")
        if envelope.artifact_type != entry.artifact_type:
            raise InvalidIntelligenceArtifact("Artifact type does not match manifest entry.")
        if envelope.content_hash != entry.content_hash:
            raise InvalidIntelligenceArtifact("Artifact hash does not match manifest entry.")
        if compute_public_artifact_content_hash(raw) != envelope.content_hash:
            raise InvalidIntelligenceArtifact("Artifact hash does not match envelope content.")

        if envelope.expires_at:
            expires_at = _parse_datetime(envelope.expires_at, field_name="expires_at")
            now = self._now or datetime.now(timezone.utc)
            if expires_at <= now.astimezone(timezone.utc):
                raise InvalidIntelligenceArtifact("Artifact is expired.")

        return envelope

    def _resolve_manifest_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise IntelligenceArtifactStoreUnavailable("Manifest artifact path is empty.")

        raw_path = relative_path.strip()
        if (
            Path(raw_path).is_absolute()
            or PureWindowsPath(raw_path).is_absolute()
            or raw_path.startswith(("/", "\\"))
        ):
            raise IntelligenceArtifactStoreUnavailable("Manifest artifact path must be relative.")

        normalized = raw_path.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise IntelligenceArtifactStoreUnavailable("Manifest artifact path is unsafe.")

        candidate = (self.root_dir / Path(*parts)).resolve()
        try:
            candidate.relative_to(self.root_dir)
        except ValueError as exc:
            raise IntelligenceArtifactStoreUnavailable("Manifest artifact path escapes the store root.") from exc
        return candidate
