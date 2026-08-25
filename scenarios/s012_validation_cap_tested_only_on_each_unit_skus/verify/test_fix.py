"""
Verification for s012. A proposed fix passes if a legitimate high
forecast for a case-unit SKU is not silently clipped to the same cap
used for each-unit SKUs.
Stub harness; replace mocks with real hooks when the harness is built.
"""

CAPS_BY_UNIT_TYPE = {"EACH": 5000, "CASE": 12000}

def broken_validate_and_clip(sku_id, forecast_qty, unit_type, cap=5000):
    return min(forecast_qty, cap)  # one global cap regardless of unit_type

def fixed_validate_and_clip(sku_id, forecast_qty, unit_type):
    cap = CAPS_BY_UNIT_TYPE.get(unit_type, CAPS_BY_UNIT_TYPE["EACH"])
    return min(forecast_qty, cap)

def test_case_unit_sku_is_not_clipped_to_each_unit_cap():
    forecast_qty = 8412.0
    unit_type = "CASE"

    broken = broken_validate_and_clip("SKU_30011", forecast_qty, unit_type)
    assert broken == 5000, "sanity check: broken behavior clips case-unit SKU to the each-unit cap"

    fixed = fixed_validate_and_clip("SKU_30011", forecast_qty, unit_type)
    assert fixed == forecast_qty, (
        f"Fix must not clip a legitimate case-unit forecast ({forecast_qty}) "
        f"down to the each-unit cap (5000); got {fixed}"
    )

if __name__ == "__main__":
    test_case_unit_sku_is_not_clipped_to_each_unit_cap()
    print("PASS: case-unit SKUs are no longer silently clipped to the each-unit validation cap")
