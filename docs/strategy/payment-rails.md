# Payment Rails Strategy

## Objective

Support multiple payment mechanisms without coupling pricing logic.

---

## Supported Rails

### 1. Subscription

* API key based
* prepaid STC
* no per-request payment

---

### 2. x402

* HTTP-native micropayments
* per-request
* agent-friendly

---

### 3. MPP (Future)

* session-based payments
* high-frequency usage optimization
* lower latency

---

### 4. STOK (Future)

* token-based incentives
* optional discount layer

---

## Design Rule

> All rails must implement a common interface:

* authorize()
* settle()
* report()

---

## Outcome

Payment innovation without architectural disruption
