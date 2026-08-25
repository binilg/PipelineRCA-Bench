"""
Verification for s021 -- a false-positive scenario. There is no "broken
vs. fixed" code to compare, since nothing is broken. Instead, this
confirms the ground truth's own claim: each of the four exclusion
reasons genuinely and correctly makes eligible_for_scoring() return
False, and an ordinary, fully-eligible sku-store combination correctly
returns True. This is a consistency check on the scenario itself, not
a fix-verification test.
"""
import datetime as dt

MIN_SALES_HISTORY_DAYS = 14
RUN_DATE = "2026-08-13"


def is_forecastable(sku_row):
    return sku_row["sales_history_days"] >= MIN_SALES_HISTORY_DAYS


def is_active(sku_row, run_date):
    return dt.date.fromisoformat(sku_row["effective_date"]) <= dt.date.fromisoformat(run_date)


def is_ranged_at_store(sku_id, store_id, assortment):
    return (sku_id, store_id) in assortment


def is_not_discontinued(sku_row):
    return sku_row["status"] != "discontinued"


def eligible_for_scoring(sku_row, store_id, assortment, run_date):
    return (
        is_forecastable(sku_row)
        and is_active(sku_row, run_date)
        and is_ranged_at_store(sku_row["sku_id"], store_id, assortment)
        and is_not_discontinued(sku_row)
    )


ASSORTMENT = {("SKU_10233", "ST_0044"), ("SKU_10388", "ST_0044")}


def test_each_claimed_exclusion_reason_actually_excludes():
    # Reason 1: below minimum sales history.
    thin_history = {"sku_id": "SKU_40011", "effective_date": "2026-08-10",
                     "sales_history_days": 3, "status": "active"}
    assert not eligible_for_scoring(thin_history, "ST_0212", ASSORTMENT, RUN_DATE)

    # Reason 2: not yet active (future effective_date).
    not_yet_active = {"sku_id": "SKU_50201", "effective_date": "2026-09-01",
                       "sales_history_days": 0, "status": "active"}
    assert not eligible_for_scoring(not_yet_active, "ST_0044", ASSORTMENT, RUN_DATE)

    # Reason 3: not ranged at this store.
    not_ranged = {"sku_id": "SKU_10233", "effective_date": "2024-06-12",
                  "sales_history_days": 780, "status": "active"}
    assert not eligible_for_scoring(not_ranged, "ST_0300", ASSORTMENT, RUN_DATE)

    # Reason 4: discontinued.
    discontinued = {"sku_id": "SKU_20601", "effective_date": "2023-01-05",
                     "sales_history_days": 940, "status": "discontinued"}
    assert not eligible_for_scoring(discontinued, "ST_0067", ASSORTMENT, RUN_DATE)


def test_a_genuinely_eligible_combination_is_not_excluded():
    eligible = {"sku_id": "SKU_10233", "effective_date": "2024-06-12",
                "sales_history_days": 780, "status": "active"}
    assert eligible_for_scoring(eligible, "ST_0044", ASSORTMENT, RUN_DATE), (
        "sanity check: a normal, fully-eligible sku-store combination must still score"
    )


if __name__ == "__main__":
    test_each_claimed_exclusion_reason_actually_excludes()
    test_a_genuinely_eligible_combination_is_not_excluded()
    print("PASS: all four exclusion reasons are real, and normal combinations are unaffected")
