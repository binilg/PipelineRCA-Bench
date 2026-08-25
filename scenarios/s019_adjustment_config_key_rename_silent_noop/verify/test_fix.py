"""
Verification for s019. A proposed fix passes if the adjustment config
loader reads the CURRENT key name and a genuinely missing/misnamed key
is surfaced (raised or visibly logged) rather than silently treated as
"adjustment disabled everywhere."
Stub harness; replace mocks with real hooks when the harness is built.
"""


class AdjustmentConfigError(Exception):
    pass


def broken_load_enabled_zones(config: dict) -> list:
    try:
        return config["weather_adjustment"]["enabled_zones"]  # stale key
    except KeyError:
        return []  # silent fallback, no visible signal


def fixed_load_enabled_zones(config: dict) -> list:
    try:
        return config["weather_adjustment"]["zones_enabled"]  # current key
    except KeyError as e:
        raise AdjustmentConfigError(f"weather_adjustment config missing expected key: {e}")


def test_current_config_key_is_read_correctly():
    current_config = {"weather_adjustment": {"zones_enabled": ["Z_N", "Z_SE"], "max_lookback_days": 14}}

    broken = broken_load_enabled_zones(current_config)
    assert broken == [], "sanity check: broken loader finds nothing under the stale key name"

    fixed = fixed_load_enabled_zones(current_config)
    assert fixed == ["Z_N", "Z_SE"], (
        "Fix must read the current config key name so enabled zones are "
        "actually picked up, not silently treated as an empty list."
    )


def test_genuinely_missing_key_is_surfaced_not_silenced():
    malformed_config = {"weather_adjustment": {"max_lookback_days": 14}}  # no zones key at all

    raised = False
    try:
        fixed_load_enabled_zones(malformed_config)
    except AdjustmentConfigError:
        raised = True
    assert raised, (
        "Fix must surface a genuinely missing config key (raise or alert), "
        "not silently fall back to a disabled/no-adjustment default."
    )


if __name__ == "__main__":
    test_current_config_key_is_read_correctly()
    test_genuinely_missing_key_is_surfaced_not_silenced()
    print("PASS: adjustment config now reads the current key and surfaces genuine misconfiguration")
