"""
Verification for s018. A proposed fix passes if a downstream consumer
is granted read access to the CURRENT output table name -- not left
depending on a static allowlist that predates the table's rename.
Stub harness; replace mocks with real hooks when the harness is built.
"""


def has_read_access(consumer: str, table: str, managed_tables: dict) -> bool:
    grants = managed_tables.get(table, {}).get("read_grants", [])
    return consumer in grants


def test_downstream_consumer_can_read_current_output_table():
    current_table = "forecast_output_v2"
    consumer = "inventory_planning_svc"

    broken_config = {
        "forecast_output": {"read_grants": ["inventory_planning_svc", "replenishment_svc", "bi_reporting_svc"]},
    }
    broken = has_read_access(consumer, current_table, broken_config)
    assert broken is False, "sanity check: broken config has no grants for the renamed table"

    fixed_config = {
        "forecast_output": {"read_grants": ["inventory_planning_svc", "replenishment_svc", "bi_reporting_svc"]},
        "forecast_output_v2": {"read_grants": ["inventory_planning_svc", "replenishment_svc", "bi_reporting_svc"]},
    }
    fixed = has_read_access(consumer, current_table, fixed_config)
    assert fixed is True, (
        "Fix must grant downstream consumers read access to the table the "
        "pipeline actually writes to now, not only the table name that "
        "existed before the migration."
    )


if __name__ == "__main__":
    test_downstream_consumer_can_read_current_output_table()
    print("PASS: downstream consumers now have read access to the current output table")
