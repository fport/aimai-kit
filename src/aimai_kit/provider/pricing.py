"""Model pricing and cost computation.

DECISION (fixed deliberately, changeable):
`input_tokens` INCLUDES cached tokens. That is, `cached_input_tokens` is a
subset of `input_tokens`, deducted from input and billed at the discounted
rate. This is how OpenAI reports it. Anthropic reports
`cache_read_input_tokens` separately (not included in input); the adapter
normalizes that difference.

No floats in money. `Decimal` throughout; the 0.1 + 0.2 != 0.3 problem is not
acceptable in billing.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

__all__ = ["MTOK", "DEFAULT_PRICING_PATH", "ModelPricing", "load_pricing"]

MTOK = Decimal(1_000_000)

DEFAULT_PRICING_PATH = "config/pricing.toml"


@dataclass(frozen=True)
class ModelPricing:
    """Price and window information for a single model."""

    model: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    context_window: int
    cached_input_per_mtok: Decimal | None = None
    max_output_tokens: int | None = None

    def cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> Decimal:
        """Return the USD cost of one call.

        `cached_input_tokens` is a subset of `input_tokens` (see the decision
        above). When no cache price is configured, cached tokens are billed
        at the normal input rate.
        """
        if cached_input_tokens > input_tokens:
            raise ValueError(
                "cached_input_tokens must be a subset of input_tokens "
                f"({cached_input_tokens} > {input_tokens}). Some adapter is "
                "not normalizing its usage fields."
            )
        if self.cached_input_per_mtok is None:
            uncached, cached = input_tokens, 0
            cached_price = self.input_per_mtok
        else:
            uncached = input_tokens - cached_input_tokens
            cached = cached_input_tokens
            cached_price = self.cached_input_per_mtok

        return (
            Decimal(uncached) * self.input_per_mtok
            + Decimal(cached) * cached_price
            + Decimal(output_tokens) * self.output_per_mtok
        ) / MTOK


def _to_decimal(value: object, field: str, model: str) -> Decimal:
    """Convert a price from TOML into a `Decimal`.

    Prices are written as STRINGS in TOML ("2.50"), never as floats.
    `tomllib` turns a float into binary floating point and `Decimal(float)`
    renders 0.1 as 0.1000000000000000055511151231257827. A float in the
    catalog is rejected outright — accepting it quietly means the error
    surfaces in a billing report.
    """
    if isinstance(value, float):
        raise ValueError(
            f"{model}.{field}: price written as a float. Quote it in TOML: "
            f'{field} = "{value}"'
        )
    return Decimal(str(value))


def load_pricing(path: str | Path | None = None) -> dict[str, ModelPricing]:
    """Read the pricing catalog from TOML.

    Model names are not hardcoded; the catalog comes from here. A missing
    file raises loudly — silently returning an empty catalog would produce a
    report showing 0.00 for every call, and a wrong number is worse than no
    number.
    """
    target = Path(path or os.getenv("AIMAI_PRICING_FILE", DEFAULT_PRICING_PATH))
    if not target.is_file():
        raise FileNotFoundError(
            f"Pricing catalog not found: {target}. Point AIMAI_PRICING_FILE "
            "at one or create config/pricing.toml."
        )
    raw = tomllib.loads(target.read_text(encoding="utf-8"))
    catalog: dict[str, ModelPricing] = {}
    for model, fields in raw.get("models", {}).items():
        catalog[model] = ModelPricing(
            model=model,
            input_per_mtok=_to_decimal(
                fields["input_per_mtok"], "input_per_mtok", model
            ),
            output_per_mtok=_to_decimal(
                fields["output_per_mtok"], "output_per_mtok", model
            ),
            context_window=int(fields["context_window"]),
            cached_input_per_mtok=(
                _to_decimal(
                    fields["cached_input_per_mtok"], "cached_input_per_mtok", model
                )
                if "cached_input_per_mtok" in fields
                else None
            ),
            max_output_tokens=(
                int(fields["max_output_tokens"])
                if "max_output_tokens" in fields
                else None
            ),
        )
    return catalog
