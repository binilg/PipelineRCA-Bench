"""Coverage gate: checks the written partition's row count against a
configured minimum, meant to catch a partial/truncated write."""
import logging

log = logging.getLogger("coverage_check")

# Set 2026-02-14 when the pipeline had 255 active models (~1.28M rows/day).
# Never revisited since.
MIN_EXPECTED_ROWS = 1_000_000

def run_coverage_check(actual_rows: int):
    passed = actual_rows >= MIN_EXPECTED_ROWS
    status = "PASS" if passed else "FAIL"
    log.info(f"Coverage check: {status} ({actual_rows:,} >= {MIN_EXPECTED_ROWS:,})")
    if not passed:
        raise RuntimeError(f"Coverage check failed: {actual_rows:,} < {MIN_EXPECTED_ROWS:,}")
    return passed
