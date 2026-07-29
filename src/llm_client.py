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
# rather than parse the whole response.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_BRACES = re.compile(r"\{.*\}", re.DOTALL)


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
    # small a ceiling truncates the JSON mid-object.
    DEFAULT_MAX_TOKENS = 16000

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
            msg = client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system,
                messages=[{"role": "user", "content": user}])
            if getattr(msg, "stop_reason", None) == "max_tokens":
                raise ValueError(
                    f"The model hit the {self.max_tokens}-token output ceiling and its "
                    "reply was cut off mid-JSON. Raise LLM_MAX_TOKENS in .env and retry."
                )
            return _text_of(msg)
        OpenAI = _require("openai", "deepseek").OpenAI
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        r = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        return r.choices[0].message.content

    def complete_json(self, system, user):
        txt = self._raw_complete(system, user)
        fenced = _FENCE.search(txt)
        if fenced:
            txt = fenced.group(1)
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            braces = _BRACES.search(txt)
            if not braces:
                raise ValueError(f"No JSON object found in model response: {txt[:200]!r}")
            return json.loads(braces.group(0))


def get_client(backend, model, api_key, base_url=None, max_tokens=None):
    return LLMClient(backend, model, api_key, base_url, max_tokens)
