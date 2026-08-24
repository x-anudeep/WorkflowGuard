# Invoice Processing Requirement

Read invoices from Gmail, extract invoice fields, require manual approval for invoices over $10,000, then save approved invoices to SAP.

Acceptance criteria:

- Gmail is the trigger.
- Invoice fields are extracted before any approval or SAP write.
- Amounts above 10000 require a human approval step before SAP.
- Approved invoices are written to SAP.
- Failed SAP/API operations should have timeout/retry/error-path behavior.
