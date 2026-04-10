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

```bash id="pwbpb8"
curl -X POST https://api.stocktrends.com/v1/decision/evaluate_symbol \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "exchange": "NASDAQ"
  }'
```

---

### 2. Example Response

```json id="57obtf"
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

## 💵 Pricing (STC → USD)

STC (Stock Trends Credits) is the **unified pricing unit** of the API.

To make pricing clear and predictable:

👉 **1 STC ≈ $0.01 USD**

This means:

* 10 STC ≈ $0.10
* 100 STC ≈ $1.00

---

### Example Endpoint Costs

| Endpoint                                | STC Cost | Approx USD   |
| --------------------------------------- | -------- | ------------ |
| Evaluate Symbol                         | 10 STC   | ~$0.10       |
| Evaluate Portfolio                      | 50 STC   | ~$0.50       |
| Construct Portfolio                     | 25 STC   | ~$0.25       |
| Market Data (stim, breadth, leadership) | 1–5 STC  | ~$0.01–$0.05 |

---

### How Payment Works

* **Subscription (Stripe)**
  Purchase STC in advance
  Example: $50 → 5000 STC

* **x402 (Agent Payments)**
  Pay per request automatically
  No account required

---

👉 Pricing is enforced in STC, but value is anchored to USD for transparency

---

## 💡 Core Concepts

### STC (Stock Trends Credits)

* endpoints map to STC cost
* pricing is defined once (STC)
* payment rails convert value → STC

---

### Multi-Rail Payments

Supported:

* **Subscription (Stripe)**
* **x402 (per-request payments)**

Planned:

* **MPP (Machine Payments Protocol)**
* **STOK token (discount + incentive layer)**

---

## 🧠 Key Endpoints

### Decision Engine (High Value)

#### Evaluate a Symbol

```id="4u406s"
POST /v1/decision/evaluate_symbol
```

```json id="k1obzf"
{
  "symbol": "AAPL",
  "exchange": "NASDAQ"
}
```

---

#### Evaluate a Portfolio

```id="gznjct"
POST /v1/portfolio/evaluate
```

```json id="feof8n"
{
  "symbols": [
    {"symbol": "AAPL", "exchange": "NASDAQ"},
    {"symbol": "MSFT", "exchange": "NASDAQ"}
  ]
}
```

---

#### Construct a Portfolio

```id="egzgde"
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

```id="wtzzt6"
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

```bash id="1yxmwa"
pip install -r requirements.txt
```

### 2. Run the API

```bash id="1e1uio"
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
