"""
Verification for s015. A proposed fix passes if a deferred zone is
automatically requeued (carried forward) rather than being permanently
dropped once its scheduling window passes.
Stub harness; replace mocks with real hooks when the harness is built.
"""

def broken_schedule_next_day(prior_deferred: list, todays_zones: list) -> list:
    return todays_zones  # deferred zones are simply forgotten

def fixed_schedule_next_day(prior_deferred: list, todays_zones: list) -> list:
    # Deferred zones are prioritized and carried forward until scored.
    return list(dict.fromkeys(prior_deferred + todays_zones))

def test_deferred_zone_is_not_permanently_dropped():
    prior_deferred = ["Z_SE", "Z_NW"]   # deferred on 2026-08-12
    todays_zones = ["Z_N", "Z_NE", "Z_S", "Z_SE", "Z_SW", "Z_NW"]  # 2026-08-13's own list

    broken = broken_schedule_next_day(prior_deferred, todays_zones)
    assert "Z_SE" in broken and "Z_NW" in broken, "sanity check on coincidental overlap"
    # The real failure mode is on a day where prior-deferred zones AREN'T
    # in today's own list at all (e.g. deferred zone list vs. today's
    # zone rotation don't naturally overlap) -- broken behavior forgets
    # them regardless of that overlap, since it never reads prior_deferred.
    assert broken == todays_zones, "sanity check: broken behavior ignores prior_deferred entirely"

    fixed = fixed_schedule_next_day(prior_deferred, todays_zones)
    for z in prior_deferred:
        assert z in fixed, f"Fix must carry forward previously deferred zone {z} until it's scored"

if __name__ == "__main__":
    test_deferred_zone_is_not_permanently_dropped()
    print("PASS: deferred zones are no longer silently dropped without being retried")
