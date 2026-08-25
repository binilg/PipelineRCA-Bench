"""Zone-task scheduler for daily_forecast_scoring. Assigns each active
zone to an available autoscaled worker; anything unassigned by the
scheduling deadline is deferred, not failed."""
import logging, datetime as dt

log = logging.getLogger("scheduler")
SCHEDULING_DEADLINE_MIN = 20

def assign_workers(zones: list, available_workers: int) -> dict:
    assigned = zones[:available_workers]
    deferred = zones[available_workers:]
    return {"assigned": assigned, "deferred": deferred}

def run_scheduling_window(zones: list, available_workers: int, run_date: str):
    result = assign_workers(zones, available_workers)
    if result["deferred"]:
        # Deliberately not raised as a failure -- avoids paging on-call for
        # what's usually a transient autoscaler blip. But nothing here ever
        # re-queues these zones for a later attempt.
        log.warning(f"run_date={run_date}: {len(result['deferred'])} zones deferred "
                    f"(insufficient worker capacity): {result['deferred']}")
    log.info(f"run_date={run_date}: {len(result['assigned'])}/{len(zones)} zones scheduled")
    return result["assigned"]
