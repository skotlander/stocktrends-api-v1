from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from urllib import error, request


logger = logging.getLogger("stocktrends_api.payment_policy")

_DEFAULT_CONFIG_TTL_SECONDS = 30
_DEFAULT_FETCH_TIMEOUT_SECONDS = 2.0

_cache_lock = threading.Lock()
_cached_config: "RuntimePaymentPolicyConfig | None" = None
_cached_at: float = 0.0
_last_known_good_config: "RuntimePaymentPolicyConfig | None" = None
_last_reported_fallback_reason: str | None = None


def _parse_csv_env(env_name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(env_name, default)
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass
class EndpointPaymentPolicy:
    endpoint_id: str
    path_pattern: str
    method: str
    allowed_rails: tuple[str, ...]
    pricing_rule_id: str | None = None


@dataclass
class EffectiveEndpointPaymentPolicy:
    source: str
    allowed_rails: tuple[str, ...]
    machine_payment_rails: tuple[str, ...]
    allows_subscription: bool


@dataclass
class RuntimePaymentPolicyConfig:
    source: str
    version: str | None
    ttl_seconds: int
    fetched_at: float | None
    environment: str | None
    enabled_environment_rails: tuple[str, ...]
    pricing_rule_ids: tuple[str, ...]
    endpoint_payment_policies: tuple[EndpointPaymentPolicy, ...]
    free_metered_paths: tuple[str, ...]
    agent_pay_path_prefixes: tuple[str, ...]
    agent_pay_auth_bypass_methods: tuple[str, ...]
    enforcement_path_prefixes: tuple[str, ...]
    accepted_payment_methods_agent_required_default: str
    accepted_payment_methods_agent_required_by_method: dict[str, str] = field(default_factory=dict)
    accepted_payment_methods_agent_optional: str = "subscription,mpp,x402,crypto"
    accepted_payment_methods_subscription: str = "subscription"
    accepted_payment_methods_default: str = "none"


def _normalize_string_list(value, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
        return tuple(item for item in items if item) or default
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            if item is None:
                continue
            normalized = str(item).strip()
            if normalized:
                items.append(normalized)
        return tuple(items) or default
    return default


def _normalize_string_map(value, *, default: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        return dict(default)

    normalized: dict[str, str] = {}
    for key, map_value in value.items():
        normalized_key = str(key).strip().lower()
        normalized_value = str(map_value).strip() if map_value is not None else ""
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value

    return normalized or dict(default)


def _normalize_int(value, *, default: int) -> int:
    try:
        normalized = int(value)
        return normalized if normalized > 0 else default
    except (TypeError, ValueError):
        return default


def _default_policy_config() -> RuntimePaymentPolicyConfig:
    return RuntimePaymentPolicyConfig(
        source="defaults",
        version=None,
        ttl_seconds=_normalize_int(
            os.getenv("PAYMENT_POLICY_CONFIG_TTL_SECONDS"),
            default=_DEFAULT_CONFIG_TTL_SECONDS,
        ),
        fetched_at=None,
        environment=None,
        enabled_environment_rails=(),
        pricing_rule_ids=(),
        endpoint_payment_policies=(),
        free_metered_paths=(
            "/v1/ai/context",
            "/v1/breadth/sector/latest",
        ),
        agent_pay_path_prefixes=(
            "/v1/stim",
            "/v1/agent/screener",
        ),
        agent_pay_auth_bypass_methods=(
            "mpp",
            "x402",
        ),
        enforcement_path_prefixes=_parse_csv_env(
            "AGENT_PAY_ENFORCE_PATH_PREFIXES",
            "/v1/stim",
        ),
        accepted_payment_methods_agent_required_default="mpp,x402,crypto",
        accepted_payment_methods_agent_required_by_method={
            "x402": "x402",
            "mpp": "mpp",
            "crypto": "crypto",
        },
        accepted_payment_methods_agent_optional="subscription,mpp,x402,crypto",
        accepted_payment_methods_subscription="subscription",
        accepted_payment_methods_default="none",
    )


def _normalize_enabled_rails(value) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()

    rails: list[str] = []
    for rail_name, enabled in value.items():
        normalized_name = str(rail_name).strip().lower()
        if normalized_name and bool(enabled):
            rails.append(normalized_name)

    return tuple(rails)


def _normalize_pricing_rule_ids(value) -> tuple[str, ...]:
    if isinstance(value, dict):
        value = list(value.values()) or list(value.keys())

    if not isinstance(value, (list, tuple)):
        return ()

    pricing_rule_ids: list[str] = []
    for item in value:
        if isinstance(item, dict):
            candidate = item.get("rule_name") or item.get("id") or item.get("name")
        else:
            candidate = item

        normalized = str(candidate).strip() if candidate is not None else ""
        if normalized:
            pricing_rule_ids.append(normalized)

    return tuple(pricing_rule_ids)


def _normalize_endpoint_payment_policies(value) -> tuple[EndpointPaymentPolicy, ...]:
    if isinstance(value, dict):
        value = list(value.values())

    if not isinstance(value, (list, tuple)):
        return ()

    policies: list[EndpointPaymentPolicy] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        path_pattern = str(item.get("path_pattern") or "").strip()
        method = str(item.get("method") or "").strip().upper()
        if not path_pattern or not method:
            continue

        allowed_rails = _normalize_string_list(item.get("allowed_rails"), default=())
        endpoint_id = str(
            item.get("endpoint_id") or item.get("endpoint_key") or item.get("id") or f"{method}:{path_pattern}"
        ).strip()
        pricing_rule_id = str(item.get("pricing_rule_id") or "").strip() or None

        policies.append(
            EndpointPaymentPolicy(
                endpoint_id=endpoint_id,
                path_pattern=path_pattern,
                method=method,
                allowed_rails=tuple(rail.lower() for rail in allowed_rails),
                pricing_rule_id=pricing_rule_id,
            )
        )

    return tuple(policies)


def _resolve_config_url() -> str | None:
    explicit_url = (os.getenv("PAYMENT_POLICY_CONFIG_URL") or "").strip()
    if explicit_url:
        return explicit_url

    control_plane_base = (os.getenv("CONTROL_PLANE_BASE_URL") or "").strip()
    if control_plane_base:
        return f"{control_plane_base.rstrip('/')}/v1/runtime/payment-config"

    return None


def _extract_policy_section(payload: dict) -> dict:
    for key in ("payment_policy", "payment_config", "config", "data"):
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            return candidate
    return payload


def _lookup_exact_endpoint_policy(
    config: RuntimePaymentPolicyConfig,
    path: str,
    method: str | None,
) -> EndpointPaymentPolicy | None:
    if not method:
        return None

    normalized_method = method.strip().upper()
    for policy in config.endpoint_payment_policies:
        if policy.method == normalized_method and policy.path_pattern == path:
            return policy
    return None


def _derive_allowed_rails_for_endpoint(
    config: RuntimePaymentPolicyConfig,
    path: str,
    method: str | None,
) -> tuple[str, ...] | None:
    endpoint_policy = _lookup_exact_endpoint_policy(config, path, method)
    if endpoint_policy is None:
        return None

    if not config.enabled_environment_rails:
        return endpoint_policy.allowed_rails

    enabled = set(config.enabled_environment_rails)
    return tuple(rail for rail in endpoint_policy.allowed_rails if rail in enabled)


def _build_effective_endpoint_policy(
    path: str,
    method: str | None,
) -> EffectiveEndpointPaymentPolicy | None:
    config = get_runtime_payment_policy_config()
    allowed_rails = _derive_allowed_rails_for_endpoint(config, path, method)
    if allowed_rails is None:
        return None

    machine_payment_rails = tuple(
        rail for rail in allowed_rails if rail in {"x402", "mpp", "crypto"}
    )
    return EffectiveEndpointPaymentPolicy(
        source="control_plane_exact",
        allowed_rails=allowed_rails,
        machine_payment_rails=machine_payment_rails,
        allows_subscription="subscription" in allowed_rails,
    )


def _parse_config_payload(payload: dict) -> RuntimePaymentPolicyConfig:
    if not isinstance(payload, dict):
        raise ValueError("Payment policy config payload must be an object.")

    defaults = _default_policy_config()
    policy = _extract_policy_section(payload)
    accepted_methods = policy.get("accepted_payment_methods")
    if not isinstance(accepted_methods, dict):
        accepted_methods = {}
    endpoint_payment_policies = _normalize_endpoint_payment_policies(
        policy.get("endpoint_payment_policies", payload.get("endpoint_payment_policies"))
    )

    agent_required = accepted_methods.get("agent_pay_required")
    if isinstance(agent_required, dict):
        agent_required_default = str(agent_required.get("default") or "").strip() or defaults.accepted_payment_methods_agent_required_default
        agent_required_by_method = _normalize_string_map(
            agent_required.get("by_method"),
            default=defaults.accepted_payment_methods_agent_required_by_method,
        )
    else:
        agent_required_default = str(agent_required or "").strip() or defaults.accepted_payment_methods_agent_required_default
        agent_required_by_method = dict(defaults.accepted_payment_methods_agent_required_by_method)

    return RuntimePaymentPolicyConfig(
        source="control_plane",
        version=str(policy.get("version") or payload.get("version") or "").strip() or None,
        ttl_seconds=_normalize_int(
            policy.get("ttl_seconds", payload.get("ttl_seconds")),
            default=defaults.ttl_seconds,
        ),
        fetched_at=time.time(),
        environment=str(policy.get("environment") or payload.get("environment") or "").strip() or None,
        enabled_environment_rails=_normalize_enabled_rails(
            policy.get("environment_rail_enablement", payload.get("environment_rail_enablement"))
        ),
        pricing_rule_ids=_normalize_pricing_rule_ids(
            policy.get("pricing_rules", payload.get("pricing_rules"))
        ),
        endpoint_payment_policies=endpoint_payment_policies,
        free_metered_paths=_normalize_string_list(
            policy.get("free_metered_paths"),
            default=defaults.free_metered_paths,
        ),
        agent_pay_path_prefixes=_normalize_string_list(
            policy.get("agent_pay_path_prefixes"),
            default=defaults.agent_pay_path_prefixes,
        ),
        agent_pay_auth_bypass_methods=_normalize_string_list(
            policy.get("agent_pay_auth_bypass_methods"),
            default=defaults.agent_pay_auth_bypass_methods,
        ),
        enforcement_path_prefixes=_normalize_string_list(
            policy.get("enforcement_path_prefixes"),
            default=defaults.enforcement_path_prefixes,
        ),
        accepted_payment_methods_agent_required_default=agent_required_default,
        accepted_payment_methods_agent_required_by_method=agent_required_by_method,
        accepted_payment_methods_agent_optional=str(
            accepted_methods.get("agent_pay_optional") or defaults.accepted_payment_methods_agent_optional
        ).strip(),
        accepted_payment_methods_subscription=str(
            accepted_methods.get("subscription_v1") or defaults.accepted_payment_methods_subscription
        ).strip(),
        accepted_payment_methods_default=str(
            accepted_methods.get("default") or defaults.accepted_payment_methods_default
        ).strip(),
    )


def _fetch_runtime_payment_policy_config() -> RuntimePaymentPolicyConfig:
    config_url = _resolve_config_url()
    if not config_url:
        raise RuntimeError("No payment policy config URL is configured.")

    timeout_seconds = _DEFAULT_FETCH_TIMEOUT_SECONDS
    timeout_raw = os.getenv("PAYMENT_POLICY_CONFIG_TIMEOUT_SECONDS")
    if timeout_raw:
        try:
            timeout_seconds = max(float(timeout_raw), 0.1)
        except ValueError:
            timeout_seconds = _DEFAULT_FETCH_TIMEOUT_SECONDS

    with request.urlopen(config_url, timeout=timeout_seconds) as response:
        payload = json.load(response)

    return _parse_config_payload(payload)


def get_runtime_payment_policy_config(force_refresh: bool = False) -> RuntimePaymentPolicyConfig:
    global _cached_at, _cached_config, _last_known_good_config, _last_reported_fallback_reason

    with _cache_lock:
        if not force_refresh and _cached_config is not None:
            age_seconds = time.time() - _cached_at
            if age_seconds < _cached_config.ttl_seconds:
                return _cached_config

        try:
            fetched_config = _fetch_runtime_payment_policy_config()
        except RuntimeError as exc:
            fallback = _last_known_good_config or _cached_config or _default_policy_config()
            _cached_config = fallback
            _cached_at = time.time()
            if _last_reported_fallback_reason != "unconfigured":
                logger.info("Payment policy config not configured; using %s snapshot.", fallback.source)
                _last_reported_fallback_reason = "unconfigured"
            return fallback
        except (ValueError, error.URLError, error.HTTPError, OSError, json.JSONDecodeError) as exc:
            fallback = _last_known_good_config or _cached_config or _default_policy_config()
            if _last_reported_fallback_reason != "fetch_failed":
                logger.warning(
                    "Payment policy config fetch failed; using %s snapshot: %s",
                    fallback.source,
                    exc,
                )
                _last_reported_fallback_reason = "fetch_failed"
            _cached_config = fallback
            _cached_at = time.time()
            return fallback

        _cached_config = fetched_config
        _cached_at = time.time()
        _last_known_good_config = fetched_config
        _last_reported_fallback_reason = None
        return fetched_config


def is_free_metered_path(path: str) -> bool:
    config = get_runtime_payment_policy_config()
    return path in config.free_metered_paths


def get_effective_endpoint_payment_policy(
    path: str,
    method: str | None = None,
) -> EffectiveEndpointPaymentPolicy | None:
    return _build_effective_endpoint_policy(path, method)


def get_allowed_payment_rails_for_path(
    path: str,
    method: str | None = None,
) -> tuple[str, ...] | None:
    effective_policy = get_effective_endpoint_payment_policy(path, method)
    if effective_policy is None:
        return None
    return effective_policy.allowed_rails


def is_agent_pay_route(path: str, method: str | None = None) -> bool:
    effective_policy = get_effective_endpoint_payment_policy(path, method)
    if effective_policy is not None:
        return bool(effective_policy.machine_payment_rails)

    config = get_runtime_payment_policy_config()
    return any(path.startswith(prefix) for prefix in config.agent_pay_path_prefixes)


def get_agent_pay_auth_bypass_methods(path: str, method: str | None = None) -> tuple[str, ...]:
    effective_policy = get_effective_endpoint_payment_policy(path, method)
    if effective_policy is not None:
        return effective_policy.machine_payment_rails

    if not is_agent_pay_route(path, method):
        return ()

    config = get_runtime_payment_policy_config()
    return tuple(method.lower() for method in config.agent_pay_auth_bypass_methods)


def is_agent_pay_auth_candidate(
    path: str,
    payment_method: str | None,
    agent_id: str | None,
    *,
    method: str | None = None,
) -> bool:
    if not agent_id:
        return False

    normalized_method = (payment_method or "").strip().lower()
    if not normalized_method:
        return False

    return normalized_method in set(get_agent_pay_auth_bypass_methods(path, method))


def is_agent_pay_enforcement_path(path: str, method: str | None = None) -> bool:
    effective_policy = get_effective_endpoint_payment_policy(path, method)
    if effective_policy is not None:
        return bool(effective_policy.machine_payment_rails)

    config = get_runtime_payment_policy_config()
    return any(path.startswith(prefix) for prefix in config.enforcement_path_prefixes)


def get_accepted_payment_methods_for_path(
    path: str,
    pricing_rule_id: str | None,
    *,
    method: str | None = None,
    enforced_payment_method: str | None = None,
) -> str:
    config = get_runtime_payment_policy_config()
    normalized_method = (enforced_payment_method or "").strip().lower()
    endpoint_allowed_rails = get_allowed_payment_rails_for_path(path, method)

    if endpoint_allowed_rails is not None:
        return ",".join(endpoint_allowed_rails) if endpoint_allowed_rails else config.accepted_payment_methods_default

    if pricing_rule_id == "agent_pay_required":
        if normalized_method:
            return config.accepted_payment_methods_agent_required_by_method.get(
                normalized_method,
                config.accepted_payment_methods_agent_required_default,
            )
        return config.accepted_payment_methods_agent_required_default

    if any(path.startswith(prefix) for prefix in config.agent_pay_path_prefixes):
        return config.accepted_payment_methods_agent_optional

    if path.startswith("/v1/"):
        return config.accepted_payment_methods_subscription

    return config.accepted_payment_methods_default
