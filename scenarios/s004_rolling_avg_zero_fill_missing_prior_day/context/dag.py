"""daily_forecast_scoring -- scores demand models nightly using a 3-day
trailing average of actuals as a demand-level feature."""
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd, logging
from feature_loader import trailing_avg

def build_features(model_id: str, zone: str, run_date: str):
    return {
        "trailing_3d_avg": trailing_avg(zone, run_date, window_days=3),
    }

def score_all_models(**ctx):
    run_date = ctx["ds"]
    log = logging.getLogger("score_all_models")
    registry = pd.read_csv("/config/model_registry.csv").query("active")
    log.info(f"Run started. run_date={run_date}")
    rows = []
    for row in registry.itertuples():
        feats = build_features(row.model_id, row.zone, run_date)
        rows.append(_score_one(row.model_id, feats, run_date))
    log.info("Scoring complete. status=SUCCESS")
    return pd.concat(rows, ignore_index=True)

with DAG("daily_forecast_scoring", schedule_interval="@daily") as dag:
    score = PythonOperator(task_id="score_all_models", python_callable=score_all_models)
