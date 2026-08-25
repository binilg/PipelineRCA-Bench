"""
Verification for s014. A proposed fix passes if the DAG's completeness
check catches a zone that's missing from output -- regardless of the
underlying reason (OOM-kill or otherwise) -- instead of silently
reporting overall SUCCESS.
Stub harness; replace mocks with real hooks when the harness is built.
"""

class IncompleteRunError(Exception):
    pass

def broken_finalize(active_zones: list, scored_zones: set) -> str:
    return "SUCCESS"  # doesn't check completeness at all

def fixed_finalize(active_zones: list, scored_zones: set) -> str:
    missing = set(active_zones) - scored_zones
    if missing:
        raise IncompleteRunError(f"Zones missing from output: {sorted(missing)}")
    return "SUCCESS"

def test_missing_zone_is_caught_before_reporting_success():
    active_zones = ["Z_N", "Z_NE", "Z_S", "Z_SE", "Z_SW", "Z_NW"]
    scored_zones = {"Z_N", "Z_NE", "Z_SE", "Z_SW", "Z_NW"}  # Z_S missing (OOM-killed)

    broken = broken_finalize(active_zones, scored_zones)
    assert broken == "SUCCESS", "sanity check: broken behavior reports success anyway"

    raised = False
    try:
        fixed_finalize(active_zones, scored_zones)
    except IncompleteRunError:
        raised = True

    assert raised, (
        "Fix must catch a zone missing from output before reporting overall "
        "SUCCESS, regardless of why that zone's task didn't complete."
    )

if __name__ == "__main__":
    test_missing_zone_is_caught_before_reporting_success()
    print("PASS: a silently-skipped zone is no longer masked by an overall SUCCESS status")
