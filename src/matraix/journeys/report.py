"""Deterministic concise readout; never generates findings using a model."""

import json
from pathlib import Path


def write_report(bundle):
    bundle = Path(bundle)
    c = json.loads((bundle / "completion.json").read_text(encoding="utf-8"))
    lines = [
        "# Car / Home 运行报告",
        "",
        f"运行类型：{c['purpose']}；状态：{c['status']}。",
        f"计划 {c['planned']}；已启动 {c['attempted']}；可回放终态 {c['terminal_records']}；缺失/未决 {c['missing_or_unresolved']}；未尝试 {c['unattempted']}。",
        "",
        f"API 请求 {c['ledger']['requests']}；已报告用量 {c['ledger']['usage_reported_tokens']} tokens；用量未知请求 {c['ledger']['usage_unknown_requests']}。不是现金账单。",
        "",
    ]
    if c["purpose"] == "validation":
        lines += [
            "这是 API / 环境集成验证，不是 pilot 或正式实验；不用于报告产品成功率或统计显著性。",
            "代码通过的标准是接口、隔离、收据与状态回放完整，模型本身可以完成或未完成某个任务。",
        ]
    else:
        a = json.loads(
            (bundle / "analysis/descriptive.json").read_text(encoding="utf-8")
        )
        lines += [
            "## 分任务结果",
            "",
            "成功率 = 已确认完整成功 / 全部计划案例。部分完成另列；缺失保留分母。",
            "",
            "| 场景 | 任务 | 已确认成功率 | 计划数 | 缺失/未决 | 可行部分完成 |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for g in a["groups"]:
            lines.append(
                f"| {g['domain']} | {g['task']} | {g['success_rate']:.1%} | {g['planned']} | {g['missing_or_unresolved']} | {g['partial']} |"
            )
        lines += ["", "## 总体对照", "", "| 对照 | 识别范围（百分点） |", "|---|---:|"]
        for r in a["overall_comparisons"]:
            lines.append(
                f"| {r['domain']} / {r['comparison']} | [{100 * r['difference_lower']:+.1f}, {100 * r['difference_upper']:+.1f}] |"
            )
        lines += ["", "以上范围包含缺失不确定性，不是置信区间。"]
        if a["inference_enabled"]:
            lines += [
                "",
                "## 固定最终统计检查",
                "",
                "按源 persona 成组 bootstrap，四项总体比较作 Bonferroni 校正；覆盖率近似，不是有限样本精确保证。",
                "",
                "| 对照 | 校正后区间（百分点） | 方向结论 |",
                "|---|---:|---|",
            ]
            for r in a["inference"]["intervals"]:
                lines.append(
                    f"| {r['comparison']} | [{100 * r['lower']:+.1f}, {100 * r['upper']:+.1f}] | {r['direction']} |"
                )
        else:
            lines += ["未进行正式推断：pilot / 未冻结或未完成的运行不输出显著结论。"]
        lines += [
            "",
            "## 可追溯的问题证据",
            "",
            "重复问题按 episode/code 去重；只陈述实际观察到的动作和约束，不推断隐藏思维。",
        ]
        for r in a["evidence"][:30]:
            lines.append(f"- `{r['case_id']}`：`{r['code']}`；事件 {r['events']}。")
        if not a["evidence"]:
            lines.append(
                "未生成可归类的越权/状态问题证据；这不等于所有任务成功，也不评价自由文本质量。"
            )
        lines += [
            "",
            "合成 persona 不代表真实人口；本轮只有固定基线 SUT，产品改进建议需要后续验证。",
        ]
    lines += [
        "",
        "原始动作、绑定与模型用量见本目录 records/、actor/、sut-api-records/ 和 verifier/。失败请求不重试。",
    ]
    resource_path = bundle / "resources.json"
    if resource_path.exists():
        r = json.loads(resource_path.read_text(encoding="utf-8"))
        lines += [
            "",
            "## 资源测量",
            "",
            f"配置并发：{r['concurrency']}；完整画像覆盖检查：{r['full_persona_coverage']}。",
            "命中/未命中输入、输出 token、分任务耗时、未知用量和费用情景见 resources.json。费用按注明日期的公开价格估算，不是现金账单。",
            "提示字符数的变化不是 token 或费用节省比例；未复用任何模型答案。",
        ]
        for p in r.get("planning_scenarios", []):
            lines.append(
                f"- 每场景 {p['source_personas_per_domain']} 个源 persona：{p['planned_cases']} 案例；按当前观测吞吐线性外推约 {p['linear_wall_hours_at_observed_concurrency']:.2f} 小时，仅为规划情景。"
            )
    (bundle / "REPORT_CN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
