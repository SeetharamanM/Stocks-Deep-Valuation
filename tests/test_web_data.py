from src.web_data import build_market_data

def test_manual_overrides_win(monkeypatch):
    def boom(*a, **k): raise AssertionError("yfinance called")
    monkeypatch.setattr("src.web_data._yf_fetch", boom)
    md = build_market_data(ticker="AURIONPRO", exchange="NSE",
                           overrides={"price": 735.4, "market_cap": 4076.37,
                                      "low_52w": 500.0, "high_52w": 1600.0,
                                      "beta": 0.9})
    assert md.price == 735.4 and md.beta == 0.9
    assert md.source["price"] == "manual"

def test_yfinance_fills_gaps(monkeypatch):
    monkeypatch.setattr("src.web_data._yf_fetch",
        lambda t: {"price": 700.0, "market_cap": 3900.0,
                   "low_52w": 480.0, "high_52w": 1550.0, "beta": 1.1})
    md = build_market_data(ticker="AURIONPRO", exchange="NSE",
                           overrides={"price": 735.4})
    assert md.price == 735.4 and md.source["price"] == "manual"
    assert md.beta == 1.1 and md.source["beta"] == "yfinance"

def test_unavailable_is_none(monkeypatch):
    monkeypatch.setattr("src.web_data._yf_fetch", lambda t: {})
    md = build_market_data(ticker="XXXX", exchange="NSE", overrides={})
    assert md.price is None and md.source["price"] == "unavailable"
