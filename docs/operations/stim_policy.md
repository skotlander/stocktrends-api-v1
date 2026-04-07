# STIM Access Policy (v2 — STC Aligned)

## Overview

The `/v1/stim*` endpoints operate under a **hybrid access model**:

* subscription-based access
* agent-pay (per-request)
* future session-based payments (MPP)

All access is governed by:

→ **STC (Stock Trends Credits)**

---

## Access Modes

### 1. Subscription Access (STC Covered)

Request:

* no payment headers
* valid API key with active subscription

Behavior:

* request allowed
* STC deducted from subscription allocation
* no per-request payment required

Logging:

* `pricing_rule_id = stc_subscription_covered`
* `payment_status = covered`
* `payment_rail = subscription`

---

### 2. Agent Pay (x402 — STC Metered)

Request:

* includes valid payment headers

Behavior:

* treated as explicit per-request payment
* STC cost covered via x402 payment

Logging:

* `pricing_rule_id = stc_metered`
* `payment_status = presented`
* `payment_rail = x402`

---

### 3. Invalid or Incomplete Payment

Request:

* payment headers present but invalid or incomplete

Behavior:

* request rejected
* may return `402 Payment Required`

Logging:

* `pricing_rule_id = stc_metered`
* `payment_status = failed_validation`
* `payment_rail = x402`

---

### 4. MPP Session Access (Future)

Request:

* associated with active payment session

Behavior:

* STC consumed within session
* no per-request payment overhead

Logging:

* `pricing_rule_id = stc_session`
* `payment_status = presented`
* `payment_rail = mpp`

---

### 5. Sandbox Plan

Behavior:

* access denied at auth layer
* no metering recorded

---

### 6. Missing API Key

Behavior:

* denied at authentication layer
* no metering recorded

---

## Key Principles

### STC is the Source of Truth

All requests must resolve to:

→ STC consumption

---

### Payment Rails Are Abstracted

* pricing does not depend on payment method
* all rails convert value → STC

---

### Explicit Agent Intent

* presence of payment headers = explicit agent-pay intent
* overrides subscription path

---

## Response Behavior

| Scenario           | Outcome              |
| ------------------ | -------------------- |
| Valid subscription | 200 OK               |
| Valid x402 payment | 200 OK               |
| Invalid payment    | 402 Payment Required |
| No auth            | 401/403              |

---

## Logging Requirements

Every valid request must log:

* `stc_cost`
* `pricing_rule_id`
* `payment_rail`
* `payment_status`

---

## Strategic Outcome

This policy enables:

* hybrid monetization
* agent-native payments
* seamless expansion to new payment rails

---

## Key Rule

Every request must be either:

* STC covered
* STC paid
* or rejected
