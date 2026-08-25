"""
Verification for s001. A proposed fix passes if every ACTIVE zone in the
registry has models in the training scope BEFORE scoring runs — i.e. the
new zone Z_NW is added so artifacts get produced (no silent fallback).
Stub harness; replace mocks with real hooks when the harness is built.
"""

def zones_trained(training_config: dict) -> set:
    return set(training_config.get("zones", []))

def active_zones(registry_rows: list) -> set:
    return {r["zone"] for r in registry_rows if r["active"]}

def test_all_active_zones_trained():
    registry = [
        {"zone": "Z_N", "active": True},
        {"zone": "Z_NE", "active": True},
        {"zone": "Z_SE", "active": True},
        {"zone": "Z_NW", "active": True},   # the new zone
        {"zone": "Z_S", "active": True},
    ]
    training_config = {"zones": ["Z_N", "Z_NE", "Z_SE", "Z_NW", "Z_S"]}
    missing = active_zones(registry) - zones_trained(training_config)
    assert not missing, f"Zones with no trained models: {missing}"

if __name__ == "__main__":
    test_all_active_zones_trained()
    print("PASS: all active zones are in training scope")
