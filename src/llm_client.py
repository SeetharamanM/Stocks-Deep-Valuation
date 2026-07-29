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


class LLMClient:
    def __init__(self, backend, model, api_key, base_url=None):
        self.backend = backend
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def _raw_complete(self, system, user):
        if not self.api_key:
            raise ValueError(
                f"No API key configured for backend {self.backend!r}. "
                "Set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY in your .env file."
            )
        if self.backend == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            msg = client.messages.create(
                model=self.model, max_tokens=8000, system=system,
                messages=[{"role": "user", "content": user}])
            return msg.content[0].text
        from openai import OpenAI
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


def get_client(backend, model, api_key, base_url=None):
    return LLMClient(backend, model, api_key, base_url)
