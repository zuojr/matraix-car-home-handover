"""Source-dated per-role usage repricing; no account balance or invoice claims."""

from urllib.parse import urlsplit

SOURCES = {
    "gpt-6.1-sol": {
        "provider": "OpenAI",
        "model": "gpt-6.1-sol",
        "checked_date": "2026-10-23",
        "currency": "USD",
        "unit": "per_million_tokens",
        "source": "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
        "mode": "standard short-context; default 30-minute cache writes",
        "off_peak": {
            "cache_hit": 0.10,
            "cache_miss": 2.0,
            "cache_write": 2.50,
            "output": 10.0,
        },
        "peak": {
            "cache_hit": 0.10,
            "cache_miss": 2.0,
            "cache_write": 2.50,
            "output": 10.0,
        },
    },
    "deepseek-flash": {
        "provider": "DeepSeek",
        "model": "deepseek-flash",
        "checked_date": "2026-10-23",
        "currency": "USD",
        "unit": "per_million_tokens",
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "off_peak": {
            "cache_hit": 0.003,
            "cache_miss": 0.15,
            "cache_write": 0.15,
            "output": 0.6,
        },
        "peak": {
            "cache_hit": 0.006,
            "cache_miss": 0.30,
            "cache_write": 0.30,
            "output": 1.2,
        },
    },
    "gpt-5.6-sol": {
        "provider": "OpenAI",
        "model": "gpt-5.6-sol",
        "checked_date": "2026-10-23",
        "currency": "USD",
        "unit": "per_million_tokens",
        "source": "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        "mode": "standard short-context; default 30-minute cache writes",
        "off_peak": {
            "cache_hit": 0.40,
            "cache_miss": 4.0,
            "cache_write": 5.0,
            "output": 20.0,
        },
        "peak": {
            "cache_hit": 0.40,
            "cache_miss": 4.0,
            "cache_write": 5.0,
            "output": 20.0,
        },
    },
}


def pricing_for(config):
    model = config["model"]
    host = urlsplit(config["base_url"]).hostname
    if (host, model) in {
        ("api.deepseek.com", "deepseek-flash"),
        ("api.openai.com", "gpt-5.6-sol"),
        ("api.openai.com", "gpt-6.1-sol"),
    }:
        return SOURCES[model]
    return None


def usage_cost(usage, pricing, period):
    if "prompt_tokens" not in usage or "completion_tokens" not in usage:
        return None
    p, o = usage["prompt_tokens"], usage["completion_tokens"]
    details = usage.get("prompt_tokens_details") or {}
    h = usage.get("prompt_cache_hit_tokens", details.get("cached_tokens"))
    w = details.get("cache_write_tokens")
    rates = pricing[period]
    # Long-context Sol price applies to the full request, not only its excess.
    input_scale = (
        2 if pricing["model"] in {"gpt-5.6-sol", "gpt-6.1-sol"} and p > 272000 else 1
    )
    output_scale = 1.5 if input_scale == 2 else 1
    if h is None:
        low, high = (
            p * rates["cache_hit"],
            p * max(rates["cache_miss"], rates["cache_write"]),
        )
    else:
        if not 0 <= h <= p or (w is not None and not 0 <= w <= p - h):
            raise ValueError("Inconsistent reported cache token counts")
        if w is None:
            low = h * rates["cache_hit"] + (p - h) * rates["cache_miss"]
            high = h * rates["cache_hit"] + (p - h) * max(
                rates["cache_miss"], rates["cache_write"]
            )
        else:
            low = high = (
                h * rates["cache_hit"]
                + w * rates["cache_write"]
                + (p - h - w) * rates["cache_miss"]
            )
    # Reasoning tokens are already included in completion_tokens: never add twice.
    output = o * rates["output"] * output_scale
    return {
        "lower": (low * input_scale + output) / 1e6,
        "upper": (high * input_scale + output) / 1e6,
    }
