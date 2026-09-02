# Validation

Static validation is deterministic and never calls an LLM. Parsers catch malformed XML/JSON and schema issues before canonicalization. Graph rules detect duplicate IDs, invalid edge references, empty workflows, missing starts/terminals, unreachable/orphan nodes, dead ends, disconnected components, suspicious cycles, missing required configuration, and invalid/empty conditions where detectable.

Findings use `INFO`, `WARNING`, `ERROR`, and `CRITICAL` severities and include rule ID, title, message, affected node/edge, metadata, and remediation. The Structural Quality Score is a deterministic Part 1 score and is distinct from the later Overall Workflow Score.


## WG-ALIGN-001 severity varies by evidence

A missing requirement is an ERROR when it came from the source prompt, or when an AI matcher
judged it absent. It is a WARNING when a *document* requirement was judged missing by keyword
matching alone, because in that case the system does not actually know it is missing - only
that token overlap did not clear its threshold. The finding's `metadata` carries
`requirement_source`, `source_anchor`, and `match_method` so the distinction is visible in the
report. See `docs/ai-evaluation.md` for the full table.
