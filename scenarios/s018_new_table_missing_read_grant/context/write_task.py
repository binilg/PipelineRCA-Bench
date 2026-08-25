"""write_forecast_partition -- writes to forecast_output_v2 as of the
2026-08-12 schema migration. The writing service account has implicit
write access to any table it creates in its own project, independent of
the separate downstream read-grant process (see access_provisioning.py)."""
import logging

log = logging.getLogger("write_forecast_partition")

OUTPUT_TABLE = "forecast_output_v2"  # was forecast_output before 2026-08-12


def write_forecast_partition(df, run_date: str):
    log.info(f"Writing {len(df)} rows to {OUTPUT_TABLE} for run_date={run_date}")
    _write_table(OUTPUT_TABLE, df)  # succeeds: writer has implicit access to own tables
    log.info("Write complete. status=SUCCESS")
