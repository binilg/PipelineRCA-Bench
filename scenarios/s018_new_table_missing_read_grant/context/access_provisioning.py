"""Nightly job that grants downstream service accounts read access to
pipeline output tables. Reads its target table list from a static
allowlist (access_provisioning_config.yaml) rather than the pipeline's
actual current output-table registry."""
import logging, yaml

log = logging.getLogger("access_provisioning")


def run_access_provisioning():
    config = yaml.safe_load(open("/config/access_provisioning_config.yaml"))
    for table in config["managed_tables"]:
        for consumer in config["managed_tables"][table]["read_grants"]:
            _grant_read(table, consumer)
            log.info(f"Granted read on {table} to {consumer}")
    log.info(f"Provisioning complete. {len(config['managed_tables'])} table(s) processed.")
    # Any table not present in managed_tables is silently untouched --
    # no warning, no error, nothing to signal a newly created table was
    # never added to this list.
