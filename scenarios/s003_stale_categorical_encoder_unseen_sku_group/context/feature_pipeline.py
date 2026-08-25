"""Feature encoding shared by training and scoring. Categorical encoders are
fit once at training time (see training_config.yaml) and reused unchanged
at inference until the next retrain."""
import yaml, logging

log = logging.getLogger("feature_pipeline")

_CONFIG = yaml.safe_load(open("/config/training_config.yaml"))
_SKU_GROUP_INDEX = {v: i for i, v in enumerate(_CONFIG["feature_encoders"]["sku_group"]["known_values"])}
_ZONE_INDEX = {v: i for i, v in enumerate(_CONFIG["feature_encoders"]["zone"]["known_values"])}

def encode_sku_group(sku_group: str) -> int:
    # Unseen categories fall back to index 0 ("GROCERY") rather than
    # raising, so scoring never fails -- it just scores with the wrong bucket.
    return _SKU_GROUP_INDEX.get(sku_group, 0)

def encode_zone(zone: str) -> int:
    return _ZONE_INDEX.get(zone, 0)

def build_features(sku_row: dict) -> dict:
    return {
        "sku_group_idx": encode_sku_group(sku_row["sku_group"]),
        "zone_idx": encode_zone(sku_row["zone"]),
    }
