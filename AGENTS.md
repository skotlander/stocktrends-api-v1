# AGENTS.md — Stock Trends API

## Purpose

This repository powers the Stock Trends API and agent monetization system.

Primary goals:
- maintain a stable FastAPI production service
- support multiple payment rails for API access
- ensure accurate request logging and metering
- enable agent-native monetization (per-request payments)
- preserve backward compatibility for developers

---

## Core Principles

1. **Production stability first**
2. **Payment correctness is critical**
3. **Logging and metering are first-class**
4. **Support multiple payment rails (not just one)**
5. **Make minimal, targeted changes only**

---

## Payment Architecture (CRITICAL)

This API is designed to support **multiple payment rails** for agent and developer traffic.

### Active / Implemented
- **Subscription (Stripe)** → account-based access
- **x402** → per-request agent payments (primary current rail)

### Planned / Supported by Design
- **MPP (Machine Payments Protocol)** → machine-to-machine payments

---

## Payment Model (IMPORTANT CONCEPT)

Payment handling is intentionally **decomposed into layers**:

1. **Access Policy**
   - Is this route free, subscription-gated, or pay-per-request?

2. **Payment Requirement**
   - Does this request require payment?

3. **Payment Rail**
   - subscription | x402 | mpp | none

4. **Verification**
   - Was payment successfully verified?

5. **Metering / Billing**
   - What should be recorded and billed?

---

## Critical Rule

⚠️ **Do NOT couple the system to a single payment rail (e.g., x402).**

All payment-related logic should remain:
- rail-aware
- extensible
- clearly separated

---

## Payment Rails Guidance

### x402 (Current Focus)
- Used for per-request agent payments
- Requires challenge/verify flow
- Must remain fully functional and verifiable

### MPP (Future Integration)
- Will support machine-native payments
- May use different request/verification semantics
- Must be integratable without rewriting core API logic

---

## Implementation Rules for Payment Code

When modifying payment logic:

### DO:
- identify where the following are handled:
  - pricing rule selection
  - payment requirement decision
  - payment rail classification
  - verification logic
  - metering/logging
- keep these concerns **separate**
- ensure logging captures the payment rail explicitly

### DO NOT:
- hardcode logic assuming only x402 exists
- mix payment verification with routing logic
- collapse payment classification into boolean flags only
- remove fallback behavior (e.g., subscription vs pay-per-request)

---

## Logging and Metering (FIRST-CLASS)

All API requests must be logged with sufficient detail to support:
- billing
- analytics
- debugging
- multi-rail support

### Required Concepts

Each request should clearly capture:

- pricing_rule_id
- payment_required (true/false)
- payment_rail (subscription | x402 | mpp | none)
- payment_status (not_required | presented | verified | failed)
- agent_id or customer_id
- request_count
- billed_amount

---

## Logging Rules

- Logging must occur on:
  - success paths
  - failure paths
  - verification failures
- Logging must reflect **actual enforcement behavior**, not assumptions
- Avoid duplicate or missing records
- Do not remove logging to reduce noise without preserving signal

---

## API Architecture

Expected stack:
- FastAPI backend
- routes under `/v1/`
- middleware for:
  - auth
  - pricing
  - payment enforcement
  - logging/metering

Deployment:
- AWS EC2 (Ubuntu)
- nginx reverse proxy
- systemd service

---

## API Behavior Rules

When modifying endpoints:

- preserve response schema unless required
- preserve OpenAPI/docs functionality
- ensure headers reflect actual behavior

Critical endpoints:
- `/v1/`
- `/v1/docs`
- `/v1/openapi.json`

---

## Payment Headers

Headers must accurately reflect enforcement:

Examples:
- x-stocktrends-pricing-rule
- x-stocktrends-payment-required
- x-stocktrends-accepted-payment-methods

Rules:
- headers must match actual behavior
- do not mark endpoints payable if they are not enforced
- do not omit payment requirement if enforced

---

## x402-Specific Guidance

If modifying x402:

- trace:
  - challenge generation
  - verify payload construction
  - request headers
  - external verifier interaction
- ensure:
  - Base mainnet assumptions are correct
  - token assumptions (e.g., USDC) are correct
  - error handling is explicit and logged

---

## MPP-Readiness Guidance

Even if MPP is not yet active:

- ensure system can support:
  - alternate verification flows
  - different payment payload formats
  - different settlement models

- do not assume:
  - challenge/verify structure is universal
  - same headers will apply

---

## Debugging Strategy

Always identify failure layer first:

1. nginx
2. service startup
3. FastAPI app startup
4. route logic
5. middleware
6. payment verification
7. logging/metering

Fix the **lowest responsible layer only**

---

## Infrastructure-Sensitive Areas

Be careful when modifying:

- main.py (startup)
- middleware
- payment enforcement logic
- logging/metering writes
- config/env loading
- static file handling
- OpenAPI/docs generation

---

## Validation Checklist

Before completing any task:

### API
- app starts cleanly
- `/v1/` responds
- `/v1/docs` loads
- `/v1/openapi.json` loads

### Payment
- free routes behave correctly
- subscription routes behave correctly
- x402 routes challenge/verify correctly

### Logging
- request is logged
- payment_rail is correct
- payment_status is correct
- pricing_rule_id is correct

### Safety
- no secrets exposed
- no debug bypasses
- no regressions

---

## Output Requirements

For every task:

1. diagnosis
2. files changed
3. reason for each change
4. validation performed
5. remaining risks

---

## DO NOT

- break payment enforcement
- remove logging
- hardcode single payment rail assumptions
- introduce breaking API changes
- refactor unrelated code

---

## Definition of Done

A task is complete only when:

- issue is resolved at correct layer
- payment logic remains correct
- logging/metering remains accurate
- system remains multi-rail compatible
- validation steps are documented