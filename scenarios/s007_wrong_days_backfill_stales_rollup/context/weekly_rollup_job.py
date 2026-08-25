"""weekly_sales_vs_forecast_rollup -- runs once each Monday, aggregates the
prior week's forecast partitions into a report. Does not track which
partitions it consumed, and is never re-triggered if a source partition
changes after the fact."""
import pandas as pd, logging

def run_weekly_rollup(week_start: str, week_end: str):
    log = logging.getLogger("weekly_rollup")
    frames = [pd.read_parquet(f"/warehouse/forecasts/run_date={d}")
              for d in _dates_between(week_start, week_end)]
    rollup = pd.concat(frames).groupby("zone")["forecast"].sum()
    rollup.to_csv(f"/reports/weekly_rollup_{week_start}.csv")
    log.info(f"Rollup for week {week_start}..{week_end} written. status=SUCCESS")
    # No record is kept of partition versions consumed; if a partition is
    # later overwritten, this report is never automatically refreshed.
