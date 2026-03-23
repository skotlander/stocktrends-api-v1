
#StockTrends STIM Billing Runbook (v1)


##1. Monthly Billing Extraction

### Query: customer totals

```sql
SELECT
    customer_id,
    COUNT(*) AS presented_requests,
    SUM(billed_amount_usd) AS billed_usd
FROM api_request_economics
WHERE pricing_rule_id = 'agent_pay_required'
  AND payment_status = 'presented'
  AND created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
GROUP BY customer_id
ORDER BY billed_usd DESC;
```

?? This is your **invoice source of truth**

---

##2. Customer Drilldown (Ledger)

```sql
SELECT
    created_at,
    request_id,
    api_key_id,
    payment_method,
    payment_network,
    payment_reference,
    billed_amount_usd
FROM api_request_economics
WHERE customer_id = 'CUSTOMER_ID_HERE'
  AND pricing_rule_id = 'agent_pay_required'
  AND payment_status = 'presented'
  AND created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
ORDER BY created_at DESC;
```

 Use this when:

* customer disputes usage
* validating payment references
* auditing agent activity

---

##  3. Failed Payment Diagnostics

```sql
SELECT
    customer_id,
    COUNT(*) AS failed_requests
FROM api_request_economics
WHERE pricing_rule_id = 'agent_pay_required'
  AND payment_status = 'failed_validation'
  AND created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
GROUP BY customer_id
ORDER BY failed_requests DESC;
```

 Use this to identify:

* broken agent integrations
* missing headers
* potential onboarding issues

---

##  4. Hybrid Usage Overview

```sql
SELECT
    pricing_rule_id,
    payment_status,
    COUNT(*) AS request_count,
    SUM(billed_amount_usd) AS billed_usd
FROM api_request_economics
WHERE created_at >= '2026-03-01'
  AND created_at <  '2026-04-01'
GROUP BY pricing_rule_id, payment_status;
```

 This shows:

* subscription usage vs agent-pay usage
* conversion into paid traffic

---

##  5. Interpretation Rules

* `default_subscription`
   covered by plan  not billed per request

* `agent_pay_required + presented`
   billable usage

* `agent_pay_required + failed_validation`
   not billed, but indicates failed payment attempts

---

##  6. Known Edge Cases

* Older rows (pre-Phase 4):

  * may have `NULL customer_id`
  * may have inconsistent `payment_status`
     ignore for billing

* Sandbox users:

  * never appear in billing (blocked upstream)

* Missing API key:

  * not logged in metering (auth layer handles)

---

##  7. Monthly Workflow

1. Run **Monthly Billing Extraction**
2. Review top customers
3. Run **Failed Payment Diagnostics**
4. Spot anomalies
5. Drill into any issues using Ledger query
6. Export results (CSV or internal system)

---

#  What you just achieved

You now have:

* enforcement 
* pricing model 
* clean metering 
* hybrid policy 
* billing pipeline 

This is a **complete monetization loop**

---

