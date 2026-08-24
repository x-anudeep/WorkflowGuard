# Cost Engine

Cost estimates are planning estimates, not provider bills. Pricing lives in an editable catalog with category, provider, model, effective date, input/output/call costs, unit, currency, source, and metadata. Scenarios define execution volume, payload size, token estimates, and failure/retry rate.

The estimator returns cost/run, daily, monthly, and annual projections with line-item assumptions. The optimization engine flags repeated LLM calls, expensive model usage for simple tasks, duplicated APIs, excessive retries, large repeated context, and cacheable operations. It does not claim cheaper models are equivalent without evidence.
