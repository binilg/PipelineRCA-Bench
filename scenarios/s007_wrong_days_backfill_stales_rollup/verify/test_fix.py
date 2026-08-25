"""
Verification for s007. A proposed fix passes if backfilling a single
date never silently reprocesses additional dates beyond what was
explicitly requested, and if it does reprocess a date already consumed
by a downstream rollup, that rollup gets invalidated/re-triggered.
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

def test_backfill_does_not_silently_widen_the_date_range():
    broken = broken_dates_to_reprocess("2026-07-28", 4)
    assert broken == ["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"], (
        "sanity check on broken behavior"
    )

    raised = False
    try:
        fixed_dates_to_reprocess("2026-07-28", 4)
    except ValueError:
        raised = True

    assert raised, (
        "Fix must not silently reprocess a wider date range than intended -- "
        "it should require explicit confirmation before touching more than "
        "one date."
    )

if __name__ == "__main__":
    test_backfill_does_not_silently_widen_the_date_range()
    print("PASS: backfill no longer silently widens the reprocessed date range")
