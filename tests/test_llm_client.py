from src.llm_client import get_client, LLMClient


def test_get_client_selects_backend():
    c = get_client(backend="claude", model="claude-opus-4-8", api_key="x")
    assert isinstance(c, LLMClient) and c.backend == "claude"
    d = get_client(backend="deepseek", model="deepseek-chat", api_key="y",
                   base_url="https://api.deepseek.com")
    assert d.backend == "deepseek"


def test_complete_is_mockable(monkeypatch):
    c = get_client(backend="claude", model="m", api_key="x")
    monkeypatch.setattr(c, "_raw_complete", lambda system, user: '{"ok": true}')
    out = c.complete_json(system="s", user="u")
    assert out == {"ok": True}


def test_complete_json_extracts_from_prose(monkeypatch):
    """Models often wrap JSON in prose or fences; we must still parse it."""
    c = get_client(backend="deepseek", model="m", api_key="x")
    monkeypatch.setattr(c, "_raw_complete",
                        lambda system, user: 'Sure!\n```json\n{"a": [1, 2]}\n```\nDone.')
    assert c.complete_json(system="s", user="u") == {"a": [1, 2]}


def test_missing_api_key_raises_before_network():
    c = get_client(backend="claude", model="m", api_key="")
    try:
        c._raw_complete("s", "u")
    except ValueError as e:
        assert "api key" in str(e).lower()
    else:
        raise AssertionError("expected ValueError for missing API key")
