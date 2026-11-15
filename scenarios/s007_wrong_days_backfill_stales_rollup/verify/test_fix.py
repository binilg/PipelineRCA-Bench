"""
Verification for s007. A proposed fix passes if (a) backfilling a single
date never silently reprocesses additional dates beyond what was
explicitly requested, and (b) when a backfill does touch dates already
consumed by weekly rollups, every affected week's rollup is re-triggered
-- not just the week containing the start date.
Stub harness; replace mocks with real hooks when the harness is built.
"""
import datetime as dt


def broken_dates_to_reprocess(start_date: str, days: int) -> list:
    start = dt.date.fromisoformat(start_date)
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]


def fixed_dates_to_reprocess(start_date: str, days: int) -> list:
    # A correct implementation treats an unqualified backfill call as a
    # single date unless a range is explicitly confirmed.
    if days > 1:
        raise ValueError(
            "Backfilling more than one date requires explicit --confirm-range"
        )
    return [start_date]


def _week_start(date: str) -> str:
    d = dt.date.fromisoformat(date)
    return (d - dt.timedelta(days=d.weekday())).isoformat()  # Monday


def broken_rollups_to_rerun(start_date: str, reprocessed: list) -> set:
    # Runbook behavior: re-run only the week containing the intended date.
    return {_week_start(start_date)}


def fixed_rollups_to_rerun(start_date: str, reprocessed: list) -> set:
    # Dependency-aware: every week whose partitions were overwritten.
    return {_week_start(d) for d in reprocessed}


def test_backfill_does_not_silently_widen_the_date_range():
    broken = broken_dates_to_reprocess("2026-07-26", 4)
    assert broken == ["2026-07-26", "2026-07-27", "2026-07-28", "2026-07-29"], (
        "sanity check on broken behavior"
    )

    raised = False
    try:
        fixed_dates_to_reprocess("2026-07-26", 4)
    except ValueError:
        raised = True

    assert raised, (
        "Fix must not silently reprocess a wider date range than intended -- "
        "it should require explicit confirmation before touching more than "
        "one date."
    )


def test_every_affected_weekly_rollup_is_retriggered():
    reprocessed = broken_dates_to_reprocess("2026-07-26", 4)

    broken = broken_rollups_to_rerun("2026-07-26", reprocessed)
    assert broken == {"2026-07-20"}, "sanity check: runbook only refreshes week of 07-20"

    fixed = fixed_rollups_to_rerun("2026-07-26", reprocessed)
    assert fixed == {"2026-07-20", "2026-07-27"}, (
        f"Fix must re-trigger every week whose partitions were overwritten, got {fixed}"
    )


if __name__ == "__main__":
    test_backfill_does_not_silently_widen_the_date_range()
    test_every_affected_weekly_rollup_is_retriggered()
    print("PASS: backfill can't silently widen its range, and all affected rollups are re-triggered")
