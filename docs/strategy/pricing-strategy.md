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

All payment rails convert into STC using a **configurable server-side pricing policy**.

### Default Policy (Current)

→ **1 USD = 1 STC**

This is the current operational assumption but **not a permanent peg**.

---

## Important Rules

* STC conversion is determined **server-side**
* External systems (Stripe, crypto) are **inputs**, not accounting truth
* All funding must be derived from **verified payment amounts**
* STC balances must be **immutable after settlement**
* Pricing must always be expressed in STC internally

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

## Payment Rails

### x402 (Per Request)

* pay per request
* stateless
* no account required
* real-time settlement

**Important:**

x402 responses include:

* `amount_usd` → human-readable price
* `amount` → token base units

Example:
