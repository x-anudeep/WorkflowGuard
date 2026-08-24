# Security

WorkflowGuard validates upload extensions, content size, and source format. XML parsing disables network access and entity resolution. JSON is parsed safely and uploaded workflow code is never executed.

Security analysis is best-effort and explicit about limitations. It detects secret-like values in configuration, unsafe HTTP endpoints, missing authentication indicators for external APIs, suspicious data transmission, and LLM sensitive-data/prompt-injection exposure where detectable.

Repair proposals are schema-validated, previewed against a temporary candidate, and accepted only by creating a new version. The system flags new external destinations, approval removal, and node removal. API keys and secrets should be supplied through environment variables and are not logged.
