"""Measured cache/usage/latency and explicit linear planning scenarios, no model calls."""

import json
from pathlib import Path
from statistics import mean

from .cohort import write_new
from .pricing import pricing_for, usage_cost


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * q))]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def report(bundle):
    bundle = Path(bundle)
    plan = read(bundle / "plan/plan.json")
    completion = read(bundle / "completion.json")
    settings = read(bundle / "settings.json")
    cases = {c["id"]: c for c in plan["cases"]}
    sessions = {
        read(p)["sessionId"]: read(p)["case"]["id"]
        for p in (bundle / "records").glob("*/binding.json")
    }
    receipts = []
    for path in (bundle / "actor").glob("*/put/*/receipt.json"):
        receipts.append((path.parents[2].name, read(path)))
    for path in (bundle / "sut-api-records").glob("*/*/receipt.json"):
        receipts.append((sessions.get(path.parents[1].name), read(path)))
    timing = {p.parent.name: read(p) for p in (bundle / "actor").glob("*/timing.json")}
    audits = [read(p) for p in (bundle / "actor").glob("*/prompt-audit.json")]
    scheduler = (
        read(bundle / "actor/scheduler.json")
        if (bundle / "actor/scheduler.json").exists()
        else {}
    )
    role_prices = {role: pricing_for(settings[role]) for role in ("sut", "put")}
    eligible_price = all(role_prices.values())
    groups = []
    for domain in ("car", "home"):
        for i in range(1, 7):
            task = ("J" if domain == "car" else "H") + str(i)
            ids = {
                cid
                for cid, c in cases.items()
                if c["domain"] == domain and c["task"] == task
            }
            selected = [
                r for cid, r in receipts if cid in ids and r.get("request_sent", True)
            ]
            times = [
                timing[cid]["duration_seconds"]
                for cid in ids
                if cid in timing and timing[cid]["completed"]
            ]
            rows = []
            unknown = 0
            for r in selected:
                u = r.get("usage") or {}
                if "prompt_tokens" not in u or "completion_tokens" not in u:
                    unknown += 1
                    continue
                hit = u.get(
                    "prompt_cache_hit_tokens",
                    (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                )
                rows.append((u["prompt_tokens"], u["completion_tokens"], hit))
            costs = {}
            if eligible_price:
                for period in ("off_peak", "peak"):
                    priced = [
                        usage_cost(r.get("usage") or {}, role_prices[r["role"]], period)
                        for r in selected
                    ]
                    priced = [row for row in priced if row is not None]
                    costs[period] = {
                        key: sum(row[key] for row in priced)
                        for key in ("lower", "upper")
                    }
            groups.append(
                {
                    "domain": domain,
                    "task": task,
                    "planned": len(ids),
                    "completed": len(times),
                    "api_requests_sent": len(selected),
                    "usage_unknown_requests": unknown,
                    "reported_prompt_tokens": sum(r[0] for r in rows),
                    "reported_completion_tokens": sum(r[1] for r in rows),
                    "mean_case_seconds": mean(times) if times else None,
                    "p95_case_seconds": percentile(times, 0.95),
                    "reported_usage_cost_scenarios_usd": costs,
                }
            )
    result = {
        "purpose": plan["purpose"],
        "concurrency": completion["concurrency"],
        "complete": completion["status"] == "complete",
        "scheduled_wall_seconds": scheduler.get("wall_seconds"),
        "peak_submitted_unfinished": scheduler.get("peak_submitted_unfinished"),
        "ledger": completion["ledger"],
        "task_groups": groups,
        "prompt_characters_before": sum(
            a["previous_layout_characters"] for a in audits
        ),
        "prompt_characters_after": sum(a["initial_prompt_characters"] for a in audits),
        "full_persona_coverage": all(
            a["coverage"]["omitted_dimensions"] == 0 for a in audits
        )
        if audits
        else None,
        "pricing_scenarios": role_prices if eligible_price else None,
        "cash_bill_measured": False,
        "model_answer_cache": False,
        "caveats": [
            "Provider prices may change; reported-usage scenarios are not a cash invoice.",
            "Unknown usage is not zero and is excluded from priced totals.",
            "Linear time projections are scenarios at this observed concurrency/workload, not an ETA guarantee.",
            "A small convenience pilot estimates resource use, not population representativeness or statistical power.",
            "Unknown OpenAI cache-write counts are bounded by ordinary-input/default-30m-write pricing; reasoning tokens are included in completion tokens.",
            "Peak/off-peak scenarios vary DeepSeek prices only; OpenAI uses its dated standard rates. This is not a confidence interval.",
        ],
    }
    from .design import validate_matrix

    try:
        validate_matrix({**plan, "purpose": "pilot"})
        balanced = True
    except ValueError:
        balanced = False
    result["complete_paired_matrix"] = balanced
    if (
        balanced
        and result["complete"]
        and all(
            g["completed"] == g["planned"] and not g["usage_unknown_requests"]
            for g in groups
        )
    ):
        result["planning_scenarios"] = []
        for n in (20, 30, 50):
            total_cases = 96 * n
            scale = total_cases / len(cases)
            result["planning_scenarios"].append(
                {
                    "source_personas_per_domain": n,
                    "planned_cases": total_cases,
                    "linear_wall_hours_at_observed_concurrency": scheduler[
                        "wall_seconds"
                    ]
                    * scale
                    / 3600,
                    "usd_off_peak_lower": sum(
                        g["reported_usage_cost_scenarios_usd"]
                        .get("off_peak", {})
                        .get("lower", 0)
                        for g in groups
                    )
                    * scale
                    if eligible_price
                    else None,
                    "usd_peak_upper": sum(
                        g["reported_usage_cost_scenarios_usd"]
                        .get("peak", {})
                        .get("upper", 0)
                        for g in groups
                    )
                    * scale
                    if eligible_price
                    else None,
                }
            )
    write_new(bundle / "resources.json", result)
    return result
