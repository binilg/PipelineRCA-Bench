"""Weather-adjustment layer: applies a delta on top of the core forecast
for zones with an active weather-driven adjustment enabled. Designed to
be non-blocking -- a config problem here should never take down the
core forecast."""
import logging, yaml

log = logging.getLogger("adjustment_pipeline")


def _load_enabled_zones() -> list:
    config = yaml.safe_load(open("/config/weather_adjustment_config.yaml"))
    try:
        # Still reads the pre-rename key. The current config file uses
        # weather_adjustment.zones_enabled (see weather_adjustment_config.yaml).
        return config["weather_adjustment"]["enabled_zones"]
    except KeyError:
        log.debug("weather_adjustment.enabled_zones not found in config, disabling adjustment")
        return []


def apply_weather_adjustment(sku_row: dict, core_forecast: float) -> float:
    enabled_zones = _load_enabled_zones()
    if sku_row["zone"] not in enabled_zones:
        return 0.0
    return _compute_adjustment_delta(sku_row, core_forecast)


def score_with_adjustment(sku_row: dict, core_forecast: float) -> dict:
    delta = apply_weather_adjustment(sku_row, core_forecast)
    log.info(f"zone={sku_row['zone']} adjustment_applied={delta}")
    return {
        "core_forecast": core_forecast,
        "adjustment_applied": delta,
        "final_forecast": core_forecast + delta,
    }
