from src.screener_parser import parse_screener
from src.metrics import relative_multiples, historical_bands

def test_relative_multiples():
    fin = parse_screener("Aurionpro Sol.xlsx")
    rm = relative_multiples(fin)
    assert abs(rm["pe_current"] - (735.4 / (209.31 / 5.53))) < 0.3
    assert rm["pb_current"] > 0
    assert "ev_ebitda_current" in rm
    assert rm["fcf_yield"] is not None

def test_historical_bands():
    fin = parse_screener("Aurionpro Sol.xlsx")
    hb = historical_bands(fin)
    assert hb["median_pe_10y"] > 0
    assert hb["sd_pe"] >= 0
    assert "current_z" in hb
    assert hb["upper_band"] > hb["median_pe_10y"] > hb["lower_band"]

def test_band_skew_disclosure():
    fin = parse_screener("Aurionpro Sol.xlsx")
    hb = historical_bands(fin)
    assert hb["lower_band_display"] >= 0.0
    assert hb["band_skewed"] is True   # Aurionpro's P/E series is right-skewed
