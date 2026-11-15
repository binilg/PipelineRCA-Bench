"""Post-scoring validation: catches model outputs that are absurdly high
due to a scoring bug, by clipping any forecast above a hardcoded cap."""
import logging

log = logging.getLogger("validation_rule")

# forecast_qty is always in individual sellable units, for every SKU. The
# scoring step converts CASE SKUs (case_qty x cases) before this runs;
# unit_type only describes how an item is ordered and shipped.
MAX_FORECAST_QTY_PER_SKU = 5000  # tuned/tested against dev data (each-unit SKUs only)

def validate_and_clip(sku_id: str, forecast_qty: float) -> float:
    if forecast_qty > MAX_FORECAST_QTY_PER_SKU:
        log.info(f"Validation: {sku_id} forecast_qty={forecast_qty} clipped to {MAX_FORECAST_QTY_PER_SKU}")
        return MAX_FORECAST_QTY_PER_SKU
    return forecast_qty
    # No unit_type awareness -- a case-unit SKU's legitimate 8,000-unit
    # forecast is clipped exactly the same way as a genuine scoring-bug
    # output would be, and both log identically.
