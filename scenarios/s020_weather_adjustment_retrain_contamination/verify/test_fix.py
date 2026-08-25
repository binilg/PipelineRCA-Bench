"""
Verification for s020. A proposed fix passes if a one-off anomalous
week does not keep pulling the learned correction toward a large,
sustained negative value across multiple retrains after the event ends.
Stub harness; replace mocks with real hooks when the harness is built.
"""


def broken_retrain(weekly_residuals: list, anomaly_weeks: set) -> float:
    """Every week weighted equally, no exclusion, no cap."""
    return sum(weekly_residuals) / len(weekly_residuals)


def fixed_retrain(weekly_residuals: list, anomaly_weeks: set, max_abs_correction: float = 0.02) -> float:
    """Excludes flagged anomaly weeks from the training window and caps
    the resulting correction magnitude."""
    normal = [r for i, r in enumerate(weekly_residuals) if i not in anomaly_weeks]
    if not normal:
        return 0.0
    correction = sum(normal) / len(normal)
    return max(-max_abs_correction, min(max_abs_correction, correction))


def test_anomalous_week_does_not_dominate_the_learned_correction():
    # index 1 is the storm week: a large one-off negative residual.
    weekly_residuals = [-0.02, -0.14, -0.01, -0.02, -0.01, -0.02]
    anomaly_weeks = {1}

    broken = broken_retrain(weekly_residuals, anomaly_weeks)
    assert broken < -0.03, "sanity check: broken retrain lets the storm week pull the average well past normal-week noise"

    fixed = fixed_retrain(weekly_residuals, anomaly_weeks)
    assert abs(fixed) <= 0.02, (
        "Fix must exclude the flagged anomalous week from the retrain window "
        "and/or cap the resulting adjustment magnitude, so a one-off event "
        "cannot produce a large, sustained correction across many retrains."
    )


if __name__ == "__main__":
    test_anomalous_week_does_not_dominate_the_learned_correction()
    print("PASS: a one-off anomalous week no longer dominates the learned adjustment")
