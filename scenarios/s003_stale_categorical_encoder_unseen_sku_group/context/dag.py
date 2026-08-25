"""daily_forecast_scoring -- scores per-zone demand models nightly.
Each zone has one model that scores every active SKU in that zone;
sku_group is one of the categorical features fed to the model."""
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd, pickle, logging
from feature_pipeline import build_features

ARTIFACT_ROOT = "/models/prod"

def score_zone(zone: str, run_date: str, catalog: pd.DataFrame):
    log = logging.getLogger(f"score_zone.{zone}")
    with open(f"{ARTIFACT_ROOT}/{zone}/model.pkl", "rb") as fh:
        model = pickle.load(fh)
    skus = catalog.query("zone == @zone")
    feats = [build_features(row) for row in skus.to_dict("records")]
    preds = model.predict(feats)
    log.info(f"zone={zone} scored {len(skus)} SKUs. status=SUCCESS")
    return skus.assign(forecast=preds, run_date=run_date)

def score_all_models(**ctx):
    run_date = ctx["ds"]
    log = logging.getLogger("score_all_models")
    registry = pd.read_csv("/config/model_registry.csv").query("active")
    catalog = pd.read_csv("/config/sku_catalog.csv")
    log.info(f"Run started. run_date={run_date}")
    log.info(f"SKU catalog loaded: {len(catalog)} active SKUs across {len(registry)} zone models")
    frames = [score_zone(row.zone, run_date, catalog) for row in registry.itertuples()]
    out = pd.concat(frames, ignore_index=True)
    log.info(f"Scoring complete. {len(out)} rows. status=SUCCESS")
    return out

def write_forecast_partition(**ctx):
    df = ctx["ti"].xcom_pull(task_ids="score_all_models")
    run_date = ctx["ds"]
    log = logging.getLogger("write_forecast_partition")
    log.info(f"Writing forecast partition: /warehouse/forecasts/run_date={run_date} ({len(df)} rows)")
    df.to_parquet(f"/warehouse/forecasts/run_date={run_date}")
    log.info("Write complete. status=SUCCESS")

with DAG("daily_forecast_scoring", schedule_interval="@daily") as dag:
    score = PythonOperator(task_id="score_all_models", python_callable=score_all_models)
    write = PythonOperator(task_id="write_forecast_partition", python_callable=write_forecast_partition)
    score >> write
