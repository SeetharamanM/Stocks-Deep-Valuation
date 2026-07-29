from src.metrics import justified_pb

def test_justified_pb():
    pb = justified_pb(roe=0.16, g=0.08, coe=0.14)
    assert abs(pb - ((0.16-0.08)/(0.14-0.08))) < 1e-9
    assert justified_pb(roe=0.16, g=0.14, coe=0.14) is None
