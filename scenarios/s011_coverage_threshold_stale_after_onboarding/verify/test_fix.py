"""
Verification for s011. A proposed fix passes if the coverage threshold
scales with the current active model count rather than staying fixed,
so a partial write that's incomplete relative to CURRENT expectations
is caught even if it would have cleared an old, stale threshold.
Stub harness; replace mocks with real hooks when the harness is built.
"""

AVG_ROWS_PER_MODEL = 5001  # ~1,300,260 / 260

def broken_coverage_check(actual_rows: int, static_threshold: int = 1_000_000) -> bool:
    return actual_rows >= static_threshold

def fixed_coverage_check(actual_rows: int, active_model_count: int, tolerance: float = 0.1) -> bool:
    expected = active_model_count * AVG_ROWS_PER_MODEL
    min_expected = expected * (1 - tolerance)
    return actual_rows >= min_expected

def test_partial_write_is_caught_against_current_model_count():
    actual_rows = 1_050_220       # 80/260 models' worth of rows
    active_model_count = 260      # current active count

    broken = broken_coverage_check(actual_rows)
    assert broken is True, "sanity check: broken check passes against the stale static threshold"

    fixed = fixed_coverage_check(actual_rows, active_model_count)
    assert fixed is False, (
        "Fix must fail coverage when the partition is incomplete relative to "
        "the CURRENT active model count, even though it clears the old "
        "static threshold."
    )

if __name__ == "__main__":
    test_partial_write_is_caught_against_current_model_count()
    print("PASS: coverage check no longer passes a partition that's incomplete for the current model count")
