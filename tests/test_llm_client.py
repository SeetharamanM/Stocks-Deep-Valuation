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


def test_missing_sdk_names_the_running_interpreter(monkeypatch):
    """A missing package must not send the user to the wrong Python."""
    import sys

    def fake_import(name, *a, **k):
        raise ModuleNotFoundError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fake_import)
    c = get_client(backend="deepseek", model="m", api_key="key", base_url="u")
    try:
        c._raw_complete("s", "u")
    except ModuleNotFoundError as e:
        msg = str(e)
        assert "openai" in msg
        assert sys.executable in msg, "must name the interpreter actually running"
        assert "pip install" in msg
    else:
        raise AssertionError("expected ModuleNotFoundError")


class _Block:
    """Mimics an SDK content block: thinking blocks carry no .text."""
    def __init__(self, type_, text=None, thinking=None):
        self.type = type_
        if text is not None:
            self.text = text
        if thinking is not None:
            self.thinking = thinking


class _Msg:
    def __init__(self, blocks):
        self.content = blocks


class _Stream:
    """Context manager mimicking client.messages.stream(...)."""
    def __init__(self, msg):
        self._msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._msg


def test_extended_thinking_response_is_parsed(monkeypatch):
    """Reasoning models put a ThinkingBlock first; the text block follows."""
    import src.llm_client as mod

    class FakeMessages:
        def stream(self, **kw):
            return _Stream(_Msg([_Block("thinking", thinking="pondering the drivers..."),
                         _Block("text", text='{"rating": "HOLD"}')]))

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(mod, "_require",
                        lambda module, backend: type("M", (), {"Anthropic": FakeAnthropic}))
    c = get_client(backend="claude", model="claude-opus-5", api_key="k")
    assert c.complete_json("s", "u") == {"rating": "HOLD"}


def test_multiple_text_blocks_are_joined(monkeypatch):
    import src.llm_client as mod

    class FakeMessages:
        def stream(self, **kw):
            return _Stream(_Msg([_Block("thinking", thinking="..."),
                         _Block("text", text='{"a": 1,'),
                         _Block("text", text=' "b": 2}')]))

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(mod, "_require",
                        lambda module, backend: type("M", (), {"Anthropic": FakeAnthropic}))
    c = get_client(backend="claude", model="claude-opus-5", api_key="k")
    assert c.complete_json("s", "u") == {"a": 1, "b": 2}


def test_response_with_no_text_block_raises_clearly(monkeypatch):
    import src.llm_client as mod

    class FakeMessages:
        def stream(self, **kw):
            return _Stream(_Msg([_Block("thinking", thinking="only thinking")]))

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(mod, "_require",
                        lambda module, backend: type("M", (), {"Anthropic": FakeAnthropic}))
    c = get_client(backend="claude", model="claude-opus-5", api_key="k")
    try:
        c._raw_complete("s", "u")
    except ValueError as e:
        assert "no text" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


def test_get_client_forwards_max_tokens():
    import src.llm_client as mod
    c = get_client(backend="claude", model="m", api_key="k", max_tokens=48000)
    assert c.max_tokens == 48000
    default = get_client(backend="claude", model="m", api_key="k").max_tokens
    assert default == mod.LLMClient.DEFAULT_MAX_TOKENS


def test_persistent_truncation_escalates_then_reports_clearly(monkeypatch):
    """Escalation is bounded: it must stop at the cap with an actionable message."""
    import src.llm_client as mod
    budgets = []

    class FakeMessages:
        def stream(self, **kw):
            budgets.append(kw["max_tokens"])
            m = _Msg([_Block("text", text='{"partial": ')])
            m.stop_reason = "max_tokens"
            return _Stream(m)

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(mod, "_require",
                        lambda module, backend: type("M", (), {"Anthropic": FakeAnthropic}))
    c = get_client(backend="claude", model="m", api_key="k")
    try:
        c._raw_complete("s", "u")
    except ValueError as e:
        assert "cut off" in str(e).lower()
    else:
        raise AssertionError("expected ValueError on persistent truncation")
    assert budgets[0] == mod.LLMClient.DEFAULT_MAX_TOKENS
    assert budgets[-1] == mod.LLMClient.MAX_TOKENS_CAP
    assert len(budgets) < 8, "escalation must terminate, not loop"


def _client_returning(text, monkeypatch):
    c = get_client(backend="claude", model="m", api_key="k")
    monkeypatch.setattr(c, "_raw_complete", lambda system, user: text)
    return c


def test_json_found_when_a_non_json_fence_comes_first(monkeypatch):
    """The model often quotes source material in a fence before the answer."""
    reply = (
        "Here is the relevant transcript extract:\n\n"
        "```\ncoming quarters.\n\u2022\nOrder book remains robust and the company\n"
        "hopes to post strong product growth in FY2027.\n```\n\n"
        "Based on that, my assumptions:\n\n"
        '```json\n{"terminal_growth": 0.05, "model_choice": "DCF"}\n```\n'
    )
    c = _client_returning(reply, monkeypatch)
    assert c.complete_json("s", "u") == {"terminal_growth": 0.05, "model_choice": "DCF"}


def test_json_found_when_only_prose_fence_and_bare_json(monkeypatch):
    reply = (
        "```\nquoted material, not json\n```\n"
        'Final answer: {"rating": "HOLD", "fair_value": 620}'
    )
    c = _client_returning(reply, monkeypatch)
    assert c.complete_json("s", "u") == {"rating": "HOLD", "fair_value": 620}


def test_nested_braces_survive_extraction(monkeypatch):
    reply = 'Result:\n{"a": {"b": [1, 2]}, "c": "text with } brace"}\nDone.'
    c = _client_returning(reply, monkeypatch)
    assert c.complete_json("s", "u") == {"a": {"b": [1, 2]}, "c": "text with } brace"}


def test_unparseable_response_error_shows_the_tail_too(monkeypatch):
    c = _client_returning("no json at all here, just prose " * 20, monkeypatch)
    try:
        c.complete_json("s", "u")
    except ValueError as e:
        assert "no json" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


def test_truncation_retries_with_a_larger_budget(monkeypatch):
    """A cut-off reply should be retried automatically, not pushed onto the user."""
    import src.llm_client as mod
    attempts = []

    class FakeMessages:
        def stream(self, **kw):
            attempts.append(kw["max_tokens"])
            m = _Msg([_Block("text", text='{"ok": true}')])
            # truncate on the first, smaller budget only
            m.stop_reason = "max_tokens" if len(attempts) == 1 else "end_turn"
            return _Stream(m)

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(mod, "_require",
                        lambda module, backend: type("M", (), {"Anthropic": FakeAnthropic}))
    c = get_client(backend="claude", model="m", api_key="k", max_tokens=16000)
    assert c.complete_json("s", "u") == {"ok": True}
    assert attempts == [16000, 32000], f"expected one escalated retry, got {attempts}"


def test_truncation_gives_up_at_the_cap(monkeypatch):
    import src.llm_client as mod
    attempts = []

    class FakeMessages:
        def stream(self, **kw):
            attempts.append(kw["max_tokens"])
            m = _Msg([_Block("text", text='{"partial":')])
            m.stop_reason = "max_tokens"
            return _Stream(m)

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(mod, "_require",
                        lambda module, backend: type("M", (), {"Anthropic": FakeAnthropic}))
    c = get_client(backend="claude", model="m", api_key="k", max_tokens=32000)
    try:
        c._raw_complete("s", "u")
    except ValueError as e:
        assert "ceiling" in str(e).lower()
    else:
        raise AssertionError("expected ValueError once the cap is reached")
    assert attempts[-1] <= mod.LLMClient.MAX_TOKENS_CAP
