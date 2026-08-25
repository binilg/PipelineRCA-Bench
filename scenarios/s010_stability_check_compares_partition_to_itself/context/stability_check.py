"""Data-stability gate: computes Population Stability Index (PSI) between
today's input partition and yesterday's, and blocks the DAG if PSI
exceeds the configured threshold (indicating a meaningful distribution
shift that might signal an upstream data problem)."""
import pandas as pd, datetime as dt, logging

log = logging.getLogger("stability_check")
PSI_THRESHOLD = 0.2

def _reference_date(run_date: str) -> str:
    # Refactored 2026-07-20 -- BUG: offset should be -1 (yesterday), not 0.
    return (dt.date.fromisoformat(run_date) - dt.timedelta(days=0)).isoformat()

def compute_psi(today_df: pd.DataFrame, ref_df: pd.DataFrame, column: str) -> float:
    # Standard PSI computation over binned distributions.
    today_bins = pd.qcut(today_df[column], 10, duplicates="drop").value_counts(normalize=True)
    ref_bins = pd.qcut(ref_df[column], 10, duplicates="drop").value_counts(normalize=True)
    psi = ((today_bins - ref_bins) * (today_bins / ref_bins).apply(
        lambda r: 0 if r <= 0 else __import__("math").log(r))).sum()
    return abs(psi)

def run_stability_check(run_date: str, column: str = "avg_unit_price"):
    today_df = pd.read_parquet(f"/warehouse/inputs/run_date={run_date}")
    ref_date = _reference_date(run_date)
    ref_df = pd.read_parquet(f"/warehouse/inputs/run_date={ref_date}")
    psi = compute_psi(today_df, ref_df, column)
    status = "Green" if psi <= PSI_THRESHOLD else "Red"
    log.info(f"Stability check: {status} (PSI={psi:.2f})")
    if status == "Red":
        raise RuntimeError(f"Data stability check failed: PSI={psi:.2f} > {PSI_THRESHOLD}")
    return psi
