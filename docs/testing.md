# Workflow Testing

Workflow tests are first-class reusable records with inputs, mocked integrations, failure injections, expected paths, expected outputs, expected/forbidden side effects, assertions, expected errors, tags, importance, generation source, rationale, and linked requirements.

The deterministic generator covers happy paths, branches, edge cases, malformed input, duplicate events, API failures, timeouts, 429/500 responses, LLM failures, authorization failures, and retry exhaustion. Coverage is workflow coverage: node, edge, branch, requirement, and overall.

## How a test runs

Tests execute in a real n8n instance. The workflow is compiled to an n8n workflow, published
once, and triggered per test; the execution is then read back and translated into canonical node
and edge ids, so assertions and coverage mean exactly what they always did.

That is a real engine running a real workflow, with two things deliberately withheld: an
integration call never reaches its declared destination - it is redirected to WorkflowGuard's
own mock endpoints, which serve the test's `mocked_integrations` and turn its
`failure_injections` into genuine 429s, 500s, timeouts and malformed responses - and uploaded
code is not executed. See the Security Posture section of `docs/architecture.md`.

Because failures are real rather than modelled, a workflow that declares retries genuinely
retries: a single injected timeout against a node configured to retry is survived, and the run
passes. To exhaust the retries, inject the failure on each attempt (`occurrence` 1, 2, 3).

Anything the engine could not reproduce faithfully is recorded on the run as a warning and shown
in the Tests panel. A green run with warnings is weaker evidence than a green run without them.

Running tests requires a reachable n8n (`WORKFLOWGUARD_N8N_BASE_URL`, and an API key with the
`workflow:activate` scope). There is no in-process fallback: reporting invented coverage would
be worse than failing loudly, so an unreachable engine is recorded as an engine failure and
never as a workflow defect.

## Fuzz Campaigns

Workflow tests are regression tests: fixed cases with expected outcomes, stored and re-run.
Fuzz campaigns answer a different question - not "does this case still pass" but "does the
declared error handling survive contact with failure".

`workflow_core.fuzzing` crosses input mutations (nulls, type confusion, oversized payloads,
unicode, duplicate events) with dependency-failure scenarios (every failure type against every
external/database/LLM node, simultaneous outages, and repeat failures that exhaust retries).
Cases are generated from a seed, so any failing case is reproducible.

Each case runs through the same engine, in failure-propagating mode, and is classified by what the
workflow actually did:

| Verdict | Meaning |
| --- | --- |
| `handled` | The failure reached an error path that notified or compensated |
| `silent_success` | The failure fired but the run reported success with nothing compensated |
| `unhandled_crash` | The run aborted with nowhere to continue |
| `hung` | Retries or a loop never terminated |
| `not_triggered` | The perturbation never fired; excluded from the score |

`silent_success` is the finding worth looking for first. The run is green, so nobody
investigates, while the record it was supposed to process was quietly dropped.

Reaching an error edge is not by itself evidence of handling. An edge counts only when it
leaves the failed node or its condition reads that step's result, and the branch must run
real recovery work - an error path straight to `End` hides a failure rather than handling it.

The simulator used for fuzzing runs with `propagate_failures=True`, because workflows commonly
handle errors downstream: the call runs, then the next condition inspects `result.success`. A
run that stops at the failing node cannot see that handling at all. Stored test runs keep the
strict behaviour.

`workflowguard fuzz <file> --min-robustness 70` exits non-zero below the threshold. A campaign
that exercised nothing does not fail the gate - use `validate` to gate on graph structure.

