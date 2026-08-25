"""Shared feature-loading helpers for daily_forecast_scoring."""
import pandas as pd, datetime as dt, logging

log = logging.getLogger("feature_loader")

def _load_actuals_partition(zone: str, run_date: str) -> float:
    path = f"/warehouse/actuals/zone={zone}/run_date={run_date}/total.parquet"
    return pd.read_parquet(path)["actual_qty"].sum()

def trailing_avg(zone: str, run_date: str, window_days: int = 3) -> float:
    """Average of actual demand over the trailing window_days days."""
    values = []
    for offset in range(1, window_days + 1):
        day = (dt.date.fromisoformat(run_date) - dt.timedelta(days=offset)).isoformat()
        try:
            values.append(_load_actuals_partition(zone, day))
        except FileNotFoundError:
            log.warning(f"No actuals partition for zone={zone} date={day}; using 0.0")
            values.append(0.0)   # <- silently treats "missing" as "zero demand"
    return sum(values) / len(values)
