# CLAUDE.md — Stock Trends API

## MANDATORY FIRST STEP

Before making ANY changes:

1. Read `AGENTS.md`
2. Confirm:

   * pricing model = STC only
   * no rail-specific pricing logic
   * logging is mandatory
3. If unclear → ASK QUESTIONS before proceeding

---

## BIDIRECTIONAL ALIGNMENT (REQUIRED)

Before coding:

1. State what you think the task is
2. List assumptions
3. Ask clarifying questions if anything is ambiguous

Do NOT proceed until alignment is confirmed.

---

## EXECUTION RULES

* Make minimal, targeted changes
* Do NOT rewrite large sections unless required
* Preserve working production behavior
* Separate:

  * pricing (STC)
  * payment rails
  * logging

---

## PAYMENT ARCHITECTURE

* Pricing = STC (single source of truth)
* Payment rails:

  * subscription
  * x402
  * MPP (future)
* No pricing logic inside payment adapters

---

## LOGGING (MANDATORY)

Every request must produce:

* stc_cost
* pricing_rule_id
* payment_rail
* payment_status

No logging → invalid implementation

---

## ERROR DISCIPLINE

If anything goes wrong:

→ STOP and analyze

Focus on:

* prompt clarity
* missing constraints
* context issues

Use `/log-error` workflow

---

## CONTEXT DISCIPLINE

* Avoid long sessions (context rot)
* Prefer fresh sessions (/clear)
* Do not rely on stale conversation state

---

## OUTPUT REQUIREMENTS

Always provide:

* diagnosis
* exact files changed
* code snippets
* reasoning
* validation steps
* risks

---

## PRINCIPLE

This system is:

* a financial engine
* a pricing engine
* an agent payment layer

Accuracy and structure > speed
