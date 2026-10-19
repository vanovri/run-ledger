"""Decimal-only money helpers. Floats are rejected at the boundary."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MICRO = Decimal("0.000001")
ZERO = Decimal("0.000000")


class MoneyError(ValueError):
    pass


def as_decimal(value, label: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise MoneyError(f"{label}: floats are not accepted; pass a string or integer")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"{label}: invalid decimal") from exc
    if not number.is_finite():
        raise MoneyError(f"{label}: finite value required")
    return number


def rate(value, label: str) -> Decimal:
    number = as_decimal(value, label)
    if number < 0:
        raise MoneyError(f"{label}: rate cannot be negative")
    return number


def tokens(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError(f"{label}: integer token count required")
    if value < 0:
        raise MoneyError(f"{label}: token count cannot be negative")
    return value


def cost(tokens_used: int, rate_per_million: Decimal) -> Decimal:
    return Decimal(tokens(tokens_used, 'tokens')) / Decimal(1_000_000) * rate(rate_per_million, 'rate')


def fmt(amount: Decimal | None, currency: str = "USD") -> str:
    if amount is None:
        return "unknown"
    return f"{amount.quantize(MICRO)} {currency}"


@dataclass(frozen=True)
class ModelPrice:
    model: str
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None


@dataclass(frozen=True)
class PriceTable:
    version: str
    currency: str
    models: dict[str, ModelPrice]

    @classmethod
    def load(cls, payload: dict) -> "PriceTable":
        if payload.get("schema") != "PRICE_TABLE_V1":
            raise MoneyError("unsupported price schema")
        version = payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise MoneyError("price table needs a non-empty version")
        currency = payload.get("currency", "USD")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency != currency.upper():
            raise MoneyError("currency must be a three-letter code")
        models = {}
        for name, row in (payload.get("models") or {}).items():
            if not isinstance(name, str) or not name:
                raise MoneyError("model names must be non-empty strings")
            models[name] = ModelPrice(
                model=name,
                input_per_million=rate(row.get("input_per_million"), f"{name}.input"),
                output_per_million=rate(row.get("output_per_million"), f"{name}.output"),
                cached_input_per_million=(
                    rate(row["cached_input_per_million"], f"{name}.cached")
                    if row.get("cached_input_per_million") is not None else None
                ),
            )
        return cls(version=version, currency=currency, models=models)

    def quote(self, model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> Decimal | None:
        for label, value in [('input_tokens', input_tokens), ('output_tokens', output_tokens), ('cached_tokens', cached_tokens)]:
            tokens(value, label)
        if cached_tokens > input_tokens:
            raise MoneyError('cached_tokens cannot exceed input_tokens')
        price = self.models.get(model)
        if price is None:
            return None
        cached = cached_tokens
        uncached = input_tokens - cached
        cached_rate = price.cached_input_per_million if price.cached_input_per_million is not None else price.input_per_million
        return (
            cost(uncached, price.input_per_million)
            + cost(cached, cached_rate)
            + cost(output_tokens, price.output_per_million)
        )
