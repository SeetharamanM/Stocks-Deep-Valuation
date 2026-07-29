import json
from src.screener_parser import parse_screener
from src.web_data import MarketData
from src.valuation_pack import build_pack

def test_pack_is_json_serialisable_and_complete():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9,
                    source={k:"manual" for k in ["price","market_cap","low_52w","high_52w","beta"]})
    pack = build_pack(fin, md, sector="non-financial", rf=0.069, erp=0.055)
    s = json.dumps(pack)
    for key in ["base","relative","bands","returns","dcf","reverse_dcf","meta"]:
        assert key in pack
    assert pack["meta"]["sector"] == "non-financial"

def test_dcf_not_fabricated_when_normalised_fcff_negative():
    # Aurionpro's normalised FCFF (NOPAT + Dep - 3yr-avg capex - dWC) is
    # negative given its current heavy capex/acquisition phase. The DCF
    # must be marked non-viable with a disclosed reason and the raw inputs
    # recorded -- never silently clamped to a small positive number.
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    pack = build_pack(fin, md, sector="non-financial", rf=0.069, erp=0.055)
    dcf = pack["dcf"]
    if dcf["base_fcff"] is not None and dcf["base_fcff"] <= 0:
        assert dcf["viable"] is False
        assert "reason" in dcf
        assert pack["reverse_dcf"]["available"] is False
    else:
        assert dcf["viable"] is True

def test_meta_prefers_market_price_over_stale_xlsx_price():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=999.0, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    pack = build_pack(fin, md, sector="non-financial", rf=0.069, erp=0.055)
    assert pack["meta"]["current_price"] == 999.0
