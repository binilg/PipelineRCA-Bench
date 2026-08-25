"""upload_to_partner_feed -- ships the finished forecast file to a partner
and notifies them via webhook that it's ready to ingest."""
import logging, requests

def notify_partner_webhook(run_date: str):
    log = logging.getLogger("notify_partner_webhook")
    # Fires unconditionally, every attempt -- no idempotency key, no gate
    # on whether the upload actually succeeds afterward.
    requests.post(
        "https://partner.example.com/hooks/forecast-ready",
        json={"run_date": run_date, "feed": "daily_forecast"},
        timeout=10,
    )
    log.info(f"Notified partner webhook for run_date={run_date}")

def upload_to_partner_feed(**ctx):
    run_date = ctx["ds"]
    log = logging.getLogger("upload_to_partner_feed")
    notify_partner_webhook(run_date)
    log.info(f"Uploading forecast file for run_date={run_date}")
    _transfer_file(run_date, timeout_s=60)   # can time out
    log.info("Upload complete. status=SUCCESS")
