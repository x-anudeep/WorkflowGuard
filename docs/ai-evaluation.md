# AI Evaluation

Evaluation is layered after static validation. WorkflowGuard extracts a structured requirement spec from the prompt, maps workflow semantics from the canonical graph, then scores prompt alignment, reliability, security, and maintainability with explainable evidence.

AI providers are optional and provider-neutral. With `WORKFLOWGUARD_AI_PROVIDER=none`, deterministic extraction and analyzers still run. OpenAI can be enabled through environment variables. AI responses are schema-validated before use, and provider errors/timeouts/malformed output fall back to deterministic behavior.
