"""
Verification for s010. A proposed fix passes if the stability check's
reference-date resolution actually points at the prior day, not the
current day.
Stub harness; replace mocks with real hooks when the harness is built.
"""
import datetime as dt

def broken_reference_date(run_date: str) -> str:
    return (dt.date.fromisoformat(run_date) - dt.timedelta(days=0)).isoformat()

def fixed_reference_date(run_date: str) -> str:
    return (dt.date.fromisoformat(run_date) - dt.timedelta(days=1)).isoformat()

def test_reference_date_is_the_prior_day_not_today():
    run_date = "2026-08-10"

    broken = broken_reference_date(run_date)
    assert broken == run_date, "sanity check: broken behavior returns today as 'yesterday'"

    fixed = fixed_reference_date(run_date)
    assert fixed == "2026-08-09", f"Expected reference date to be the prior day, got {fixed}"
    assert fixed != run_date, "Fix must not compare a partition against itself"

if __name__ == "__main__":
    test_reference_date_is_the_prior_day_not_today()
    print("PASS: stability check reference date is no longer today's own partition")
