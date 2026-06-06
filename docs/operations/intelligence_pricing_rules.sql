-- Active pricing rules for paid Intelligence Artifact routes.
-- Conservative PR 3 launch pricing:
--   guidance artifacts: 0.25 STC per request
--   research artifacts: 0.50 STC per request
--
-- STC remains the source of truth. Payment rails translate these STC costs;
-- rails must not define independent endpoint prices.
--
-- Deployment note:
--   Before running this ON DUPLICATE KEY UPDATE seed, confirm
--   api_pricing_rules has UNIQUE(rule_name). If rule_name is not unique,
--   use a DELETE-then-INSERT deployment procedure instead.
--
-- Route precedence:
--   Exact /latest routes use priority=10.
--   By-id template routes use priority=20 so exact routes sort first if
--   a deployment loader applies priority-based endpoint matching.

INSERT INTO api_pricing_rules (
    rule_name,
    endpoint_pattern,
    endpoint_family,
    api_version,
    priority,
    access_type,
    cost_per_request,
    cost_unit,
    requires_subscription,
    requires_payment,
    is_active
) VALUES
    (
        'intelligence_guidance_latest',
        '/v1/intelligence/guidance/latest',
        'intelligence',
        'v1',
        10,
        'paid',
        0.250000,
        'STC',
        0,
        1,
        1
    ),
    (
        'intelligence_guidance_by_id',
        '/v1/intelligence/guidance/{artifact_id}',
        'intelligence',
        'v1',
        20,
        'paid',
        0.250000,
        'STC',
        0,
        1,
        1
    ),
    (
        'intelligence_research_latest',
        '/v1/intelligence/research/latest',
        'intelligence',
        'v1',
        10,
        'paid',
        0.500000,
        'STC',
        0,
        1,
        1
    ),
    (
        'intelligence_research_by_id',
        '/v1/intelligence/research/{artifact_id}',
        'intelligence',
        'v1',
        20,
        'paid',
        0.500000,
        'STC',
        0,
        1,
        1
    )
ON DUPLICATE KEY UPDATE
    endpoint_pattern = VALUES(endpoint_pattern),
    endpoint_family = VALUES(endpoint_family),
    api_version = VALUES(api_version),
    priority = VALUES(priority),
    access_type = VALUES(access_type),
    cost_per_request = VALUES(cost_per_request),
    cost_unit = VALUES(cost_unit),
    requires_subscription = VALUES(requires_subscription),
    requires_payment = VALUES(requires_payment),
    is_active = VALUES(is_active);
