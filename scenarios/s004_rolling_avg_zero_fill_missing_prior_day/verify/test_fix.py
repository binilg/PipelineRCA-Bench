"""
Verification for s004. A proposed fix passes if a missing day inside a
rolling-average window is excluded from the average (or raises/blocks)
rather than being silently treated as 0.0.
Stub harness; replace mocks with real hooks when the harness is built.
"""

def broken_trailing_avg(daily_values: dict, days: list) -> float:
    values = [daily_values.get(d, 0.0) for d in days]   # <- missing -> 0.0
    return sum(values) / len(values)

def fixed_trailing_avg(daily_values: dict, days: list) -> float:
    values = [daily_values[d] for d in days if d in daily_values]
    if not values:
        raise ValueError("No data available for any day in the window")
    return sum(values) / len(values)

def test_missing_day_is_not_silently_zeroed():
    daily_values = {"2026-08-01": 15000.0, "2026-08-03": 15200.0}  # 08-02 missing
    days = ["2026-08-01", "2026-08-02", "2026-08-03"]

    broken = broken_trailing_avg(daily_values, days)
    fixed = fixed_trailing_avg(daily_values, days)

    assert broken == (15000.0 + 0.0 + 15200.0) / 3, "sanity check on broken behavior"
    assert fixed > broken, (
        f"Fix must not silently treat a missing day as 0.0 -- expected an "
        f"average computed only over available days ({fixed}) to be higher "
        f"than the zero-filled average ({broken})"
    )
    assert abs(fixed - 15100.0) < 1e-6, f"Expected average of available days only, got {fixed}"

if __name__ == "__main__":
    test_missing_day_is_not_silently_zeroed()
    print("PASS: missing day in rolling window is no longer silently zero-filled")
