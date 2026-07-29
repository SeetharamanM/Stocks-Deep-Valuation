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
    REQUEST_TIMEOUT = 900.0

    def __init__(self, backend, model, api_key, base_url=None, max_tokens=None):
        self.backend = backend
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS

    def _call_claude(self, system, user, budget):
        anthropic = _require("anthropic", "claude")
        client = anthropic.Anthropic(api_key=self.api_key,
                                     timeout=self.REQUEST_TIMEOUT)
        # Streaming is mandatory at these budgets: the SDK refuses a
        # non-streaming request that could exceed its ten-minute cap.
        with client.messages.stream(
                model=self.model, max_tokens=budget, system=system,
                messages=[{"role": "user", "content": user}]) as stream:
            msg = stream.get_final_message()
        truncated = getattr(msg, "stop_reason", None) == "max_tokens"
        return _text_of(msg) if not truncated else "", truncated

    def _call_openai_compatible(self, system, user, budget):
        OpenAI = _require("openai", "deepseek").OpenAI
        client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                        timeout=self.REQUEST_TIMEOUT)
        r = client.chat.completions.create(
            model=self.model, max_tokens=budget,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        choice = r.choices[0]
        truncated = getattr(choice, "finish_reason", None) == "length"
        return (choice.message.content or ""), truncated

    def _complete_at(self, system, user, budget):
        if not self.api_key:
            raise ValueError(
                f"No API key configured for backend {self.backend!r}. "
                "Set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY in your .env file."
            )
        call = self._call_claude if self.backend == "claude" else self._call_openai_compatible
        return call(system, user, budget)

    def _raw_complete(self, system, user):
        """Single completion at the configured budget, escalating on truncation."""
        budget = self.max_tokens
        while True:
            text, truncated = self._complete_at(system, user, budget)
            if not truncated:
                return text
            if budget >= self.MAX_TOKENS_CAP:
                raise ValueError(
                    f"The model hit the {budget}-token output ceiling even after "
                    "escalation, and its reply was cut off mid-JSON. The request is "
                    "too large for a single response; reduce the qualitative context "
                    "or the number of sections per narrative batch."
                )
            budget = min(budget * 2, self.MAX_TOKENS_CAP)

    @staticmethod
    def _parse(txt):
        for candidate in _json_candidates(txt):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def complete_json(self, system, user):
        """Complete and parse, escalating the budget while the reply is cut off.

        A backend does not always set a truncation flag: a reply can open with
        a valid '{' and simply stop mid-object. Unparseable output that looks
        like the start of JSON is therefore treated as truncation and retried
        at a larger budget, rather than reported as "answered in prose".
        """
        budget = self.max_tokens
        while True:
            txt, flagged = self._complete_at(system, user, budget)
            parsed = self._parse(txt)
            at_cap = budget >= self.MAX_TOKENS_CAP
            if parsed is not None and not flagged:
                return parsed
            if parsed is not None:
                # Parseable but the backend flagged truncation: content may be
                # semantically incomplete, so retry unless there is no headroom.
                if at_cap:
                    return parsed
                budget = min(budget * 2, self.MAX_TOKENS_CAP)
                continue
            looks_truncated = flagged or txt.lstrip().startswith(("{", "```"))
            if not looks_truncated:
                raise ValueError(
                    "No JSON object found in the model response. The model appears "
                    "to have answered in prose instead of the requested JSON. "
                    f"Response began: {txt[:300]!r} ... and ended: {txt[-300:]!r}"
                )
            if budget >= self.MAX_TOKENS_CAP:
                raise ValueError(
                    f"The reply was still cut off mid-JSON at the {budget}-token "
                    "ceiling. Reduce the number of sections per narrative batch "
                    f"or the qualitative context. Reply ended: {txt[-300:]!r}"
                )
            budget = min(budget * 2, self.MAX_TOKENS_CAP)


def get_client(backend, model, api_key, base_url=None, max_tokens=None):
    return LLMClient(backend, model, api_key, base_url, max_tokens)
