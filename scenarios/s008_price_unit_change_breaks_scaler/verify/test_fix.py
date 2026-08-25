"""
Verification for s008. A proposed fix passes if a numeric feature value
that's wildly outside the scaler's training-time distribution (e.g. a
100x unit-scale mismatch) is flagged/rejected before scoring, rather
than silently scaled and passed to the model.
Stub harness; replace mocks with real hooks when the harness is built.
"""

TRAINING_MEAN = 1500.0   # cents
TRAINING_STD = 150.0     # cents


class OutOfDistributionError(Exception):
    pass


def broken_scale(raw_value, mean=TRAINING_MEAN, std=TRAINING_STD):
    return (raw_value - mean) / std   # no validation


def fixed_scale(raw_value, mean=TRAINING_MEAN, std=TRAINING_STD, max_abs_z=4.0):
    z = (raw_value - mean) / std
    if abs(z) > max_abs_z:
        raise OutOfDistributionError(
            f"avg_unit_price z-score {z:.2f} is far outside the training "
            f"distribution (|z| > {max_abs_z}) -- possible unit/scale drift"
        )
    return z


def test_out_of_distribution_price_is_flagged_not_silently_scaled():
    dollar_scale_value = 18.50  # what used to be ~1850 cents is now reported as $18.50

    broken_z = broken_scale(dollar_scale_value)
    assert broken_z < -9.0, "sanity check: broken scaling produces an extreme z-score silently"

    raised = False
    try:
        fixed_scale(dollar_scale_value)
    except OutOfDistributionError:
        raised = True

    assert raised, (
        "Fix must flag/reject a feature value whose scaled z-score falls far "
        "outside the training distribution instead of silently passing it "
        "through to the model."
    )

if __name__ == "__main__":
    test_out_of_distribution_price_is_flagged_not_silently_scaled()
    print("PASS: out-of-distribution avg_unit_price values are no longer silently scaled and scored")
