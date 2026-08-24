# Validation

Static validation is deterministic and never calls an LLM. Parsers catch malformed XML/JSON and schema issues before canonicalization. Graph rules detect duplicate IDs, invalid edge references, empty workflows, missing starts/terminals, unreachable/orphan nodes, dead ends, disconnected components, suspicious cycles, missing required configuration, and invalid/empty conditions where detectable.

Findings use `INFO`, `WARNING`, `ERROR`, and `CRITICAL` severities and include rule ID, title, message, affected node/edge, metadata, and remediation. The Structural Quality Score is a deterministic Part 1 score and is distinct from the later Overall Workflow Score.
