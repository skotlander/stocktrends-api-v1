from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import middleware.api_key as api_key_module
import middleware.metering as metering_module
from payments.policy_provider import is_public_intelligence_path
from services.intelligence_artifact_store import (
    CONTRACT_SCHEMA_PATH,
    STORE_ENV_VAR,
    IntelligenceArtifactStore,
    IntelligenceArtifactStoreUnavailable,
    compute_public_artifact_content_hash,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "intelligence" / "public_artifacts" / "v1"

GUIDANCE_ID = "market_guidance:N:2026-04-11:guidance:aff9aaeee1660a31"
RESEARCH_ID = "market_research_report:N:2026-04-11:research:2a7d870d628448a0"


def _copy_fixture_store(tmp_path: Path) -> Path:
    target = tmp_path / "public_artifacts" / "v1"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_manifest(root: Path) -> dict:
    return _read_json(root / "manifest.json")


def _save_manifest(root: Path, manifest: dict) -> None:
    _write_json(root / "manifest.json", manifest)


def _entry_for(manifest: dict, artifact_type: str) -> dict:
    return next(entry for entry in manifest["artifacts"] if entry["artifact_type"] == artifact_type)


def _artifact_path(root: Path, entry: dict) -> Path:
    return root / Path(*entry["path"].split("/"))


def _rewrite_artifact(root: Path, artifact_type: str, updates: dict) -> dict:
    manifest = _load_manifest(root)
    entry = _entry_for(manifest, artifact_type)
    artifact_path = _artifact_path(root, entry)
    artifact = _read_json(artifact_path)
    artifact.update(updates)
    artifact["content_hash"] = compute_public_artifact_content_hash(artifact)

    for key in ("artifact_id", "artifact_type", "content_hash", "exchange", "published_at", "weekdate"):
        entry[key] = artifact[key]

    _write_json(artifact_path, artifact)
    _save_manifest(root, manifest)
    return artifact


def _stub_runtime_side_effects(monkeypatch):
    monkeypatch.setattr(metering_module, "log_api_request_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(metering_module, "log_api_request_economics", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_key_module, "log_auth_failure_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        metering_module,
        "resolve_economic_amounts",
        lambda *args, **kwargs: (Decimal("0"), Decimal("0"), Decimal("0")),
    )


@pytest.fixture
def artifact_root(tmp_path):
    return _copy_fixture_store(tmp_path)


@pytest.fixture
def intelligence_client(monkeypatch, artifact_root):
    _stub_runtime_side_effects(monkeypatch)
    monkeypatch.setenv(STORE_ENV_VAR, str(artifact_root))
    with TestClient(main.app) as client:
        yield client


def test_api_loads_vendored_agent_fixtures(artifact_root):
    store = IntelligenceArtifactStore(artifact_root)

    artifacts = store.list_valid_artifacts()

    assert len(artifacts) == 4
    assert {artifact.artifact_type for artifact in artifacts} == {
        "discovery_metadata",
        "editorial_preview",
        "market_guidance",
        "market_research_report",
    }


def test_api_validates_artifacts_against_vendored_schema(artifact_root):
    schema = _read_json(CONTRACT_SCHEMA_PATH)
    assert schema["title"] == "PublicArtifactEnvelope.v1"
    assert schema["additionalProperties"] is False
    assert "canonical_url" not in schema["properties"]

    artifact = IntelligenceArtifactStore(artifact_root).get_latest("market_guidance")
    assert artifact is not None
    assert artifact.schema_version == "1"


def test_api_verifies_content_hash(artifact_root):
    manifest = _load_manifest(artifact_root)
    entry = _entry_for(manifest, "market_guidance")
    artifact = _read_json(_artifact_path(artifact_root, entry))

    assert compute_public_artifact_content_hash(artifact) == artifact["content_hash"]
    assert artifact["content_hash"] == entry["content_hash"]


def test_invalid_hash_fails_closed(artifact_root):
    manifest = _load_manifest(artifact_root)
    entry = _entry_for(manifest, "market_guidance")
    entry["content_hash"] = "sha256:" + ("0" * 64)
    _save_manifest(artifact_root, manifest)

    assert IntelligenceArtifactStore(artifact_root).get_latest("market_guidance") is None


def test_unsupported_schema_version_fails_closed(artifact_root):
    _rewrite_artifact(artifact_root, "market_guidance", {"schema_version": "2"})

    assert IntelligenceArtifactStore(artifact_root).get_latest("market_guidance") is None


def test_missing_manifest_fails_closed(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    store = IntelligenceArtifactStore(root)

    with pytest.raises(IntelligenceArtifactStoreUnavailable):
        store.get_latest("market_guidance")


def test_malformed_manifest_fails_closed(artifact_root):
    (artifact_root / "manifest.json").write_text("{", encoding="utf-8")

    with pytest.raises(IntelligenceArtifactStoreUnavailable):
        IntelligenceArtifactStore(artifact_root).get_latest("market_guidance")


def test_artifact_path_traversal_is_rejected(artifact_root):
    manifest = _load_manifest(artifact_root)
    _entry_for(manifest, "market_guidance")["path"] = "../outside.json"
    _save_manifest(artifact_root, manifest)

    with pytest.raises(IntelligenceArtifactStoreUnavailable):
        IntelligenceArtifactStore(artifact_root).get_latest("market_guidance")


def test_files_not_referenced_by_manifest_are_ignored(artifact_root):
    rogue = artifact_root / "artifacts" / "market_guidance" / "rogue.json"
    rogue.write_text("{", encoding="utf-8")

    artifact = IntelligenceArtifactStore(artifact_root).get_latest("market_guidance")

    assert artifact is not None
    assert artifact.artifact_id == GUIDANCE_ID


def test_wrong_artifact_type_for_route_returns_404(intelligence_client):
    response = intelligence_client.get(f"/v1/intelligence/guidance/{RESEARCH_ID}")

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "intelligence_artifact_not_found"


def test_latest_resolves_deterministically(artifact_root):
    manifest = _load_manifest(artifact_root)
    entry = _entry_for(manifest, "market_guidance")
    source_artifact = _read_json(_artifact_path(artifact_root, entry))

    newer = copy.deepcopy(source_artifact)
    newer.update(
        {
            "artifact_id": "market_guidance:N:2026-04-18:guidance:newer",
            "weekdate": "2026-04-18",
            "generated_at": "2026-04-19T06:00:00+00:00",
            "published_at": "2026-04-19T06:00:00+00:00",
        }
    )
    newer["content_hash"] = compute_public_artifact_content_hash(newer)
    newer_path = artifact_root / "artifacts" / "market_guidance" / "market_guidance-newer.json"
    _write_json(newer_path, newer)

    manifest["artifacts"].append(
        {
            "artifact_id": newer["artifact_id"],
            "artifact_type": newer["artifact_type"],
            "content_hash": newer["content_hash"],
            "exchange": newer["exchange"],
            "path": "artifacts/market_guidance/market_guidance-newer.json",
            "published_at": newer["published_at"],
            "weekdate": newer["weekdate"],
        }
    )
    manifest["artifact_count"] = len(manifest["artifacts"])
    _save_manifest(artifact_root, manifest)

    store = IntelligenceArtifactStore(artifact_root)

    assert store.get_latest("market_guidance").artifact_id == newer["artifact_id"]
    assert store.get_latest("market_guidance").artifact_id == newer["artifact_id"]


def test_static_published_at_rejected_for_dated_types(artifact_root):
    _rewrite_artifact(artifact_root, "market_guidance", {"published_at": "static"})

    assert IntelligenceArtifactStore(artifact_root).get_latest("market_guidance") is None


def test_static_published_at_accepted_for_discovery_metadata(artifact_root):
    artifact = IntelligenceArtifactStore(artifact_root).get_latest("discovery_metadata")

    assert artifact is not None
    assert artifact.published_at == "static"


def test_canonical_url_rejected_in_vendored_artifacts(artifact_root):
    _rewrite_artifact(
        artifact_root,
        "market_guidance",
        {"canonical_url": "https://api.stocktrends.com/v1/intelligence/guidance/example"},
    )

    assert IntelligenceArtifactStore(artifact_root).get_latest("market_guidance") is None


def test_expired_artifacts_fail_closed(artifact_root):
    _rewrite_artifact(artifact_root, "market_guidance", {"expires_at": "2026-04-13T00:00:00+00:00"})

    store = IntelligenceArtifactStore(
        artifact_root,
        now=datetime(2026, 4, 14, tzinfo=timezone.utc),
    )
    assert store.get_latest("market_guidance") is None


def test_no_agent_repo_imports():
    checked_paths = [
        REPO_ROOT / "services" / "intelligence_artifact_store.py",
        REPO_ROOT / "routers" / "intelligence.py",
    ]
    for path in checked_paths:
        source = path.read_text(encoding="utf-8")
        assert "stocktrends-intelligence-agent" not in source
        assert "app.models.public" not in source
        assert "app.services.public_artifacts" not in source


def test_openapi_includes_intelligence_routes(intelligence_client):
    main.v1.openapi_schema = None

    response = intelligence_client.get("/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    for path in (
        "/intelligence/discovery",
        "/intelligence/guidance/latest",
        "/intelligence/guidance/{artifact_id}",
        "/intelligence/research/latest",
        "/intelligence/research/{artifact_id}",
        "/intelligence/editorial/latest/preview",
    ):
        assert path in paths


@pytest.mark.parametrize(
    "path",
    [
        "/v1/intelligence/discovery",
        "/v1/intelligence/guidance/latest",
        f"/v1/intelligence/guidance/{GUIDANCE_ID}",
        "/v1/intelligence/research/latest",
        f"/v1/intelligence/research/{RESEARCH_ID}",
        "/v1/intelligence/editorial/latest/preview",
    ],
)
def test_public_intelligence_routes_return_200_without_api_key(intelligence_client, path):
    response = intelligence_client.get(path)

    assert response.status_code == 200
    assert response.headers["x-stocktrends-payment-required"] == "false"
    assert response.headers["x-stocktrends-accepted-payment-methods"] == "none"


def test_missing_store_returns_503(monkeypatch):
    _stub_runtime_side_effects(monkeypatch)
    monkeypatch.delenv(STORE_ENV_VAR, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/v1/intelligence/discovery")

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "intelligence_artifact_store_unavailable"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/v1/intelligence/discovery", True),
        ("/v1/intelligence/guidance/latest", True),
        ("/v1/intelligence/guidance/example", True),
        ("/v1/intelligence/guidance/example/extra", False),
        ("/v1/intelligence/research/example", True),
        ("/v1/intelligence/research/example/extra", False),
        ("/v1/intelligence/editorial/latest/preview", True),
        ("/v1/intelligence/editorial/latest", False),
    ],
)
def test_intelligence_public_classification_is_exact(path, expected):
    assert is_public_intelligence_path(path) is expected
