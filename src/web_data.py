from dataclasses import dataclass, field

FIELDS = ["price", "market_cap", "low_52w", "high_52w", "beta"]

@dataclass
class MarketData:
    ticker: str
    price: float = None
    market_cap: float = None
    low_52w: float = None
    high_52w: float = None
    beta: float = None
    as_of: str = None
    source: dict = field(default_factory=dict)

def _yf_fetch(yf_ticker):
    import yfinance as yf
    t = yf.Ticker(yf_ticker)
    info = getattr(t, "fast_info", None) or {}
    hist = t.history(period="1y")
    out = {}
    # Drop rows with NaN Close (e.g. an in-progress/incomplete session row) so
    # we never surface NaN as a fabricated-looking price; treat it as missing.
    try: closes = hist["Close"].dropna()
    except Exception: closes = None
    try: out["price"] = float(closes.iloc[-1])
    except Exception: pass
    try: out["low_52w"] = float(closes.min()); out["high_52w"] = float(closes.max())
    except Exception: pass
    try: out["market_cap"] = float(info["market_cap"]) / 1e7  # to Cr
    except Exception: pass
    try: out["beta"] = float(t.info.get("beta"))
    except Exception: pass
    try: out["as_of"] = closes.index[-1].date().isoformat()
    except Exception: pass
    return out

def _suffix(exchange):
    return ".NS" if exchange.upper() == "NSE" else ".BO"

def build_market_data(ticker, exchange, overrides):
    overrides = overrides or {}
    fetched = {}
    if any(overrides.get(f) is None for f in FIELDS):
        try: fetched = _yf_fetch(ticker + _suffix(exchange)) or {}
        except Exception: fetched = {}
    md = MarketData(ticker=ticker)
    for f in FIELDS:
        if overrides.get(f) is not None:
            setattr(md, f, float(overrides[f])); md.source[f] = "manual"
        elif fetched.get(f) is not None:
            setattr(md, f, float(fetched[f])); md.source[f] = "yfinance"
        else:
            md.source[f] = "unavailable"
    md.as_of = overrides.get("as_of") or fetched.get("as_of")
    return md
