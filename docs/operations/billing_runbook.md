# Stock Trends API Billing Runbook (v2)

## Purpose

This runbook supports:

* billing
* reconciliation
* payment diagnostics
* multi-rail auditability

The system is STC-priced and multi-rail in production.

Production rails currently include:

* subscription
* x402
* MPP

---

## Core Rule

Billing and diagnostics must reflect:

* the pricing rule applied
* the rail actually used
* the payment status actually recorded

Do NOT assume all paid usage is x402.

---

## 1. Monthly Billing Extraction

### Query: customer totals

```sql
SELECT
    customer_id,
    payment_rail,
    COUNT(*) AS request_count,
    SUM(billed_amount_usd) AS billed_usd
FROM api_request_economics
WHERE created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
  AND payment_status IN ('presented', 'covered')
GROUP BY customer_id, payment_rail
ORDER BY billed_usd DESC;
```

This is the high-level billing and usage summary by customer and rail.

Use it to distinguish:

* subscription-covered usage
* x402 metered usage
* MPP session usage

---

## 2. x402 Customer Drilldown (Ledger)

```sql
SELECT
    created_at,
    request_id,
    customer_id,
    api_key_id,
    pricing_rule_id,
    stc_cost,
    payment_rail,
    payment_status,
    payment_method,
    payment_network,
    payment_token,
    payment_reference,
    billed_amount_usd
FROM api_request_economics
WHERE customer_id = 'CUSTOMER_ID_HERE'
  AND payment_rail = 'x402'
  AND created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
ORDER BY created_at DESC;
```

Use this when:

* customer disputes x402 usage
* validating payment references
* auditing per-request agent payment activity

---

## 3. MPP Customer Drilldown (Session Ledger)

```sql
SELECT
    created_at,
    request_id,
    customer_id,
    api_key_id,
    pricing_rule_id,
    stc_cost,
    payment_rail,
    payment_status,
    session_id,
    billed_amount_usd
FROM api_request_economics
WHERE customer_id = 'CUSTOMER_ID_HERE'
  AND payment_rail = 'mpp'
  AND created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
ORDER BY created_at DESC;
```

Use this when:

* auditing MPP session-backed usage
* reconciling session activity against request activity
* validating correct session linkage

---

## 4. Failed Payment Diagnostics

```sql
SELECT
    payment_rail,
    customer_id,
    COUNT(*) AS failed_requests
FROM api_request_economics
WHERE payment_status IN ('failed_validation', 'rejected')
  AND created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
GROUP BY payment_rail, customer_id
ORDER BY failed_requests DESC;
```

Use this to identify:

* broken x402 integrations
* invalid MPP session usage
* onboarding issues
* enforcement problems by rail

---

## 5. Hybrid Usage Overview

```sql
SELECT
    pricing_rule_id,
    payment_rail,
    payment_status,
    COUNT(*) AS request_count,
    SUM(billed_amount_usd) AS billed_usd
FROM api_request_economics
WHERE created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
GROUP BY pricing_rule_id, payment_rail, payment_status
ORDER BY pricing_rule_id, payment_rail, payment_status;
```

This shows:

* subscription vs x402 vs MPP usage
* success vs failure rates
* monetized traffic distribution

---

## 6. STC Usage by Rail

```sql
SELECT
    payment_rail,
    COUNT(*) AS request_count,
    SUM(stc_cost) AS total_stc
FROM api_request_economics
WHERE created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
  AND payment_status IN ('presented', 'covered')
GROUP BY payment_rail
ORDER BY total_stc DESC;
```

Use this to verify:

* STC consumption distribution
* pricing consistency across rails
* anomalies in usage patterns

---

## 7. MPP Session Consistency Check

```sql
SELECT
    session_id,
    COUNT(*) AS request_count,
    SUM(stc_cost) AS total_stc,
    SUM(billed_amount_usd) AS billed_usd
FROM api_request_economics
WHERE payment_rail = 'mpp'
  AND created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
GROUP BY session_id
ORDER BY billed_usd DESC;
```

Use this to:

* review high-usage sessions
* identify abnormal sessions
* support reconciliation with session-level accounting

---

## 8. Interpretation Rules

### Subscription-covered usage

* `payment_rail = subscription`
* `payment_status = covered`

Meaning:

* usage covered by plan
* not billed per request

---

### x402 metered usage

* `payment_rail = x402`
* `payment_status = presented`

Meaning:

* per-request payment processed
* payment metadata should be populated

---

### x402 failed usage

* `payment_rail = x402`
* `payment_status = failed_validation` or `rejected`

Meaning:

* not billed
* indicates broken agent payment flow

---

### MPP session usage

* `payment_rail = mpp`
* `payment_status = presented`
* `session_id` present

Meaning:

* request tied to session balance
* should reconcile to session accounting

---

### MPP failed usage

* `payment_rail = mpp`
* `payment_status = failed_validation` or `rejected`

Meaning:

* invalid session state or linkage
* not billable

---

## 9. Known Edge Cases

* older rows may have incomplete metadata
* legacy rows may have inconsistent status fields
* sandbox traffic may be excluded
* missing API key requests may not be logged

Use recent data for billing accuracy.

---

## 10. Monthly Workflow

1. Run Monthly Billing Extraction
2. Review top customers by rail
3. Run Failed Payment Diagnostics
4. Review Hybrid Usage Overview
5. Review STC Usage by Rail
6. Drill into x402 issues if needed
7. Drill into MPP sessions if needed
8. Export validated results

---

## 11. Key Audit Questions

For any issue:

* What pricing rule was applied?
* What rail was used?
* What was the payment status?
* Was STC recorded correctly?
* For x402: is payment metadata present?
* For MPP: is session_id valid?
* Does billed USD match request activity?

---

## Final Principle

This runbook supports a complete monetization loop across active rails:

* unified STC pricing
* rail-specific enforcement
* consistent logging
* auditable billing
