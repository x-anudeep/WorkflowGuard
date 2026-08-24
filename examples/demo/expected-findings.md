# Expected Demo Findings

The broken AI-generated invoice workflow should demonstrate WorkflowGuard's value quickly:

- Prompt alignment should flag the missing human approval requirement for invoices over $10,000.
- Reliability analysis should flag the SAP API call missing timeout/retry/failure handling.
- Security analysis should note that external API authentication is not detectable in the broken workflow.
- Generated tests should include a high-value invoice branch where approval is expected before SAP.
- Quality gates should fail until semantic alignment, reliability, and coverage thresholds are satisfied.
