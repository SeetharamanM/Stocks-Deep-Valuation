from src.metrics import triangulate, scenario_expected_value

def test_triangulate_weighted_blend():
    methods = [{"name":"DCF","value":1620,"weight":0.5},
               {"name":"Relative","value":1050,"weight":0.3},
               {"name":"P/B","value":1180,"weight":0.2}]
    r = triangulate(methods)
    assert abs(r["blended"] - (1620*0.5 + 1050*0.3 + 1180*0.2)) < 1e-6
    assert r["low"] == 1050 and r["high"] == 1620

def test_scenario_ev():
    scen = [{"name":"Bear","value":1020,"prob":0.25},
            {"name":"Base","value":1577,"prob":0.55},
            {"name":"Bull","value":1980,"prob":0.20}]
    r = scenario_expected_value(scen, current_price=1248)
    assert abs(r["expected_value"] - (1020*0.25+1577*0.55+1980*0.20)) < 1e-6
    assert "upside_pct" in r

def test_triangulate_drops_none_and_renormalises():
    methods = [{"name":"DCF","value":None,"weight":0.5},
               {"name":"Relative","value":1050,"weight":0.3},
               {"name":"P/B","value":1180,"weight":0.2}]
    r = triangulate(methods)
    assert "DCF" in r["dropped"]
    expected_blend = (1050*0.3 + 1180*0.2) / (0.3+0.2)
    assert abs(r["blended"] - expected_blend) < 1e-6
    assert abs(r["total_weight"] - 0.5) < 1e-9

def test_scenario_prob_sum_flagged():
    scen = [{"name":"Bear","value":1020,"prob":0.25},
            {"name":"Base","value":1577,"prob":0.55},
            {"name":"Bull","value":1980,"prob":0.10}]  # sums to 0.90
    r = scenario_expected_value(scen, current_price=1248)
    assert abs(r["prob_sum"] - 0.90) < 1e-9
    assert r["prob_sum_ok"] is False
