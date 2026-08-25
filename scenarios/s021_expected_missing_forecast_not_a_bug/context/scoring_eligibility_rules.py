"""Eligibility filters applied before scoring. A sku-store combination
that fails any of these is intentionally never scored -- this is not an
error path, it's the pipeline correctly declining to forecast something
it was never supposed to forecast."""
import datetime as dt

MIN_SALES_HISTORY_DAYS = 14


def is_forecastable(sku_row: dict) -> bool:
    """Excludes SKUs without enough sales history for a statistical
    forecast to be meaningful."""
    return sku_row["sales_history_days"] >= MIN_SALES_HISTORY_DAYS


def is_active(sku_row: dict, run_date: str) -> bool:
    """Excludes SKUs whose catalog effective_date hasn't arrived yet."""
    return dt.date.fromisoformat(sku_row["effective_date"]) <= dt.date.fromisoformat(run_date)


def is_ranged_at_store(sku_id: str, store_id: str, assortment: set) -> bool:
    """Excludes sku-store pairs where the store doesn't carry the SKU."""
    return (sku_id, store_id) in assortment


def is_not_discontinued(sku_row: dict) -> bool:
    """Excludes SKUs marked discontinued in the current catalog."""
    return sku_row["status"] != "discontinued"


def eligible_for_scoring(sku_row: dict, store_id: str, assortment: set, run_date: str) -> bool:
    return (
        is_forecastable(sku_row)
        and is_active(sku_row, run_date)
        and is_ranged_at_store(sku_row["sku_id"], store_id, assortment)
        and is_not_discontinued(sku_row)
    )
    # No forecast row is written for any sku-store combination that
    # fails eligibility -- this is by design, not a bug, and nothing
    # here logs a per-combination exclusion reason today.
