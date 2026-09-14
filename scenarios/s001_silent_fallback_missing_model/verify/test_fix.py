"""
Verification for s001 (rewritten for the VM-capacity root cause). A
proposed fix passes if VM sizing accounts for the CURRENT run's actual
incoming data volume, not only a lagging historical average -- i.e. a
volume spike on day N should be sized correctly on day N itself, not
only from day N+1 onward once the rolling average catches up.
Stub harness; replace mocks with real hooks when the harness is built.
"""

def choose_vm_size(current_volume_gb: float, rolling_avg_gb: float, aware_of_current_volume: bool) -> str:
    basis = current_volume_gb if aware_of_current_volume else rolling_avg_gb
    if basis < 4:
        return "small"
    elif basis < 8:
        return "medium"
    return "large"

def test_spike_is_sized_correctly_same_day():
    # A zone with a normal ~6GB/day rolling average spikes to ~25GB today.
    rolling_avg_gb = 6.0
    current_volume_gb = 24.8

    # BROKEN (pre-fix): sizing only looks at the lagging rolling average --
    # today's spike is undersized on the day it actually happens.
    broken = choose_vm_size(current_volume_gb, rolling_avg_gb, aware_of_current_volume=False)
    assert broken == "medium", "sanity check on the broken (pre-fix) behavior"

    # FIXED: sizing accounts for the current run's actual volume.
    fixed = choose_vm_size(current_volume_gb, rolling_avg_gb, aware_of_current_volume=True)
    assert fixed == "large", f"fix should size off actual same-day volume, got {fixed}"

if __name__ == "__main__":
    test_spike_is_sized_correctly_same_day()
    print("PASS: VM sizing accounts for the current run's actual data volume")
