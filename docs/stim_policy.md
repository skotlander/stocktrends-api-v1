# STIM Access Policy

## Permanent Hybrid Policy

- `/v1/stim*` without payment headers:
  - allowed for entitled paid API users
  - billed as subscription-backed usage
  - pricing rule: `default_subscription`

- `/v1/stim*` with payment headers:
  - treated as explicit agent-pay usage
  - pricing rule: `agent_pay_required`
  - incomplete/invalid payment headers may return `402 Payment Required`

- sandbox plan:
  - denied by auth/plan enforcement

- missing API key:
  - denied by auth layer