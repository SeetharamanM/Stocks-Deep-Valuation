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

def test_single_year_fcff_snapshot_disclosed_not_fabricated():
    # Aurionpro's single-year normalised FCFF snapshot (NOPAT + Dep -
    # 3yr-avg capex - dWC) is negative given its current heavy capex/
    # acquisition build-out phase. That figure is retained and disclosed
    # as-is (base_fcff, base_fcff_method) for transparency -- it is never
    # clamped to a fabricated small positive number.
    #
    # NOTE: this snapshot no longer gates DCF viability. Projecting one
    # build-out year's capex flat for perpetuity was the modelling bug this
    # change fixes (see test_aurionpro_dcf_is_viable_with_fading_capex):
    # the primary DCF is now the 5-year driver-based model with a fading
    # capex path, which can be -- and for Aurionpro is -- viable even
    # though this single-year snapshot is negative.
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    pack = build_pack(fin, md, sector="non-financial", rf=0.069, erp=0.055)
    dcf = pack["dcf"]
    assert dcf["base_fcff"] is not None and dcf["base_fcff"] <= 0
    assert "base_fcff_method" in dcf
    assert dcf["viable"] is True

def test_meta_prefers_market_price_over_stale_xlsx_price():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=999.0, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    pack = build_pack(fin, md, sector="non-financial", rf=0.069, erp=0.055)
    assert pack["meta"]["current_price"] == 999.0

def test_aurionpro_dcf_is_viable_with_fading_capex():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37, beta=0.9, source={})
    pack = build_pack(fin, md, sector="non-financial", rf=0.069, erp=0.055)
    assert pack["dcf"]["viable"] is True
    assert pack["dcf"]["fair_value_per_share"] > 0
    assert len(pack["dcf"]["projection"]) == 5
    # tax fades toward statutory, not held at the concessional 16%
    assert pack["dcf"]["assumptions"]["drivers"][-1]["tax_rate"] > 0.20
    # reverse DCF now available
    assert pack["reverse_dcf"]["available"] is True
