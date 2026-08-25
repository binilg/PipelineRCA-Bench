"""Numeric feature scaling shared by training and scoring. Scaler
statistics are fit once at training time (see training_config.yaml) and
reused unchanged at inference."""
import pickle, logging

log = logging.getLogger("feature_pipeline")

with open("/models/prod/scalers/avg_unit_price_scaler.pkl", "rb") as fh:
    _PRICE_SCALER = pickle.load(fh)   # fit at training time: mean=1500.0, std=150.0 (cents)

def scale_avg_unit_price(raw_value: float) -> float:
    # No unit or range validation -- any float is passed straight through.
    return (raw_value - _PRICE_SCALER.mean_) / _PRICE_SCALER.std_

def build_features(sku_row: dict) -> dict:
    return {
        "avg_unit_price_z": scale_avg_unit_price(sku_row["avg_unit_price"]),
    }
