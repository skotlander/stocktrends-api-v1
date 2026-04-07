# Stock Trends API

## Overview

The Stock Trends API is a **financial data platform and agent-native monetization system** built on:

* FastAPI
* unified pricing (STC — Stock Trends Credits)
* multi-rail payments (subscription, x402, MPP-ready)
* full request metering and billing

This is not just a data API.

It is:

→ a **pricing engine**
→ a **payment system**
→ an **agent-accessible financial layer**

---

## Core Concepts

### STC (Stock Trends Credits)

All API usage is priced in:

→ **STC (Stock Trends Credits)**

* endpoints map to STC cost
* payment rails convert value → STC
* pricing is independent of payment method

---

### Multi-Rail Payments

Supported:

* **Subscription (Stripe)**

  * prepaid STC allocation

* **x402**

  * per-request agent payments

Planned:

* **MPP (Machine Payments Protocol)**

  * session-based payments

* **STOK token**

  * discount and incentive layer

---

## Documentation

All system design and strategy lives in:

→ `/docs`

### Structure

* `/docs/strategy/`

  * system vision and pricing model

* `/docs/architecture/`

  * system design and request lifecycle

* `/docs/operations/`

  * policies, billing, and runbooks

---

## Key Files

### `AGENTS.md`

* defines strict system rules
* MUST be followed by all AI agents
* includes:

  * STC pricing rules
  * payment architecture
  * logging requirements

---

### `CLAUDE.md`

* defines execution behavior
* automatically loaded into Claude Code
* ensures:

  * alignment
  * minimal changes
  * correct implementation flow

---

## Local Development

### Install dependencies

```bash
pip install -r requirements.txt
```

---

## Local Development

### 1. Install dependencies

```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
http://127.0.0.1:8000/v1/docs
---

### Open API Docs

```text
http://127.0.0.1:8000/docs
```

---

## API Version

`v1`

---

## Major Endpoint Groups

* `/instruments`
* `/prices`
* `/indicators`
* `/stim`
* `/selections`
* `/stwr`
* `/breadth`
* `/leadership`

---

## AI Agent Instructions

Before making any changes:

1. Read `AGENTS.md`
2. Follow all pricing, payment, and logging rules
3. Use `/docs` for system understanding

---

## Design Principles

* pricing is unified (STC)
* payment rails are modular
* logging is first-class
* system must remain multi-rail compatible
* future token integration must not break pricing

---

## Key Rule

Pricing is defined once (STC) and enforced everywhere.

---

## Status

* STC pricing: active
* subscription model: active
* x402 payments: active
* MPP: planned
* STOK integration: planned

---

## Final Note

This repository represents a **programmable financial layer for data access**, designed for:

* developers
* AI agents
* automated systems

---
