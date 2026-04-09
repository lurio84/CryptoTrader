"""Background monitor using APScheduler to run periodic alert checks."""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from alerts.telegram_bot import check_and_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _run_check():
    """Wrapper that runs the alert check and prints status."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info("Running alert check at %s", now)
    try:
        triggered = check_and_alert()
        if triggered:
            for alert in triggered:
                logger.info(
                    "ALERT TRIGGERED: %s (severity: %s)", alert["type"], alert["severity"]
                )
        else:
            logger.info("No alerts triggered. All clear.")
    except Exception as e:
        logger.error("Alert check failed: %s", e)


def start_monitor(interval_hours: int = 1):
    """Start the blocking scheduler that runs checks on an interval."""
    logger.info("Starting CryptoTrader Monitor (interval: %dh)", interval_hours)
    logger.info("Press Ctrl+C to stop.")

    # Run once immediately
    _run_check()

    scheduler = BlockingScheduler()
    scheduler.add_job(_run_check, "interval", hours=interval_hours)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Monitor stopped.")
