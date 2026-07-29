"""Pluggable LLM backend.

The analysis layer talks to exactly one interface, `LLMClient.complete_json`,
so the choice between Claude and DeepSeek is a config decision rather than a
code change. The client never computes valuation figures -- it only supplies
judgment assumptions and prose. See src/analyst.py for how that boundary is
enforced.
"""

import json
import re

# Models wrap JSON in prose or markdown fences often enough that we extract
# rather than parse the whole response. A reply may contain several fences --
# quoted source material as well as the answer -- so every candidate is tried
# rather than committing to the first one found.
_JSON_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_ANY_FENCE = re.compile(r"```(?:[a-zA-Z0-9_-]*)\s*(.*?)```", re.DOTALL)


def _balanced_spans(text):
    """Yield top-level {...} spans, respecting nesting and quoted braces."""
    depth = start = 0
    in_string = escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1]


def _json_candidates(text):
    """Ordered best guesses at the JSON payload inside a model reply."""
    seen = set()
    for group in (_JSON_FENCE.findall(text), _ANY_FENCE.findall(text),
                  _balanced_spans(text), [text]):
        for cand in group:
            cand = cand.strip()
            if cand and cand not in seen:
                seen.add(cand)
                yield cand


def _require(module, backend):
    """Import a backend SDK, naming the exact interpreter if it is absent.

    Machines commonly have several Pythons (system, Anaconda, venv). A bare
    ModuleNotFoundError sends people to reinstall into the wrong one, so the
    message states which interpreter is actually running.
    """
    import importlib
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        import sys
        raise ModuleNotFoundError(
            f"The {backend!r} backend needs the {module!r} package, which is not "
            f"installed for the Python running this app ({sys.executable}). "
            f'Install it with:  "{sys.executable}" -m pip install {module}'
        ) from exc


def _text_of(message):
    """Concatenate the text blocks of an Anthropic response.

    Reasoning models emit a ThinkingBlock before the answer, so the first
    content block is not necessarily text and carries no `.text` attribute.
    Collect every text block rather than indexing blindly.
    """
    parts = [getattr(b, "text", None) for b in getattr(message, "content", [])
             if getattr(b, "type", None) == "text"]
    parts = [p for p in parts if p]
    if not parts:
        kinds = [getattr(b, "type", "?") for b in getattr(message, "content", [])]
        raise ValueError(
            "The model returned no text block; content blocks were: "
            f"{kinds or 'none'}. If the response was cut off mid-thought, the "
            "token budget may be too small for the requested reasoning."
        )
    return "".join(parts)


class LLMClient:
    # The narrative pass emits eleven HTML sections in one response, and on
    # reasoning models the thinking tokens draw from this same budget. Too
    # small a ceiling truncates the JSON mid-object, so start generously and
    # escalate automatically rather than making the user tune it by hand.
    DEFAULT_MAX_TOKENS = 32000
    MAX_TOKENS_CAP = 64000

    def __init__(self, backend, model, api_key, base_url=None, max_tokens=None):
        self.backend = backend
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS

    def _raw_complete(self, system, user):
        if not self.api_key:
            raise ValueError(
                f"No API key configured for backend {self.backend!r}. "
                "Set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY in your .env file."
            )
        if self.backend == "claude":
            anthropic = _require("anthropic", "claude")
            client = anthropic.Anthropic(api_key=self.api_key)
            budget = self.max_tokens
            while True:
                msg = client.messages.create(
                    model=self.model, max_tokens=budget, system=system,
                    messages=[{"role": "user", "content": user}])
                if getattr(msg, "stop_reason", None) != "max_tokens":
                    return _text_of(msg)
                if budget >= self.MAX_TOKENS_CAP:
                    raise ValueError(
                        f"The model hit the {budget}-token output ceiling even after "
                        "escalation, and its reply was cut off mid-JSON. The request is "
                        "too large for a single response; reduce the qualitative context "
                        "or lower the reasoning effort."
                    )
                budget = min(budget * 2, self.MAX_TOKENS_CAP)
        OpenAI = _require("openai", "deepseek").OpenAI
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        r = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        return r.choices[0].message.content

    def complete_json(self, system, user):
        txt = self._raw_complete(system, user)
        for candidate in _json_candidates(txt):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ValueError(
            "No JSON object found in the model response. The model may have "
            "answered in prose instead of the requested JSON. Response began: "
            f"{txt[:300]!r} ... and ended: {txt[-300:]!r}"
        )


def get_client(backend, model, api_key, base_url=None, max_tokens=None):
    return LLMClient(backend, model, api_key, base_url, max_tokens)
