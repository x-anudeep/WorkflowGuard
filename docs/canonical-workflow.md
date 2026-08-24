# Canonical Workflow

All supported formats become a typed `Workflow` with `nodes`, `edges`, variables, source metadata, and preserved provider-specific configuration. The core representation is intentionally engine-neutral so BPMN, generic JSON, n8n, and future UiPath/Temporal/Airflow/LangGraph/Make/Zapier parsers can feed the same validators, evaluators, simulator, costing, repair, CLI, and UI.

Nodes include ID, name, type, subtype, provider, operation, configuration, schemas, and metadata. Edges include ID, source, target, condition, label, and metadata. Uploaded source files remain stored separately; repair acceptance creates a new canonical version rather than overwriting the original file.
