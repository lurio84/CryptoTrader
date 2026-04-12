"""Tests for cli/commands_projection.py (C5 sparplan-projection, C6 fx, C7 compare-periods)."""

import argparse
import importlib.util
from unittest.mock import MagicMock, patch

import pytest

_yfinance_available = importlib.util.find_spec("yfinance") is not None
skipif_no_yfinance = pytest.mark.skipif(not _yfinance_available, reason="yfinance not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# C5: sparplan-projection
# ---------------------------------------------------------------------------

class TestSparplanProjection:
    def test_basic_output_contains_totals(self, capsys):
        from cli.commands_projection import cmd_sparplan_projection
        cmd_sparplan_projection(_ns(months=12, ret=0.15))
        out = capsys.readouterr().out
        assert "SPARPLAN PROJECTION" in out
        assert "Total aportado" in out
        assert "Valor proyectado" in out
        assert "Multiplicador" in out

    def test_12_months_contains_year_1(self, capsys):
        from cli.commands_projection import cmd_sparplan_projection
        cmd_sparplan_projection(_ns(months=12, ret=0.10))
        out = capsys.readouterr().out
        # Month 12 should appear
        assert "12" in out

    def test_zero_return_equals_contributions(self, capsys):
        """At 0% return, projected value should roughly equal total contributed."""
        from cli.commands_projection import cmd_sparplan_projection
        cmd_sparplan_projection(_ns(months=12, ret=0.0))
        out = capsys.readouterr().out
        # Contributed = 12 * 140 = 1680; Python uses comma as thousands sep in {:,}
        assert "1,680" in out

    def test_invalid_months(self, capsys):
        from cli.commands_projection import cmd_sparplan_projection
        cmd_sparplan_projection(_ns(months=0, ret=0.15))
        out = capsys.readouterr().out
        assert "Error" in out

    def test_asset_breakdown_lists_all_6(self, capsys):
        from cli.commands_projection import cmd_sparplan_projection
        cmd_sparplan_projection(_ns(months=6, ret=0.10))
        out = capsys.readouterr().out
        for asset in ("BTC", "ETH", "SP500", "SEMICONDUCTORS", "REALTY_INCOME", "URANIUM"):
            assert asset in out


# ---------------------------------------------------------------------------
# C6: fx
# ---------------------------------------------------------------------------

FRED_CSV_FIXTURE = """observation_date,DEXUSEU
2026-01-01,1.05
2026-02-01,1.06
2026-03-01,1.07
2026-03-12,1.08
2026-03-13,1.09
2026-03-14,1.10
"""


class TestFxCommand:
    def _mock_fred_response(self):
        mock_resp = MagicMock()
        mock_resp.text = FRED_CSV_FIXTURE
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_basic_output_contains_spot(self, capsys):
        from cli.commands_projection import cmd_fx
        with patch("requests.get", return_value=self._mock_fred_response()):
            cmd_fx(_ns(pair="EURUSD"))
        out = capsys.readouterr().out
        assert "EUR/USD" in out
        assert "1.10" in out  # spot rate

    def test_output_contains_ath_atl(self, capsys):
        from cli.commands_projection import cmd_fx
        with patch("requests.get", return_value=self._mock_fred_response()):
            cmd_fx(_ns(pair="EURUSD"))
        out = capsys.readouterr().out
        assert "ATH" in out
        assert "ATL" in out

    def test_http_error_is_handled(self, capsys):
        from cli.commands_projection import cmd_fx
        with patch("requests.get", side_effect=Exception("connection refused")):
            cmd_fx(_ns(pair="EURUSD"))
        out = capsys.readouterr().out
        assert "Error" in out

    def test_output_contains_30d_change(self, capsys):
        from cli.commands_projection import cmd_fx
        with patch("requests.get", return_value=self._mock_fred_response()):
            cmd_fx(_ns(pair="EURUSD"))
        out = capsys.readouterr().out
        assert "30d" in out


# ---------------------------------------------------------------------------
# C7: compare-periods
# ---------------------------------------------------------------------------

class TestComparePeriods:
    def _make_price_series(self, name: str, n: int = 30, start: float = 100.0):
        import pandas as pd
        dates = pd.date_range("2020-01-01", periods=n, freq="D")
        # Use a list (not a Series) to avoid index-alignment NaN issues when
        # passing to pd.Series with a DatetimeIndex.
        prices = pd.Series(
            [start * (1.005 ** i) for i in range(n)],
            index=dates,
            name=name,
        )
        return prices

    def _patch_yf(self, prices_asset, prices_sp):
        """Patch yfinance.download to return mock price DataFrames."""
        import pandas as pd

        call_count = [0]

        def _download(ticker, start, end, interval, progress, auto_adjust):
            call_count[0] += 1
            if "USD" in ticker or ticker in ("SPY", "SOXX", "O", "URA"):
                if ticker == "SPY":
                    prices = prices_sp
                else:
                    prices = prices_asset
            else:
                prices = prices_asset
            # yfinance returns DataFrame with "Close" column
            return pd.DataFrame({"Close": prices})

        return patch("yfinance.download", side_effect=_download)

    @skipif_no_yfinance
    def test_basic_comparison_output(self, capsys):
        from cli.commands_projection import cmd_compare_periods
        p1 = self._make_price_series("BTC")
        p2 = self._make_price_series("BTC", start=200.0)
        sp = self._make_price_series("SPY")

        with self._patch_yf(p1, sp):
            cmd_compare_periods(_ns(asset="BTC", p1="2020-01-01:2020-02-01", p2="2021-01-01:2021-02-01"))
        out = capsys.readouterr().out
        assert "COMPARE-PERIODS" in out
        assert "BTC" in out
        assert "Retorno total" in out

    def test_invalid_period_format(self, capsys):
        from cli.commands_projection import cmd_compare_periods
        cmd_compare_periods(_ns(asset="BTC", p1="20200101-20210101", p2="2021-01-01:2022-01-01"))
        out = capsys.readouterr().out
        assert "Error" in out

    def test_invalid_asset(self, capsys):
        from cli.commands_projection import cmd_compare_periods
        cmd_compare_periods(_ns(asset="DOGECOIN", p1="2020-01-01:2021-01-01", p2="2021-01-01:2022-01-01"))
        out = capsys.readouterr().out
        assert "Error" in out

    @skipif_no_yfinance
    def test_delta_shown_when_both_periods_valid(self, capsys):
        from cli.commands_projection import cmd_compare_periods
        p = self._make_price_series("BTC")
        sp = self._make_price_series("SPY")

        with self._patch_yf(p, sp):
            cmd_compare_periods(_ns(asset="BTC", p1="2020-01-01:2020-02-01", p2="2021-01-01:2021-02-01"))
        out = capsys.readouterr().out
        assert "Delta" in out
