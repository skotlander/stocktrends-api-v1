# Stock Trends API Strategy

## Purpose

The Stock Trends API is evolving into:

* a **multi-rail payment system**
* a **unified pricing engine (STC)**
* an **agent-native monetization platform**
* a **foundation for AI agents, game mechanics, and tokenomics**

---

## Core Principle

All API access is priced in:

→ **STC (Stock Trends Credits)**

Everything else is a **payment rail abstraction**

---

## System Layers

### 1. Pricing Layer (STC)

* Defines cost per endpoint
* Independent of payment method
* Example:

| Endpoint      | STC Cost |
| ------------- | -------- |
| /stim/latest  | 1 STC    |
| /stim/history | 5 STC    |

---

### 2. Payment Layer (Multi-Rail)

Payment methods convert value → STC:

* Subscription → prepaid STC allowance
* x402 → per-request STC payment
* MPP → session-based STC streaming
* STOK → discount or staking-based STC

---

### 3. Enforcement Layer

* Validates payment or entitlement
* Ensures STC is covered before response

---

### 4. Metering Layer

Logs every request:

* stc_cost
* pricing_rule_id
* payment_rail
* payment_status

---

## Strategic Goals

### 1. Agent-Native Monetization

Enable AI agents to:

* discover pricing
* pay per request
* open sessions
* optimize cost

---

### 2. Multi-Rail Flexibility

No dependency on:

* specific blockchain
* specific payment provider
* specific protocol

---

### 3. Token Integration (Future)

STOK will:

* reduce STC cost
* incentivize participation
* integrate with game mechanics

---

## Design Constraint

> Pricing must NEVER depend on payment rail

---

## Outcome

The API becomes:

→ a **programmable financial layer for data access**
