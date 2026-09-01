from __future__ import annotations


class AIProviderError(RuntimeError):
    pass


class AIProviderUnavailable(AIProviderError):
    pass


class MalformedAIResponse(AIProviderError):
    pass
