"""daily_forecast_scoring -- builds features for the currently active
production model per the serving feature manifest, then scores."""
import yaml, pandas as pd, logging

log = logging.getLogger("score_all_models")

def load_serving_features() -> list:
    manifest = yaml.safe_load(open("/config/serving_feature_manifest.yaml"))
    return manifest["active_model_features"]

def build_feature_vector(sku_row: dict, expected_features: list) -> dict:
    vector = {f: sku_row.get(f) for f in expected_features}
    return vector

def score_sku(model, vector: dict) -> float:
    # Inference wrapper: any feature the model expects but that's missing
    # from the vector gets filled with 0 before scoring.
    filled = {k: (v if v is not None else 0) for k, v in vector.items()}
    return model.predict(filled)

def score_all_models(**ctx):
    run_date = ctx["ds"]
    expected_features = load_serving_features()
    catalog = pd.read_csv("/config/sku_catalog.csv")
    log.info(f"Run started. run_date={run_date}. Serving features: {expected_features}")
    model = _load_active_model()
    rows = [score_sku(model, build_feature_vector(r, expected_features))
            for r in catalog.to_dict("records")]
    log.info("Scoring complete. status=SUCCESS")
    return rows
