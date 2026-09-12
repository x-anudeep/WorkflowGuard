# Recorded n8n execution payloads

Captured from a live n8n 2.38.7 during the step-0 spike, verbatim from
`GET /api/v1/executions/{id}?includeData=true`. They exist so the result mapper can be built
and tested without a running engine.

| File | Captures | The thing it pins |
| --- | --- | --- |
| `execution-branching.json` | Webhook -> IF (`amount > 1000`) -> two Set nodes | `taskData.source[].previousNode` / `previousNodeOutput` exist, which is what makes `executed_edges` and `branch_decisions` recoverable. The untaken branch is absent from `runData`. |
| `execution-error-output.json` | HTTP node to a refused port, `onError: continueErrorOutput` | The failing node reports `executionStatus: "success"` with **no** `taskData.error`; the error is inside the error-output item's `json.error`. |
| `execution-stop-on-error.json` | Same node, default `onError` | Execution `status: "error"`, `finished: false`, `taskData.error` present, `resultData.error` populated. |

Both error fixtures ran with `retryOnFail: true, maxTries: 3` and contain exactly **one**
`taskData` entry each - the evidence that n8n reports no retry attempt count, and therefore that
`SimulationResult.retries` has to come from the mock server's call log.

Do not hand-edit. Re-record with the probe in `references/claude-gen/n8n-spike/probes/`.
