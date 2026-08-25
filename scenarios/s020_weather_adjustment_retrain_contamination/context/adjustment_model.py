"""Weather-adjustment model: retrains weekly on a trailing window of
per-zone (core_forecast - actual) residuals, and applies the learned
correction to the current week's core forecast. No anomaly exclusion,
no magnitude cap, no event-tied decay."""
import pandas as pd, logging

log = logging.getLogger("adjustment_model")

TRAILING_WINDOW_WEEKS = 6


def load_trailing_residuals(zone: str, as_of_week: str) -> pd.DataFrame:
    """Every week's residual is weighted equally -- no distinction
    between 'ordinary week' and 'week with a known one-off anomaly'."""
    return _read_residuals(zone, weeks=TRAILING_WINDOW_WEEKS, as_of=as_of_week)


def retrain_zone_correction(zone: str, as_of_week: str) -> float:
    residuals = load_trailing_residuals(zone, as_of_week)
    correction = residuals["pct_residual"].mean()
    log.info(f"zone={zone} as_of={as_of_week} retrained correction={correction:.3f} "
             f"(over {len(residuals)} weeks, no anomaly exclusion, no magnitude cap)")
    return correction  # no clamping, no decay, no expiration logic anywhere


def apply_adjustment(zone: str, core_forecast: float, as_of_week: str) -> float:
    correction = retrain_zone_correction(zone, as_of_week)
    return core_forecast * (1 + correction)
