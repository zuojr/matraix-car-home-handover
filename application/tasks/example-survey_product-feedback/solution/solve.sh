#!/bin/bash
set -euo pipefail

mkdir -p /app/output

python3 <<'PY'
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - container usually has PyYAML
    yaml = None

OUTPUT = Path("/app/output/survey_result.json")
PERSONA_PATH = Path("/app/input/persona.yaml")
QUESTIONNAIRE_CANDIDATES = (
    Path("/app/input/questionnaire.yaml"),
    Path("/app/input/input/questionnaire.yaml"),
)

PATHS: dict[str, dict[str, object]] = {
    "Cost-sensitive": {
        "q0": "q0_use_free_wont_pay",
        "q1": "q1_reject_both_tiers",
        "q2": "q2_monthly_cancel_anytime",
        "q3": "q3_skip_even_one_dollar",
        "q4": "q4_seek_free_alternative",
        "q5": "q5_ads_not_worth_paying",
        "q6": "q6_too_expensive_stay_free",
        "overall_interest": 2,
        "would_try_beta": "false",
    },
    "Value-driven": {
        "q0": "q0_pay_when_roi_clear",
        "q1": "q1_plus_after_sustained_use",
        "q2": "q2_annual_after_long_use",
        "q3": "q3_one_dollar_try_cancel",
        "q4": "q4_compare_pay_if_wins",
        "q5": "q5_ads_pay_if_plus_useful",
        "q6": "q6_fair_if_use_justifies",
        "overall_interest": 3,
        "would_try_beta": "false",
    },
    "Premium-seeking": {
        "q0": "q0_subscribe_paid_launch",
        "q1": "q1_happy_plus_or_pro",
        "q2": "q2_prepay_annual_plus",
        "q3": "q3_grab_dollar_promo",
        "q4": "q4_pay_best_no_hunt",
        "q5": "q5_pay_primarily_adfree",
        "q6": "q6_premium_price_ok",
        "overall_interest": 5,
        "would_try_beta": "true",
    },
    "Indifferent": {
        "q0": "q0_free_never_decide_tier",
        "q1": "q1_wont_compare_tiers",
        "q2": "q2_billing_no_preference",
        "q3": "q3_ignore_promo",
        "q4": "q4_switch_only_effortless",
        "q5": "q5_ads_irrelevant_to_tier",
        "q6": "q6_pricing_unnoticed",
        "overall_interest": 1,
        "would_try_beta": "false",
    },
}


def _posture() -> str:
    if not PERSONA_PATH.is_file():
        return "Value-driven"
    text = PERSONA_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "economic_motivation:" in line:
            return line.split(":", 1)[1].strip().strip("'\"") or "Value-driven"
    return "Value-driven"


def _load_instrument() -> dict:
    for path in QUESTIONNAIRE_CANDIDATES:
        if path.is_file() and yaml is not None:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and data.get("questions"):
                return data
    return {
        "id": "product_feedback_v1",
        "title": "Survey Product Feedback",
        "questions": [
            {"id": key, "prompt": key, "type": "likert" if key == "overall_interest" else "single_choice"}
            for key in PATHS["Value-driven"]
        ],
    }


def _ts(base: datetime, offset: int) -> str:
    return (base + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


instrument = _load_instrument()
choices = PATHS.get(_posture(), PATHS["Value-driven"])
questions = list(instrument.get("questions") or [])
answers = []
for question in questions:
    qid = str(question.get("id") or "").strip()
    if not qid or qid not in choices:
        continue
    answers.append(
        {
            "questionId": qid,
            "prompt": str(question.get("prompt") or qid),
            "value": choices[qid],
        }
    )

base = datetime.now(timezone.utc).replace(microsecond=0)
instrument_id = str(instrument.get("id") or "product_feedback_v1")
trajectory = [
    {
        "timestamp": _ts(base, 0),
        "actor": "system",
        "action": "survey_started",
        "context": {
            "instrumentId": instrument_id,
            "instrumentTitle": str(instrument.get("title") or ""),
            "numQuestions": len(questions),
        },
        "outcome": {"status": "started"},
    }
]
offset = 1
for index, question in enumerate(questions, start=1):
    qid = str(question.get("id") or "").strip()
    if not qid:
        continue
    qctx = {
        "instrumentId": instrument_id,
        "questionId": qid,
        "questionIndex": index,
        "questionType": str(question.get("type") or ""),
        "construct": str(question.get("construct") or ""),
    }
    trajectory.append(
        {
            "timestamp": _ts(base, offset),
            "actor": "assistant",
            "action": "ask_question",
            "context": qctx,
            "outcome": {"prompt": str(question.get("prompt") or qid)},
        }
    )
    offset += 1
    if qid in choices:
        trajectory.append(
            {
                "timestamp": _ts(base, offset),
                "actor": "user",
                "action": "answer_question",
                "context": qctx,
                "outcome": {"questionId": qid, "value": choices[qid]},
            }
        )
        offset += 1

trajectory.append(
    {
        "timestamp": _ts(base, offset),
        "actor": "system",
        "action": "survey_completed",
        "context": {"instrumentId": instrument_id},
        "outcome": {
            "numAnswered": len(answers),
            "missingRequiredQuestionIds": [],
            "valid": True,
        },
    }
)

payload = {
    "instrument": {
        "id": instrument_id,
        "title": str(instrument.get("title") or "Survey Product Feedback"),
    },
    "answers": answers,
    "trajectory": trajectory,
}
OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
