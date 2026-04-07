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

### x402

* pay STC per request
* real-time settlement

---

### MPP

* open session
* spend STC over time
* lower friction for high-frequency agents

---

## Conversion Layer

Payment rails convert:

* USD → STC
* crypto → STC
* token → STC

---

## Design Rules

* No endpoint-specific USD pricing
* No rail-specific pricing logic
* STC is the only pricing reference

---

## Future (STOK)

STOK may:

* reduce STC cost
* provide rebates
* enable premium access tiers

---

## Outcome

A unified pricing system across all rails and platforms
