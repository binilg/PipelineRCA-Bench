"""daily_forecast_scoring -- reads a static holiday calendar reference
file to adjust demand features around public holidays."""
import pandas as pd, logging

log = logging.getLogger("score_all_models")

def load_holiday_calendar() -> pd.DataFrame:
    # Read-only reference file, never modified by this pipeline.
    return pd.read_csv("/reference-data/holiday_calendar_reference.csv")

def score_all_models(**ctx):
    run_date = ctx["ds"]
    log.info(f"Run started. run_date={run_date}")
    holidays = load_holiday_calendar()   # <- raises FileNotFoundError once archived
    log.info(f"Holiday calendar loaded: {len(holidays)} entries")
    log.info("Scoring complete. status=SUCCESS")
