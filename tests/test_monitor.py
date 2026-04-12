"""Tests for alerts.monitor (background scheduler)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock


def test_run_check_invokes_check_and_alert_and_returns_no_raise():
    from alerts import monitor

    with patch("alerts.monitor.check_and_alert", return_value=[]) as mock_check:
        monitor._run_check()
        mock_check.assert_called_once()


def test_run_check_logs_triggered_alerts_without_raising():
    from alerts import monitor

    triggered = [
        {"type": "btc_crash", "severity": "red", "sent": True},
        {"type": "funding_negative", "severity": "orange", "sent": False},
    ]
    with patch("alerts.monitor.check_and_alert", return_value=triggered):
        monitor._run_check()  # should not raise


def test_run_check_swallows_check_exception():
    """If check_and_alert raises, _run_check should log and continue (no propagation)."""
    from alerts import monitor

    with patch("alerts.monitor.check_and_alert", side_effect=RuntimeError("api down")):
        # No assertion needed -- the test passes if no exception escapes.
        monitor._run_check()


def test_start_monitor_configures_scheduler_and_initial_run():
    from alerts import monitor

    fake_scheduler = MagicMock()
    fake_scheduler.start.side_effect = KeyboardInterrupt  # break the blocking loop cleanly

    with (
        patch("alerts.monitor.BlockingScheduler", return_value=fake_scheduler),
        patch("alerts.monitor.check_and_alert", return_value=[]),
    ):
        monitor.start_monitor(interval_hours=2)

    fake_scheduler.add_job.assert_called_once()
    args, kwargs = fake_scheduler.add_job.call_args
    assert args[1] == "interval"
    assert kwargs.get("hours") == 2
    fake_scheduler.start.assert_called_once()
