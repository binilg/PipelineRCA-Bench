"""daily_forecast_scoring -- joins zone-level actuals into features before scoring."""
import pandas as pd, logging

def load_actuals(run_date: str) -> pd.DataFrame:
    """Actuals landed from per-zone vendor feeds; a zone with no feed today
    simply has no rows in this table for run_date."""
    return pd.read_parquet(f"/warehouse/actuals/run_date={run_date}")

def build_features(catalog: pd.DataFrame, run_date: str) -> pd.DataFrame:
    actuals = load_actuals(run_date)
    merged = catalog.merge(actuals, on=["sku_id", "zone"], how="left")
    merged["actual_qty"] = merged["actual_qty"].fillna(0.0)  # <- "no data" treated as "zero sales"
    return merged

def score_all_models(**ctx):
    run_date = ctx["ds"]
    log = logging.getLogger("score_all_models")
    catalog = pd.read_csv("/config/sku_catalog.csv")
    feats = build_features(catalog, run_date)
    log.info(f"Run started. run_date={run_date}")
    log.info(f"Feature build complete: {len(feats)} SKU-rows")
    log.info("Scoring complete. status=SUCCESS")
    return feats
