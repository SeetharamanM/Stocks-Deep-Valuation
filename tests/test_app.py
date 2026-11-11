import io
import os

from app import create_app, _float_or_none


def test_index_get():
    client = create_app().test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Deep Valuation" in r.data
    assert b"Screener.in export" in r.data


def test_float_or_none_handles_blanks_and_commas():
    assert _float_or_none("") is None
    assert _float_or_none(None) is None
    assert _float_or_none("  ") is None
    assert _float_or_none("1,234.5") == 1234.5
    assert _float_or_none("not a number") is None


def _form():
    return {"stock_name": "Aurionpro Solutions", "ticker": "AURIONPRO",
            "exchange": "NSE", "sector": "non-financial", "llm_backend": "claude"}


def test_run_route_invokes_pipeline(tmp_path):
    calls = {}

    def fake_pipeline(form, files, out_dir):
        calls["stock"] = form["stock_name"]
        calls["xlsx"] = files["xlsx"].filename
        p = tmp_path / "Aurionpro_Solutions_Valuation.html"
        p.write_text("<html>report</html>", encoding="utf-8")
        return str(p)

    client = create_app(pipeline=fake_pipeline).test_client()
    data = _form()
    data["xlsx"] = (io.BytesIO(b"fake"), "Aurionpro Sol.xlsx")
    r = client.post("/run", data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert calls["stock"] == "Aurionpro Solutions"
    assert calls["xlsx"] == "Aurionpro Sol.xlsx"


def test_pipeline_failure_renders_error_page_not_500_trace(tmp_path):
    def boom(form, files, out_dir):
        raise ValueError("No API key configured for backend 'claude'.")

    client = create_app(pipeline=boom).test_client()
    data = _form()
    data["xlsx"] = (io.BytesIO(b"fake"), "x.xlsx")
    r = client.post("/run", data=data, content_type="multipart/form-data")

    assert r.status_code == 500
    assert b"Report generation failed" in r.data
    assert b"No API key configured" in r.data


def test_index_offers_both_backends():
    r = create_app().test_client().get("/")
    assert b'value="claude"' in r.data and b'value="deepseek"' in r.data
    assert b'name="api_key"' in r.data


def _capture_get_client(monkeypatch):
    import src.llm_client as llm
    seen = {}

    def fake(backend, model, api_key, base_url=None, max_tokens=None):
        seen.update(backend=backend, model=model, key=api_key, base_url=base_url)
        return object()

    monkeypatch.setattr(llm, "get_client", fake)
    return seen


def test_build_client_uses_typed_deepseek_key_and_model(monkeypatch):
    from app import _build_client
    seen = _capture_get_client(monkeypatch)
    _build_client({"llm_backend": "deepseek", "api_key": " sk-typed ", "model": "deepseek-reasoner"})
    assert seen["backend"] == "deepseek"
    assert seen["key"] == "sk-typed"
    assert seen["model"] == "deepseek-reasoner"
    assert seen["base_url"]


def test_build_client_falls_back_to_configured_claude(monkeypatch):
    from app import _build_client
    from config import config
    seen = _capture_get_client(monkeypatch)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-conf")
    _build_client({"llm_backend": "claude"})
    assert seen["key"] == "sk-ant-conf" and seen["model"] == config.ANTHROPIC_MODEL


def test_build_client_without_any_key_errors(monkeypatch):
    import pytest
    from app import _build_client
    from config import config
    _capture_get_client(monkeypatch)
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    with pytest.raises(ValueError, match="No API key for DeepSeek"):
        _build_client({"llm_backend": "deepseek"})
