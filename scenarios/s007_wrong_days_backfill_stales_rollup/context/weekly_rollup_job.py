"""weekly_sales_vs_forecast_rollup -- scheduled to run once each Monday at
06:00, aggregating the prior Monday-Sunday week's forecast partitions
into a report. Can also be run by hand for a specific week.

Does not track which partitions (or partition versions) it consumed, and
is never re-triggered automatically if a source partition changes after
the fact."""
import argparse, logging
import pandas as pd

def run_weekly_rollup(week_start: str, week_end: str):
    log = logging.getLogger("weekly_rollup")
    frames = [pd.read_parquet(f"/warehouse/forecasts/run_date={d}")
              for d in _dates_between(week_start, week_end)]
    rollup = pd.concat(frames).groupby("run_date")["forecast_qty"].sum()
    rollup.to_csv(f"/reports/weekly_rollup_{week_start}.csv")
    log.info(f"Rollup for week {week_start}..{week_end} written. status=SUCCESS")
    # No record is kept of partition versions consumed; if a partition is
    # later overwritten, this report is never automatically refreshed.

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--week-end", required=True)
    args = parser.parse_args()
    run_weekly_rollup(args.week_start, args.week_end)
