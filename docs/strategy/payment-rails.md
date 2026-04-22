# Payment Rails Strategy

## Objective

Support multiple payment mechanisms without coupling pricing logic.

All payment rails must consume a common pricing unit:

→ **STC (Stock Trends Credits)**

The payment rail determines **how value is transferred**, not **what is charged**.

---

## Production Rails

### 1. Subscription

* API key based
* prepaid STC allocation
* no per-request payment challenge
* active production rail

---

### 2. x402

* HTTP-native micropayments
* per-request payment model
* agent-friendly
* active production rail

---

### 3. MPP

* session-based payments
* optimized for repeated/high-frequency usage
* lower overhead than per-request challenge flows
* active production rail

MPP must be treated as a first-class payment rail, not a future placeholder.

It may use a different verification and settlement model from x402 and must NOT be forced into x402 assumptions.

---

## Future Rail / Incentive Layer

### 4. STOK

* token-based incentives
* optional discount layer
* future integration layer

STOK does NOT replace STC pricing.
STOK modifies access economics while all pricing still resolves through STC.

---

## Design Rule

> All rails must implement a common conceptual interface:

* authorize()
* settle()
* report()

The exact implementation may differ by rail, but all rails must remain:

* modular
* observable
* interchangeable at the pricing boundary

---

## Pricing Boundary

All rails must consume pricing resolved in STC.

### Rules

* pricing must be resolved before rail enforcement
* rails must not define endpoint pricing
* rails must not override pricing policy
* rails must not introduce rail-specific pricing logic

---

## Rail Profiles

### Subscription Profile

* account-based entitlement
* STC deducted from subscription balance
* no explicit payment headers required

---

### x402 Profile

* per-request explicit payment
* challenge / verify flow
* rail-specific amount derived from STC
* suitable for anonymous or agent-native request payment

---

### MPP Profile

* session-based balance model
* STC deducted from funded / reserved session value
* may not use x402-style request challenge behavior
* suitable for repeated requests where session economics reduce friction

### MPP Design Constraints

* do not assume request-by-request settlement
* do not assume x402 headers or x402 verification semantics
* maintain session consistency
* log session usage clearly

---

## Logging Requirements Across Rails

All rails must produce consistent metering context.

Minimum expected logged context:

* pricing_rule_id
* stc_cost
* payment_rail
* payment_status
* billed_amount_usd
* request_id

Additional rail-specific context:

### x402
* payment_method
* payment_network
* payment_token
* payment_reference

### MPP
* session_id
* funded / reserved / captured context where applicable
* session-linked settlement state

---

## Key Rule

> Pricing must NEVER depend on payment rail.

This applies equally to:

* subscription
* x402
* MPP
* future STOK integrations

---

## Strategic Outcome

Payment innovation without architectural disruption.

The system supports:

* prepaid account access
* per-request agent payments
* session-based agent payments
* future token incentives

...while preserving a unified STC pricing engine.