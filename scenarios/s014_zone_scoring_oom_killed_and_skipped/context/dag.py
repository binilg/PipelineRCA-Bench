"""daily_forecast_scoring -- per-zone scoring tasks run best-effort; one
zone's failure doesn't block the others from shipping on time."""
import logging

log = logging.getLogger("score_all_models")

def score_zone_best_effort(zone: str, run_date: str) -> bool:
    try:
        _score_zone(zone, run_date)   # can be OOM-killed by the orchestrator mid-call
        return True
    except Exception as e:
        # Deliberate design: any zone-task failure is treated as a skip,
        # not a DAG failure, so 259 other zones aren't blocked. Doesn't
        # distinguish OOM-kill from any other failure, doesn't retry with
        # more memory, doesn't alert specifically on OOM.
        log.warning(f"zone={zone} skipped due to task failure: {e}")
        return False

def score_all_models(**ctx):
    run_date = ctx["ds"]
    zones = _active_zones()
    results = {z: score_zone_best_effort(z, run_date) for z in zones}
    ok = sum(results.values())
    log.info(f"Scoring complete. {ok}/{len(zones)} zones OK. status=SUCCESS")
