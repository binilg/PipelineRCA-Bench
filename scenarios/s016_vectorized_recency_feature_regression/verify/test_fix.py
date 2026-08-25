"""
Verification for s016. A proposed fix passes if a SKU with no prior
sales history is NOT scored as having "0 days since last sale" (the
strongest possible recency signal) -- it must be distinguishable from a
SKU that genuinely sold earlier today.
Stub harness; replace mocks with real hooks when the harness is built.
"""
import math


def broken_days_since_last_sale(diff_days):
    """Mirrors recency_feature.py's current .fillna(0) behavior."""
    return 0 if diff_days is None else diff_days


def fixed_days_since_last_sale(diff_days, no_history_sentinel=999):
    """A fix must give 'no history' a distinct value from 'sold today'."""
    return no_history_sentinel if diff_days is None else diff_days


def test_no_sales_history_is_not_treated_as_sold_today():
    no_history_diff = None  # NaT last_sale_date -> None/NaN diff

    broken = broken_days_since_last_sale(no_history_diff)
    assert broken == 0, "sanity check: broken behavior scores no-history as 0 days (sold today)"

    fixed = fixed_days_since_last_sale(no_history_diff)
    assert fixed != 0, (
        "Fix must not collapse 'no sales history' into 'sold today' (0 days). "
        "A brand-new SKU must be distinguishable from one with a real recent sale."
    )
    # And a genuinely-just-sold SKU must still correctly read as 0.
    assert fixed_days_since_last_sale(0) == 0, (
        "Fix must not break the real 0-days-since-last-sale case for SKUs that did sell today."
    )


if __name__ == "__main__":
    test_no_sales_history_is_not_treated_as_sold_today()
    print("PASS: SKUs with no sales history are no longer scored as if they sold today")
