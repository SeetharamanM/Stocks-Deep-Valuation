import os
from dotenv import load_dotenv

load_dotenv()

def _f(name, default):
    v = os.getenv(name)
    return float(v) if v not in (None, "") else default

class Config:
    LLM_BACKEND = os.getenv("LLM_BACKEND", "claude")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
    LLM_MAX_TOKENS = int(_f("LLM_MAX_TOKENS", 32000))
    RISK_FREE_RATE = _f("RISK_FREE_RATE", 0.069)
    EQUITY_RISK_PREMIUM = _f("EQUITY_RISK_PREMIUM", 0.055)
    STATUTORY_TAX = _f("STATUTORY_TAX", 0.2517)

    def available_backends(self):
        b = []
        if self.ANTHROPIC_API_KEY: b.append("claude")
        if self.DEEPSEEK_API_KEY: b.append("deepseek")
        return b

config = Config()
