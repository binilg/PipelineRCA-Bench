"""upload_to_warehouse -- writes the finished forecast partition to the
warehouse. Switched to fastparquet_writer on 2026-08-12 for faster
writes on large partitions."""
import logging
import fastparquet_writer  # <- new dependency, not in requirements_prod.txt

log = logging.getLogger("upload_to_warehouse")


def upload_to_warehouse(df, run_date: str):
    path = f"/warehouse/forecasts/run_date={run_date}"
    log.info(f"Writing partition to {path} via fastparquet_writer")
    fastparquet_writer.write(path, df)
    log.info("Upload complete. status=SUCCESS")
