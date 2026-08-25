"""Manual backfill CLI for daily_forecast_scoring.

Usage:
  python backfill_cli.py --start-date YYYY-MM-DD --days N

--days: number of sequential run_dates to reprocess, starting from
        --start-date (inclusive). NOT a feature lookback window --
        that's configured separately in feature_config.yaml.
"""
import argparse, datetime as dt

def dates_to_reprocess(start_date: str, days: int) -> list:
    start = dt.date.fromisoformat(start_date)
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()

    targets = dates_to_reprocess(args.start_date, args.days)
    print(f"Reprocessing {len(targets)} run_date(s): {targets}")
    for run_date in targets:
        _rerun_scoring_dag(run_date)

if __name__ == "__main__":
    main()
