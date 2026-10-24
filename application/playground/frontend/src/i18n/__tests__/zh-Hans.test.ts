import { describe, expect, it } from "vitest";

import sourceMessages from "../messages/en-US.json";
import zhHansMessages from "../messages/zh-Hans.json";
import {
  createLocalePackLoader,
  loadLocaleWithFallback,
  loadRegisteredLocale,
} from "../loader";
import { getLocaleDefinition, LOCALE_REGISTRY } from "../registry";
import { SOURCE_LOCALE, SOURCE_MESSAGES } from "../source";

type Catalog = Record<string, string>;

function readBalancedBlock(value: string, start: number): { body: string; end: number } {
  let depth = 0;
  for (let index = start; index < value.length; index += 1) {
    if (value[index] === "{") depth += 1;
    if (value[index] === "}") {
      depth -= 1;
      if (depth === 0) return { body: value.slice(start + 1, index), end: index + 1 };
    }
  }
  throw new Error(`Unbalanced ICU block in ${value}`);
}

function splitTopLevel(value: string): string[] {
  const parts: string[] = [];
  let start = 0;
  let depth = 0;
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === "{") depth += 1;
    if (value[index] === "}") depth -= 1;
    if (value[index] === "," && depth === 0) {
      parts.push(value.slice(start, index).trim());
      start = index + 1;
    }
  }
  parts.push(value.slice(start).trim());
  return parts;
}

function readControlBranches(value: string): Array<{ label: string; body: string }> {
  const branches: Array<{ label: string; body: string }> = [];
  let index = 0;
  while (index < value.length) {
    while (index < value.length && /[\s,]/.test(value[index])) index += 1;
    const match = /^([^\s{,]+)\s*\{/.exec(value.slice(index));
    if (!match) break;
    const blockStart = index + match[0].lastIndexOf("{");
    const block = readBalancedBlock(value, blockStart);
    branches.push({ label: match[1], body: block.body });
    index = block.end;
  }
  return branches;
}

function icuSignature(value: string): string[] {
  const signature: string[] = [];
  const visit = (message: string): void => {
    for (let index = 0; index < message.length; index += 1) {
      if (message[index] !== "{") continue;
      const block = readBalancedBlock(message, index);
      const parts = splitTopLevel(block.body);
      const argument = parts[0];
      const format = parts[1] ?? "bare";
      if (/^[A-Za-z][\w.-]*$/.test(argument)) {
        signature.push(`arg:${argument}:${format}`);
      }
      if (["plural", "select", "selectordinal"].includes(format)) {
        const branches = readControlBranches(parts.slice(2).join(","));
        signature.push(
          `control:${argument}:${format}:${branches.map(({ label }) => label).join(",")}`,
        );
        for (const branch of branches) visit(branch.body);
      }
      index = block.end - 1;
    }
  };
  visit(value);
  for (const tag of value.matchAll(/<\/?([A-Za-z][\w-]*)[^>]*>/g)) {
    signature.push(`tag:${tag[0]}`);
  }
  return signature.sort();
}

describe("zh-Hans optional UI locale pack", () => {
  it("is registry-driven, lazy, and truthfully labeled", async () => {
    const definition = getLocaleDefinition("zh-Hans");
    expect(definition.nativeName).toBe("简体中文");
    expect(definition.englishName).toBe("Simplified Chinese");
    expect(definition.dir).toBe("ltr");
    expect(definition.fallback).toBe(SOURCE_LOCALE);
    expect(definition.translationStatus).toBe("machine-assisted");

    const loader = createLocalePackLoader(LOCALE_REGISTRY);
    expect(loader.hasCached("zh-Hans")).toBe(false);
    const first = await loader.load("zh-Hans");
    const second = await loader.load("zh-Hans");
    expect(first).toBe(second);
    expect(loader.hasCached("zh-Hans")).toBe(true);
  });

  it("matches the current English key set with no obsolete or unknown keys", () => {
    const sourceKeys = Object.keys(sourceMessages).sort();
    const translatedKeys = Object.keys(zhHansMessages).sort();
    expect(translatedKeys).toEqual(sourceKeys);
  });

  it("uses English for an omitted optional key through the registry fallback", async () => {
    const partialDefinitions = LOCALE_REGISTRY.map((definition) =>
      definition.code === "zh-Hans"
        ? { ...definition, load: async () => ({ "locale.current": zhHansMessages["locale.current"] }) }
        : definition,
    );
    const loader = createLocalePackLoader(partialDefinitions);
    const resolved = await loadLocaleWithFallback("zh-Hans", partialDefinitions, loader);

    expect(resolved["locale.current"]).toBe("当前语言");
    expect(resolved["shell.nav.home"]).toBe(SOURCE_MESSAGES["shell.nav.home"]);
  });

  it("preserves ICU arguments, plural/select branches, and rich-text tags", () => {
    const source = sourceMessages as Catalog;
    const translated = zhHansMessages as Catalog;
    for (const key of Object.keys(source)) {
      expect(icuSignature(translated[key]), key).toEqual(icuSignature(source[key]));
    }
  });

  it("distinguishes ICU argument formats and arbitrary select branches", () => {
    expect(icuSignature("{value}"), "bare argument").not.toEqual(
      icuSignature("{value, number}"),
    );
    expect(icuSignature("{when, date}"), "date argument").not.toEqual(
      icuSignature("{when, time}"),
    );
    const selectSignature = icuSignature(
      "{mode, select, follow_ui {Follow UI} explicit-zh {Chinese} other {Other}}",
    );
    expect(selectSignature).toContain("control:mode:select:follow_ui,explicit-zh,other");
    expect(selectSignature).not.toContain("arg:Other:bare");
  });

  it("translates representative chrome, setup, report, status, and accessibility copy", async () => {
    const resolved = (await loadRegisteredLocale("zh-Hans")) as Catalog;
    expect(resolved["shell.nav.home"]).toBe("首页");
    expect(resolved["locale.buttonLabel"]).toBe("切换语言");
    expect(resolved["personaSetup.filters.stratify"]).toBe("分层");
    expect(resolved["personaSetup.errors.poolCoverageHint"]).toContain("当前筛选条件");
    expect(resolved["reports.usage.costTitle"]).toContain("LLM 成本");
    expect(resolved["scorecards.scale.legend"]).toContain("<green>绿色</green>");
    expect(resolved["runs.deleteJobAria"]).toBe("删除作业 {jobName}");
    expect(resolved["taskScorecard.web.overallAria"]).toBe("总体 UX：{overall} / 10");
    expect(resolved["reports.page.oneConversation"]).toBe(
      "每个数字人各有一次对话 — 打开任意一项查看完整记录",
    );
    expect(resolved["reports.bucket.grounding"]).toBe("无法基于 UI 提供依据");
    expect(resolved["reports.bucket.sharedWorld"]).toBe("共享控制");
    expect(resolved["cockpit.environment.systemPrompt"]).toBe("系统提示词");
    expect(resolved["taskScorecard.reward"]).toBe("奖励 {reward}");
  });

  it("keeps high-risk Chinese terminology and count grammar stable", async () => {
    const resolved = (await loadRegisteredLocale("zh-Hans")) as Catalog;
    const expected: Record<string, string> = {
      "cockpitSetup.pipeline.instrument": "问卷",
      "personaSetup.strategy.selectedValues": "{label}的已选值",
      "reports.facet.policyCheck": "政策合规检查",
      "runHeader.subtitle.survey": "选择数字人和问卷后启动。模拟用户会填写表单，我们会对回答进行评分。",
      "structuredExposure.top": "排名第一",
      "cockpit.pipeline.persona": "数字人",
      "cockpit.pipeline.status.choosePersona": "选择数字人",
      "cockpit.trajectory.persona": "数字人",
      "cockpitSetup.batch.simulatedCohort": "模拟数字人群组",
      "cockpitSetup.batch.peopleCount":
        "{count, plural, one {# 个数字人} other {# 个数字人}}",
      "eval.progress.batchAllFinished":
        "{total, plural, one {全部 # 个数字人已完成} other {全部 # 个数字人已完成}}",
      "eval.progress.batchFinished":
        "{done} / {total, plural, one {# 个数字人} other {# 个数字人}} 已完成",
      "cockpitSetup.batch.activeCount": "进行中 {count} 个",
      "cockpitSetup.batch.failedCount": "失败 {count} 个",
      "cockpitSetup.batch.finishedCount": "已完成 {count} 个",
      "cockpitSetup.batch.waitingCount": "等待中 {count} 个",
      "shell.preflight.blocksReady": "阻塞项已就绪",
      "reports.report.clearCount": "{count} 项明显占优",
      "reports.bucket.hybrid": "混合检查",
      "taskSetup.capabilities.userSimTool": "UserSim 工具",
      "reports.report.answeredCount": "已回答 {count} 项",
      "reports.report.individualAnswers": "逐项回答",
      "eval.survey.answers": "已回答 {count} 题",
      "runs.answered": "已回答 {count} 题",
      "runs.questionsAnswered": "已回答题数",
      "reports.report.present": "有值",
      "reports.report.presentCount": "{count} 项有值",
      "reports.report.missingCount": "{count} 项缺失",
      "reports.report.unanimousCount": "{count} 项完全一致",
      "reports.report.splitCount": "{count} 项存在分歧",
      "reports.analysis.quotes": "引语",
      "reports.analysis.quotesByAnswer": "按回答分组的引语",
      "reports.analysis.aiSummary": "各组数字人解释的 AI 摘要",
      "reports.analysis.personaByAnswer": "按回答分组的数字人解释",
      "reports.task.agentModel": "智能体模型",
      "runs.appType.chatbot": "聊天机器人",
      "runs.chatApp": "聊天应用",
      "runs.appType.osApp": "OS 应用",
    };
    for (const [key, value] of Object.entries(expected)) {
      expect(resolved[key], key).toBe(value);
    }

    const signal = resolved["reports.analysis.signalFrequency"];
    expect(signal).toBe(
      "每个信号在已评分{sampleLabel}中的出现频率（样本数：{count}；仅表示占比，不代表质量评分）",
    );
    const zeroSample = signal.replace("{count}", resolved["reports.analysis.the"]);
    expect(zeroSample).toContain("样本数：未注明");
    expect(zeroSample).not.toContain("若干");
  });

});
