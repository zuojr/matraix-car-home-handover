"""Stable reusable input prefixes; never caches a model answer or tool outcome."""

import json

from .cohort import digest, native_context
from .identity import complete_parts

LAYOUT = "native-complete-deduplicated-prefix-v1"
PUT_SYSTEM = """你在使用车机/家居助手。按你的原生画像决定合法交互选择。
只返回JSON：{"act":"continue","style":"balanced"}。
act只能是continue（继续/回答当前问题）、clarify（要求澄清）或stop（结束）；
style只能是terse、balanced或polite。任务内取舍和主动/按需条件优先于背景属性。
事实、数字和授权由程序返回；不要添加字段、改变事实或执行工具。
你的耐心、信任、技术熟悉度和理解习惯可以影响继续、澄清或结束的选择。
"""


def compact(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def put_messages(case, plan, plan_path):
    narrative, residual, coverage = complete_parts(case, plan, plan_path)
    identity = narrative
    if residual:
        identity += (
            "\nAdditional original identity attributes (including source defaults):\n"
            + compact(residual)
        )
    card = {
        "case_id": case["id"],
        "source_persona_id": case["source_persona_id"],
        "condition": case["persona"],
        "current_facts": case["facts"],
        "stable_profile": case["profile"],
        "situation": case["initial_message"],
        "precedence": "fixed task facts/consent > assigned current condition > background attributes",
    }
    messages = [
        {"role": "system", "content": PUT_SYSTEM},
        {"role": "system", "content": identity},
        {"role": "user", "content": compact(card)},
    ]
    audit = {
        "layout": LAYOUT,
        "common_prefix_sha256": digest(messages[:1]),
        "persona_prefix_sha256": digest(messages[:2]),
        "initial_prompt_characters": sum(len(m["content"]) for m in messages),
        "coverage": coverage,
        "model_answer_cache": False,
    }
    legacy_card = {
        "persona": native_context(case),
        "current_facts": case["facts"],
        "stable_profile": case["profile"],
        "situation": case["initial_message"],
    }
    audit["previous_layout_characters"] = len(narrative + "\n" + PUT_SYSTEM) + len(
        json.dumps(legacy_card, ensure_ascii=False)
    )
    audit["character_reduction"] = (
        audit["previous_layout_characters"] - audit["initial_prompt_characters"]
    )
    audit["character_counts_are_not_token_or_fee_estimates"] = True
    audit["source_dimensions_sha256"] = digest(case["native_persona"]["dimensions"])
    return messages, audit


def public_view(view):
    """One representation per visible field; raw wire response stays in artifacts."""
    return {
        key: view[key]
        for key in ("reply", "pendingUserRequest", "terminal")
        if key in view
    }
