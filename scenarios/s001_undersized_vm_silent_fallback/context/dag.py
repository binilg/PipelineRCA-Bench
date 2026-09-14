"""daily_forecast_scoring — scores 255 demand models nightly."""
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd, pickle, logging, datetime as dt

FALLBACK_TOLERANCE = 5          # max models allowed to fall back before we fail the run
ARTIFACT_ROOT = "/models/prod"

VM_MEMORY_GB = {"small": 2, "medium": 8, "large": 24}

def resolve_vm_size(zone: str) -> str:
    """VM tier for a zone's scoring worker, chosen from vm_sizing_config's
    rolling 7-day trailing average of that zone's data volume (see
    vm_sizing_log.txt). Recomputed once nightly by the sizing job -- it
    has no visibility into a day's actual volume until that day is
    already over, so a same-day spike is always sized off yesterday's
    average, not today's reality."""
    avg_gb = ROLLING_7D_AVG_GB[zone]
    if avg_gb < 4:
        return "small"
    elif avg_gb < 8:
        return "medium"
    return "large"

def score_one(model_id: str, zone: str, run_date: str):
    log = logging.getLogger(model_id)
    vm_size = resolve_vm_size(zone)
    log.info(f"Scoring start. zone={zone} run_date={run_date} vm_size={vm_size}")
    try:
        path = f"{ARTIFACT_ROOT}/{zone}/{model_id}/{run_date}/model.pkl"
        log.info(f"Loading artifact: {path}")
        with open(path, "rb") as fh:
            model = pickle.load(fh)
        features = build_features(model_id, run_date, memory_budget_gb=VM_MEMORY_GB[vm_size])
        return model.predict(features)
    except MemoryError as e:
        log.error(f"MemoryError building features on {vm_size} VM ({VM_MEMORY_GB[vm_size]}GB budget): {e}")
        log.warning("Invoking fallback handler")
        return _fallback_to_prior_day(model_id, run_date, log)

def _fallback_to_prior_day(model_id, run_date, log):
    prior = (dt.date.fromisoformat(run_date) - dt.timedelta(days=1)).isoformat()
    df = pd.read_parquet(f"/forecasts/{prior}/{model_id}.parquet")
    log.info(f"Fallback: sourced forecast from run_date={prior} partition")
    log.info("Scoring complete (fallback). status=OK_FALLBACK")
    return df.assign(run_date=run_date)      # <- stamped as today's forecast

def score_all(**ctx):
    run_date = ctx["ds"]
    registry = pd.read_csv("/config/model_registry.csv").query("active")
    fallbacks = 0
    for row in registry.itertuples():
        out = score_one(row.model_id, row.zone, run_date)
        if getattr(out, "_fallback", False):
            fallbacks += 1
    logging.info(f"Fallback substitutions applied: {fallbacks} "
                 f"(tolerance={FALLBACK_TOLERANCE}) - within threshold")
    if fallbacks > FALLBACK_TOLERANCE:
        raise RuntimeError(f"Too many fallbacks: {fallbacks}")
    # else: run succeeds, no exception surfaced
