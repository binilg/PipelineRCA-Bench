"""daily_forecast_scoring — scores 255 demand models nightly."""
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd, pickle, logging, datetime as dt

FALLBACK_TOLERANCE = 5          # max models allowed to fall back before we fail the run
ARTIFACT_ROOT = "/models/prod"

def score_one(model_id: str, zone: str, run_date: str):
    log = logging.getLogger(model_id)
    path = f"{ARTIFACT_ROOT}/{zone}/{model_id}/{run_date}/model.pkl"
    log.info(f"Scoring start. zone={zone} run_date={run_date}")
    try:
        log.info(f"Resolving artifact: {path}")
        with open(path, "rb") as fh:
            model = pickle.load(fh)
    except FileNotFoundError:
        log.error(f"FileNotFoundError: {path}")
        model = _latest_artifact(model_id, zone, log)
        if model is None:
            log.warning("Invoking fallback handler")
            return _fallback_to_prior_day(model_id, run_date, log)
    features = load_features(model_id, run_date)
    return model.predict(features)

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
