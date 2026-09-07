"""Cost computation — the numbers below were worked out by hand.

Prices: input 2.50 / Mtok, output 10.00 / Mtok, cached input 0.25 / Mtok.

Scenario A (no cache):
  input  12,000 tok -> 12000/1e6 * 2.50  = 0.030
  output  3,400 tok ->  3400/1e6 * 10.00 = 0.034
  total                                  = 0.064

Scenario B (8,000 of the 12,000 input tokens read from cache):
  uncached input 4,000 -> 4000/1e6 * 2.50 = 0.010
  cached input   8,000 -> 8000/1e6 * 0.25 = 0.002
  output         3,400 -> 0.034
  total                                   = 0.046
"""

from decimal import Decimal

import pytest

from aimai_kit.provider.pricing import ModelPricing, load_pricing


@pytest.fixture
def price() -> ModelPricing:
    return ModelPricing(
        model="test-model",
        input_per_mtok=Decimal("2.50"),
        output_per_mtok=Decimal("10.00"),
        cached_input_per_mtok=Decimal("0.25"),
        context_window=200_000,
    )


def test_cost_without_cache(price: ModelPricing) -> None:
    assert price.cost(12_000, 3_400) == Decimal("0.064")


def test_cache_discount_is_applied(price: ModelPricing) -> None:
    assert price.cost(12_000, 3_400, cached_input_tokens=8_000) == Decimal("0.046")


def test_no_discount_when_cache_price_missing() -> None:
    price = ModelPricing(
        model="test-model",
        input_per_mtok=Decimal("2.50"),
        output_per_mtok=Decimal("10.00"),
        context_window=200_000,
    )
    assert price.cost(12_000, 3_400, cached_input_tokens=8_000) == Decimal("0.064")


def test_cost_returns_decimal(price: ModelPricing) -> None:
    assert isinstance(price.cost(1, 1), Decimal)


def test_zero_tokens_zero_cost(price: ModelPricing) -> None:
    assert price.cost(0, 0) == Decimal(0)


def test_cached_larger_than_input_is_rejected(price: ModelPricing) -> None:
    """Catches an adapter that failed to normalize its usage fields."""
    with pytest.raises(ValueError, match="subset"):
        price.cost(100, 10, cached_input_tokens=200)


def test_catalog_is_read_from_file(tmp_path) -> None:
    path = tmp_path / "pricing.toml"
    path.write_text(
        '[models."x-1"]\n'
        'input_per_mtok = "1.00"\n'
        'output_per_mtok = "2.00"\n'
        "context_window = 128000\n",
        encoding="utf-8",
    )
    catalog = load_pricing(path)
    assert catalog["x-1"].input_per_mtok == Decimal("1.00")
    assert catalog["x-1"].context_window == 128_000


def test_float_price_is_rejected(tmp_path) -> None:
    """The Decimal(float) trap is caught at the catalog boundary."""
    path = tmp_path / "pricing.toml"
    path.write_text(
        '[models."x-1"]\n'
        "input_per_mtok = 1.00\n"
        'output_per_mtok = "2.00"\n'
        "context_window = 128000\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="float"):
        load_pricing(path)


def test_missing_catalog_raises_clear_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Pricing catalog not found"):
        load_pricing(tmp_path / "missing.toml")
