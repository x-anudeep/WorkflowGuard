# Workflow Testing

Workflow tests are first-class reusable records with inputs, mocked integrations, failure injections, expected paths, expected outputs, expected/forbidden side effects, assertions, expected errors, tags, importance, generation source, rationale, and linked requirements.

The deterministic generator covers happy paths, branches, edge cases, malformed input, duplicate events, API failures, timeouts, 429/500 responses, LLM failures, authorization failures, and retry exhaustion. The simulator walks the canonical graph with controlled adapters and never executes uploaded code or calls external systems. Coverage is workflow coverage: node, edge, branch, requirement, and overall.
