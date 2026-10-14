"""Per-model token prices ($ per million tokens), used for cost logging and the daily spend cap."""

# Claude API list prices, October 2026 (platform.claude.com/docs/en/about-claude/pricing).
# Haiku 5.5's rates are for prompts up to 100k tokens; this bot's prompts stay far below that.
# Cache writes are the 5-minute rate.
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.10, "cache_write": 2.5},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25},
}
# Unknown models are costed at the most expensive listed rate, so the spend cap errs on the safe side.
FALLBACK = max(PRICES.values(), key=lambda p: p["output"])


def cost_usd(usage: dict, model: str) -> float:
    p = PRICES.get(model, FALLBACK)
    return sum((usage.get(k) or 0) * p[k] for k in ("input", "output", "cache_read", "cache_write")) / 1e6
