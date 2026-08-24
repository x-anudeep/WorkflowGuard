from __future__ import annotations

from datetime import date

from workflow_core.costing.models import CostCategory, PricingEntry, PricingUnit

DEFAULT_PRICING_CATALOG = [
    PricingEntry(
        category=CostCategory.LLM,
        provider="openai",
        model="gpt-4o-mini",
        effective_date=date(2026, 1, 1),
        input_unit_cost=0.00015,
        output_unit_cost=0.0006,
        unit=PricingUnit.TOKEN_1K,
        source="seeded development assumption, editable pricing catalog",
    ),
    PricingEntry(
        category=CostCategory.LLM,
        provider="openai",
        model="gpt-4o",
        effective_date=date(2026, 1, 1),
        input_unit_cost=0.005,
        output_unit_cost=0.015,
        unit=PricingUnit.TOKEN_1K,
        source="seeded development assumption, editable pricing catalog",
    ),
    PricingEntry(
        category=CostCategory.EXTERNAL_API,
        provider="generic",
        effective_date=date(2026, 1, 1),
        call_unit_cost=0.001,
        unit=PricingUnit.CALL,
        source="seeded configurable default",
    ),
    PricingEntry(
        category=CostCategory.DATABASE,
        provider="generic",
        effective_date=date(2026, 1, 1),
        call_unit_cost=0.0002,
        unit=PricingUnit.CALL,
        source="seeded configurable default",
    ),
    PricingEntry(
        category=CostCategory.EMAIL_MESSAGING,
        provider="generic",
        effective_date=date(2026, 1, 1),
        call_unit_cost=0.0005,
        unit=PricingUnit.CALL,
        source="seeded configurable default",
    ),
    PricingEntry(
        category=CostCategory.COMPUTE,
        provider="workflowguard",
        effective_date=date(2026, 1, 1),
        call_unit_cost=0.0001,
        unit=PricingUnit.EXECUTION,
        source="seeded configurable default",
    ),
]


class PricingCatalog:
    def __init__(self, entries: list[PricingEntry] | None = None) -> None:
        self.entries = entries or list(DEFAULT_PRICING_CATALOG)

    def find(self, category: CostCategory, provider: str | None, model: str | None = None) -> PricingEntry | None:
        provider_key = (provider or "generic").lower()
        candidates = [
            entry
            for entry in self.entries
            if entry.category == category
            and entry.provider.lower() in {provider_key, "generic"}
            and (model is None or entry.model is None or entry.model.lower() == model.lower())
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda entry: (entry.provider.lower() == provider_key, entry.effective_date), reverse=True)
        return candidates[0]
