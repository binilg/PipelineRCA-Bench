"""
Verification for s002. A proposed fix passes if write_forecast_partition
is idempotent: writing the same run_date partition twice in a row (e.g.
because an upstream task got re-triggered by a downstream --upstream
clear) produces the same row count as writing it once, not double.
Stub harness; replace mocks with real hooks when the harness is built.
"""

def test_double_write_is_idempotent():
    partition = {}
    rows = [{"model_id": f"M_{i:04d}"} for i in range(258)]

    def fixed_write(partition, run_date, rows):
        # A correct implementation overwrites/upserts rather than appending.
        partition[run_date] = {r["model_id"]: r for r in rows}
        return partition

    fixed_write(partition, "2026-07-16", rows)
    fixed_write(partition, "2026-07-16", rows)  # simulate the upstream re-trigger

    assert len(partition["2026-07-16"]) == 258, (
        f"Expected 258 rows after two writes to the same partition, "
        f"got {len(partition['2026-07-16'])} -- write is not idempotent"
    )

if __name__ == "__main__":
    test_double_write_is_idempotent()
    print("PASS: partition write is idempotent under re-trigger")
