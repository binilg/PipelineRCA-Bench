"""daily_forecast_scoring — scores demand models nightly and publishes to the warehouse."""
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd, logging, datetime as dt

def score_all_models(**ctx):
    run_date = ctx["ds"]
    log = logging.getLogger("score_all_models")
    registry = pd.read_csv("/config/model_registry.csv").query("active")
    log.info(f"Run started. run_date={run_date}")
    log.info(f"Model registry loaded: {len(registry)} active models")
    rows = [_score_one(row.model_id, row.zone, run_date) for row in registry.itertuples()]
    log.info("Scoring complete. status=SUCCESS")
    return pd.concat(rows, ignore_index=True)

def write_forecast_partition(**ctx):
    run_date = ctx["ds"]
    log = logging.getLogger("write_forecast_partition")
    df = ctx["ti"].xcom_pull(task_ids="score_all_models")
    path = f"/warehouse/forecasts/run_date={run_date}"
    log.info(f"Writing forecast partition: {path} ({len(df)} rows)")
    df.to_parquet(path, mode="append")   # <- appends; no delete-before-write, no upsert key
    log.info("Write complete. status=SUCCESS")

def publish_to_warehouse(**ctx):
    run_date = ctx["ds"]
    log = logging.getLogger("publish_to_warehouse")
    log.info(f"Publishing partition run_date={run_date} to analytics warehouse")
    _push_to_warehouse_api(run_date, timeout_s=120)   # network call; can time out
    log.info("Publish complete. status=SUCCESS")

with DAG("daily_forecast_scoring", schedule_interval="@daily") as dag:
    score = PythonOperator(task_id="score_all_models", python_callable=score_all_models)
    write = PythonOperator(task_id="write_forecast_partition", python_callable=write_forecast_partition)
    publish = PythonOperator(task_id="publish_to_warehouse", python_callable=publish_to_warehouse)
    score >> write >> publish
