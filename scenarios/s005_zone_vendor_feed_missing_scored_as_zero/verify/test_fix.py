"""
Verification for s005. A proposed fix passes if a zone with no landed
actuals feed is NOT scored as if it had zero sales -- it should be
flagged/skipped or imputed from history, not silently defaulted to 0.0.
Stub harness; replace mocks with real hooks when the harness is built.
"""

def broken_join_and_fill(catalog_zones: list, landed_zones: set, actuals: dict) -> dict:
    return {z: actuals.get(z, 0.0) for z in catalog_zones}  # <- missing feed -> 0.0

def fixed_join_and_fill(catalog_zones: list, landed_zones: set, actuals: dict) -> dict:
    result = {}
    for z in catalog_zones:
        if z not in landed_zones:
            raise MissingFeedError(f"No actuals feed landed for zone {z}")
        result[z] = actuals[z]
    return result

class MissingFeedError(Exception):
    pass

def test_missing_zone_feed_is_not_silently_zeroed():
    catalog_zones = ["Z_N", "Z_NE", "Z_S", "Z_SE", "Z_SW", "Z_NW"]
    landed_zones = {"Z_N", "Z_NE", "Z_S", "Z_SE", "Z_NW"}  # Z_SW missing
    actuals = {"Z_N": 114220, "Z_NE": 98410, "Z_S": 121880, "Z_SE": 105332, "Z_NW": 61004}

    broken = broken_join_and_fill(catalog_zones, landed_zones, actuals)
    assert broken["Z_SW"] == 0.0, "sanity check on broken behavior"

    raised = False
    try:
        fixed_join_and_fill(catalog_zones, landed_zones, actuals)
    except MissingFeedError:
        raised = True

    assert raised, (
        "Fix must not silently score a zone with no landed feed as zero "
        "sales -- it should raise/flag so the zone is skipped or imputed "
        "from history instead."
    )

if __name__ == "__main__":
    test_missing_zone_feed_is_not_silently_zeroed()
    print("PASS: a zone with no landed actuals feed is no longer silently scored as zero")
