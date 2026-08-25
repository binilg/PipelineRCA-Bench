"""Recency feature computation for daily_forecast_scoring. Rewritten in
the 2026-08-10 release to replace a per-SKU loop with a vectorized
pandas implementation for performance -- see release_notes.txt."""
import pandas as pd


def days_since_last_sale(catalog: pd.DataFrame, run_date: str) -> pd.Series:
    """Vectorized implementation (current).

    catalog has one row per SKU with a `last_sale_date` column, which is
    NaT for any SKU that has never recorded a sale.
    """
    run = pd.Timestamp(run_date)
    diff = (run - catalog["last_sale_date"]).dt.days
    # NaT last_sale_date -> NaN diff -> "cleaned up" to 0.
    # This silently means "no sales history" is scored identically to
    # "sold earlier today" -- the strongest possible recency signal.
    return diff.fillna(0)


def build_features(catalog: pd.DataFrame, run_date: str) -> pd.DataFrame:
    catalog = catalog.copy()
    catalog["days_since_last_sale"] = days_since_last_sale(catalog, run_date)
    return catalog
