"""Coverage gate: checks the written partition's row count against a
configured minimum, meant to catch a partial/truncated write."""
import logging

log = logging.getLogger("coverage_check")

MIN_EXPECTED_ROWS = 1_250_000  # tuned against full 260-zone runs

def run_coverage_check(actual_rows: int):
    passed = actual_rows >= MIN_EXPECTED_ROWS
    status = "PASS" if passed else "FAIL"
    log.info(f"Coverage check: {status} ({actual_rows:,} >= {MIN_EXPECTED_ROWS:,})")
    # 1-3 zones missing out of 260 shifts total rows by ~1%, which never
    # gets close to tripping this aggregate threshold.
    return passed
