"""
Verification for s009. A proposed fix passes if a feature the active
model expects but that's absent from the serving feature manifest
causes an explicit failure/flag at scoring time, rather than being
silently filled with a default value.
Stub harness; replace mocks with real hooks when the harness is built.
"""

class MissingServingFeatureError(Exception):
    pass

def broken_build_vector(sku_row: dict, expected_features: list) -> dict:
    return {f: (sku_row.get(f) if sku_row.get(f) is not None else 0) for f in expected_features}

def fixed_build_vector(sku_row: dict, expected_features: list, model_declared_features: list) -> dict:
    missing = [f for f in model_declared_features if f not in expected_features]
    if missing:
        raise MissingServingFeatureError(
            f"Model expects {missing} but serving manifest doesn't compute them"
        )
    return {f: sku_row.get(f) for f in expected_features}

def test_missing_serving_feature_is_not_silently_zero_filled():
    sku_row = {"sku_group_idx": 0, "zone_idx": 2, "avg_unit_price_z": -0.3, "trailing_3d_avg": 15000}
    serving_manifest_features = ["sku_group_idx", "zone_idx", "avg_unit_price_z", "trailing_3d_avg"]
    model_declared_features = serving_manifest_features + ["promo_flag"]  # v5 needs promo_flag too

    broken = broken_build_vector(sku_row, model_declared_features)
    assert broken["promo_flag"] == 0, "sanity check: broken behavior silently zero-fills promo_flag"

    raised = False
    try:
        fixed_build_vector(sku_row, serving_manifest_features, model_declared_features)
    except MissingServingFeatureError:
        raised = True

    assert raised, (
        "Fix must raise/flag when the active model expects a feature the "
        "serving manifest doesn't compute, instead of silently scoring "
        "with a default-filled value."
    )

if __name__ == "__main__":
    test_missing_serving_feature_is_not_silently_zero_filled()
    print("PASS: a model-vs-serving-manifest feature gap is no longer silently zero-filled")
