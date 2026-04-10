# Stock Trends API

## 🚀 Agent-Native Financial Intelligence API

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

## ⚡ Quick Start (2 Minutes)

### 1. Make your first request

```bash
curl -X POST https://api.stocktrends.com/v1/decision/evaluate_symbol \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "exchange": "NASDAQ"
  }'
```

---

### 2. Example Response

```json
{
  "symbol": "AAPL",
  "decision": "OUTPERFORM",
  "confidence": 0.62,
  "time_horizon": "13-week"
}
```

---

### 3. Payment (Automatic)

* If payment is required:

  * API returns x402 payment request
* Agents complete payment automatically
* Request is fulfilled

👉 No separate billing integration required

---

## 💡 Core Concepts

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
  prepaid STC allocation

* **x402**
  per-request agent payments

Planned:

* **MPP (Machine Payments Protocol)**
  session-based payments

* **STOK token**
  discount and incentive layer

---

## 🧠 Key Endpoints

### Decision Engine (High Value)

#### Evaluate a Symbol

```
POST /v1/decision/evaluate_symbol
```

```json
{
  "symbol": "AAPL",
  "exchange": "NASDAQ"
}
```

---

#### Evaluate a Portfolio

```
POST /v1/portfolio/evaluate
```

```json
{
  "symbols": [
    {"symbol": "AAPL", "exchange": "NASDAQ"},
    {"symbol": "MSFT", "exchange": "NASDAQ"}
  ]
}
```

---

#### Construct a Portfolio

```
POST /v1/portfolio/construct
```

---

### Market Intelligence

* `/v1/stim/latest`
* `/v1/leadership`
* `/v1/breadth`
* `/v1/selections`
* `/v1/indicators`

---

## 📊 Cost Estimation

Estimate request cost before execution:

```
GET /v1/cost-estimate
```

---

## 📘 API Documentation (Swagger)

👉 https://api.stocktrends.com/v1/docs

Use the interactive docs to:

* explore endpoints
* test requests
* view schemas

---

## 🤖 Designed for AI Agents

This API is built for:

* autonomous agents
* trading systems
* financial copilots
* workflow automation

Features:

* machine-readable pricing
* deterministic billing
* stateless payments (x402)
* predictable response structures

---

## 🧾 Request Lifecycle

1. Request received
2. Pricing evaluated (STC)
3. Payment verified (if required)
4. Request executed
5. Usage logged + billed

---

## 🔥 What Makes This Different

Most APIs:

* charge subscriptions
* separate billing from usage

Stock Trends API:

* **monetizes each request**
* **native to AI agent workflows**
* **unified pricing across payment rails**

---

## 📂 Repository Structure

* `/routers` → API endpoints
* `/pricing` → STC pricing logic
* `/payments` → payment rails
* `/metering` → request logging + billing
* `/middleware` → enforcement layer
* `/docs` → system design and strategy

---

## 📚 Documentation

All system design and strategy lives in:

→ `/docs`

### Structure

* `/docs/strategy/` → system vision and pricing
* `/docs/architecture/` → request lifecycle and design
* `/docs/operations/` → policies and billing

---

## 📄 Key Files

### `AGENTS.md`

Defines strict system rules for AI agents:

* pricing enforcement
* payment behavior
* logging requirements

---

### `CLAUDE.md`

Defines execution behavior for Claude Code:

* implementation alignment
* controlled change strategy
* system consistency

---

## 🛠 Local Development

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the API

```bash
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Open docs

http://127.0.0.1:8000/v1/docs

---

## 🧠 Design Principles

* pricing is defined once (STC)
* payment rails are modular
* logging is first-class
* system is agent-first
* token integration must not break pricing

---

## ⚠️ AI Agent Rules

Before interacting with the system:

1. Read `AGENTS.md`
2. Follow pricing and payment rules
3. Do not bypass billing logic
4. Use documented endpoints

---

## 🧭 Status

* STC pricing: active
* subscription model: active
* x402 payments: active
* MPP: planned
* STOK integration: planned

---

## 📣 Final Note

This repository represents a **programmable financial layer for data access**, designed for:

* developers
* AI agents
* automated systems

---

👉 Start building. Start querying. Start monetizing intelligence.
