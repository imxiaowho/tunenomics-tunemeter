# Financial Evidence Contract

Keep six concepts separate: payments, provider charges, subscription plans, quota snapshots, API-equivalent estimates and optional management allocations. This version computes neither reference prices nor automatic allocations. A monthly fee covering a week is not a payment made that week. A token reduction does not establish cash savings.

Structured input is `{ "schema": "tunemeter-evidence/1.0.0", "records": [...] }`. See [fictional evidence](../examples/evidence.json). The Agent can create this file from already authorized selected facts; do not make the customer author JSON or manually export bills.

Each record has neutral `record_id` E1, `source_alias` S1 and `scope_alias` A1. Never use real invoice/account/customer identifiers. Kinds: payment, provider_charge, subscription_plan, quota_snapshot, payment_coverage. Evidence status is declared or documented. Documented is a review declaration, never independent proof. Monetary amounts are nonnegative decimal strings and currency is a three-letter code. Original bytes are not attached.

- payment: amount, currency, aware paid_at; optional refund=true subtracts from known net payments. Only documented selected payments inside the payment window enter the known subtotal. It remains partial evidence, not a complete account total.
- provider_charge: amount/currency, aware period_start and period_end_exclusive. Cross-window charge totals cannot be silently split; unverified/out-of-range coverage goes unmatched. Never add the charge subtotal to its matching payment.
- subscription_plan: amount/currency, aware period boundaries; declared/documented maintained. Intersecting plans are displayed but not automatically allocated to the report period.
- quota_snapshot: aware period boundaries/as_of and used_percent decimal in 0..100; not inferred from tokens. It carries no currency field.
- payment_coverage: period boundaries/currency, complete=true and confirmed_zero=true only with supporting selected evidence. Explicit zero applies to that scope; global account completeness remains unknown. Missing records alone cannot establish zero payment.

Duplicate neutral aliases are rejected; identical selected facts under different aliases are excluded from totals and listed as duplicate candidates rather than silently added twice. `charge_link` may point to a neutral E alias for traceability; it is not proof of matching amounts or account identity. Different currencies remain separate. Unsupported inputs fail safely without echoing original content.

Before reading selected originals, disclose actual/unknown model exposure. If a tool cannot safely isolate the necessary fields, explain exposure and obtain the customer's choice; never read auth/credential files. Preserve originals; keep selected facts outside the repository. Future attachment or online billing integrations require their own implementation, authorization and verification.
