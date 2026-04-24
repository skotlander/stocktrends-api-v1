# Pricing Strategy (STC Model)

## Objective

Unify all pricing across:

* subscription plans
* per-request payments (x402)
* session payments (MPP)
* future token models (STOK)

---

## Core Unit

→ **1 STC = unit of API consumption**

STC (Stock Trends Credit) is an **internal accounting unit**, not a currency.

---

## STC Valuation

STC does **not** have a fixed intrinsic USD value.

All payment rails convert into STC using a **configurable pricing policy**.

### Default Policy

→ **1 USD = 1 STC**

This is the current operational assumption but **not a permanent peg**.

### Important Rules

* STC conversion is determined **server-side**
* Stripe or external metadata is used for **correlation only**, not accounting truth
* All funding must be derived from verified payment amounts

### Future Flexibility

STC conversion may vary based on:

* pricing updates
* volume tiers
* promotional incentives
* STOK token incentives
* enterprise agreements

---

## Pricing Model

### Per Request

| Endpoint      | STC |
| ------------- | --- |
| /stim/latest  | 1   |
| /stim/history | 5   |

---

### Subscription Plans

| Plan       | Monthly STC |
| ---------- | ----------- |
| Basic      | 1,000       |
| Pro        | 10,000      |
| Enterprise | custom      |

---

### x402 (Per Request)

* pay STC per request
* real-time settlement
* suitable for stateless agent interactions

---

### MPP (Session-Based)

* open session
* spend STC over time
* lower friction for high-frequency agents
* funded via external payment rails (e.g., Stripe)

---

## Conversion Layer

All payment rails convert into STC:

* USD → STC (Stripe)
* crypto → STC (x402 / future funding flows)
* token → STC (STOK, future)

---

## Design Rules

* No endpoint-specific USD pricing
* No rail-specific pricing logic
* STC is the **only pricing reference**
* Payment systems must not bypass STC accounting
* External systems (Stripe, crypto) are **inputs**, not sources of truth

---

## Future (STOK)

STOK is a **separate economic layer**, not a replacement for STC.

STOK may:

* reduce STC cost (discounts)
* provide rebates
* enable premium access tiers
* incentivize long-term participation

---

## Outcome

A unified pricing system across all rails and platforms, where:

* STC = stable consumption unit
* payment rails = funding mechanisms
* STOK = value and incentive layer